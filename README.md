# Venstar local Skyport server

The T7850 thermostat is popular with the smart home crowd because it provides a
local API for controlling the thermostat with solutions like Home Assistant.  
The only remaining problem is that the thermostat's do not support time or weather
updates via this local API.  The thermostat also does not support NTP.  The only
method to gain time synchronization and outdoor weather on the thermostats is by
enabling the venstart skyport cloud interface.  

This project provides a solution to replicate the cloud interface for weather and
time using a local server.  The implementation relies on an exploit which replaces
the local root CA on the device with a locally generated version.  The exploit 
leverages the SD card interface to deploy the new root CA.  

This project includes an SD-card builder script that creates a **new random
root CA and matching server certificate for each installation**. No shared keys,
pre-generated certificates, firmware images, or deployment configuration are
included.  The existing Home Assistant Venstar integration continues to control 
the thermostat through its local API. This project implements the separate Skyport
weather session; it does not implement all the features of skyport, only weather, 
ping and time.  

The local Skyport server can run standalone or as a Home Assistant Supervisor
add-on/app. Besides the unique
root CA that must be deployed to the thermostat via the SD card, the local network
dns server (typically on the local internet router/firewall) must be configured to
route the cloud address to the LAN server.  Open-meteo is used by the server to
serve weather for your location to the thermostat.

## Requirements

- Download or clone this repo to your system
- Python 3.11+ and `python -m pip install -r requirements.txt`.
- A FAT32 SD card mounted on your computer. Note the VH firmware version shown
  under About on the thermostat (for example, `VH6.93`).
- A server reachable from the thermostat on TCP 9001 and 41414, with internet
  access to Open-Meteo and an accurate clock.
- A local DNS override on your network router for `connect.skyport.io` which
  points at your local server's IP address.

The SD import mechanism is specific to the VH firmware's Images importer. It has
not been validated across all ColorTouch models or firmware versions. This project
was tested on a T7850 with firmware VH6.93. Other firmware versions or
thermostats may work too. The card contains a four-byte version stub matching the
version shown under About; it does not contain or apply firmware. If the thermostat
offers a firmware upgrade, cancel it.

## Build the SD card and generate credentials

On Windows, from a Python-enabled terminal (replace `E` with your card's drive letter which is mounted in windows):

```powershell
python -m pip install -r requirements.txt
.\New-VenstarCard.ps1 -DriveLetter E -DeviceVersion VH6.93 `
    -CredentialsDirectory .\credentials -Inspect
.\New-VenstarCard.ps1 -DriveLetter E -DeviceVersion VH6.93 `
    -CredentialsDirectory .\credentials
```

`-PythonCommand` selects another Python executable. The PowerShell launcher checks
that the drive is removable and FAT32. Neither tool formats disks.

On Linux and macOS, use the Bash launcher with Python 3.11+ (I haven't tested this
because all my linux machines are headless without sd card readers):

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
./new-venstar-card.sh --firmware-version VH6.93 --target card \
  --credentials-dir credentials --dry-run
./new-venstar-card.sh --firmware-version VH6.93 --target card \
  --credentials-dir credentials
```

To write directly to a mounted FAT32 card, replace `card` with its mount directory,
such as `/Volumes/VENSTAR` on macOS or `/media/$USER/VENSTAR` on Linux. Confirm the
actual mount path first; the launcher accepts staging directories too and does not
automatically check filesystem type or mount status. Keep credentials on your
computer, outside that directory, and eject the card after writing completes.

Use `--python /path/to/python3` or the `PYTHON` environment variable to select an
interpreter. All builder options, including `--reuse-credentials`, `--force`,
and `--firmware-version`, are forwarded unchanged. Run
`./new-venstar-card.sh --help` for usage. The launcher also runs with macOS's
stock Bash 3.2; Python 3.11+ must be installed separately if unavailable.

The cross-platform Python builder writes to a mounted card or staging directory:

```sh
python build_sdcard.py --firmware-version VH6.93 --target card \
  --credentials-dir credentials --dry-run
python build_sdcard.py --firmware-version VH6.93 --target card \
  --credentials-dir credentials
```

If you generated credentials inside the Home Assistant add-on, use its Web UI to
create and download the matching SD-card image. You can write that image directly
to the card. If you use this standalone directory-based builder instead, provide
the exact matching public root CA PEM:

```sh
./new-venstar-card.sh --firmware-version VH6.93 --target card \
  --root-ca-pem root-ca.pem --dry-run
./new-venstar-card.sh --firmware-version VH6.93 --target card \
  --root-ca-pem root-ca.pem
```

On Windows, supply `-DeviceVersion VH6.93` and `-RootCaPem .\root-ca.pem` instead
of `-CredentialsDirectory`.
The direct Python option is also `--root-ca-pem`. This mode checks the public root
and writes no private keys. It requires an epoch-valid, self-signed RSA CA, as
generated by the add-on. Use either public-CA input or a credentials directory;
generating another CA separately would produce a different identity.

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
Existing credential directories are refused. To provision another thermostat you can
re-use the same SD card.  But if for some reason you need to regenerate the same cert,
explicitly pass `--reuse-credentials` (`-ReuseCredentials` in PowerShell) with that 
installation's directory. `--force` permits replacing card output files but never 
overwrites credentials. Back up the credentials separately; Git ignores generated 
certificates and keys. POSIX systems use restrictive file permissions; on Windows, 
keep the credential directory under your private user profile and restrict access 
using Windows ACLs.

The generated root and leaf are valid from 1970-01-01 through 2037-12-12 so a device
with an unset clock can validate them. They use a private CA, not publicly trusted
certificates. Import the matching root before switching a thermostat to this server.
Certificate structure and TLS verification are tested in software; newly generated
credentials still require validation on the target thermostat.

For firmware `VH6.93`, `VH/firmware1a/update.bin` contains only four bytes:
`56 48 5D 06` (`VH`, minor 93, major 6). The version you enter must match the
Firmware value shown on that thermostat's About screen.

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

## Run the server

For Home Assistant OS, see [Install the Home Assistant add-on](#home-assistant-add-on)
below. For standalone use, follow these command-line instructions.

Copy `server-chain.pem` and `server.key` to the server, then supply **your own**
coordinates and IANA timezone. Replace the uppercase placeholders below:

```sh
python venstar_weather_server.py \
  --cert credentials/server-chain.pem --key credentials/server.key \
  --lat YOUR_LATITUDE --lon YOUR_LONGITUDE --tz YOUR_IANA_TIMEZONE
```

For example, this runs the server for London using the credentials generated by
the SD-card builder:

```sh
python3 venstar_weather_server.py \
  --cert credentials/server-chain.pem \
  --key credentials/server.key \
  --lat 51.5074 --lon -0.1278 --tz Europe/London
```

Replace the example coordinates and timezone with your location. Run the command
from the repository directory after installing the dependencies; it starts the
server in the foreground, listening on TCP 9001 and 41414 on all interfaces.

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
echo separately.

## Home Assistant add-on

The Supervisor add-on is maintained in its own repository:
[localstar-openport-addon](https://github.com/kevincw01/localstar-openport-addon).

[Add the add-on repository to Home Assistant](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fkevincw01%2Flocalstar-openport-addon)

Use that repository's installation and migration instructions to run the server
inside HA. This repository contains the standalone server and SD-card builder.
The existing HA Venstar integration remains responsible for HVAC controls.

## Import on the thermostat

1. Save any custom wallpapers you want to keep: importing Images clears the gallery.
2. Eject the card, insert it into the thermostat, and open **Settings > Import/Export**.
3. Select **Images**, then use the transfer button. The four-byte version stub enables
   this UI; **if you're prompted to update the firmware, cancel the prompt.**
4. After import, remove the card and restart the thermostat to reload the trust anchor.

A successful TLS login in the local server log is evidence that the root was accepted. 
The top right corner of the thermostat display show a globe with a green check and the
temperature next to a tree will be besides it.  Sometimes it takes a few minutes for the 
temperature to show up.  You can force it to show by turning off / on weather updates in
the skyport settings.


## Tests

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Tests generate disposable credentials and miniature synthetic firmware containers.
They exercise real local TLS sockets, root isolation, ping/echo, local time, weather
conversion, and card contents without contacting the weather provider or a thermostat.
If PowerShell is installed, the launcher is also exercised against a staging folder.
On POSIX systems, the Bash launcher is tested from another working directory with
paths containing spaces, dry runs, explicit credential reuse, and invalid inputs.
Firmware acceptance and on-device import/rendering require a separate hardware test.
