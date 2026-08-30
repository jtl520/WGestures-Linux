param(
    [switch]$SourceOnly,
    [string]$InstallerPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $repoRoot 'WGestures.App\app.manifest'
$appProjectPath = Join-Path $repoRoot 'WGestures.App\WGestures.App.csproj'
$commonProjectPath = Join-Path $repoRoot 'WGestures.Common\WGestures.Common.csproj'
$windowsInputProjectPath = Join-Path $repoRoot 'WindowsInput\WindowsInput.csproj'
$autoStarterPath = Join-Path $repoRoot 'WGestures.Common\OsSpecific\Windows\AutoStarter.cs'
$installerScriptPath = Join-Path $repoRoot 'packaging\windows\CrossGestures.iss'
$defaultGesturesPath = Join-Path $repoRoot 'WGestures.App\defaults\gestures.wg2'

[xml]$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
$manifestText = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
$appProjectText = Get-Content -LiteralPath $appProjectPath -Raw -Encoding UTF8
$commonProjectText = Get-Content -LiteralPath $commonProjectPath -Raw -Encoding UTF8
$windowsInputProjectText = Get-Content -LiteralPath $windowsInputProjectPath -Raw -Encoding UTF8
$autoStarterText = Get-Content -LiteralPath $autoStarterPath -Raw -Encoding UTF8
$installerScriptText = Get-Content -LiteralPath $installerScriptPath -Raw -Encoding UTF8
$programText = Get-Content -LiteralPath (Join-Path $repoRoot 'WGestures.App\Program.cs') -Raw -Encoding UTF8
$constantsText = Get-Content -LiteralPath (Join-Path $repoRoot 'WGestures.App\Constants.cs') -Raw -Encoding UTF8
$trackerText = Get-Content -LiteralPath `
    (Join-Path $repoRoot 'WGestures.Core\Impl\Windows\Win32MousePathTracker2.cs') -Raw -Encoding UTF8
$parserText = Get-Content -LiteralPath `
    (Join-Path $repoRoot 'WGestures.Core\GestureParser.cs') -Raw -Encoding UTF8
$gestureIntentText = Get-Content -LiteralPath `
    (Join-Path $repoRoot 'WGestures.Core\GestureIntent.cs') -Raw -Encoding UTF8
$windowCommandText = Get-Content -LiteralPath `
    (Join-Path $repoRoot 'WGestures.Core\Commands\Impl\WindowControlCommand.cs') -Raw -Encoding UTF8
$hotKeyText = Get-Content -LiteralPath `
    (Join-Path $repoRoot 'WGestures.Core\Commands\Impl\HotKeyCommand.cs') -Raw -Encoding UTF8
$pathTrackerText = Get-Content -LiteralPath (Join-Path $repoRoot 'WGestures.Core\IPathTracker.cs') -Raw -Encoding UTF8
$portableText = Get-Content -LiteralPath `
    (Join-Path $repoRoot 'WGestures.App\Migrate\PortableConfigService.cs') -Raw -Encoding UTF8
$settingsText = Get-Content -LiteralPath `
    (Join-Path $repoRoot 'WGestures.App\Gui\Windows\SettingsForm.cs') -Raw -Encoding UTF8
$settingsDesignerText = Get-Content -LiteralPath `
    (Join-Path $repoRoot 'WGestures.App\Gui\Windows\SettingsForm.Designer.cs') -Raw -Encoding UTF8
$canvasViewText = Get-Content -LiteralPath `
    (Join-Path $repoRoot 'WGestures.View\Impl\Windows\CanvasWindowGestureView.cs') -Raw -Encoding UTF8
$panelConfigText = Get-Content -LiteralPath `
    (Join-Path $repoRoot 'WGestures.App\QuickPanel\PanelConfig.cs') -Raw -Encoding UTF8
$panelFormText = Get-Content -LiteralPath `
    (Join-Path $repoRoot 'WGestures.App\QuickPanel\QuickPanelForm.cs') -Raw -Encoding UTF8
$defaultGestures = Get-Content -LiteralPath $defaultGesturesPath -Raw -Encoding UTF8 | ConvertFrom-Json

if ($manifestText -match 'uiAccess="true"' -or
    $manifestText -notmatch 'level="requireAdministrator"') {
    throw 'Unsigned release builds must run elevated instead of depending on the original uiAccess certificate.'
}
if ($manifestText -notmatch '8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a') {
    throw 'Release manifest is missing the Windows 10/11 compatibility identifier.'
}
if ($appProjectText -match 'YingDevSPC|SIGNPASS') {
    throw 'The public Windows build still depends on the original private signing material.'
}
if ($windowsInputProjectText -notmatch '<SignAssembly>false</SignAssembly>' -or
    $windowsInputProjectText -match 'AssemblyOriginatorKeyFile|WindowsInput\.snk') {
    throw 'WindowsInput must build from a clean checkout without a private strong-name key.'
}
if ($appProjectText -notmatch '<AssemblyName>WGestures</AssemblyName>' -or
    $appProjectText -notmatch 'CrossGestures\.exe') {
    throw 'The Windows build must preserve the WGestures assembly identity and emit CrossGestures.exe.'
}
if ($commonProjectText -notmatch 'GlobalKeyboardHook\.Win32\.cs' -or
    $commonProjectText -match 'Compile Include="OsSpecific\\Windows\\GlobalKeyboardHook\.cs"') {
    throw 'The x64-safe keyboard hook is not the implementation compiled by WGestures.Common.'
}
if ($programText -match 'defaults/gestures\.wg"') {
    throw 'Corrupt gesture recovery still references the removed gestures.wg default.'
}
if ($programText -notmatch 'Text = "弹出快捷面板"' -or
    $programText -notmatch 'quickPanel\.ShowAt\(Cursor\.Position\)' -or
    $panelFormText -notmatch 'CalculateLayoutScale') {
    throw 'Windows tray fallback or per-monitor quick-panel scaling is missing.'
}
if ($programText -match 'ShowQuickStartGuide|快速入门' -or
    $appProjectText -match 'QuickStartGuide\\' -or
    $installerScriptText -notmatch 'Excludes:.*QuickStartGuide\\\*' -or
    $installerScriptText -notmatch 'filesandordirs; Name: "\{app\}\\QuickStartGuide"') {
    throw 'The Windows startup tutorial must not be launched, exposed, or packaged.'
}
if ($constantsText -notmatch 'Identifier = "com\.jtl520\.CrossGestures"' -or
    $constantsText -notmatch 'IpcPipeName = "CrossGestures_IPC_API"' -or
    $programText -notmatch 'AutoStarter\.Register\(Constants\.AutoStartIdentifier' -or
    $programText -match 'AutoStarter\.Register\(Constants\.Identifier') {
    throw 'CrossGestures runtime identity must not collide with legacy WGestures.'
}
if ($trackerText -notmatch 'e\.key == Keys\.Escape' -or
    $trackerText -notmatch 'Post\(WM\.GESTBTN_CANCEL\)' -or
    $pathTrackerText -notmatch 'event PathTrackEventHandler PathCanceled') {
    throw 'Windows gesture cancellation must suppress Escape and cancel the active path.'
}
if ($trackerText -notmatch 'UpdateContextAndEventArgs\(true\)' -or
    $trackerText -notmatch 'Native\.GetForegroundWindow\(\)' -or
    $hotKeyText -notmatch 'Context\.WinId' -or
    $hotKeyText -notmatch 'SendModifiedKeyStrokeWithPacing' -or
    $hotKeyText -notmatch 'transitionDelayMillis = 25' -or
    $hotKeyText -match 'WindowFromPoint') {
    throw 'Windows shortcuts must keep the mouse-down target and pace key transitions reliably.'
}
if ($windowCommandText -notmatch 'Context\.WinId' -or
    $windowCommandText -notmatch 'SWP_NOACTIVATE' -or
    $windowCommandText -match 'var cursorWin = Native\.WindowFromPoint' -or
    $gestureIntentText -match 'SetProcessWorkingSetSize|GC\.Collect') {
    throw 'Window actions must use the mouse-down target and must not evict the quick-panel working set.'
}
if ($hotKeyText -notmatch 'TryGetConsoleClipboardShortcut' -or
    $hotKeyText -notmatch 'VirtualKeyCode\.INSERT' -or
    $hotKeyText -notmatch 'IsLegacyConsoleMenuShortcut' -or
    $hotKeyText -notmatch 'IsWindowsTerminalTarget' -or
    $hotKeyText -notmatch 'VirtualKeyCode\.LSHIFT') {
    throw 'Windows console copy/paste must distinguish Terminal native shortcuts from Console Host.'
}
if ($autoStarterText -notmatch 'Schedule\.Service' -or
    $autoStarterText -notmatch 'TaskRunLevelHighest' -or
    $installerScriptText -notmatch 'PrivilegesRequired=admin' -or
    $installerScriptText -notmatch 'DefaultDirName=\{autopf\}\\CrossGestures' -or
    $installerScriptText -notmatch 'ArchitecturesAllowed=x86compatible' -or
    $installerScriptText -notmatch 'ArchitecturesInstallIn64BitMode=x64compatible' -or
    $installerScriptText -notmatch 'schtasks\.exe') {
    throw 'Elevated Windows builds must install securely and autostart through a highest-privilege task.'
}
if ($installerScriptText -notmatch
    'Flags:\s+nowait\s+postinstall\s+skipifsilent\s+runascurrentuser') {
    throw 'The post-install launch must inherit Setup elevation because CrossGestures requires administrator privileges.'
}
$hotCornerCommands = @($defaultGestures.HotCornerCommands)
$rightTopCommand = $hotCornerCommands[2]
$unexpectedDefaults = @(@(0, 1, 3, 4, 5, 6, 7) | Where-Object {
    $null -ne $hotCornerCommands[$_]
})
if ($hotCornerCommands.Count -ne 8 -or
    $unexpectedDefaults.Count -ne 0 -or
    $null -eq $rightTopCommand -or
    $rightTopCommand.'$type' -notmatch 'HotKeyCommand' -or
    @($rightTopCommand.Modifiers).Count -ne 1 -or
    $rightTopCommand.Modifiers[0] -ne 91 -or
    @($rightTopCommand.Keys).Count -ne 1 -or
    $rightTopCommand.Keys[0] -ne 9) {
    throw 'Windows defaults must assign only the top-right corner to Win+Tab.'
}
if ($parserText -notmatch 'FindTolerantSingleDirectionIntent' -or
    $parserText -notmatch 'error <= 35\.0f') {
    throw 'Windows single-direction gestures must retain the documented 35-degree tolerance.'
}
if ($programText -match 'maxStackSize:\s*1' -or $trackerText -match 'maxStackSize:\s*1') {
    throw 'Long-lived Windows threads must use the runtime default stack size.'
}
if ($canvasViewText -notmatch 'readonly object _viewSync = new object\(\)' -or
    $canvasViewText -notmatch 'lock \(_viewSync\)' -or
    $canvasViewText -notmatch 'String\.IsNullOrEmpty\(text\)' -or
    $canvasViewText -notmatch '_labelPath\.AddString\(text,' -or
    $canvasViewText -match '_labelPath\.AddString\(_labelText,') {
    throw 'Windows gesture rendering must serialize fade-out and reject empty label text.'
}
if ($portableText -notmatch 'crossgestures-portable' -or
    $settingsText -notmatch '\.cgestures' -or
    $settingsText -notmatch 'github\.com/yingDev/WGestures') {
    throw 'Windows portable configuration or upstream attribution is missing.'
}
if ($settingsText -match 'File\.ReadAllText.*UpdateLog' -or
    $settingsDesignerText -notmatch 'flowLayoutPanel7\.Visible = false' -or
    $settingsDesignerText -notmatch 'linkLabel2\.Visible = false') {
    throw 'The simplified About page must not show the old update log, email or donation panel.'
}
if ($panelConfigText -notmatch 'Schema\s*=\s*1' -or
    $panelConfigText -notmatch 'SlotCount\s*=\s*16' -or
    $panelConfigText -notmatch 'UriSchemeHttp' -or
    $panelConfigText -notmatch '\.lnk' -or
    $panelFormText -notmatch 'PanelVisibilityChanged' -or
    $panelFormText -notmatch 'GetDpiForMonitor' -or
    $panelFormText -notmatch 'AddCreateMenuItem' -or
    $panelFormText -notmatch '"启动软件"' -or
    $panelFormText -notmatch '"打开文件"' -or
    $panelFormText -notmatch '"打开文件夹"' -or
    $panelFormText -notmatch '"打开网址"' -or
    $panelFormText -notmatch 'RunAfterMenuClosed' -or
    $panelFormText -notmatch 'QueueIconLoad' -or
    $panelFormText -notmatch 'ResolveShortcutTarget\(iconTarget\)' -or
    $programText -notmatch 'quick panel UI burst' -or
    $trackerText -notmatch 'MiddlePanelRequested' -or
    $trackerText -notmatch 'PanelInteractionActive' -or
    $programText -notmatch 'MiddlePanelEnabled' -or
    $programText -notmatch 'user-data-directory') {
    throw 'Windows quick panel schema or middle-button arbitration is incomplete.'
}

if (-not $SourceOnly) {
    $outputDir = Join-Path $repoRoot 'WGestures.App\bin\Release'
    if (Test-Path -LiteralPath (Join-Path $outputDir 'QuickStartGuide')) {
        throw 'The Windows build output still contains the startup tutorial.'
    }
    $requiredFiles = @(
        'CrossGestures.exe',
        'CrossGestures.exe.config',
        'WGestures.Common.dll',
        'WGestures.Core.dll',
        'WGestures.View.dll',
        'WindowsInput.dll',
        'NativeMultiFileArchiveLib.dll',
        'Newtonsoft.Json.dll',
        'NLua.dll',
        'KeraLua.dll',
        'defaults\config.plist',
        'defaults\gestures.wg2'
    )

    foreach ($relativePath in $requiredFiles) {
        $path = Join-Path $outputDir $relativePath
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Missing Windows build output: $relativePath"
        }
    }

    $version = [Diagnostics.FileVersionInfo]::GetVersionInfo(
        (Join-Path $outputDir 'CrossGestures.exe')).FileVersion
    if ($version -ne '2.1.8.0') {
        throw "Unexpected CrossGestures.exe version: $version"
    }

    $appExePath = Join-Path $outputDir 'CrossGestures.exe'
    $fileInfo = [Diagnostics.FileVersionInfo]::GetVersionInfo($appExePath)
    if ($fileInfo.ProductName -ne 'CrossGestures') {
        throw "Unexpected Windows product name: $($fileInfo.ProductName)"
    }
    $assemblyName = [Reflection.AssemblyName]::GetAssemblyName($appExePath).Name
    if ($assemblyName -ne 'WGestures') {
        throw "Legacy .wg2 compatibility requires the WGestures assembly identity: $assemblyName"
    }
}

if ($InstallerPath) {
    $resolvedInstaller = Resolve-Path -LiteralPath $InstallerPath
    if ([IO.Path]::GetFileName($resolvedInstaller.Path) -notlike 'CrossGestures-*-Windows-Setup.exe') {
        throw "Unexpected Windows installer name: $resolvedInstaller"
    }
    if ([IO.Path]::GetExtension($resolvedInstaller.Path) -ne '.exe') {
        throw "Windows installer is not an .exe: $resolvedInstaller"
    }
    if ((Get-Item -LiteralPath $resolvedInstaller.Path).Length -lt 1MB) {
        throw "Windows installer is unexpectedly small: $resolvedInstaller"
    }
}

Write-Host 'Windows source and build checks passed.'
