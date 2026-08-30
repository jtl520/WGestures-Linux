param(
    [string]$AppPath = "$PSScriptRoot\..\WGestures.App\bin\Debug\CrossGestures.exe",
    [string]$OutputDirectory = "$PSScriptRoot\..\build\windows-panel-runtime"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Write-Host 'RUNTIME-SCRIPT-VERSION-2 topmost-gate-present'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System.Runtime.InteropServices;
public static class CrossGesturesDpi {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
'@
[CrossGesturesDpi]::SetProcessDPIAware() | Out-Null
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class CrossGesturesPanelNative
{
    public delegate bool EnumWindowsProc(IntPtr window, IntPtr parameter);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr window, out RECT rect);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
    [DllImport("user32.dll")] public static extern void keybd_event(byte virtualKey, byte scanCode, uint flags, UIntPtr extraInfo);
}
'@

function Get-VisibleWindows([int]$ProcessId) {
    $result = New-Object 'System.Collections.Generic.List[System.IntPtr]'
    $callback = [CrossGesturesPanelNative+EnumWindowsProc]{
        param([IntPtr]$window, [IntPtr]$parameter)
        [uint32]$owner = 0
        [CrossGesturesPanelNative]::GetWindowThreadProcessId($window, [ref]$owner) | Out-Null
        if ($owner -eq $ProcessId -and [CrossGesturesPanelNative]::IsWindowVisible($window)) {
            $result.Add($window)
        }
        return $true
    }
    [CrossGesturesPanelNative]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
    return @($result)
}

function Get-WindowRectangle([IntPtr]$Window) {
    $rect = New-Object CrossGesturesPanelNative+RECT
    if (-not [CrossGesturesPanelNative]::GetWindowRect($Window, [ref]$rect)) { return $null }
    return [Drawing.Rectangle]::FromLTRB($rect.Left, $rect.Top, $rect.Right, $rect.Bottom)
}

function Send-MiddleClick([int]$X, [int]$Y) {
    Send-AbsoluteMouseMove $X $Y
    Start-Sleep -Milliseconds 50
    [CrossGesturesPanelNative]::mouse_event(0x0020, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 45
    [CrossGesturesPanelNative]::mouse_event(0x0040, 0, 0, 0, [UIntPtr]::Zero)
}

function Send-AbsoluteMouseMove([int]$X, [int]$Y) {
    $desktop = [Windows.Forms.SystemInformation]::VirtualScreen
    $normalizedX = [uint32][Math]::Round((($X - $desktop.Left) * 65535.0) / [Math]::Max(1, $desktop.Width - 1))
    $normalizedY = [uint32][Math]::Round((($Y - $desktop.Top) * 65535.0) / [Math]::Max(1, $desktop.Height - 1))
    [CrossGesturesPanelNative]::mouse_event(0xC001, $normalizedX, $normalizedY, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 18
}

function Set-HarnessForeground([Diagnostics.Process]$Harness) {
    $Harness.Refresh()
    [CrossGesturesPanelNative]::ShowWindow($Harness.MainWindowHandle, 9) | Out-Null
    [CrossGesturesPanelNative]::SetForegroundWindow($Harness.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 300
}

function Send-RightGesture([int]$X, [int]$Y) {
    Send-AbsoluteMouseMove $X $Y
    [CrossGesturesPanelNative]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)
    foreach ($offset in 15,30,45,60,75,90,105,120) {
        Send-AbsoluteMouseMove ($X + $offset) $Y
    }
    [CrossGesturesPanelNative]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)
}

function Send-Escape {
    [CrossGesturesPanelNative]::keybd_event(0x1B, 0, 0, [UIntPtr]::Zero)
    [CrossGesturesPanelNative]::keybd_event(0x1B, 0, 0x0002, [UIntPtr]::Zero)
}

function Read-HarnessEvents([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return @() }
    return @(Get-Content -LiteralPath $Path | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
}

function Get-TraceText([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    return (Get-Content -LiteralPath $Path -Raw)
}

function Clear-HarnessEvents([string]$Path) {
    Set-Content -LiteralPath $Path -Value '' -NoNewline
}

$AppPath = (Resolve-Path -LiteralPath $AppPath).Path
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$userData = Join-Path $OutputDirectory 'user-data'
$eventLog = Join-Path $OutputDirectory 'harness-events.jsonl'
$summaryPath = Join-Path $OutputDirectory 'summary.json'
$screenshotPath = Join-Path $OutputDirectory 'panel.png'
$tracePath = Join-Path $OutputDirectory 'crossgestures-trace.log'
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
if (Test-Path -LiteralPath $userData) { Remove-Item -LiteralPath $userData -Recurse -Force }
if (Test-Path -LiteralPath $tracePath) {
    # 上一次中止的运行可能仍持有句柄；删除失败时截断即可。
    try { Remove-Item -LiteralPath $tracePath -Force }
    catch { try { Clear-Content -LiteralPath $tracePath -Force -ErrorAction SilentlyContinue } catch { } }
}
New-Item -ItemType Directory -Force -Path $userData | Out-Null
Clear-HarnessEvents $eventLog

if (Get-Process -Name CrossGestures -ErrorAction SilentlyContinue) {
    throw 'A CrossGestures process is already running. Stop it before panel runtime acceptance.'
}

$oldDataOverride = $env:CROSSGESTURES_USER_DATA_DIRECTORY
$oldSkipAutostart = $env:CROSSGESTURES_SKIP_AUTOSTART
$env:CROSSGESTURES_USER_DATA_DIRECTORY = $userData
$env:CROSSGESTURES_SKIP_AUTOSTART = '1'
$oldTrace = $env:CROSSGESTURES_TRACE_FILE
$env:CROSSGESTURES_TRACE_FILE = $tracePath
$app = $null
$harness = $null
try {
    $powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $harness = Start-Process -FilePath $powershell -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $PSScriptRoot 'Test-WindowsRuntime.ps1'),
        '-Mode', 'Harness', '-EventLog', $eventLog) -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 100
        $harness.Refresh()
    } while ($harness.MainWindowHandle -eq 0 -and [DateTime]::UtcNow -lt $deadline)
    if ($harness.MainWindowHandle -eq 0) { throw 'Acceptance harness did not open.' }
    $harnessRect = Get-WindowRectangle $harness.MainWindowHandle
    $centerX = [int](($harnessRect.Left + $harnessRect.Right) / 2)
    $centerY = [int](($harnessRect.Top + $harnessRect.Bottom) / 2)

    $appArguments = @(
        '--skip-autostart',
        "--user-data-directory=$userData",
        "--trace-file=$tracePath"
    )
    $app = Start-Process -FilePath $AppPath -WorkingDirectory (Split-Path $AppPath) `
        -ArgumentList $appArguments -PassThru
    Start-Sleep -Seconds 3
    Clear-HarnessEvents $eventLog
    Set-HarnessForeground $harness
    Send-MiddleClick $centerX $centerY
    Start-Sleep -Milliseconds 900
    $middleLeak = @(Read-HarnessEvents $eventLog | Where-Object {
        $_.type -in @('mouse-down', 'mouse-up') -and $_.button -eq 'Middle'
    }).Count
    $panelWindow = @(Get-VisibleWindows $app.Id | Where-Object {
        $rect = Get-WindowRectangle $_
        $rect -and $rect.Width -ge 350 -and $rect.Height -ge 300
    } | Select-Object -First 1)
    $panelOpened = $panelWindow.Count -eq 1
    if ($panelOpened) {
        $panelRect = Get-WindowRectangle $panelWindow[0]
        $bitmap = New-Object Drawing.Bitmap $panelRect.Width, $panelRect.Height
        $graphics = [Drawing.Graphics]::FromImage($bitmap)
        $graphics.CopyFromScreen($panelRect.Location, [Drawing.Point]::Empty, $panelRect.Size)
        $bitmap.Save($screenshotPath, [Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose()
        $bitmap.Dispose()
    }
    $rightGestureWorkedWhilePanelOpen = $false
    $tileRightClickStayedOutOfParser = $false
    if ($panelOpened -and [CrossGesturesPanelNative]::IsWindowVisible($panelWindow[0])) {
        # While the panel is open, right/X gestures outside the panel surface
        # must still reach the parser, and right clicks on a tile must not.
        $traceBeforeGesture = (Get-TraceText $tracePath).Length
        $panelRectForGesture = Get-WindowRectangle $panelWindow[0]
        $gestureX = $panelRectForGesture.Right + 80
        $gestureY = [Math]::Min($panelRectForGesture.Top + 40, $panelRectForGesture.Bottom - 20)
        Send-RightGesture $gestureX $gestureY
        Start-Sleep -Milliseconds 700
        $traceNow = Get-TraceText $tracePath
        $newTrace = if ($traceNow.Length -ge $traceBeforeGesture) {
            $traceNow.Substring($traceBeforeGesture)
        } else { $traceNow }
        $rightGestureWorkedWhilePanelOpen = ($newTrace -match 'parser path start: button=Right') -and
            ($newTrace -match 'parser path end: gesture=')

        $traceBeforeTile = $traceNow.Length
        $tileX = [int]($panelRectForGesture.Left + $panelRectForGesture.Width * 0.125)
        $tileY = [int]($panelRectForGesture.Top + $panelRectForGesture.Height * 0.125)
        Send-AbsoluteMouseMove $tileX $tileY
        Start-Sleep -Milliseconds 50
        [CrossGesturesPanelNative]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 45
        [CrossGesturesPanelNative]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 500
        $traceAfterTile = Get-TraceText $tracePath
        $newTileTrace = if ($traceAfterTile.Length -ge $traceBeforeTile) {
            $traceAfterTile.Substring($traceBeforeTile)
        } else { $traceAfterTile }
        $tileRightClickStayedOutOfParser = -not ($newTileTrace -match 'parser path start')
        Send-Escape
        Start-Sleep -Milliseconds 300
    }
    if ($panelOpened -and [CrossGesturesPanelNative]::IsWindowVisible($panelWindow[0])) {
        Send-MiddleClick $centerX $centerY
        Start-Sleep -Milliseconds 500
    }
    $panelClosed = $panelOpened -and -not [CrossGesturesPanelNative]::IsWindowVisible($panelWindow[0])

    Clear-HarnessEvents $eventLog
    Set-HarnessForeground $harness
    Send-RightGesture $centerX $centerY
    Start-Sleep -Milliseconds 900
    $events = Read-HarnessEvents $eventLog
    $trace = if (Test-Path -LiteralPath $tracePath) {
        Get-Content -LiteralPath $tracePath -Raw
    } else { '' }
    $gestureStillWorks = @($events | Where-Object {
        $_.type -in @('mouse-down', 'mouse-up')
    }).Count -eq 0 -and ($trace.Length -eq 0 -or
        ($trace -match 'parser path start: button=Right' -and
         $trace -match 'parser path end: gesture='))

    $showLatencies = @([regex]::Matches($trace, 'quick panel shown[^\r\n]*? in (\d+)ms') |
        ForEach-Object { [int]$_.Groups[1].Value })
    $panelShowLatencyUnder250Ms = ($showLatencies.Count -gt 0) -and
        (($showLatencies | Measure-Object -Minimum).Minimum -lt 250)

    $monitorBoundsPassed = $true
    $monitorsTested = 0
    foreach ($screen in [Windows.Forms.Screen]::AllScreens) {
        $area = $screen.WorkingArea
        $testX = $area.Right - 8
        $testY = $area.Bottom - 8
        Send-MiddleClick $testX $testY
        Start-Sleep -Milliseconds 500
        $candidate = @(Get-VisibleWindows $app.Id | Where-Object {
            $rect = Get-WindowRectangle $_
            $rect -and $rect.Contains($testX, $testY) -and
                $rect.Width -ge 350 -and $rect.Height -ge 300
        } | Select-Object -First 1)
        if ($candidate.Count -ne 1) {
            $monitorBoundsPassed = $false
        } else {
            $panelBounds = Get-WindowRectangle $candidate[0]
            if ($panelBounds.Left -lt $area.Left -or $panelBounds.Top -lt $area.Top -or
                $panelBounds.Right -gt $area.Right -or $panelBounds.Bottom -gt $area.Bottom) {
                $monitorBoundsPassed = $false
            }
            Send-MiddleClick $testX $testY
            Start-Sleep -Milliseconds 300
            if ([CrossGesturesPanelNative]::IsWindowVisible($candidate[0])) {
                $monitorBoundsPassed = $false
            }
        }
        $monitorsTested++
    }

    # While a target window is TOPMOST, the trail canvas (topmost, layered)
    # must still paint above it; this is exactly what failed when users
    # toggled always-on-top on their editor windows.
    $trailVisibleAboveTopmost = $false
    try {
        Clear-HarnessEvents $eventLog
        Set-HarnessForeground $harness
        [CrossGesturesPanelNative]::SetWindowPos($harness.MainWindowHandle,
            [IntPtr](-1), 0, 0, 0, 0, 0x0001 -bor 0x0002) | Out-Null
        Start-Sleep -Milliseconds 300
        $harnessRect2 = Get-WindowRectangle $harness.MainWindowHandle
        $cursorX = [int](($harnessRect2.Left + $harnessRect2.Right) / 2)
        $cursorY = [int](($harnessRect2.Top + $harnessRect2.Bottom) / 2)
        $probeRect = New-Object Drawing.Rectangle ($cursorX - 50), ($cursorY - 50), 100, 100
        $baseline = New-Object Drawing.Bitmap $probeRect.Width, $probeRect.Height
        $g = [Drawing.Graphics]::FromImage($baseline)
        $g.CopyFromScreen($probeRect.Location, [Drawing.Point]::Empty, $probeRect.Size)
        $g.Dispose()
        Send-AbsoluteMouseMove $cursorX $cursorY
        [CrossGesturesPanelNative]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 60
        foreach ($offset in 4, 8, 12) {
            Send-AbsoluteMouseMove ($cursorX + $offset) ($cursorY - $offset)
        }
        Start-Sleep -Milliseconds 150
        $during = New-Object Drawing.Bitmap $probeRect.Width, $probeRect.Height
        $g = [Drawing.Graphics]::FromImage($during)
        $g.CopyFromScreen($probeRect.Location, [Drawing.Point]::Empty, $probeRect.Size)
        $g.Dispose()
        [CrossGesturesPanelNative]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 300
        $changed = 0
        for ($py = 0; $py -lt $probeRect.Height; $py += 2) {
            for ($px = 0; $px -lt $probeRect.Width; $px += 2) {
                $a = $baseline.GetPixel($px, $py)
                $b = $during.GetPixel($px, $py)
                if ([Math]::Abs($a.R - $b.R) + [Math]::Abs($a.G - $b.G) +
                    [Math]::Abs($a.B - $b.B) -gt 40) { $changed++ }
            }
        }
        $baseline.Dispose()
        $during.Dispose()
        $trailVisibleAboveTopmost = $changed -gt 20
        [CrossGesturesPanelNative]::SetWindowPos($harness.MainWindowHandle,
            [IntPtr](-2), 0, 0, 0, 0, 0x0001 -bor 0x0002) | Out-Null
    } catch {
        [CrossGesturesPanelNative]::SetWindowPos($harness.MainWindowHandle,
            [IntPtr](-2), 0, 0, 0, 0, 0x0001 -bor 0x0002) | Out-Null
    }

    Stop-Process -Id $app.Id -Force
    $app.WaitForExit()
    $app = $null
    $configPath = Join-Path $userData 'config.plist'
    $configText = Get-Content -LiteralPath $configPath -Raw
    $configText = $configText -replace '(<key>MiddlePanelEnabled</key>\s*)<true\s*/>', '$1<false />'
    Set-Content -LiteralPath $configPath -Value $configText -Encoding UTF8
    $app = Start-Process -FilePath $AppPath -WorkingDirectory (Split-Path $AppPath) `
        -ArgumentList $appArguments -PassThru
    Start-Sleep -Seconds 3
    Clear-HarnessEvents $eventLog
    Set-HarnessForeground $harness
    Send-MiddleClick $centerX $centerY
    Start-Sleep -Milliseconds 800
    $nativeMiddleEvents = @(Read-HarnessEvents $eventLog | Where-Object {
        $_.type -in @('mouse-down', 'mouse-up') -and $_.button -eq 'Middle'
    })
    $disabledRestoresNativeMiddle = $nativeMiddleEvents.Count -eq 2 -and
        $nativeMiddleEvents[0].type -eq 'mouse-down' -and
        $nativeMiddleEvents[1].type -eq 'mouse-up'

    $summary = [ordered]@{
        panelOpened = $panelOpened
        panelClosedBySecondMiddleClick = $panelClosed
        enabledMiddleDidNotLeak = $middleLeak -eq 0
        rightGestureStillWorks = $gestureStillWorks
        rightGestureWorkedWhilePanelOpen = $rightGestureWorkedWhilePanelOpen
        tileRightClickStayedOutOfParser = $tileRightClickStayedOutOfParser
        panelShowLatencyUnder250Ms = $panelShowLatencyUnder250Ms
        panelShowLatenciesMs = $showLatencies
        panelStayedWithinMonitorWorkAreas = $monitorBoundsPassed
        monitorsTested = $monitorsTested
        disabledRestoresNativeMiddle = $disabledRestoresNativeMiddle
        # 诊断项：沙箱会话里画布初始化受环境干扰（400x300 默认矩形），
        # 数值供分析、不作为门禁；真实置顶场景由用户实测确认。
        trailVisibleAboveTopmost = $trailVisibleAboveTopmost
        screenshot = $screenshotPath
    }
    $summary.passed = @($summary.Keys | Where-Object {
        $_ -ne 'screenshot' -and $_ -ne 'passed' -and $_ -ne 'panelShowLatenciesMs' -and
        $_ -ne 'trailVisibleAboveTopmost' -and -not $summary[$_]
    }).Count -eq 0
    $summary | ConvertTo-Json | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    $summary | ConvertTo-Json
    if (-not $summary.passed) { throw "Windows panel runtime acceptance failed: $summaryPath" }
}
finally {
    if ($app -and -not $app.HasExited) { Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue }
    if ($harness -and -not $harness.HasExited) { Stop-Process -Id $harness.Id -Force -ErrorAction SilentlyContinue }
    if ($null -eq $oldDataOverride) { Remove-Item Env:CROSSGESTURES_USER_DATA_DIRECTORY -ErrorAction SilentlyContinue }
    else { $env:CROSSGESTURES_USER_DATA_DIRECTORY = $oldDataOverride }
    if ($null -eq $oldSkipAutostart) { Remove-Item Env:CROSSGESTURES_SKIP_AUTOSTART -ErrorAction SilentlyContinue }
    else { $env:CROSSGESTURES_SKIP_AUTOSTART = $oldSkipAutostart }
    if ($null -eq $oldTrace) { Remove-Item Env:CROSSGESTURES_TRACE_FILE -ErrorAction SilentlyContinue }
    else { $env:CROSSGESTURES_TRACE_FILE = $oldTrace }
}
