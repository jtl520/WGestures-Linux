param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$installation = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
if (-not $installation) { throw 'Visual Studio compiler was not found.' }
$compiler = Join-Path $installation 'MSBuild\Current\Bin\Roslyn\csc.exe'
$appOutput = Join-Path $repoRoot "WGestures.App\bin\$Configuration"
$outputDirectory = Join-Path $repoRoot 'build\windows-window-actions'
$output = Join-Path $outputDirectory 'WindowsWindowActionSmoke.exe'
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

& $compiler /nologo /target:exe "/out:$output" `
    /reference:System.Drawing.dll /reference:System.Windows.Forms.dll `
    "/reference:$(Join-Path $appOutput 'WGestures.Core.dll')" `
    (Join-Path $repoRoot 'tools\WindowsWindowActionSmoke.cs')
if ($LASTEXITCODE -ne 0) { throw 'Windows window-action smoke compilation failed.' }

foreach ($assembly in @('WGestures.Core.dll', 'WGestures.Common.dll', 'WindowsInput.dll')) {
    Copy-Item -LiteralPath (Join-Path $appOutput $assembly) -Destination $outputDirectory -Force
}
& $output
if ($LASTEXITCODE -ne 0) { throw 'Windows window-action smoke checks failed.' }
