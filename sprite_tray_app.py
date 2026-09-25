#!/usr/bin/env python3
r"""
sprite_tray_app.py  (Windows only)  --  Aemy

Aemy runs quietly in the system tray. When the PC sits idle (no mouse or
keyboard input for a chosen amount of time) it shows your transparent sprite
animation from frames as a fullscreen, click-through, always-on-top
overlay -- a custom screensaver. The instant you touch the mouse or keyboard
again, the overlay disappears and you are back to your normal desktop.

Tray menu:
  - Show now        : force the overlay on immediately
  - Pause auto-show : temporarily disable idle triggering
  - Idle delay      : how long the PC must sit idle first (live-adjustable)
  - Play speed      : animation frame rate (live-adjustable)
  - Loop pause      : hold between animation loops (live-adjustable)
  - About           : version and current settings
  - Exit            : quit

Threading model (important):
  Tkinter must live on the MAIN thread. So the main thread owns a single
  hidden Tk root that runs one mainloop for the whole process, and the
  overlay is a Toplevel created inside it. pystray runs on a background
  thread and only flips flags that the Tk thread polls.

Build a standalone .exe (no console window, tray-only):
  build.bat
which produces dist\Aemy.exe with a proper icon and Windows file properties.

Run from source for testing:
  python sprite_tray_app.py --idle-seconds 10 --fps 15
"""

import argparse
import ctypes
import glob
import io
import os
import sys
import threading
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

try:
    import pystray
except ImportError:
    sys.exit("Missing dependency. Install with: pip install pystray")

# DPI awareness comes from app.manifest (PerMonitorV2) when frozen, which
# Windows applies at process creation. Do NOT call SetProcessDpiAwarenessContext
# in a frozen build: it is a no-op once the manifest has set awareness, and the
# legacy fallback would *downgrade* the process to system-DPI awareness, making
# Windows report scaled-down coordinates (1536x864 instead of 1920x1080 at 125%
# scaling) so the overlay would not cover the screen.
#
# When running from source there is no manifest, so opt in explicitly.
if sys.platform == "win32" and not getattr(sys, "frozen", False):
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
        except Exception:
            pass

TRANSPARENT_KEY = "#010203"  # arbitrary, unlikely-to-occur RGB color
ICON_NAME = "aicon.png"
POLL_MS = 300
APP_NAME = "Aemy"
APP_VERSION = "1.0.0"


def resource_path(relative_path):
    """Resolve a path that works from source and from a PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _get_tick():
    """Millisecond tick count as an UNSIGNED 64-bit value.

    GetTickCount returns a DWORD (unsigned 32-bit) but ctypes defaults
    restype to c_int (SIGNED), so on a machine that has been up more than
    ~24.8 days the value flips negative and every idle calculation breaks.
    GetTickCount64 avoids both the signedness trap and the 49.7-day wrap.
    """
    try:
        k = ctypes.windll.kernel32
        fn = getattr(k, "GetTickCount64", None)
        if fn is not None:
            fn.restype = ctypes.c_ulonglong
            fn.argtypes = []
            return fn()
        k.GetTickCount.restype = ctypes.c_ulong
        k.GetTickCount.argtypes = []
        return k.GetTickCount()
    except Exception:
        return 0


def get_idle_seconds():
    """Seconds since last keyboard/mouse input, or None if the API failed.

    Returning None (instead of 0.0) matters: a silent 0.0 would look like
    "the user is at the keyboard" and the overlay would never appear.
    """
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    try:
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return None
        tick = _get_tick()
        idle = (tick - lii.dwTime) / 1000.0
        # A negative result means the two clocks disagreed (or wrapped); treat
        # it as "unknown" rather than as a huge idle or a bogus negative.
        if idle < 0:
            return None
        return idle
    except Exception:
        return None


def idle_now():
    """get_idle_seconds() that never returns None to the caller."""
    v = get_idle_seconds()
    if v is None:
        return float("inf")
    return v


class ActivityTracker:
    """Second, independent idle clock that only counts REAL user activity.

    GetLastInputInfo is reset by *any* input event, including ones no person
    caused: a touchscreen reporting hover, a jittery mouse sensor, an RGB or
    driver utility, a drawing tablet, an RDP client. On such machines the
    system idle counter can sit near zero forever and the overlay never shows.

    This tracker instead watches two things a person actually does:
      * the cursor position moving, and
      * any virtual key transitioning to "just pressed".
    If neither happens between polls, time counts as idle.
    """

    def __init__(self, poll_ms=POLL_MS):
        self.poll_ms = max(0.05, poll_ms / 1000.0)
        self.idle = 0.0
        self._last_pos = None
        self._primed = False

    def _cursor(self):
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        p = POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(p)):
            return (p.x, p.y)
        return None

    def _any_key_pressed(self):
        # The high-order bit means "down since the previous call", so a held
        # key is reported once and does not keep resetting the counter.
        for vk in range(0x01, 0xFF):
            if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
                return True
        return False

    def poll(self):
        """Advance the tracker; returns the current observed idle seconds."""
        pos = self._cursor()
        moved = pos is not None and self._last_pos is not None and pos != self._last_pos
        if pos is not None:
            self._last_pos = pos
        key = self._any_key_pressed()

        if not self._primed:
            # First call only establishes a baseline.
            self._primed = True
            return self.idle

        if moved or key:
            self.idle = 0.0
        else:
            self.idle += self.poll_ms
        return self.idle


def get_virtual_desktop():
    """Return (x, y, width, height) of the whole virtual desktop, in real
    physical pixels, covering every connected monitor.

    Using SM_CXVIRTUALSCREEN / SM_CYVIRTUALSCREEN means a multi-monitor setup

    setup, so Windows hands back scaled-down virtual coordinates.
    """
    try:
        u = ctypes.windll.user32
        SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
        SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
        x = u.GetSystemMetrics(SM_XVIRTUALSCREEN)
        y = u.GetSystemMetrics(SM_YVIRTUALSCREEN)
        w = u.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        h = u.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if w > 0 and h > 0:
            return x, y, w, h
    except Exception:
        pass
    return 0, 0, 1920, 1080


def app_version():
    """Read the real version from the running executable when frozen, so the
    About page matches the Windows file properties."""
    if not getattr(sys, "frozen", False):
        return APP_VERSION
    try:
        import ctypes

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", ctypes.c_uint),
                ("dwStrucVersion", ctypes.c_uint),
                ("dwFileVersionMS", ctypes.c_uint),
                ("dwFileVersionLS", ctypes.c_uint),
                ("dwProductVersionMS", ctypes.c_uint),
                ("dwProductVersionLS", ctypes.c_uint),
                ("dwFileFlagsMask", ctypes.c_uint),
                ("dwFileFlags", ctypes.c_uint),
                ("dwFileOS", ctypes.c_uint),
                ("dwFileType", ctypes.c_uint),
                ("dwFileSubtype", ctypes.c_uint),
                ("dwFileDateMS", ctypes.c_uint),
                ("dwFileDateLS", ctypes.c_uint),
            ]

        size = ctypes.c_uint(0)
        buf = ctypes.create_string_buffer(4096)
        if not ctypes.windll.version.GetFileVersionInfoW(sys.executable, 0, 4096, buf):
            return APP_VERSION
        ffi_ptr = ctypes.c_void_p()
        if not ctypes.windll.version.VerQueryValueW(
            buf, "\\", ctypes.byref(ffi_ptr), ctypes.byref(size)
        ):
            return APP_VERSION
        info = ctypes.cast(ffi_ptr, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        parts = [(ms >> 16) & 0xFFFF, ms & 0xFFFF, (ls >> 16) & 0xFFFF, ls & 0xFFFF]
        while len(parts) > 2 and parts[-1] == 0:
            parts.pop()
        return ".".join(str(p) for p in parts)
    except Exception:
        return APP_VERSION



def _alpha_bbox(img, threshold=40):
    """Tight bounding box of the visible sprite, ignoring the faint glow.

    The source frames are mostly empty canvas, so this is what lets us resize
    only the sprite instead of the whole full-screen frame every tick.
    """
    mask = img.split()[-1].point(lambda v: 255 if v > threshold else 0)
    bbox = mask.getbbox()
    return bbox if bbox else (0, 0, img.width, img.height)


def load_frames(frames_dir, pattern="*.png", target_size=None, sprite_scale=1.0):
    """Load frame metadata + compressed bytes. Startup must stay fast.

    The previous version resized all 121 frames to full screen AND re-encoded
    them to PNG here, which took minutes on a large display. Now we only read
    the original (small) PNG bytes and record each frame's sprite bounding
    box. All scaling happens per tick, on just the sprite region.
    """
    paths = sorted(glob.glob(os.path.join(frames_dir, pattern)))
    if not paths:
        sys.exit(f"No files matched {pattern!r} inside {frames_dir!r}")

    frames = []
    for p in paths:
        with open(p, "rb") as fh:
            data = fh.read()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        w, h = img.size
        bbox = _alpha_bbox(img)
        img.close()
        frames.append((data, w, h, bbox))
    return frames


def decode_frame(entry, target_size, sprite_scale=1.0):
    """Render one frame onto a full-screen transparency-key canvas.

    Only the sprite's bounding box is resized and composited, which is a few
    hundred pixels wide instead of the entire 4K frame.
    """
    data, w, h, bbox = entry
    tw, th = target_size
    x0, y0, x1, y1 = bbox

    sx = tw / float(w)
    sy = th / float(h)
    cw = max(1, round((x1 - x0) * sx))
    ch = max(1, round((y1 - y0) * sy))
    ox = round(x0 * sx)
    oy = round(y0 * sy)

    if sprite_scale != 1.0:
        cw = max(1, round(cw * sprite_scale))
        ch = max(1, round(ch * sprite_scale))
        ox = (tw // 2) - (cw // 2)
        oy = (th // 2) - (ch // 2)

    img = Image.open(io.BytesIO(data)).convert("RGBA")
    img = img.crop(bbox).resize((cw, ch), Image.LANCZOS)

    key = tuple(int(TRANSPARENT_KEY[i:i + 2], 16) for i in (1, 3, 5))
    canvas = Image.new("RGB", (tw, th), key)
    r, g, b, a = img.split()
    canvas.paste(Image.merge("RGB", (r, g, b)), (ox, oy), a)
    img.close()
    return canvas


def _fit_into_canvas(img, size=64):
    """Trim transparent padding, scale to fit, centre on a square canvas."""
    img = img.convert("RGBA")
    bbox = _alpha_bbox(img)
    pad = 2
    bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
            min(img.width, bbox[2] + pad), min(img.height, bbox[3] + pad))
    img = img.crop(bbox)
    # thumbnail() only shrinks, so scale up explicitly when needed.
    scale = size / max(img.size)
    if scale != 1.0:
        img = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(img, ((size - img.width) // 2, (size - img.height) // 2))
    return canvas


def make_tray_icon_image():
    for base in (resource_path(""), os.path.dirname(os.path.abspath(__file__))):
        icon_path = os.path.join(base, ICON_NAME)
        if os.path.isfile(icon_path):
            try:
                return _fit_into_canvas(Image.open(icon_path))
            except Exception:
                pass
    candidates = sorted(glob.glob(os.path.join(resource_path("frames"), "*.png")))
    if candidates:
        try:
            return _fit_into_canvas(Image.open(candidates[len(candidates) // 2]))
        except Exception:
            pass
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((4, 4, 60, 60), fill=(80, 170, 255, 255))
    return img


class OverlayController:
    """Owns the hidden Tk root on the MAIN thread; the overlay is a Toplevel
    created inside that same mainloop. Tk cannot run on a worker thread."""

    def __init__(self, app):
        self.app = app
        self.frames = None
        self.photo = None
        self.overlay = None
        self.label = None
        self.frame_i = 0
        self.visible = False
        self.manual = False  # True when shown via "Show now"
        self.tracker = ActivityTracker(POLL_MS)

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.wm_attributes("-topmost", True)

    def ensure_frames(self):
        if self.frames is not None:
            return self.frames
        _, _, sw, sh = get_virtual_desktop()
        self.app.frames = load_frames(
            self.app.frames_dir,
            target_size=(sw, sh),
            sprite_scale=self.app.sprite_scale,
        )
        self.frames = self.app.frames
        return self.frames

    def show(self, manual=False):
        if self.visible:
            if not manual:
                return
            # "Show now" while already showing manually toggles it off.
            if self.manual:
                self.hide()
                return
        frames = self.ensure_frames()
        vx, vy, sw, sh = get_virtual_desktop()
        size = (sw, sh)

        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.attributes("-transparentcolor", TRANSPARENT_KEY)
        top.geometry(f"{sw}x{sh}+{vx}+{vy}")

        if self.photo is None:
            self.photo = ImageTk.PhotoImage(
                decode_frame(frames[0], size, self.app.sprite_scale)
            )

        self.label = tk.Label(top, bd=0, highlightthickness=0, bg=TRANSPARENT_KEY)
        self.label.place(x=0, y=0, width=sw, height=sh)
        top.bind("<Escape>", lambda e: self.hide())

        self.overlay = top
        self.frame_i = 0
        self.visible = True
        self.manual = manual
        self.label.configure(image=self.photo)
        if manual:
            # Let Esc close a manually triggered overlay.
            try:
                top.focus_force()
            except Exception:
                pass
        self._schedule_frame()

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        self.manual = False
        try:
            if self.overlay is not None:
                self.overlay.destroy()
        except Exception:
            pass
        self.overlay = None
        self.label = None
        self.photo = None

    def _schedule_frame(self, extra_ms=0):
        if not self.visible:
            return
        delay = max(10, int(1000 / max(1, self.app.fps))) + max(0, int(extra_ms))
        self.root.after(delay, self._next_frame)

    def _next_frame(self):
        if not self.visible:
            return
        loop_pause_ms = 0
        if self.frames and self.photo is not None:
            if self.frame_i == len(self.frames) - 1:
                loop_pause_ms = max(0, int(self.app.loop_delay * 1000))
            self.frame_i = (self.frame_i + 1) % len(self.frames)
            photo_size = (self.photo.width(), self.photo.height())
            frame = decode_frame(
                self.frames[self.frame_i], photo_size, self.app.sprite_scale
            )
            self.photo.paste(frame)
            frame.close()
        self._schedule_frame(extra_ms=loop_pause_ms)

    def observed_idle(self):
        """The larger of the Windows idle clock and our own activity tracker.

        Taking the max means phantom input that keeps resetting
        GetLastInputInfo can no longer stop the overlay from ever appearing.
        """
        sys_idle = idle_now()
        my_idle = self.tracker.poll()
        return max(sys_idle, my_idle)

    def start(self):
        self.root.after(POLL_MS, self._tick)
        self.root.mainloop()

    # -- about window ------------------------------------------------------
    def show_about(self):
        """Small About dialog. Must run on the Tk (main) thread."""
        BG = "#1b1622"
        PINK = "#ff8fd0"
        CYAN = "#7fe6ea"

        top = tk.Toplevel(self.root)
        top.title("About")
        top.resizable(False, False)
        top.configure(bg=BG)
        top.attributes("-topmost", True)

        tk.Label(top, text="Aemy v%s" % app_version(), bg=BG, fg=PINK,
                 font=("Segoe UI", 16, "bold")).pack(padx=24, pady=(18, 2))
        tk.Label(top, text="Journey well", bg=BG, fg=CYAN,
                 font=("Segoe UI", 10, "italic")).pack()
        tk.Label(top, text="by bloodtobomb", bg=BG, fg="#6f6a9c",
                 font=("Segoe UI", 8)).pack(pady=(3, 0))
        # \U0001F497 is the pink heart. Written as an escape so this file
        # stays pure ASCII and cannot be corrupted by an editor's encoding.
        tk.Label(top, text="made in \U0001F497 in Solaris-3", bg=BG, fg=PINK,
                 font=("Segoe UI", 8)).pack()
        tk.Frame(top, bg=PINK, height=1).pack(fill="x", padx=30, pady=(12, 16))
        tk.Button(top, text="Close", width=10, command=top.destroy, bg=BG,
                  fg=CYAN, activebackground="#2a2233", activeforeground=PINK,
                  relief="flat", bd=0, pady=4).pack(pady=(0, 18))

        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        vx, vy, sw, sh = get_virtual_desktop()
        top.geometry(f"+{vx + (sw - w) // 2}+{vy + (sh - h) // 3}")
        top.focus_force()

    def _tick(self):
        app = self.app

        if app.exiting:
            self.hide()
            self.root.quit()
            return

        if app.force_show:
            # "Show now": show manually, or toggle off if already showing.
            app.force_show = False
            if self.visible and self.manual:
                self.hide()
            else:
                self.show(manual=True)
        elif self.visible:
            # A manually triggered overlay stays put until Esc / toggle / Exit.
            # Idle-triggered ones vanish as soon as the user touches input.
            if not self.manual and self.observed_idle() < max(1, app.idle_seconds):
                self.hide()
        elif (
            not app.paused
            and app.idle_seconds > 0
            and self.observed_idle() >= app.idle_seconds
        ):
            self.show(manual=False)

        self.root.after(POLL_MS, self._tick)


IDLE_PRESETS = [
    ("10 seconds", 10), ("30 seconds", 30), ("1 minute", 60),
    ("2 minutes", 120), ("5 minutes", 300), ("10 minutes", 600),
    ("15 minutes", 900), ("30 minutes", 1800), ("1 hour", 3600),
    ("Never (manual only)", 0),
]
FPS_PRESETS = [
    ("5 fps  (very slow)", 5), ("10 fps (slow)", 10), ("12 fps", 12),
    ("15 fps (default)", 15), ("20 fps", 20), ("24 fps", 24),
    ("30 fps (fast)", 30), ("60 fps (smooth)", 60),
]
DEFAULT_FPS = 15
LOOP_DELAY_PRESETS = [
    ("No pause (seamless)", 0), ("0.5 s", 0.5), ("1 s", 1), ("2 s", 2),
    ("3 s", 3), ("5 s", 5), ("10 s", 10), ("30 s", 30), ("1 min", 60),
]
DEFAULT_LOOP_DELAY = 2


class TrayApp:
    def __init__(self, frames_dir, fps, idle_seconds, sprite_scale, loop_delay=DEFAULT_LOOP_DELAY):
        self.frames_dir = frames_dir
        self.fps = fps
        self.idle_seconds = idle_seconds
        self.sprite_scale = sprite_scale
        self.loop_delay = loop_delay
        self.paused = False
        self.force_show = False
        self.exiting = False
        self.frames = None
        self.controller = None

        self.icon = pystray.Icon(
            APP_NAME, make_tray_icon_image(), APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("Show now", self.on_show_now),
                pystray.MenuItem("Pause auto-show", self.on_toggle_pause,
                                 checked=lambda item: self.paused),
                pystray.MenuItem("Idle delay", pystray.Menu(*[
                    pystray.MenuItem(label, self._make_idle_setter(sec), radio=True,
                                     checked=lambda item, s=sec: self.idle_seconds == s)
                    for label, sec in IDLE_PRESETS])),
                pystray.MenuItem("Play speed", pystray.Menu(*[
                    pystray.MenuItem(label, self._make_fps_setter(f), radio=True,
                                     checked=lambda item, v=f: self.fps == v)
                    for label, f in FPS_PRESETS])),
                pystray.MenuItem("Loop pause", pystray.Menu(*[
                    pystray.MenuItem(label, self._make_loop_delay_setter(sec), radio=True,
                                     checked=lambda item, d=sec: self.loop_delay == d)
                    for label, sec in LOOP_DELAY_PRESETS])),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("About", self.on_about),
                pystray.MenuItem("Exit", self.on_exit),
            ),
        )

    def _make_idle_setter(self, seconds):
        def setter(icon, item):
            self.idle_seconds = seconds
        return setter

    def _make_fps_setter(self, fps):
        def setter(icon, item):
            self.fps = fps
        return setter

    def _make_loop_delay_setter(self, seconds):
        def setter(icon, item):
            self.loop_delay = seconds
        return setter

    def on_show_now(self, icon, item):
        self.force_show = True

    def on_toggle_pause(self, icon, item):
        self.paused = not self.paused

    def on_about(self, icon, item):
        # pystray runs this on the tray thread; Tk must be touched from main.
        if self.controller is not None:
            try:
                self.controller.root.after(0, self.controller.show_about)
            except Exception:
                pass

    def on_exit(self, icon, item):
        self.exiting = True
        try:
            self.icon.stop()
        except Exception:
            pass

    def run(self):
        # pystray owns its own message loop, so it must not own the main
        # thread -- Tkinter needs that. Tray on a worker, Tk on main.
        threading.Thread(target=self.icon.run, daemon=True).start()
        self.controller = OverlayController(self)
        self.controller.start()
        self.exiting = True
        try:
            self.icon.stop()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames-dir", default=resource_path("frames"))
    ap.add_argument("--fps", type=int, default=DEFAULT_FPS)
    ap.add_argument("--idle-seconds", type=int, default=60)
    ap.add_argument("--sprite-scale", type=float, default=1.0)
    ap.add_argument("--loop-delay", type=float, default=DEFAULT_LOOP_DELAY)
    args = ap.parse_args()

    TrayApp(args.frames_dir, args.fps, args.idle_seconds,
            args.sprite_scale, args.loop_delay).run()


if __name__ == "__main__":
    main()
