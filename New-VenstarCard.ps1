#Requires -Version 5.1
<#
.SYNOPSIS
Build a Venstar VH CA-import SD card with fresh installation-specific credentials.
.DESCRIPTION
Requires Python 3.11+ and the packages in requirements.txt. Does not format cards.
When generating, private keys are written to CredentialsDirectory, never to the SD card.
Alternatively use RootCaPem for a public CA downloaded from the HA add-on; no keys are read or generated.
Inspect validates inputs without writing files or generating credentials.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Drive')]
    [ValidatePattern('^[A-Za-z]$')][string]$DriveLetter,
    [Parameter(Mandatory = $true, ParameterSetName = 'Path')][string]$TargetPath,
    [Parameter(Mandatory = $true)][string]$UpdateBin,
    [string]$CredentialsDirectory,
    [string]$RootCaPem,
    [string]$DeviceVersion = '6.93',
    [string]$PythonCommand = 'python',
    [string]$ExpectedSha256,
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
$builderArgs = @($builder, '--update-bin', $UpdateBin, '--target', $TargetPath,
    '--device-version', $DeviceVersion)
if ($CredentialsDirectory) { $builderArgs += @('--credentials-dir', $CredentialsDirectory) }
if ($RootCaPem) { $builderArgs += @('--root-ca-pem', $RootCaPem) }
if ($ExpectedSha256) { $builderArgs += @('--expected-sha256', $ExpectedSha256) }
if ($ReuseCredentials) { $builderArgs += '--reuse-credentials' }
if ($Inspect) { $builderArgs += '--dry-run' }
if ($Force) { $builderArgs += '--force' }
& $PythonCommand @builderArgs
if ($LASTEXITCODE -ne 0) { throw "Card builder failed (exit $LASTEXITCODE)." }
