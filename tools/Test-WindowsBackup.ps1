param(
    [string]$AppPath = "$PSScriptRoot\..\WGestures.App\bin\Release\CrossGestures.exe",
    [string]$OutputDirectory = "$PSScriptRoot\..\build\windows-backup"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$AppPath = [IO.Path]::GetFullPath($AppPath)
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$compilerCandidates = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
)
$compiler = $compilerCandidates | Where-Object {
    Test-Path -LiteralPath $_ -PathType Leaf
} | Select-Object -First 1
if (-not $compiler) {
    throw "The .NET Framework C# compiler was not found: $compiler"
}

$source = Join-Path $PSScriptRoot 'WindowsBackupSmoke.cs'
$testExecutable = Join-Path $OutputDirectory 'WindowsBackupSmoke.exe'
$backup = Join-Path $OutputDirectory 'roundtrip.wgb'

& $compiler /nologo /target:exe "/out:$testExecutable" $source
if ($LASTEXITCODE -ne 0) { throw 'Windows backup smoke test compilation failed.' }

& $testExecutable $AppPath $backup
if ($LASTEXITCODE -ne 0) { throw 'Windows backup export/import round-trip failed.' }

$windowsPortable = [IO.Path]::ChangeExtension($backup, '.cgestures')
$linuxPortable = Join-Path $OutputDirectory 'linux-roundtrip.cgestures'
$pythonCode = @'
import os, sys
root, source, target = sys.argv[1:]
sys.path.insert(0, os.path.join(root, "linux"))
from wgestures.portable import import_config, export_portable_config
with open(source, "r", encoding="utf-8") as stream:
    imported = import_config(stream.read())
assert imported["report"]["imported"] > 0
with open(target, "w", encoding="utf-8", newline="\n") as stream:
    stream.write(export_portable_config(imported["config"]))
'@
& python -c $pythonCode $repoRoot $windowsPortable $linuxPortable
if ($LASTEXITCODE -ne 0) { throw 'Linux portable import/export round-trip failed.' }

& $testExecutable $AppPath (Join-Path $OutputDirectory 'cross-platform-roundtrip.wgb') $linuxPortable
if ($LASTEXITCODE -ne 0) { throw 'Windows could not import the Linux-generated portable configuration.' }
