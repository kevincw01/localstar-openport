import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from build_sdcard import build
from credentials import generate, validate, NOT_BEFORE

ROOT = Path(__file__).resolve().parents[1]


def firmware(path, version=(6, 93)):
    header = bytearray(22)
    header[:4] = bytes((ord('V'), ord('H'), version[1], version[0]))
    struct.pack_into('<II', header, 8, 4, 4)
    path.write_bytes(header + b'\x27\x05\x19\x56TEST')
    return path


class TestCard(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.update = firmware(self.root / 'update.bin')
        self.card = self.root / 'card'
        self.creds = self.root / 'credentials'

    def make(self, **kwargs):
        return build(self.update, self.card, self.creds, **kwargs)

    def test_fresh_roots_card_contents_and_explicit_reuse(self):
        first = self.make()
        other = build(self.update, self.root / 'other-card', self.root / 'other-creds')
        self.assertNotEqual(first['credentials']['root_sha256'], other['credentials']['root_sha256'])
        expected = set(first['files'])
        files = {str(p.relative_to(self.card)).replace(os.sep, '/') for p in self.card.rglob('*') if p.is_file()}
        self.assertEqual(files, expected)
        root_bytes = (self.creds / 'root-ca.pem').read_bytes()
        self.assertEqual((self.card / 'VH/skyport_root.pem').read_bytes(), root_bytes)
        self.assertEqual((self.card / 'VH/gallery/skyport_root.pem').read_bytes(), root_bytes)
        self.assertEqual((self.card / 'VH/firmware1a/update.bin').read_bytes(), self.update.read_bytes())
        for path in self.card.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'PRIVATE KEY', path.read_bytes())
        gallery = json.loads((self.card / 'VH/gallery/gallery.bin').read_text())
        self.assertEqual(gallery['imgs'][0]['path'], '../skyport_root.pem')
        # Even --force must not silently generate over a previous installation.
        with self.assertRaises(FileExistsError):
            self.make(force=True)
        reused = self.make(reuse_credentials=True, force=True)
        self.assertEqual(first['credentials']['root_sha256'], reused['credentials']['root_sha256'])
        validate(self.creds)
        if os.name == 'posix':
            self.assertEqual(self.creds.stat().st_mode & 0o777, 0o700)
            self.assertEqual((self.creds / 'root-ca.key').stat().st_mode & 0o777, 0o600)

    def test_dry_run_has_no_side_effects(self):
        self.assertTrue(self.make(dry_run=True)['dry_run'])
        self.assertFalse(self.card.exists())
        self.assertFalse(self.creds.exists())

    def test_bad_firmware_rejected_before_writes(self):
        with self.assertRaises(ValueError):
            self.make(device_version='6.92')
        with self.assertRaises(ValueError):
            self.make(expected_sha256='0' * 64)
        self.update.write_bytes(self.update.read_bytes()[:-1])
        with self.assertRaises(ValueError):
            self.make()
        self.assertFalse(self.creds.exists())
        self.assertFalse(self.card.exists())

    def test_private_material_cannot_be_under_card(self):
        with self.assertRaises(ValueError):
            build(self.update, self.card, self.card / 'credentials')
        with self.assertRaises(ValueError):
            build(self.update, self.creds / 'card', self.creds)
        self.assertFalse(self.creds.exists())

    def test_credential_mismatch_is_rejected(self):
        generate(self.creds)
        generate(self.root / 'other')
        (self.creds / 'server.key').write_bytes((self.root / 'other/server.key').read_bytes())
        with self.assertRaises(ValueError):
            self.make(reuse_credentials=True)
        self.assertFalse(self.card.exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink check')
    def test_symlink_card_destination_is_refused(self):
        self.card.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        (self.card / 'VH').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.make()
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(self.creds.exists())

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is optional')
    def test_powershell_launcher_with_spaces(self):
        card = self.root / 'card with spaces'
        creds = self.root / 'keys with spaces'
        args = ['pwsh', '-NoProfile', '-File', str(ROOT / 'New-VenstarCard.ps1'),
                '-TargetPath', str(card), '-UpdateBin', str(self.update),
                '-CredentialsDirectory', str(creds), '-PythonCommand', sys.executable]
        subprocess.run([*args, '-Inspect'], check=True, capture_output=True, text=True)
        self.assertFalse(creds.exists())
        subprocess.run(args, check=True, capture_output=True, text=True)
        self.assertTrue((card / 'VH/skyport_root.pem').is_file())
        validate(creds)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'POSIX Bash launcher')
    def test_bash_launcher_build_dry_run_reuse_and_errors(self):
        launcher = str(ROOT / 'new-venstar-card.sh')
        card = self.root / 'card with spaces'
        creds = self.root / 'keys with spaces'
        package = self.root / 'firmware with spaces.bin'
        shutil.copyfile(self.update, package)
        args = [launcher, '--python', sys.executable, '--update-bin', str(package),
                '--target', str(card), '--credentials-dir', str(creds)]

        def run(arguments):
            return subprocess.run(arguments, cwd=self.root, capture_output=True, text=True)

        inspected = run([*args, '--dry-run'])
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertFalse(card.exists())
        self.assertFalse(creds.exists())
        written = run(args)
        self.assertEqual(written.returncode, 0, written.stderr)
        self.assertEqual((card / 'VH/firmware1a/update.bin').read_bytes(), package.read_bytes())
        original = validate(creds)['root_sha256']
        reused = run([*args, '--reuse-credentials', '--force'])
        self.assertEqual(reused.returncode, 0, reused.stderr)
        self.assertEqual(validate(creds)['root_sha256'], original)
        for path in card.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'PRIVATE KEY', path.read_bytes())

        bad_package = run([*args, '--device-version', '6.92', '--force', '--reuse-credentials'])
        self.assertNotEqual(bad_package.returncode, 0)
        self.assertIn('must exactly match', bad_package.stderr)
        missing_value = run([launcher, '--python'])
        self.assertEqual(missing_value.returncode, 2)
        missing_interpreter = run([launcher, '--python', str(self.root / 'missing python')])
        self.assertEqual(missing_interpreter.returncode, 127)
        help_result = run([launcher, '--help'])
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn('--reuse-credentials', help_result.stdout)
        empty = run([launcher, '--python', sys.executable])
        self.assertEqual(empty.returncode, 2)
        self.assertIn('required', empty.stderr)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def send(conn, obj):
    body = json.dumps(obj).encode()
    conn.sendall(struct.pack('>I', len(body)) + body)


def receive(conn):
    def exact(size):
        buf = b''
        while len(buf) < size:
            data = conn.recv(size - len(buf))
            if not data:
                raise EOFError('Connection ended before complete frame')
            buf += data
        return buf
    return json.loads(exact(struct.unpack('>I', exact(4))[0]))


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.creds = cls.root / 'credentials'
        generate(cls.creds)
        cls.other = cls.root / 'other'
        generate(cls.other)
        cls.entry, cls.session = free_port(), free_port()
        while cls.entry == cls.session:
            cls.session = free_port()
        cls.logfile = (cls.root / 'server.log').open('w+')
        cls.addClassCleanup(cls.logfile.close)
        cls.proc = subprocess.Popen([
            sys.executable, str(ROOT / 'tests/serve_fixture.py'), '--bind', '127.0.0.1',
            '--entry-port', str(cls.entry), '--session-port', str(cls.session),
            '--lat', '0', '--lon', '0', '--tz', 'Europe/London',
            '--cert', str(cls.creds / 'server-chain.pem'), '--key', str(cls.creds / 'server.key'),
        ], cwd=ROOT, stdout=cls.logfile, stderr=subprocess.STDOUT)
        cls.addClassCleanup(cls.stop)
        deadline = time.monotonic() + 10
        for port in (cls.entry, cls.session):
            while True:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.2):
                        break
                except OSError:
                    if cls.proc.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError((cls.root / 'server.log').read_text())
                    time.sleep(.05)

    @classmethod
    def stop(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
            cls.proc.wait(timeout=5)

    def connect(self, port=None, ca=None, hostname='connect.skyport.io'):
        context = ssl.create_default_context(cafile=str((ca or self.creds) / 'root-ca.pem'))
        raw = socket.create_connection(('127.0.0.1', port or self.session), timeout=3)
        self.addCleanup(raw.close)
        conn = context.wrap_socket(raw, server_hostname=hostname)
        self.addCleanup(conn.close)
        return conn

    def test_redirect_and_epoch_validity(self):
        conn = self.connect(self.entry)
        leaf = x509.load_der_x509_certificate(conn.getpeercert(binary_form=True))
        before = getattr(leaf, 'not_valid_before_utc', None)
        if before is None:
            before = leaf.not_valid_before.replace(tzinfo=timezone.utc)
        self.assertEqual(before, NOT_BEFORE)
        self.assertEqual(conn.recv(256).decode(), f'connect.skyport.io:{self.session}')

    def test_wrong_installation_root_and_hostname_are_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.connect(ca=self.other)
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.connect(hostname='example.invalid')

    def test_login_time_weather_and_every_ping_echo(self):
        conn = self.connect()
        send(conn, {'command': 2, 'mac': '02:00:00:00:00:01', 'fwVer': 'VH6.93'})
        self.assertEqual(receive(conn)['command'], 3)
        send(conn, {'command': 13})
        self.assertEqual(receive(conn), {'command': 14, 'observe': []})
        send(conn, {'command': 45})
        stamp = receive(conn)['timestamp']
        expected = datetime.now(ZoneInfo('Europe/London')).replace(tzinfo=timezone.utc).timestamp() * 1000
        self.assertLess(abs(stamp - expected), 5000)
        # Listener readiness does not imply the background weather fetch has
        # finished, even with a deterministic provider. Exercise the documented
        # initial unavailable response until the fixture cache is populated.
        deadline = time.monotonic() + 5
        while True:
            send(conn, {'command': 59, 'sequence': 100})
            reply = receive(conn)
            self.assertEqual(reply['command'], 60)
            self.assertEqual(reply['sequence'], 100)
            if not reply.get('error'):
                break
            if time.monotonic() >= deadline:
                self.fail('Fixture weather cache did not populate')
            time.sleep(.01)
        payload = json.loads(reply['data'])
        self.assertEqual(payload['current']['temp_f'], 68)
        self.assertEqual(payload['current']['temp_c'], 20)
        self.assertEqual(payload['current']['wind_dir'], 'E')
        self.assertEqual(len(payload['forecast']), 6)
        self.assertEqual(payload['sun_phase']['sunrise'], {'hour': 6, 'minute': 0})
        for sequence in range(201, 213):
            send(conn, {'command': 1, 'sequence': sequence})
            self.assertEqual(receive(conn), {'command': 1, 'sequence': sequence})
        deadline = time.monotonic() + 3
        while True:
            logs = (self.root / 'server.log').read_text()
            if 'PING echo sent to 127.0.0.1 (#12, sequence=212)' in logs:
                break
            if time.monotonic() > deadline:
                self.fail(logs)
            time.sleep(.01)
        for number, sequence in enumerate(range(201, 213), 1):
            self.assertIn(f'PING received from 127.0.0.1 (#{number}, sequence={sequence})', logs)
            self.assertIn(f'PING echo sent to 127.0.0.1 (#{number}, sequence={sequence})', logs)


if __name__ == '__main__':
    unittest.main()
