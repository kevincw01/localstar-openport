#!/usr/bin/env python3
"""Build a VH CA-import card with a version stub and a public root CA."""

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
import time

from credentials import generate, public_root, validate

VERSION_PATTERN = re.compile(r"^VH([0-9]{1,3})\.([0-9]{2})$", re.IGNORECASE)


def firmware_stub(device_version):
    match = VERSION_PATTERN.fullmatch(device_version.strip()) if isinstance(device_version, str) else None
    if not match:
        raise ValueError("Firmware version must look like VH6.93, as shown on the About screen")
    major, minor = (int(part) for part in match.groups())
    if major > 255:
        raise ValueError("Firmware major version must be between 0 and 255")
    version = f"VH{major}.{minor:02}"
    return version, bytes((ord("V"), ord("H"), minor, major))


def _check_destination(card, relative):
    destination = card / relative
    for path in (destination, *destination.parents):
        if path == card:
            break
        if path.is_symlink():
            raise ValueError(f"Refusing symlink in SD output: {path}")
        if path.exists() and path != destination and not path.is_dir():
            raise ValueError(f"SD output parent is not a directory: {path}")
    if destination.exists() and not destination.is_file():
        raise ValueError(f"SD destination is not a regular file: {destination}")
    return destination


def _replace(destination, contents):
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".venstar-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build(target, credentials_dir=None, device_version=None, *,
          reuse_credentials=False, dry_run=False, force=False,
          root_ca_pem=None):
    if bool(credentials_dir) == bool(root_ca_pem):
        raise ValueError("Specify either credentials_dir or root_ca_pem, not both")
    if root_ca_pem and reuse_credentials:
        raise ValueError("Public-CA import does not use --reuse-credentials")
    card = Path(target).resolve()
    version, stub = firmware_stub(device_version)
    credentials = Path(credentials_dir).resolve() if credentials_dir else None
    if credentials and (card == credentials or card in credentials.parents or credentials in card.parents):
        raise ValueError("Credentials and SD-card directories must be separate, non-nested paths")
    if card.exists() and not card.is_dir():
        raise ValueError("SD target must be a directory or mounted card")
    relative_files = ("VH/firmware1a/update.bin", "VH/skyport_root.pem",
                      "VH/gallery/skyport_root.pem", "VH/gallery/gallery.bin")
    destinations = [_check_destination(card, name) for name in relative_files]
    if not force and any(path.exists() for path in destinations):
        raise FileExistsError("SD output files already exist; inspect them before using --force")
    ca = None
    public_ca = None
    if root_ca_pem:
        ca, fingerprint = public_root(root_ca_pem)
        public_ca = {"file": str(Path(root_ca_pem).resolve()), "root_sha256": fingerprint}
        bundle = None
    elif reuse_credentials:
        bundle = validate(credentials)
    else:
        if credentials.exists():
            raise FileExistsError("Credentials directory already exists; use --reuse-credentials explicitly")
        bundle = {"directory": str(credentials), "root_sha256": "generated when writing"}
    result = {"target": str(card), "credentials": bundle, "public_ca": public_ca,
              "firmware": {"version": version, "stub": stub.hex(" ").upper()},
              "files": list(relative_files), "dry_run": dry_run}
    if dry_run:
        return result
    if credentials and not reuse_credentials:
        result["credentials"] = generate(credentials)
    if ca is None:
        ca = (credentials / "root-ca.pem").read_bytes()
    gallery = json.dumps({
        "time": int(time.time()), "origin": 1, "model": "VH", "version": version[2:],
        "imgs": [{"path": "../skyport_root.pem", "ssExclude": True,
                  "useAsBackground": False}],
    }, separators=(",", ":")).encode("utf-8")
    for destination, contents in zip(destinations, (stub, ca, ca, gallery)):
        _replace(destination, contents=contents)
    for destination, expected in zip(destinations, (stub, ca, ca, gallery)):
        if destination.read_bytes() != expected:
            raise ValueError(f"Written SD file failed verification: {destination}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Mounted FAT32 card or staging directory")
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--credentials-dir", help="Separate directory for newly generated credentials")
    identity.add_argument("--root-ca-pem", help="Use the active public CA PEM; generate no keys")
    parser.add_argument("--firmware-version", "--device-version", dest="device_version", required=True,
                        help="Version shown on the thermostat About screen, such as VH6.93")
    parser.add_argument("--reuse-credentials", action="store_true", help="Explicitly use this installation's existing bundle")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print plan; write nothing, including keys")
    parser.add_argument("--force", action="store_true", help="Replace existing card output files; never replaces keys")
    args = vars(parser.parse_args())
    try:
        result = build(**args)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(json.dumps(result, indent=2))
    if not result["dry_run"]:
        print("Card verified. " + ("No private keys were read or written." if result["public_ca"] else
                                  "Private keys are only in the separate credentials directory."))
        print("The four-byte firmware stub only identifies the installed version; it does not update firmware.")
        print("Import Images under Settings > Import/Export, then restart the thermostat.")
        print("Importing deletes custom wallpapers. Reboot alone does not run the import.")


if __name__ == "__main__":
    main()
