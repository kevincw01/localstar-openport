#Requires -Version 5.1
<#
.SYNOPSIS
Build a Venstar VH CA-import SD card with fresh installation-specific credentials.
.DESCRIPTION
Requires Python 3.11+ and the packages in requirements.txt. Does not format cards.
When generating, private keys are written to CredentialsDirectory, never to the SD card.
Alternatively use RootCaPem for the active public CA; no keys are read or generated.
Enter the firmware version shown on the thermostat About screen; only a four-byte version stub is written.
Inspect validates inputs without writing files or generating credentials.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Drive')]
    [ValidatePattern('^[A-Za-z]$')][string]$DriveLetter,
    [Parameter(Mandatory = $true, ParameterSetName = 'Path')][string]$TargetPath,
    [string]$CredentialsDirectory,
    [string]$RootCaPem,
    [Parameter(Mandatory = $true)][string]$DeviceVersion,
    [string]$PythonCommand = 'python',
    [switch]$ReuseCredentials,
    [switch]$Inspect,
    [switch]$Force
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($DriveLetter) {
    $volume = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID='$($DriveLetter.ToUpper()):'"
    if (-not $volume -or $volume.DriveType -ne 2 -or $volume.FileSystem -ne 'FAT32') {
        throw 'DriveLetter must identify a mounted removable FAT32 card. This tool never formats disks.'
    }
    $TargetPath = "${DriveLetter}:\"
}
$builder = Join-Path $PSScriptRoot 'build_sdcard.py'
$builderArgs = @($builder, '--target', $TargetPath, '--firmware-version', $DeviceVersion)
if ($CredentialsDirectory) { $builderArgs += @('--credentials-dir', $CredentialsDirectory) }
if ($RootCaPem) { $builderArgs += @('--root-ca-pem', $RootCaPem) }
if ($ReuseCredentials) { $builderArgs += '--reuse-credentials' }
if ($Inspect) { $builderArgs += '--dry-run' }
if ($Force) { $builderArgs += '--force' }
& $PythonCommand @builderArgs
if ($LASTEXITCODE -ne 0) { throw "Card builder failed (exit $LASTEXITCODE)." }
