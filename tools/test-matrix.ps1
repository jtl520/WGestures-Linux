[CmdletBinding()]
param(
    [string]$PackagePath,
    [string]$SshKey = "$PSScriptRoot\..\build\acceptance-key",
    [string]$VmRoot = "$env:USERPROFILE\Documents\Virtual Machines",
    [string]$Vmrun = 'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe',
    [string]$KaliUser = 'kali',
    [string]$Ubuntu18User,
    [string]$Ubuntu24Host,
    [string]$Ubuntu24User,
    [switch]$StartStoppedVMs,
    [switch]$BootstrapOnly
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path -LiteralPath "$PSScriptRoot\..").Path
$buildDirectory = Join-Path $repositoryRoot 'build'
$artifactRoot = Join-Path $buildDirectory ('acceptance-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $buildDirectory, $artifactRoot | Out-Null

if (-not (Test-Path -LiteralPath $SshKey)) {
    & ssh-keygen.exe -q -t ed25519 -N '' -f $SshKey
    Write-Host 'A temporary acceptance key was created. Add this public key to each test account:'
    Get-Content -LiteralPath ($SshKey + '.pub')
    Write-Host 'No VM or physical host was modified. Re-run this command after installing the key.'
    exit 20
}
if ($BootstrapOnly) {
    Get-Content -LiteralPath ($SshKey + '.pub')
    exit 0
}
if (-not $PackagePath) {
    throw 'PackagePath is required unless -BootstrapOnly is used.'
}
$package = (Resolve-Path -LiteralPath $PackagePath).Path
if (-not (Test-Path -LiteralPath $Vmrun)) {
    throw "vmrun was not found at $Vmrun"
}

$knownHosts = Join-Path $buildDirectory 'acceptance-known-hosts'
$sshOptions = @(
    '-i', $SshKey,
    '-o', 'BatchMode=yes',
    '-o', 'ConnectTimeout=8',
    '-o', 'StrictHostKeyChecking=accept-new',
    '-o', "UserKnownHostsFile=$knownHosts"
)

function Get-GuestAddress([string]$VmxPath) {
    $running = @(& $Vmrun list | Select-Object -Skip 1)
    if ($running -notcontains $VmxPath) {
        if (-not $StartStoppedVMs) {
            throw "VM is stopped: $VmxPath (use -StartStoppedVMs to start it)"
        }
        & $Vmrun start $VmxPath nogui | Out-Null
    }
    $address = (& $Vmrun getGuestIPAddress $VmxPath -wait).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $address) {
        throw "Could not obtain a guest IP for $VmxPath"
    }
    return $address
}

function Invoke-Target(
    [string]$Name,
    [string]$HostName,
    [string]$UserName
) {
    if (-not $HostName -or -not $UserName) {
        Write-Warning "$Name skipped because host or user was not supplied."
        return
    }
    $target = "$UserName@$HostName"
    & ssh.exe @sshOptions $target 'true'
    if ($LASTEXITCODE -ne 0) {
        throw "SSH key authentication failed for $target"
    }
    $remoteRoot = "/tmp/wgestures-matrix-$([guid]::NewGuid().ToString('N'))"
    & ssh.exe @sshOptions $target "mkdir -p '$remoteRoot/output'"
    $files = @(
        $package,
        (Join-Path $repositoryRoot 'tools\remote-acceptance.sh'),
        (Join-Path $repositoryRoot 'linux\tests\x11_harness.py'),
        (Join-Path $repositoryRoot 'linux\tests\x11_driver.py')
    )
    & scp.exe @sshOptions @files "${target}:$remoteRoot/"
    if ($LASTEXITCODE -ne 0) {
        throw "SCP failed for $target"
    }
    $remotePackage = "$remoteRoot/$([IO.Path]::GetFileName($package))"
    & ssh.exe @sshOptions $target "chmod +x '$remoteRoot/remote-acceptance.sh'; '$remoteRoot/remote-acceptance.sh' '$remotePackage' '$remoteRoot/x11_harness.py' '$remoteRoot/x11_driver.py' '$remoteRoot/output'"
    $remoteExit = $LASTEXITCODE
    $localTarget = Join-Path $artifactRoot $Name
    New-Item -ItemType Directory -Force -Path $localTarget | Out-Null
    & scp.exe @sshOptions -r "${target}:$remoteRoot/output/." $localTarget
    & ssh.exe @sshOptions $target "rm -rf '$remoteRoot'"
    if ($remoteExit -ne 0) {
        throw "$Name acceptance failed with exit code $remoteExit. Evidence: $localTarget"
    }
}

function Invoke-WaylandTarget(
    [string]$Name,
    [string]$HostName,
    [string]$UserName
) {
    $target = "$UserName@$HostName"
    & ssh.exe @sshOptions $target 'true'
    if ($LASTEXITCODE -ne 0) { throw "SSH key authentication failed for $target" }
    $remoteRoot = "/tmp/wgestures-matrix-$([guid]::NewGuid().ToString('N'))"
    & ssh.exe @sshOptions $target "mkdir -p '$remoteRoot/output'"
    $files = @($package, (Join-Path $repositoryRoot 'tools\wayland-acceptance.sh'))
    & scp.exe @sshOptions @files "${target}:$remoteRoot/"
    if ($LASTEXITCODE -ne 0) { throw "SCP failed for $target" }
    $remotePackage = "$remoteRoot/$([IO.Path]::GetFileName($package))"
    & ssh.exe @sshOptions $target "chmod +x '$remoteRoot/wayland-acceptance.sh'; '$remoteRoot/wayland-acceptance.sh' '$remotePackage' '$remoteRoot/output'"
    $remoteExit = $LASTEXITCODE
    $localTarget = Join-Path $artifactRoot $Name
    New-Item -ItemType Directory -Force -Path $localTarget | Out-Null
    & scp.exe @sshOptions -r "${target}:$remoteRoot/output/." $localTarget
    & ssh.exe @sshOptions $target "rm -rf '$remoteRoot'"
    if ($remoteExit -ne 0) {
        throw "$Name static Wayland acceptance failed with exit code $remoteExit. Evidence: $localTarget"
    }
}

$vmxFiles = @(Get-ChildItem -LiteralPath $VmRoot -Filter '*.vmx' -File -Recurse)
$kaliVmx = $vmxFiles | Where-Object FullName -Match 'kali' | Select-Object -First 1
$ubuntu18Vmx = $vmxFiles | Where-Object FullName -Match 'ubuntu-18|Ubuntu 18' | Select-Object -First 1
if (-not $kaliVmx) { throw 'Kali VMX was not found.' }
if (-not $ubuntu18Vmx) { throw 'Ubuntu 18.04 VMX was not found.' }

Invoke-Target -Name 'kali-2026.2-xfce-x11' -HostName (Get-GuestAddress $kaliVmx.FullName) -UserName $KaliUser
Invoke-Target -Name 'ubuntu-18.04-gnome-xorg' -HostName (Get-GuestAddress $ubuntu18Vmx.FullName) -UserName $Ubuntu18User

if ($Ubuntu24Host -and $Ubuntu24User) {
    Invoke-WaylandTarget -Name 'ubuntu-24.04-gnome46-wayland' -HostName $Ubuntu24Host -UserName $Ubuntu24User
}

Write-Host "Acceptance evidence: $artifactRoot"
