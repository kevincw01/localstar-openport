# Venstar local Skyport server

A local weather and time server for Venstar ColorTouch thermostats using the
VH6.93 Skyport protocol. Includes an SD-card builder that creates a **new random
root CA and matching server certificate for each installation**. No shared keys,
pre-generated certificates, firmware images, or deployment configuration are included.

The existing Home Assistant Venstar integration continues to control the thermostat
through its local API. This project implements the separate Skyport weather session;
it does not implement the vendor's cloud account, firmware updater, or remote restart.

## Requirements

- Python 3.11+ and `python -m pip install -r requirements.txt`.
- A FAT32 SD card, mounted on your computer, and an official VH firmware package
  whose version exactly matches the thermostat's installed version.
- A server reachable from the thermostat on TCP 9001 and 41414, with internet
  access to Open-Meteo and an accurate clock.
- A local DNS override for `connect.skyport.io` pointing at your server.

The SD import mechanism is specific to the VH firmware's Images importer. It has
not been validated across all ColorTouch models or firmware versions. Package
checks validate the container header, version, length, and initial image magic;
they are not vendor signature verification. Obtain firmware from the manufacturer,
and optionally supply its trusted SHA-256 with `--expected-sha256`.

## Build the SD card and generate credentials

On Windows, from a Python-enabled terminal (replace `E` with your card's letter):

```powershell
python -m pip install -r requirements.txt
.\New-VenstarCard.ps1 -DriveLetter E -UpdateBin .\firmware\update.bin `
    -CredentialsDirectory .\credentials -Inspect
.\New-VenstarCard.ps1 -DriveLetter E -UpdateBin .\firmware\update.bin `
    -CredentialsDirectory .\credentials
```

`-PythonCommand` selects another Python executable. The PowerShell launcher checks
that the drive is removable and FAT32. Neither tool formats disks.

The cross-platform Python builder writes to a mounted card or staging directory:

```sh
python build_sdcard.py --update-bin firmware/update.bin --target card \
  --credentials-dir credentials --dry-run
python build_sdcard.py --update-bin firmware/update.bin --target card \
  --credentials-dir credentials
```

For a staging directory, copy the **contents** of `card` to the FAT32 card's root.
Python accepts any target directory; you must verify the correct card/mount and
filesystem yourself. Dry runs do not create directories, files, or keys.

The credentials directory must be outside the card directory, and vice versa:

| File | Purpose |
| --- | --- |
| `root-ca.pem` | Public trust anchor copied onto the card |
| `root-ca.key` | Private CA key; keep offline after provisioning |
| `server.pem` | Public server leaf certificate |
| `server-chain.pem` | Leaf followed by matching root, used by the server |
| `server.key` | Private server key, used only on the server |

Every fresh run generates independent RSA keys and random certificate serials.
Existing credential directories are refused. To provision another thermostat for
the **same** server, explicitly pass `--reuse-credentials` (`-ReuseCredentials` in
PowerShell) with that installation's directory. `--force` permits replacing card
output files but never overwrites credentials. Back up the credentials separately;
Git ignores generated certificates and keys. POSIX systems use restrictive file
permissions; on Windows, keep the credential directory under your private user
profile and restrict access using Windows ACLs.

The generated root and leaf are valid from 1970-01-01 through 2037-12-12 so a device
with an unset clock can validate them. They use a private CA, not publicly trusted
certificates. Import the matching root before switching a thermostat to this server.
Certificate structure and TLS verification are tested in software; newly generated
credentials still require validation on the target thermostat.

The card contains exactly these project files:

```text
VH/
  firmware1a/update.bin
  skyport_root.pem
  gallery/skyport_root.pem
  gallery/gallery.bin
```

No private key is copied onto the card. The gallery index uses a path traversal
in the Images importer to replace `/home/volatile/skyport_root.pem` with your root.
Use this only on thermostats you own and intend to redirect to your server.

## Import on the thermostat

1. Save any custom wallpapers you want to keep: importing Images clears the gallery.
2. Eject the card, insert it into the thermostat, and open **Settings > Import/Export**.
3. Select **Images**, then use the transfer button. Inserting the card and rebooting
   alone does not execute the import. The matching firmware package enables this UI;
   do not accept an unexpected firmware upgrade.
4. Remove the card and restart the thermostat to reload the trust anchor.

The importer may report success even if copying failed. A successful TLS login in
the server log is better evidence that the root was accepted. Retain a copy of the
original vendor root before replacing it if you want to restore vendor connectivity.
Restoring it requires an import tool that accepts that original certificate; this
builder intentionally accepts only its own epoch-valid generated bundles.

## Run the server

Copy `server-chain.pem` and `server.key` to the server, then supply **your own**
coordinates and IANA timezone. Replace the uppercase placeholders below:

```sh
python venstar_weather_server.py \
  --cert credentials/server-chain.pem --key credentials/server.key \
  --lat YOUR_LATITUDE --lon YOUR_LONGITUDE --tz YOUR_IANA_TIMEZONE
```

Certificates default to `credentials/server-chain.pem` and `credentials/server.key`
relative to the working directory. There is no default location or timezone.
The server sends local wall-clock time in milliseconds because the firmware stores
local time, rather than UTC, in its clock.

Point `connect.skyport.io` at this host using local DNS. Allow thermostat-to-server
TCP 9001/41414 and DNS to your local resolver. The thermostat may be denied direct
internet access while the server retrieves weather over HTTPS. Restrict the server
ports to trusted thermostat networks: the current protocol handler does not
authenticate individual devices with client certificates. No port forwarding from
the internet is required.

TLS 1.2+ is used by default. `--allow-old-tls` explicitly enables older TLS/ciphers
for firmware that requires them. Logs include every received ping and successful
echo separately. A successful weather send does not prove that the thermostat
display rendered it. If the weather page stays empty after reboot, toggling
**Skyport > Weather Updates** off/on can trigger a new request; automatic display
recovery is not guaranteed by this implementation.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests generate disposable credentials and miniature synthetic firmware containers.
They exercise real local TLS sockets, root isolation, ping/echo, local time, weather
conversion, and card contents without contacting the weather provider or a thermostat.
If PowerShell is installed, the launcher is also exercised against a staging folder.
Firmware acceptance and on-device import/rendering require a separate hardware test.
