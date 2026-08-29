param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$NuGetPath = 'nuget.exe',
    [string]$MSBuildPath,
    [string]$InnoCompilerPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $nuget = Get-Command $NuGetPath -ErrorAction SilentlyContinue
    if (-not $nuget) {
        throw 'nuget.exe was not found. Download it from https://www.nuget.org/downloads and add it to PATH.'
    }

    if (-not $MSBuildPath) {
        $vswhere = Join-Path ${env:ProgramFiles(x86)} `
            'Microsoft Visual Studio\Installer\vswhere.exe'
        if (Test-Path -LiteralPath $vswhere) {
            $installation = & $vswhere -latest -products * `
                -requires Microsoft.Component.MSBuild -property installationPath
            if ($installation) {
                $MSBuildPath = Join-Path $installation 'MSBuild\Current\Bin\MSBuild.exe'
            }
        }
    }
    if (-not $MSBuildPath) {
        $command = Get-Command msbuild.exe -ErrorAction SilentlyContinue
        if ($command) {
            $MSBuildPath = $command.Source
        }
    }
    if (-not $MSBuildPath -or -not (Test-Path -LiteralPath $MSBuildPath)) {
        throw 'MSBuild was not found. Install Visual Studio Build Tools with .NET desktop build tools.'
    }

    $nugetConfig = Join-Path $repoRoot 'NuGet.Config'
    & $nuget.Source restore WGestures.sln -PackagesDirectory packages `
        -ConfigFile $nugetConfig -NonInteractive
    if ($LASTEXITCODE -ne 0) { throw 'NuGet restore failed.' }

    $frameworkPath = Join-Path ${env:ProgramFiles(x86)} `
        'Reference Assemblies\Microsoft\Framework\.NETFramework\v4.8'
    if (-not (Test-Path -LiteralPath $frameworkPath)) {
        & $nuget.Source install Microsoft.NETFramework.ReferenceAssemblies.net48 `
            -Version 1.0.3 -OutputDirectory packages `
            -ConfigFile $nugetConfig -NonInteractive
        if ($LASTEXITCODE -ne 0) { throw 'Unable to restore .NET Framework 4.8 reference assemblies.' }
        $frameworkPath = Join-Path $repoRoot `
            'packages\Microsoft.NETFramework.ReferenceAssemblies.net48.1.0.3\build\.NETFramework\v4.8'
    }

    & $MSBuildPath WGestures.sln /t:Rebuild /m /v:minimal `
        "/p:Configuration=$Configuration" '/p:Platform=Any CPU' `
        "/p:FrameworkPathOverride=$frameworkPath"
    if ($LASTEXITCODE -ne 0) { throw 'Windows application build failed.' }

    if ($Configuration -ne 'Release') {
        & (Join-Path $PSScriptRoot 'Test-WindowsBuild.ps1') -SourceOnly
        Write-Host 'Debug application built; installer generation is only performed for Release.'
        return
    }

    & (Join-Path $PSScriptRoot 'Test-WindowsBuild.ps1')

    if (-not $InnoCompilerPath) {
        & $nuget.Source install Tools.InnoSetup -Version 6.4.3 `
            -OutputDirectory build\tools -ConfigFile $nugetConfig -NonInteractive
        if ($LASTEXITCODE -ne 0) { throw 'Unable to restore Inno Setup compiler.' }
        $InnoCompilerPath = Join-Path $repoRoot `
            'build\tools\Tools.InnoSetup.6.4.3\tools\ISCC.exe'
    }
    if (-not (Test-Path -LiteralPath $InnoCompilerPath)) {
        throw "Inno Setup compiler was not found: $InnoCompilerPath"
    }

    & $InnoCompilerPath 'packaging\windows\CrossGestures.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Windows installer build failed.' }

    $installer = Get-ChildItem -LiteralPath 'build\windows' `
        -Filter 'CrossGestures-*-Windows-Setup.exe' |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    & (Join-Path $PSScriptRoot 'Test-WindowsBuild.ps1') `
        -InstallerPath $installer.FullName

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer.FullName).Hash
    Write-Host "Installer: $($installer.FullName)"
    Write-Host "SHA-256:  $hash"
}
finally {
    Pop-Location
}
