param(
    [string]$AppDirectory = "$PSScriptRoot\..\WGestures.App\bin\Release",
    [string]$OutputDirectory = "$PSScriptRoot\..\build\windows-settings"
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$AppDirectory = [IO.Path]::GetFullPath($AppDirectory)
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$executable = Join-Path $AppDirectory 'WindowsSharedSettingsSmoke.exe'
$references = @('System.Drawing.dll', 'System.Windows.Forms.dll', 'System.Core.dll')
foreach ($name in @('WGestures.Core.dll', 'WGestures.Common.dll', 'WGestures.View.dll', 'WindowsInput.dll', 'Newtonsoft.Json.dll', 'Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll')) {
    $references += Join-Path $AppDirectory $name
}
$arguments = @('/nologo', '/target:exe', "/out:$executable")
$arguments += $references | ForEach-Object { "/reference:$_" }
$arguments += Join-Path $PSScriptRoot 'WindowsSharedSettingsSmoke.cs'
try {
    & $compiler @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Shared settings test compilation failed.' }
    & $executable $OutputDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Shared settings native/UI test failed.' }
} finally {
    Remove-Item -LiteralPath $executable -Force -ErrorAction SilentlyContinue
}
