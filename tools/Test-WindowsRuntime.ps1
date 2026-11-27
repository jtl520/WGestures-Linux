param(
    [ValidateSet('Run', 'Harness')]
    [string]$Mode = 'Run',
    [string]$AppPath = "$env:ProgramFiles\CrossGestures\CrossGestures.exe",
    [string]$OutputDirectory = "$PSScriptRoot\..\build\windows-runtime",
    [string]$EventLog
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Mode -eq 'Harness') {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    function Write-HarnessEvent([string]$Type, [hashtable]$Data) {
        $eventData = [ordered]@{
            type = $Type
            timestampUtc = [DateTime]::UtcNow.ToString('o')
        }
        foreach ($entry in $Data.GetEnumerator()) {
            $eventData[$entry.Key] = $entry.Value
        }
        Add-Content -LiteralPath $EventLog -Value ($eventData | ConvertTo-Json -Compress)
    }

    $form = New-Object Windows.Forms.Form
    $form.Text = 'CrossGestures Acceptance Harness ' + $PID
    $form.StartPosition = 'Manual'
    $form.Location = New-Object Drawing.Point(300, 180)
    $form.Size = New-Object Drawing.Size(720, 480)
    $form.KeyPreview = $true

    $label = New-Object Windows.Forms.Label
    $label.AutoSize = $true
    $label.Location = New-Object Drawing.Point(30, 30)
    $label.Text = 'CrossGestures Windows runtime acceptance target'
    $form.Controls.Add($label)

    $form.Add_Shown({
        $form.Activate()
        $form.Focus()
        Write-HarnessEvent 'shown' @{ handle = $form.Handle.ToInt64(); processId = $PID }
    })
    $form.Add_MouseDown({
        param($sender, $eventArgs)
        Write-HarnessEvent 'mouse-down' @{ button = $eventArgs.Button.ToString() }
    })
    $form.Add_MouseUp({
        param($sender, $eventArgs)
        Write-HarnessEvent 'mouse-up' @{ button = $eventArgs.Button.ToString() }
    })
    $form.Add_KeyDown({
        param($sender, $eventArgs)
        Write-HarnessEvent 'key-down' @{
            key = $eventArgs.KeyCode.ToString()
            alt = $eventArgs.Alt
            control = $eventArgs.Control
            shift = $eventArgs.Shift
        }
    })
    $form.Add_KeyUp({
        param($sender, $eventArgs)
        Write-HarnessEvent 'key-up' @{
            key = $eventArgs.KeyCode.ToString()
            alt = $eventArgs.Alt
            control = $eventArgs.Control
            shift = $eventArgs.Shift
        }
    })

    [Windows.Forms.Application]::Run($form)
    exit 0
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;

public static class CrossGesturesAcceptanceNative
{
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindow(string className, string windowName);

    // PowerShell converts $null to an empty string for string parameters.
    public static IntPtr FindHarnessWindow(int processId)
    {
        return FindWindow(null, "CrossGestures Acceptance Harness " + processId);
    }

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int command);

    [DllImport("user32.dll")]
    public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);

    [DllImport("user32.dll")]
    public static extern void keybd_event(byte virtualKey, byte scanCode, uint flags, UIntPtr extraInfo);
}
'@

function Read-Events {
    if (-not (Test-Path -LiteralPath $EventLog)) { return @() }
    return @(Get-Content -LiteralPath $EventLog | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
}

function Clear-Events {
    Set-Content -LiteralPath $EventLog -Value '' -NoNewline
}

function Set-HarnessForeground([Diagnostics.Process]$Harness) {
    $Harness.Refresh()
    $handle = [CrossGesturesAcceptanceNative]::FindHarnessWindow($Harness.Id)
    if ($handle -eq [IntPtr]::Zero) { throw 'The acceptance form is no longer available.' }
    [CrossGesturesAcceptanceNative]::ShowWindow($handle, 9) | Out-Null
    [CrossGesturesAcceptanceNative]::SetForegroundWindow($handle) | Out-Null
    Start-Sleep -Milliseconds 300
}

function Send-AbsoluteMouseMove([int]$X, [int]$Y) {
    # SetCursorPos/Cursor.Position moves the pointer but does not reliably emit a
    # low-level WM_MOUSEMOVE hook event.  Use an absolute injected mouse event so
    # this acceptance test exercises the same hook path as physical movement.
    $desktop = [Windows.Forms.SystemInformation]::VirtualScreen
    $normalizedX = [uint32][Math]::Round((($X - $desktop.Left) * 65535.0) / [Math]::Max(1, $desktop.Width - 1))
    $normalizedY = [uint32][Math]::Round((($Y - $desktop.Top) * 65535.0) / [Math]::Max(1, $desktop.Height - 1))
    [CrossGesturesAcceptanceNative]::mouse_event(0xC001, $normalizedX, $normalizedY, 0, [UIntPtr]::Zero)
}

function Set-CursorPosition([int]$X, [int]$Y) {
    Send-AbsoluteMouseMove $X $Y
    Start-Sleep -Milliseconds 18
}

function Send-RightClick([int]$X, [int]$Y) {
    Set-CursorPosition $X $Y
    [CrossGesturesAcceptanceNative]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 45
    [CrossGesturesAcceptanceNative]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)
}

function Send-RightGesture([int[][]]$Points) {
    Set-CursorPosition $Points[0][0] $Points[0][1]
    [CrossGesturesAcceptanceNative]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)
    foreach ($point in $Points | Select-Object -Skip 1) {
        Set-CursorPosition $point[0] $point[1]
    }
    [CrossGesturesAcceptanceNative]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)
}

function Send-Escape {
    [CrossGesturesAcceptanceNative]::keybd_event(0x1B, 0, 0, [UIntPtr]::Zero)
    [CrossGesturesAcceptanceNative]::keybd_event(0x1B, 0, 0x0002, [UIntPtr]::Zero)
}

function Test-RightClickPair {
    $buttonEvents = @(Read-Events | Where-Object { $_.type -in @('mouse-down', 'mouse-up') -and $_.button -eq 'Right' })
    return $buttonEvents.Count -eq 2 -and $buttonEvents[0].type -eq 'mouse-down' -and $buttonEvents[1].type -eq 'mouse-up'
}

$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$EventLog = Join-Path $OutputDirectory 'harness-events.jsonl'
$summaryPath = Join-Path $OutputDirectory 'summary.json'
$tracePath = Join-Path $OutputDirectory 'crossgestures-trace.log'
Clear-Events
if (Test-Path -LiteralPath $tracePath) { Remove-Item -LiteralPath $tracePath -Force }
$env:CROSSGESTURES_TRACE_FILE = $tracePath

$startedApp = $false
$appProcess = $null
$harnessProcess = $null
try {
    if (-not (Test-Path -LiteralPath $AppPath -PathType Leaf)) {
        throw "CrossGestures executable was not found: $AppPath"
    }

    $existing = @(Get-Process -Name CrossGestures -ErrorAction SilentlyContinue)
    if ($existing.Count -eq 0) {
        $appProcess = Start-Process -FilePath $AppPath -WorkingDirectory (Split-Path $AppPath) -PassThru
        $startedApp = $true
    } else {
        $appProcess = $existing[0]
    }
    Start-Sleep -Seconds 3
    $appProcess = Get-Process -Id $appProcess.Id -ErrorAction Stop

    $windowsPowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $harnessProcess = Start-Process -FilePath $windowsPowerShell -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath,
        '-Mode', 'Harness', '-EventLog', $EventLog) -PassThru `
        -RedirectStandardOutput (Join-Path $OutputDirectory 'harness-stdout.log') `
        -RedirectStandardError (Join-Path $OutputDirectory 'harness-stderr.log')

    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 100
        $harnessProcess.Refresh()
        if ($harnessProcess.HasExited) {
            throw ('Acceptance harness exited: ' + (Get-Content (Join-Path $OutputDirectory 'harness-stderr.log') -Raw))
        }
        $harnessHandle = [CrossGesturesAcceptanceNative]::FindHarnessWindow($harnessProcess.Id)
    } while (($harnessHandle -eq [IntPtr]::Zero -or @(Read-Events | Where-Object { $_.type -eq 'shown' }).Count -eq 0) -and [DateTime]::UtcNow -lt $deadline)
    if ($harnessHandle -eq [IntPtr]::Zero) {
        throw ('Acceptance harness window did not open. Events: ' + (Get-Content $EventLog -Raw) +
            ' Error: ' + (Get-Content (Join-Path $OutputDirectory 'harness-stderr.log') -Raw))
    }

    $rect = New-Object CrossGesturesAcceptanceNative+RECT
    if (-not [CrossGesturesAcceptanceNative]::GetWindowRect($harnessHandle, [ref]$rect)) {
        throw 'Unable to query acceptance harness bounds.'
    }
    $centerX = [int](($rect.Left + $rect.Right) / 2)
    $centerY = [int](($rect.Top + $rect.Bottom) / 2)

    Set-HarnessForeground $harnessProcess
    Clear-Events
    Send-RightClick $centerX $centerY
    Start-Sleep -Milliseconds 800
    $shortClickPassed = Test-RightClickPair
    @(Read-Events) | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'short-click-events.json')

    Set-HarnessForeground $harnessProcess
    Clear-Events
    $rightPoints = @()
    for ($index = 0; $index -le 10; $index++) {
        $rightPoints += ,([int[]]@($centerX, ($centerY - ($index * 14))))
    }
    Send-RightGesture $rightPoints
    Start-Sleep -Milliseconds 900
    $rightEvents = Read-Events
    @($rightEvents) | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'shortcut-events.json')
    $shortcutPassed = @($rightEvents | Where-Object { $_.type -eq 'key-down' -and $_.key -eq 'C' -and $_.control }).Count -ge 1
    $validGestureNoClickLeak = @($rightEvents | Where-Object { $_.type -in @('mouse-down', 'mouse-up') }).Count -eq 0

    Set-HarnessForeground $harnessProcess
    Clear-Events
    $invalidPoints = @(
        ([int[]]@($centerX, $centerY)),
        ([int[]]@(($centerX + 60), $centerY)),
        ([int[]]@(($centerX + 140), $centerY)),
        ([int[]]@(($centerX + 60), $centerY)),
        ([int[]]@(($centerX - 40), $centerY))
    )
    Send-RightGesture $invalidPoints
    Start-Sleep -Milliseconds 700
    $invalidNoClickLeak = @(Read-Events | Where-Object { $_.type -in @('mouse-down', 'mouse-up') }).Count -eq 0

    Set-HarnessForeground $harnessProcess
    Clear-Events
    Set-CursorPosition $centerX $centerY
    [CrossGesturesAcceptanceNative]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)
    Set-CursorPosition ($centerX + 80) ($centerY + 30)
    Send-Escape
    [CrossGesturesAcceptanceNative]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 700
    $escapeNoClickLeak = @(Read-Events | Where-Object { $_.type -in @('mouse-down', 'mouse-up') }).Count -eq 0

    Set-HarnessForeground $harnessProcess
    Set-CursorPosition $centerX $centerY
    [CrossGesturesAcceptanceNative]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)
    for ($index = 0; $index -lt 1000; $index++) {
        Send-AbsoluteMouseMove ($centerX + ($index % 100)) `
            ($centerY + ([Math]::Floor($index / 100)))
    }
    [CrossGesturesAcceptanceNative]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 700
    Set-HarnessForeground $harnessProcess
    Clear-Events
    Send-RightClick $centerX $centerY
    Start-Sleep -Milliseconds 800
    $stressRecoveryPassed = Test-RightClickPair

    $beforeIds = @(Get-Process -Name CrossGestures -ErrorAction Stop | Select-Object -ExpandProperty Id)
    Start-Process -FilePath $AppPath -WorkingDirectory (Split-Path $AppPath) -Wait
    Start-Sleep -Milliseconds 800
    $after = @(Get-Process -Name CrossGestures -ErrorAction Stop)
    $singleInstancePassed = $after.Count -eq 1 -and $after[0].Id -eq $beforeIds[0]

    $appProcess = $after[0]
    $appProcess.Refresh()
    $cpuStart = $appProcess.TotalProcessorTime.TotalSeconds
    $sampleStart = [DateTime]::UtcNow
    Start-Sleep -Seconds 5
    $appProcess.Refresh()
    $elapsed = ([DateTime]::UtcNow - $sampleStart).TotalSeconds
    $cpuPercent = (($appProcess.TotalProcessorTime.TotalSeconds - $cpuStart) * 100.0) / ($elapsed * [Environment]::ProcessorCount)
    $workingSetMiB = $appProcess.WorkingSet64 / 1MB

    $summary = [ordered]@{
        shortRightClickReplay = $shortClickPassed
        shortcutGesture = $shortcutPassed
        validGestureNoClickLeak = $validGestureNoClickLeak
        invalidGestureNoClickLeak = $invalidNoClickLeak
        escapeCancellationNoClickLeak = $escapeNoClickLeak
        queueRecoveredAfterStress = $stressRecoveryPassed
        singleInstance = $singleInstancePassed
        responding = $appProcess.Responding
        idleCpuPercent = [Math]::Round($cpuPercent, 4)
        workingSetMiB = [Math]::Round($workingSetMiB, 2)
    }
    $functionalKeys = @(
        'shortRightClickReplay', 'shortcutGesture', 'validGestureNoClickLeak',
        'invalidGestureNoClickLeak', 'escapeCancellationNoClickLeak',
        'queueRecoveredAfterStress', 'singleInstance', 'responding')
    $summary.passed = @($functionalKeys | Where-Object { -not $summary[$_] }).Count -eq 0
    $summary | ConvertTo-Json | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    $summary | ConvertTo-Json
    if (-not $summary.passed) { throw "Windows runtime acceptance failed: $summaryPath" }
}
finally {
    if ($harnessProcess -and -not $harnessProcess.HasExited) {
        Stop-Process -Id $harnessProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($startedApp -and $appProcess -and -not $appProcess.HasExited) {
        Stop-Process -Id $appProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item Env:CROSSGESTURES_TRACE_FILE -ErrorAction SilentlyContinue
}
