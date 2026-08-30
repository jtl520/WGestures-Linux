param(
    [string]$OutputDirectory = "$PSScriptRoot\..\build\windows-panel-live"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class CrossGesturesLivePanelNative {
    public delegate bool EnumWindowsProc(IntPtr window, IntPtr parameter);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr window, out RECT rect);
    [DllImport("user32.dll")] public static extern long GetWindowLongPtr(IntPtr window, int index);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
}
'@
[CrossGesturesLivePanelNative]::SetProcessDPIAware() | Out-Null

function Get-PanelWindow([int]$ProcessId) {
    $script:foundPanel = [IntPtr]::Zero
    $callback = [CrossGesturesLivePanelNative+EnumWindowsProc]{
        param([IntPtr]$window, [IntPtr]$parameter)
        [uint32]$owner = 0
        [CrossGesturesLivePanelNative]::GetWindowThreadProcessId($window, [ref]$owner) | Out-Null
        if ($owner -ne $ProcessId -or -not [CrossGesturesLivePanelNative]::IsWindowVisible($window)) {
            return $true
        }
        $rect = New-Object CrossGesturesLivePanelNative+RECT
        $style = [CrossGesturesLivePanelNative]::GetWindowLongPtr($window, -16)
        if ([CrossGesturesLivePanelNative]::GetWindowRect($window, [ref]$rect) -and
            # The trail canvas is a persistent 400x300 captioned window in this
            # environment. The quick panel is borderless (no WS_CAPTION).
            ($style -band 0x00C00000) -eq 0 -and
            ($rect.Right - $rect.Left) -ge 350 -and ($rect.Bottom - $rect.Top) -ge 300) {
            $script:foundPanel = $window
            return $false
        }
        return $true
    }
    [CrossGesturesLivePanelNative]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
    return $script:foundPanel
}

function Send-MiddleClick([int]$X, [int]$Y) {
    [CrossGesturesLivePanelNative]::SetCursorPos($X, $Y) | Out-Null
    [CrossGesturesLivePanelNative]::mouse_event(0x0020, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 35
    [CrossGesturesLivePanelNative]::mouse_event(0x0040, 0, 0, 0, [UIntPtr]::Zero)
}

function Wait-PanelState([int]$ProcessId, [bool]$Visible, [int]$TimeoutMs = 1500) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    do {
        $window = Get-PanelWindow $ProcessId
        if (($window -ne [IntPtr]::Zero) -eq $Visible) {
            return [pscustomobject]@{ Milliseconds = $timer.Elapsed.TotalMilliseconds; Window = $window }
        }
        Start-Sleep -Milliseconds 2
    } while ($timer.ElapsedMilliseconds -lt $TimeoutMs)
    throw "Panel did not reach visible=$Visible within ${TimeoutMs}ms."
}

$process = Get-Process -Name CrossGestures -ErrorAction Stop | Select-Object -First 1
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$area = [Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$x = [int]($area.Left + $area.Width / 2)
$y = [int]($area.Top + $area.Height / 2)

# Normalize to hidden before measuring.
if ((Get-PanelWindow $process.Id) -ne [IntPtr]::Zero) {
    Send-MiddleClick $x $y
    Wait-PanelState $process.Id $false | Out-Null
}

$samples = @()
for ($index = 0; $index -lt 12; $index++) {
    $expected = ($index % 2) -eq 0
    Send-MiddleClick $x $y
    $state = Wait-PanelState $process.Id $expected
    $samples += [pscustomobject]@{
        sequence = $index + 1
        visible = $expected
        latencyMs = [Math]::Round($state.Milliseconds, 2)
    }
    Start-Sleep -Milliseconds 60
}

# Leave it open long enough for asynchronous real icons to settle, then capture.
Send-MiddleClick $x $y
$shown = Wait-PanelState $process.Id $true
Start-Sleep -Seconds 7
$window = Get-PanelWindow $process.Id
$rect = New-Object CrossGesturesLivePanelNative+RECT
[CrossGesturesLivePanelNative]::GetWindowRect($window, [ref]$rect) | Out-Null
$bounds = [Drawing.Rectangle]::FromLTRB($rect.Left, $rect.Top, $rect.Right, $rect.Bottom)
$bitmap = New-Object Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Location, [Drawing.Point]::Empty, $bounds.Size)
$screenshot = Join-Path $OutputDirectory 'panel-real-config.png'
$bitmap.Save($screenshot, [Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()

Send-MiddleClick $x $y
Wait-PanelState $process.Id $false | Out-Null
for ($index = 0; $index -lt 9; $index++) {
    Send-MiddleClick $x $y
}
$burst = Wait-PanelState $process.Id $true
Send-MiddleClick $x $y
Wait-PanelState $process.Id $false | Out-Null

$showSamples = @($samples | Where-Object visible | ForEach-Object latencyMs)
$result = [ordered]@{
    processId = $process.Id
    samples = $samples
    showMaxMs = ($showSamples | Measure-Object -Maximum).Maximum
    showAverageMs = [Math]::Round(($showSamples | Measure-Object -Average).Average, 2)
    burstOddRecovered = $true
    burstLatencyMs = [Math]::Round($burst.Milliseconds, 2)
    screenshot = $screenshot
}
$summary = Join-Path $OutputDirectory 'summary.json'
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summary -Encoding UTF8
$result | ConvertTo-Json -Depth 5
