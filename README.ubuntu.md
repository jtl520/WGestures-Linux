# CrossGestures for Ubuntu, Kali and Debian-family desktops

This repository contains two native Linux input backends. The Windows Win32
projects are also built and released independently; they remain separate from
the Linux build and do not affect Debian packaging.

## Supported sessions

| Environment | Session | Backend | Support level |
| --- | --- | --- | --- |
| Ubuntu 24.04, GNOME Shell 46 | Wayland | GNOME Shell extension | Primary |
| Ubuntu 18.04, GNOME 3.28 | Xorg | Python/GTK3 X11 daemon | Primary compatibility |
| Kali 2026.2, Xfce | X11 | Python/GTK3 X11 daemon | Primary compatibility |
| Other Debian-family desktops | X11 | Python/GTK3 X11 daemon | Best effort |

GNOME/KDE Wayland sessions other than GNOME Shell 46 are deliberately rejected
with a diagnostic message. Kali Xfce continues to use X11. Ubuntu 18.04 is out
of standard security support; application compatibility does not extend the
operating system's security lifecycle.

## Features

- Right, X1 and X2 gesture triggers; right button is enabled by default.
- Middle-button 4x4 quick panel, enabled by default for every desktop user
  (including root sessions), for launching desktop applications and
  opening files, folders, or HTTP/HTTPS URLs. Middle is never a gesture trigger
  while the panel option is enabled. Tiles show the configured description as a
  tooltip, and an application slot with "activate if running" raises the open
  window (matched through /proc) instead of spawning a second instance on both
  the GNOME Shell and GTK3/X11 backends. The GTK3/X11 panel also accepts drag
  and drop: files, folders, `.desktop` launchers and web links dropped on an
  empty tile create matching entries, and multiple drops fill consecutive free
  slots. The GNOME Wayland panel does not accept drops. While the panel is
  open, right and X button gestures keep working outside the panel surface on
  both backends, and gestures also keep working inside the slot editor's
  input fields (X11); only keys on the panel itself are handed to the tiles.
  URL tiles fetch the site's `favicon.ico` directly from the target host
  (3 s timeout, cached under `$XDG_CACHE_HOME/wgestures/favicons`); sites
  which reject icon clients fall back to Google's favicon compatibility
  endpoint, then to the theme globe icon. GNOME Shell delegates the request to the
  `wgestures` helper and only reads the resulting local icon, so the compositor
  never performs network I/O. Both backends reuse an unchanged tile tree on
  repeated opens and toggle on middle-button press (motion beyond the drag
  threshold reverts the toggle). A focus watchdog closes the panel if a fullscreen overlay
  swallows the focus-out event.
  Preferences expose it as “Middle (panel)” in the trigger-button selector;
  selecting that entry enables the panel and clearing it restores native middle clicks.
  On GTK/X11, the grid is lowered while its tile editor and nested chooser are
  active, and middle-button toggles are consumed until that modal chain closes,
  so repeated middle clicks cannot raise the grid over the software list.
  While the grid itself is visible, a temporary X11 left-button grab reliably
  closes it on an outside desktop/window click and replays the original click
  to that target; inside clicks are replayed to their tile unchanged.
- Four- or eight-direction recognition with jitter and duplicate filtering.
- Transparent, input-pass-through path rendering with 60 Hz frame coalescing.
- Per-application profiles using sandbox, desktop, GTK application and WM class IDs.
- Shortcut, smart copy/paste, EWMH/GNOME window, shell command, launch, pause and no-op actions.
- Smart Copy/Paste use Ctrl+Shift+C/V in terminal windows and Ctrl+C/V elsewhere.
- Single-direction gestures allow about 35 degrees of drawing error after exact matching.
- Fresh installs bind right-up to Smart Copy, right-down to Smart Paste, and
  right up-right-up to toggle the current window's always-on-top state.
- X11 sessions autostart a tray indicator; GNOME 46 uses its native panel indicator.
- Preferences expose per-user autostart and minimize/close-to-tray switches.
- Launching preferences as a terminal background job is supported; the GTK
  process detaches its standard streams so shell job control cannot freeze it.
- Successful actions show the gesture name first (falling back to the action
  name) near the pointer and fade in 300 ms by default.
- Libadwaita preferences on GNOME 46 and a GTK3 preferences application on X11.
- Atomic configuration at
  `$XDG_CONFIG_HOME/wgestures/gestures-v1.json`, with last-valid backup recovery.
- Independent atomic quick-panel configuration at
  `$XDG_CONFIG_HOME/wgestures/panel-v1.json`, also with last-valid backup recovery.
- Allow-list-only import of legacy `.wg2` files. `$type` metadata is never loaded
  as executable code.
- Compatible `.cgestures` import/export for moving common gestures to and from
  Windows, with explicit reports for platform-specific items that are skipped.

Windows paths and commands, Lua, text injection, task switching, web-search
actions and modifier/wheel gestures remain unsupported and are reported during
import instead of being enabled.

## Commands

中文用户可先阅读 [安装说明](README.install.zh-CN.md)，其中包含依赖、首次启用、
开机自启、升级和常见故障处理；完整移除步骤见
[卸载说明](README.uninstall.zh-CN.md)。

```sh
wgestures --settings
wgestures --enable        # or --disable
wgestures --pause         # or --resume
wgestures --status
wgestures --diagnose
wgestures --diagnose --json
```

The XDG autostart entry runs `wgestures --daemon`. It starts the X11 process in
an X11 session and exits immediately in GNOME 46 Wayland, where the Shell
extension owns input. Unsupported Wayland compositors are never given an X11
fallback because XWayland cannot safely capture compositor-global input.

## Build and test

On Ubuntu 24.04:

```sh
sudo apt install build-essential debhelper libglib2.0-bin nodejs npm \
  python3 python3-gi python3-cairo python3-gi-cairo python3-xlib \
  gir1.2-gtk-3.0 zip lintian
make -f Makefile.ubuntu check
make -f Makefile.ubuntu test
make -f Makefile.ubuntu deb
lintian ../wgestures_2.1.8_all.deb
```

Install the same `Architecture: all` package on all supported targets:

```sh
sudo apt install ../wgestures_2.1.8_all.deb
wgestures --diagnose
```

In GNOME 46 Wayland, log out and back in once after the first system-wide
installation, then run `wgestures --enable`. X11 sessions start the daemon at
the next login; it can be tested immediately with `wgestures --daemon`.

## Hard release gates

1. A short trigger-button click is replayed exactly once.
2. A valid or invalid effective gesture never leaks a context menu.
3. Esc, lock, suspend, monitor changes and process exit release every grab.
4. All shortcut and window actions affect the window under the initial pointer.
5. Configuration damage recovers from the most recent valid backup.
6. X11 idle CPU remains below 1%, RSS below 80 MB, p95 display latency below
   33 ms and p95 click replay latency below 50 ms in the acceptance environment.
7. Install, upgrade and removal succeed, and removal preserves user configuration.
8. Enabling the middle panel never leaks a middle click or creates a gesture;
   disabling it restores one native press/release pair, without changing right
   or X-button gestures.

Failure of any gate blocks the release rather than being documented as a known
working-version limitation.

## VMware and physical-host acceptance

From the Windows workspace, generate/show the temporary public key without
storing a password:

```powershell
.\tools\test-matrix.ps1 -BootstrapOnly
```

After that key is authorized in the two VM accounts and the Ubuntu 24.04 test
account, run the matrix against the built package:

```powershell
.\tools\test-matrix.ps1 `
  -PackagePath ..\wgestures_2.1.8_all.deb `
  -Ubuntu18User <vm-user> `
  -Ubuntu24Host <physical-host-ip> `
  -Ubuntu24User <physical-host-user>
```

The script discovers VMware guest addresses with `vmrun`, uses key-only SSH,
collects diagnostics, GUI event evidence and performance metrics below
`build/acceptance-*`, and never records a sudo or login password. X11 gates are
fully driven with XTEST. GNOME Wayland static gates are automated; the physical
mouse, mixed-scale monitor and lock/suspend items remain explicit manual gates
because Wayland intentionally prevents an unrelated process from injecting
compositor-global hardware input.

For a Kali VM that is reachable only through VMware Guest Operations, the
repository also contains `tools/kali-xvfb-acceptance.sh`. It extracts the built
`.deb` without modifying the guest installation and runs the full GTK/X11 input
suite under an isolated Xvfb + xfwm4 session. Its report explicitly marks frame
metrics as skipped because the isolated session disables compositing; it does
not replace a logged-in desktop or GNOME Wayland acceptance run.
