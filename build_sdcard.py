#!/usr/bin/env python3
"""Build a VH CA-import card, generating a unique root and matching TLS leaf."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile

from credentials import generate, validate

GALLERY = b'{"imgs":[{"path":"../skyport_root.pem","useAsBackground":false}]}\n'


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def firmware_header(path, device_version):
    path = Path(path)
    with path.open("rb") as stream:
        head = stream.read(26)
    if len(head) != 26 or head[:2] != b"VH":
        raise ValueError("Expected a residential VH firmware package")
    match = re.fullmatch(r"(\d+)\.(\d{1,2})", device_version)
    if not match:
        raise ValueError("Device version must look like 6.93")
    version = (int(head[3]), int(head[2]))
    expected = (int(match[1]), int(match[2]))
    if version != expected:
        raise ValueError("Firmware version must exactly match the installed device version")
    slot1, slot2 = struct.unpack_from("<II", head, 8)
    if slot1 < 4 or slot2 < 1 or path.stat().st_size != 22 + slot1 + slot2:
        raise ValueError("Firmware package length does not match its header")
    if head[22:26] != b"\x27\x05\x19\x56":
        raise ValueError("Firmware package is missing the first uImage header magic")
    return {"version": f"{version[0]}.{version[1]:02}", "sha256": digest(path)}


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


def _replace(destination, source=None, contents=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".venstar-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            if source is not None:
                with source.open("rb") as input_stream:
                    shutil.copyfileobj(input_stream, stream)
            else:
                stream.write(contents)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build(update_bin, target, credentials_dir, device_version="6.93", *,
          reuse_credentials=False, dry_run=False, force=False, expected_sha256=None):
    firmware = Path(update_bin).resolve(strict=True)
    card = Path(target).resolve()
    credentials = Path(credentials_dir).resolve()
    if card == credentials or card in credentials.parents or credentials in card.parents:
        raise ValueError("Credentials and SD-card directories must be separate, non-nested paths")
    if card.exists() and not card.is_dir():
        raise ValueError("SD target must be a directory or mounted card")
    header = firmware_header(firmware, device_version)
    if expected_sha256 and header["sha256"] != expected_sha256.lower():
        raise ValueError("Firmware SHA-256 does not match the supplied checksum")
    relative_files = ("VH/firmware1a/update.bin", "VH/skyport_root.pem",
                      "VH/gallery/skyport_root.pem", "VH/gallery/gallery.bin")
    destinations = [_check_destination(card, name) for name in relative_files]
    if firmware in destinations:
        raise ValueError("Firmware input must be outside the output file paths")
    if not force and any(path.exists() for path in destinations):
        raise FileExistsError("SD output files already exist; inspect them before using --force")
    if reuse_credentials:
        bundle = validate(credentials)
    else:
        if credentials.exists():
            raise FileExistsError("Credentials directory already exists; use --reuse-credentials explicitly")
        bundle = {"directory": str(credentials), "root_sha256": "generated when writing"}
    result = {"target": str(card), "credentials": bundle, "firmware": header,
              "files": list(relative_files), "dry_run": dry_run}
    if dry_run:
        return result
    if not reuse_credentials:
        result["credentials"] = generate(credentials)
    ca = (credentials / "root-ca.pem").read_bytes()
    _replace(destinations[0], source=firmware)
    for destination, contents in zip(destinations[1:], (ca, ca, GALLERY)):
        _replace(destination, contents=contents)
    if digest(destinations[0]) != header["sha256"]:
        raise ValueError("Written firmware failed checksum verification")
    for destination, expected in zip(destinations[1:], (ca, ca, GALLERY)):
        if destination.read_bytes() != expected:
            raise ValueError(f"Written SD file failed verification: {destination}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-bin", required=True, help="Official matching VH firmware package")
    parser.add_argument("--target", required=True, help="Mounted FAT32 card or staging directory")
    parser.add_argument("--credentials-dir", required=True, help="Separate directory for newly generated credentials")
    parser.add_argument("--device-version", default="6.93")
    parser.add_argument("--expected-sha256", help="Optional trusted firmware checksum")
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
        print("Card verified. Private keys are only in the separate credentials directory.")
        print("Import Images under Settings > Import/Export, then restart the thermostat.")
        print("Importing deletes custom wallpapers. Reboot alone does not run the import.")


if __name__ == "__main__":
    main()
