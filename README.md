# Aemy

**A transparent sprite screensaver for Windows.**

Aemy hides in your system tray. When your PC sits idle, it plays a transparent
sprite animation across your whole screen, on top of your desktop, click-through.
Touch the mouse or keyboard and it vanishes instantly.

Built by **bloodtobomb**.

## Download

Grab **`Aemy-1.0.0-win64.exe`** from the [Releases page](../../releases).

1. Download it anywhere (Desktop, Program Files, a USB stick - anywhere)
2. Run `Aemy.exe`
3. Nothing appears to happen - **that is correct.** The icon goes to the
   system tray, bottom-right near the clock. It may be behind the `^` arrow.
4. Right-click the tray icon for the menu. **Exit** closes it.

It is a single self-contained file - nothing to unzip, no installer. The first
run takes a few seconds longer while it unpacks itself into a temporary folder.

Nothing is installed. No registry entries, no startup entry, no files written
anywhere.

## Features

- **Idle-triggered** - appears after a set delay with no input (default 1 min)
- **Instant dismissal** - move the mouse or type and it is gone
- **Tray-only** - no window, no taskbar button, no console
- **Live settings** - idle delay, playback speed and loop pause, all adjustable
  from the tray menu without restarting
- **Any resolution** - scales to your real screen pixels at 100/125/150 percent DPI
- **Multi-monitor** - one overlay spans the whole virtual desktop
- **Light** - about 90 MB RAM while playing
- **Quiet** - writes no log files and no config

## Antivirus warning (read this)

**This is expected, and it is a false positive.**

The binary is **unsigned**, and it is a PyInstaller build. It contains a
bundled copy of CPython, so antivirus engines see a large executable with an
embedded interpreter. Some engines use machine-learning heuristics that flag
exactly that shape, and a few report it as a trojan.

Aemy is not a trojan. It makes no network connections, has no persistence
beyond the tray icon, and does one thing: draw the sprite. **The full source
code is in this repository**, about 600 lines, and you can read every line.

Verify the file you downloaded:

```
SHA256  9AFE871A6E951793FAB91E0DDD843A02F80B0709FA4C49A574F180B9B7248697
        (Aemy.exe)
```

If your antivirus quarantines it, either add an exclusion, or build it yourself
from source - it takes one command.

## Requirements

- Windows 10 or 11
- 64-bit (x64)
- **No Python needed** to run the release build

## Build it yourself

Aemy is the screensaver engine. **The sprite artwork is not part of this
repository** - you bring your own animation.

1. Put your frames in `frames\` as a numbered PNG sequence
   (`0001.png`, `0002.png`, ... `0121.png`). Transparent PNG works best.
2. Then build:

```bat
pip install pillow pystray pyinstaller
git clone https://github.com/bloodtobomb/Aemy.git
cd Aemy
build.bat
```

The build script stops with a clear message if `frames\` is empty.

Output: `dist\Aemy.exe` - a single self-contained executable.

`build_onedir.bat` produces a folder build instead. The release uses the
single-file build, so there is nothing to unzip. Note that the single-file
build triggers noticeably more antivirus false positives, for the reasons
above.

The build scripts handle two Python 3.13+ quirks automatically: unpacking the
Tcl/Tk zip archives that PyInstaller cannot bundle, and generating the app icon
from a sprite frame.

### Using your own tray icon

Drop an `aicon.png` next to `sprite_tray_app.py` and it is used for the tray
icon and the exe icon. Without one, Aemy generates an icon from a frame of
your animation.

## How it works

- `tkinter` creates a borderless, always-on-top, fullscreen window and uses
  Windows `-transparentcolor` to punch a single RGB value out of it, so your
  desktop shows through everywhere the sprite is transparent.
- Idle time comes from `GetLastInputInfo`, cross-checked against a second
  tracker that watches real cursor movement and real key presses. The larger
  reading wins, so hardware that emits phantom input (touchscreens, jittery
  mouse sensors, driver utilities) can never stop the screensaver from running.
- Frames are kept **compressed** in memory and decoded one at a time onto a
  single reused buffer. Only each frame sprite bounding box is scaled, which
  keeps playback smooth at 4K and holds about 90 MB instead of roughly 2 GB.

## Credits

Made in 💗 in **Solaris-3**.

The default sprite animation is **Aemeath**, a playable Resonator from
*Wuthering Waves* by **Kuro Games** (released 23 May 2024). She is a 5-star
Fusion wielder who fights with a sword and rides the night sky behind her
Mechascout.

- Wuthering Waves: <https://wutheringwaves.com>
- Kuro Games: <https://kurogames.com>

**Aemeath and all related game assets belong to Kuro Games.** This is an
unofficial fan project. Aemy is not affiliated with, endorsed by or connected
to Kuro Games, and *Wuthering Waves* is a trademark of its respective owner.
The Aemy code is original and MIT-licensed; the sprite artwork is not, and is
deliberately not included in this repository.

If you are a rights holder and want this removed, open an issue and it will be
taken down straight away.

**Aemy** was built by **bloodtobomb**, using Tkinter, Pillow and pystray.

## Licence

MIT - see [LICENSE](LICENSE).
