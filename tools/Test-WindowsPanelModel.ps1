param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Debug'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$installation = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
if (-not $installation) { throw 'Visual Studio MSBuild installation was not found.' }
$compiler = Join-Path $installation 'MSBuild\Current\Bin\Roslyn\csc.exe'
$newtonsoft = Join-Path $repoRoot "WGestures.App\bin\$Configuration\Newtonsoft.Json.dll"
$outputDirectory = Join-Path $repoRoot 'build\windows-panel-model'
$output = Join-Path $outputDirectory 'WindowsPanelModelSmoke.exe'
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

& $compiler /nologo /target:exe "/out:$output" "/reference:$newtonsoft" `
    (Join-Path $repoRoot 'WGestures.App\QuickPanel\PanelConfig.cs') `
    (Join-Path $repoRoot 'tools\WindowsPanelModelSmoke.cs')
if ($LASTEXITCODE -ne 0) { throw 'Windows panel model test compilation failed.' }
Copy-Item -LiteralPath $newtonsoft -Destination $outputDirectory -Force
& $output
if ($LASTEXITCODE -ne 0) { throw 'Windows panel model checks failed.' }
