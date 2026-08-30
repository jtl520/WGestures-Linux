param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$installation = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
if (-not $installation) { throw 'Visual Studio MSBuild installation was not found.' }
$compiler = Join-Path $installation 'MSBuild\Current\Bin\Roslyn\csc.exe'
$newtonsoft = Join-Path $repoRoot "WGestures.App\bin\$Configuration\Newtonsoft.Json.dll"
$outputDirectory = Join-Path $repoRoot 'build\windows-panel-dialogs'
$output = Join-Path $outputDirectory 'WindowsPanelDialogSmoke.exe'
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

$manifest = Join-Path $outputDirectory 'dpiaware.manifest'
@'
<?xml version="1.0" encoding="utf-8"?>
<assembly manifestVersion="1.0" xmlns="urn:schemas-microsoft-com:asm.v1">
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>
    </windowsSettings>
  </application>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls"
        version="6.0.0.0" processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*" />
    </dependentAssembly>
  </dependency>
</assembly>
'@ | Set-Content -LiteralPath $manifest -Encoding UTF8

& $compiler /nologo /target:winexe "/out:$output" `
    "/win32manifest:$manifest" `
    /reference:System.Drawing.dll /reference:System.Windows.Forms.dll `
    "/reference:$newtonsoft" `
    (Join-Path $repoRoot 'WGestures.App\QuickPanel\PanelConfig.cs') `
    (Join-Path $repoRoot 'WGestures.App\QuickPanel\UrlFavicon.cs') `
    (Join-Path $repoRoot 'WGestures.App\QuickPanel\ApplicationPickerDialog.cs') `
    (Join-Path $repoRoot 'WGestures.App\QuickPanel\PanelItemDialog.cs') `
    (Join-Path $repoRoot 'tools\WindowsPanelDialogSmoke.cs')
if ($LASTEXITCODE -ne 0) { throw 'Windows panel dialog test compilation failed.' }
Copy-Item -LiteralPath $newtonsoft -Destination $outputDirectory -Force
& $output
if ($LASTEXITCODE -ne 0) { throw 'Windows panel dialog layout checks failed.' }
