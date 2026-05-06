#!/usr/bin/env python3
"""
PredatorSense Linux - GUI for Acer Predator PHN16S-71 on CachyOS
Interfaces with linuwu_sense kernel module via /sys/module filesystem.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gdk, Gio
import subprocess
import threading
import os
import sys
import json
import time
try:
    import evdev
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

# ─── sysfs paths ──────────────────────────────────────────────────────────────
_ACER_WMI_BASE  = "/sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi"

def _find_sense_dir():
    """Dynamically find predator_sense or nitro_sense directory."""
    for name in ("predator_sense", "nitro_sense"):
        p = f"{_ACER_WMI_BASE}/{name}"
        if os.path.exists(p):
            return p
    return f"{_ACER_WMI_BASE}/predator_sense"

# Set at startup; refreshed by _ensure_module_loaded()
PREDATOR_BASE   = _find_sense_dir()
HWMON_BASE      = f"{_ACER_WMI_BASE}/hwmon"
PLATFORM_PROFILE= f"{_ACER_WMI_BASE}/platform-profile/platform-profile-0/profile"
PROFILE_CHOICES = f"{_ACER_WMI_BASE}/platform-profile/platform-profile-0/choices"
# PHN16S-71 has per-key RGB (not 4-zone), KB controlled via hwmon/WMI — no sysfs node
KB_BASE         = None
THERMAL_PATH    = PLATFORM_PROFILE   # use the new platform-profile interface

def _find_hwmon_dir():
    """Find the actual hwmonN directory (number can change)."""
    import glob
    dirs = glob.glob(f"{HWMON_BASE}/hwmon*")
    return dirs[0] if dirs else None

def _ensure_module_loaded():
    """Load linuwu_sense with predator_v4=Y if not already loaded correctly."""
    global PREDATOR_BASE, BATTERY_LIMIT, BATTERY_CAL, FAN_SPEED, LCD_OVERRIDE, USB_CHARGING, BACKLIGHT_TO, BOOT_ANIM_SOUND
    if not os.path.exists(PREDATOR_BASE):
        try:
            subprocess.run(["sudo", "modprobe", "linuwu_sense", "predator_v4=Y"],
                           capture_output=True, timeout=10)
        except Exception:
            pass
    # Refresh path in case module just loaded
    PREDATOR_BASE   = _find_sense_dir()
    BATTERY_LIMIT   = f"{PREDATOR_BASE}/battery_limiter"
    BATTERY_CAL     = f"{PREDATOR_BASE}/battery_calibration"
    FAN_SPEED       = f"{PREDATOR_BASE}/fan_speed"
    LCD_OVERRIDE    = f"{PREDATOR_BASE}/lcd_override"
    USB_CHARGING    = f"{PREDATOR_BASE}/usb_charging"
    BACKLIGHT_TO    = f"{PREDATOR_BASE}/backlight_timeout"
    BOOT_ANIM_SOUND = f"{PREDATOR_BASE}/boot_animation_sound"
BATTERY_LIMIT = f"{PREDATOR_BASE}/battery_limiter"
BATTERY_CAL   = f"{PREDATOR_BASE}/battery_calibration"
FAN_SPEED     = f"{PREDATOR_BASE}/fan_speed"
LCD_OVERRIDE  = f"{PREDATOR_BASE}/lcd_override"
USB_CHARGING  = f"{PREDATOR_BASE}/usb_charging"
BACKLIGHT_TO    = f"{PREDATOR_BASE}/backlight_timeout"
BOOT_ANIM_SOUND = f"{PREDATOR_BASE}/boot_animation_sound"
PER_ZONE_MODE = f"{KB_BASE}/per_zone_mode"
FOUR_ZONE_MODE= f"{KB_BASE}/four_zone_mode"

# Maps Windows PredatorSense name -> kernel platform-profile value
# performance = Turbo, balanced-performance = Performance, balanced = Balanced
# quiet = Quiet, low-power = Eco (battery only)
THERMAL_PROFILES = ["low-power", "balanced", "balanced-performance", "performance"]

# Fan speeds per thermal profile (matches Windows PredatorSense)
PROFILE_FAN_SPEEDS = {
    "low-power":            (0,   0),    # Quiet   — EC managed
    "balanced":             (50,  50),   # Balanced
    "balanced-performance": (80,  80),   # Performance
    "performance":          (100, 100),  # Turbo
}
PROFILE_DISPLAY = {
    "performance":          ("Turbo",       "🔥", "Maximizes CPU/GPU clocks and fans. AC power required."),
    "balanced-performance": ("Performance", "⚡", "High clocks and fan speeds for gaming. AC power required."),
    "balanced":             ("Balanced",    "⚖",  "Balances performance and noise. Works on battery."),
    "low-power":            ("Quiet",       "🤫", "Reduces fans and clocks for silent use. Works on battery."),
}
PRESET_PROFILES  = {
    "Turbo":    {"fan": "100,100", "thermal": "performance",          "lcd": True},
    "Performance": {"fan": "80,80","thermal": "balanced-performance", "lcd": True},
    "Balanced": {"fan": "50,50",   "thermal": "balanced",             "lcd": False},
    "Quiet":    {"fan": "0,0",     "thermal": "low-power",            "lcd": False},
    "Custom":   None,
}

CONFIG_PATH = os.path.expanduser("~/.config/predatorsense-linux/settings.json")

def sysfs_read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None

def sysfs_write(path: str, value: str) -> bool:
    try:
        result = subprocess.run(
            ["sudo", "tee", path],
            input=value, text=True,
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False

def read_sensors() -> dict:
    data = {}
    try:
        out = subprocess.check_output(["sensors", "-j"], text=True, timeout=5)
        sensors = json.loads(out)
        # CPU temp
        for chip, vals in sensors.items():
            if "coretemp" in chip or "k10temp" in chip or "cpu_thermal" in chip:
                for k, v in vals.items():
                    if isinstance(v, dict):
                        for kk, vv in v.items():
                            if "temp" in kk.lower() and "input" in kk.lower():
                                data["cpu_temp"] = vv
                                break
                        if "cpu_temp" in data:
                            break
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,power.draw,clocks.current.graphics",
             "--format=csv,noheader,nounits"], text=True, timeout=5
        )
        parts = [p.strip() for p in out.strip().split(",")]
        if len(parts) >= 4:
            data["gpu_temp"]  = float(parts[0])
            data["gpu_util"]  = float(parts[1])
            data["gpu_power"] = float(parts[2])
            data["gpu_clock"] = float(parts[3])
    except Exception:
        pass

    # RAM
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                k, v = line.split(":")
                mem[k.strip()] = int(v.split()[0])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        used  = total - avail
        data["ram_used_gb"]  = round(used / 1024**2, 1)
        data["ram_total_gb"] = round(total / 1024**2, 1)
        data["ram_pct"]      = round(used / total * 100) if total else 0
    except Exception:
        pass

    # Battery
    try:
        bat_path = "/sys/class/power_supply/BAT0"
        if os.path.exists(bat_path):
            cap = sysfs_read(f"{bat_path}/capacity")
            sta = sysfs_read(f"{bat_path}/status")
            data["battery_pct"]    = int(cap) if cap else None
            data["battery_status"] = sta or "Unknown"
    except Exception:
        pass

    # CPU usage via /proc/stat (reliable, no sudo, no parsing issues)
    try:
        def _read_cpu_stat():
            with open("/proc/stat") as f:
                line = f.readline()
            vals = list(map(int, line.split()[1:]))
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
            total = sum(vals)
            return total, idle

        t1, i1 = _read_cpu_stat()
        time.sleep(0.15)
        t2, i2 = _read_cpu_stat()
        dt = t2 - t1
        di = i2 - i1
        data["cpu_util"] = round((1 - di / dt) * 100) if dt > 0 else 0
    except Exception:
        pass

    # Fan RPM from hwmon (real hardware values)
    hwmon = _find_hwmon_dir()
    if hwmon:
        f1 = sysfs_read(f"{hwmon}/fan1_input")
        f2 = sysfs_read(f"{hwmon}/fan2_input")
        t1 = sysfs_read(f"{hwmon}/temp1_input")
        t2 = sysfs_read(f"{hwmon}/temp2_input")
        t3 = sysfs_read(f"{hwmon}/temp3_input")
        if f1: data["fan1_rpm"] = int(f1)
        if f2: data["fan2_rpm"] = int(f2)
        # temps are in millidegrees
        if t1 and not data.get("cpu_temp"): data["cpu_temp"] = float(t1) / 1000
        if t2: data["gpu_temp_ec"] = float(t2) / 1000
        if t3: data["fan_temp3"]   = float(t3) / 1000

    # Fan speed setpoint (if readable)
    fan = sysfs_read(FAN_SPEED)
    if fan:
        parts = fan.split(",")
        data["fan_cpu"] = int(parts[0]) if parts[0].strip().isdigit() else None
        data["fan_gpu"] = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else None

    # Thermal profile
    data["thermal"] = sysfs_read(PLATFORM_PROFILE) or "unknown"

    return data


# ─── Circular gauge widget ─────────────────────────────────────────────────────
class GaugeWidget(Gtk.DrawingArea):
    """Futuristic multi-ring gauge with glow effect and animated fill."""
    def __init__(self, label="", color=(1.0, 0.42, 0.0), size=120):
        super().__init__()
        self.label      = label
        self.color      = color
        self._value     = 0
        self._target    = 0
        self._text      = "–"
        self._dark_mode = True
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._draw)

    def set_value(self, pct, text=""):
        self._target = max(0, min(100, pct))
        self._value  = self._target   # instant for now
        self._text   = text
        self.queue_draw()

    def set_dark(self, dark):
        self._dark_mode = dark
        self.queue_draw()

    def _draw(self, area, cr, w, h):
        import math
        cx, cy = w / 2, h / 2
        r_outer = min(w, h) / 2 - 6
        r_inner = r_outer - 10
        r_tick  = r_outer - 2

        bg_alpha = 0.08 if self._dark_mode else 0.12
        text_alpha = 1.0 if self._dark_mode else 0.85

        r, g, b = self.color

        # Outer tick marks (12 ticks)
        cr.set_line_width(1.5)
        for i in range(12):
            angle = -math.pi/2 + i * (2*math.pi/12)
            x1 = cx + (r_tick - 4) * math.cos(angle)
            y1 = cy + (r_tick - 4) * math.sin(angle)
            x2 = cx + r_tick * math.cos(angle)
            y2 = cy + r_tick * math.sin(angle)
            frac = i / 12
            if frac < self._value / 100:
                cr.set_source_rgba(r, g, b, 0.6)
            else:
                cr.set_source_rgba(1 if self._dark_mode else 0,
                                   1 if self._dark_mode else 0,
                                   1 if self._dark_mode else 0, 0.12)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

        # Background ring
        cr.set_line_width(8)
        cr.set_source_rgba(r, g, b, bg_alpha)
        cr.arc(cx, cy, r_inner, 0, 2 * math.pi)
        cr.stroke()

        # Glow shadow (drawn twice, blurred effect via multiple strokes)
        angle_start = -math.pi / 2
        angle_end   = angle_start + (self._value / 100) * 2 * math.pi
        if self._value > 0:
            cr.set_line_width(14)
            cr.set_source_rgba(r, g, b, 0.12)
            cr.arc(cx, cy, r_inner, angle_start, angle_end)
            cr.stroke()

            # Main arc with gradient effect
            cr.set_line_width(8)
            cr.set_source_rgba(r, g, b, 0.9)
            cr.arc(cx, cy, r_inner, angle_start, angle_end)
            cr.stroke()

            # Bright tip dot at end of arc
            tip_x = cx + r_inner * math.cos(angle_end)
            tip_y = cy + r_inner * math.sin(angle_end)
            cr.arc(tip_x, tip_y, 5, 0, 2*math.pi)
            cr.set_source_rgba(1, 1, 1, 0.9)
            cr.fill()
            cr.arc(tip_x, tip_y, 8, 0, 2*math.pi)
            cr.set_source_rgba(r, g, b, 0.4)
            cr.fill()

        # Center background circle
        cr.arc(cx, cy, r_inner - 10, 0, 2*math.pi)
        if self._dark_mode:
            cr.set_source_rgba(0.05, 0.07, 0.09, 1.0)
        else:
            cr.set_source_rgba(0.96, 0.97, 0.98, 1.0)
        cr.fill()

        # Value text
        cr.set_source_rgba(text_alpha, text_alpha, text_alpha, 0.95)
        cr.select_font_face("Monospace", 0, 1)
        fsize = 15 if len(self._text) <= 4 else 11
        cr.set_font_size(fsize)
        ext = cr.text_extents(self._text)
        cr.move_to(cx - ext.width/2, cy + ext.height/2 - 4)
        cr.show_text(self._text)

        # Label text
        cr.set_source_rgba(r, g, b, 0.8)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(8)
        ext2 = cr.text_extents(self.label)
        cr.move_to(cx - ext2.width/2, cy + 16)
        cr.show_text(self.label)


# ─── RGB Zone color button ─────────────────────────────────────────────────────
class ZoneButton(Gtk.Button):
    def __init__(self, zone_idx, color="#00BFFF"):
        super().__init__()
        self.zone_idx = zone_idx
        self._color   = color
        self.set_size_request(40, 40)
        self.set_tooltip_text(f"Zone {zone_idx + 1}")
        self._apply_css()
        self.connect("clicked", self._on_click)

    def _apply_css(self):
        css = f"""
        button {{
            background-color: {self._color};
            border-radius: 8px;
            border: 2px solid rgba(255,255,255,0.3);
            min-width: 40px; min-height: 40px;
        }}
        button:hover {{ border: 2px solid white; }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        self.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _on_click(self, btn):
        dlg = Gtk.ColorDialog()
        dlg.set_title(f"Zone {self.zone_idx + 1} Color")
        dlg.choose_rgba(self.get_root(), None, None, self._color_chosen)

    def _color_chosen(self, dialog, result):
        try:
            color = dialog.choose_rgba_finish(result)
            if color:
                r = int(color.red   * 255)
                g = int(color.green * 255)
                b = int(color.blue  * 255)
                self._color = f"#{r:02X}{g:02X}{b:02X}"
                self._apply_css()
                self.queue_draw()
        except Exception:
            pass

    def get_hex(self):
        c = self._color.lstrip("#")
        return c.zfill(6).lower()


# ─── Main Application Window ───────────────────────────────────────────────────
class PredatorApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.predatorsense.linux",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect("activate", self._on_activate)

    def _on_activate(self, app):
        if hasattr(self, "win") and self.win:
            self.win.present()
            return
        self.win = PredatorWindow(application=app)
        # Hide on close instead of quitting — key listener keeps running
        self.win.connect("close-request", self._on_close_request)
        self.win.present()
        # Keep app alive in background (holds a reference)
        self.hold()

    def _on_close_request(self, win):
        """Hide window instead of quitting so key listener stays alive."""
        win.hide()
        self._show_tray_notification()
        return True  # prevent default close/quit

    def _show_tray_notification(self):
        try:
            notification = Gio.Notification.new("PredatorSense Linux")
            notification.set_body("Running in background. Predator key still active.")
            notification.set_priority(Gio.NotificationPriority.LOW)
            notification.add_button("Open", "app.show")
            notification.add_button("Quit", "app.quit")
            self.send_notification("bg", notification)
        except Exception:
            pass

        # Register actions
        show_action = Gio.SimpleAction.new("show", None)
        show_action.connect("activate", lambda a, p: self.win.present())
        self.add_action(show_action)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda a, p: self._quit())
        self.add_action(quit_action)

    def _quit(self):
        self.release()
        self.quit()


class PredatorWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("PredatorSense Linux")
        self.set_default_size(960, 680)
        self.set_resizable(True)

        self._dark_mode = True
        self._load_config()
        self._build_css()
        self._build_ui()
        self._start_sensor_loop()

    # ── Config ──────────────────────────────────────────────────────────────
    def _load_config(self):
        _ensure_module_loaded()
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        defaults = {
            "fan_cpu": 50, "fan_gpu": 50,
            "thermal": "balanced",
            "battery_limit": False,
            "lcd_override": False,
            "usb_charging": 20,
            "backlight_timeout": False,
            "zone_colors": ["00BFFF", "FF4500", "00FF88", "FF00FF"],
        }
        try:
            with open(CONFIG_PATH) as f:
                self.config = {**defaults, **json.load(f)}
        except Exception:
            self.config = defaults

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception:
            pass

    # ── CSS ─────────────────────────────────────────────────────────────────
    # ── Theme ───────────────────────────────────────────────────────────────
    DARK_THEME = {
        "bg":           "#080B0F",
        "bg2":          "#0D1117",
        "surface":      "#111820",
        "surface2":     "#161E28",
        "border":       "rgba(255,107,0,0.15)",
        "border2":      "rgba(255,255,255,0.06)",
        "accent":       "#FF6B00",
        "accent2":      "#FF3D00",
        "accent_glow":  "rgba(255,107,0,0.3)",
        "text":         "#F0F4F8",
        "text2":        "rgba(240,244,248,0.55)",
        "text3":        "rgba(240,244,248,0.25)",
        "success":      "#00E5A0",
        "warning":      "#FFB800",
        "danger":       "#FF3D5A",
        "cyan":         "#00D4FF",
    }
    LIGHT_THEME = {
        "bg":           "#F0F2F5",
        "bg2":          "#E8ECF0",
        "surface":      "#FFFFFF",
        "surface2":     "#F5F7FA",
        "border":       "rgba(255,107,0,0.25)",
        "border2":      "rgba(0,0,0,0.08)",
        "accent":       "#FF6B00",
        "accent2":      "#FF3D00",
        "accent_glow":  "rgba(255,107,0,0.2)",
        "text":         "#0D1117",
        "text2":        "rgba(13,17,23,0.6)",
        "text3":        "rgba(13,17,23,0.3)",
        "success":      "#00B87A",
        "warning":      "#E6A500",
        "danger":       "#E0203A",
        "cyan":         "#0099CC",
    }

    def _build_css(self):
        self._dark_mode = True
        self._apply_theme()

    def _apply_theme(self):
        t = self.DARK_THEME if self._dark_mode else self.LIGHT_THEME
        css = f"""
        @keyframes pulse-glow {{
            0%   {{ opacity: 0.6; }}
            50%  {{ opacity: 1.0; }}
            100% {{ opacity: 0.6; }}
        }}
        @keyframes slide-in {{
            from {{ opacity: 0; margin-top: 12px; }}
            to   {{ opacity: 1; margin-top: 0px; }}
        }}
        @keyframes spin {{
            from {{ transform: rotate(0deg); }}
            to   {{ transform: rotate(360deg); }}
        }}

        window {{
            background-color: {t["bg"]};
            color: {t["text"]};
        }}
        headerbar {{
            background: {t["bg"]};
            border-bottom: 1px solid {t["border"]};
            color: {t["text"]};
            min-height: 52px;
        }}
        headerbar button {{
            color: {t["text2"]};
            border-radius: 8px;
            padding: 4px 8px;
        }}
        headerbar button:hover {{
            color: {t["text"]};
            background: {t["surface"]};
        }}
        headerbar .title {{
            color: {t["text"]};
            font-weight: 800;
            font-size: 13px;
            letter-spacing: 0.5px;
        }}

        .sidebar {{
            background: {t["bg2"]};
            border-right: 1px solid {t["border"]};
        }}

        .nav-btn {{
            color: {t["text2"]};
            background: transparent;
            border: none;
            border-radius: 10px;
            padding: 10px 12px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.3px;
            transition: all 150ms ease;
        }}
        .nav-btn:hover {{
            background: {t["surface"]};
            color: {t["text"]};
        }}
        .nav-btn.active {{
            background: linear-gradient(135deg, {t["accent_glow"]}, rgba(255,61,0,0.12));
            color: {t["accent"]};
            border-left: 2px solid {t["accent"]};
        }}

        .card {{
            background: {t["surface"]};
            border-radius: 16px;
            border: 1px solid {t["border2"]};
            padding: 20px;
            animation: slide-in 200ms ease;
        }}
        .card-accent {{
            background: {t["surface"]};
            border-radius: 16px;
            border: 1px solid {t["border"]};
            padding: 20px;
        }}

        .section-title {{
            color: {t["text3"]};
            font-size: 9px;
            font-weight: 800;
            letter-spacing: 2px;
        }}
        .page-title {{
            color: {t["text"]};
            font-size: 22px;
            font-weight: 800;
            letter-spacing: -0.5px;
        }}
        .sub-label {{
            color: {t["text2"]};
            font-size: 11px;
        }}
        label {{
            color: {t["text"]};
        }}
        .card label, .card-accent label {{
            color: {t["text"]};
        }}
        .card .sub-label, .card-accent .sub-label {{
            color: {t["text2"]};
        }}
        box > label {{
            color: {t["text"]};
        }}
        .accent-text {{ color: {t["accent"]}; font-weight: 700; }}
        .success-text {{ color: {t["success"]}; }}
        .warning-text {{ color: {t["warning"]}; }}
        .danger-text  {{ color: {t["danger"]}; }}
        .cyan-text    {{ color: {t["cyan"]}; }}

        .preset-btn {{
            background: {t["surface2"]};
            border: 1px solid {t["border2"]};
            border-radius: 10px;
            color: {t["text"]};
            padding: 9px 18px;
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.3px;
            transition: all 150ms ease;
        }}
        .preset-btn:hover {{
            background: {t["accent_glow"]};
            border-color: {t["accent"]};
            color: {t["accent"]};
        }}
        .preset-btn.active {{
            background: linear-gradient(135deg, {t["accent_glow"]}, rgba(255,61,0,0.15));
            border-color: {t["accent"]};
            color: {t["accent"]};
            font-weight: 800;
        }}

        .danger-btn {{
            background: rgba(255,61,90,0.1);
            border: 1px solid rgba(255,61,90,0.3);
            border-radius: 10px;
            color: {t["danger"]};
            padding: 9px 18px;
            font-size: 12px;
            font-weight: 700;
        }}
        .danger-btn:hover {{
            background: rgba(255,61,90,0.2);
            border-color: {t["danger"]};
        }}

        scale trough {{
            background: {t["surface2"]};
            border-radius: 6px;
            min-height: 6px;
        }}
        scale trough highlight {{
            background: linear-gradient(90deg, {t["accent2"]}, {t["accent"]});
            border-radius: 6px;
        }}
        scale slider {{
            background: {t["accent"]};
            border-radius: 50%;
            min-width: 18px;
            min-height: 18px;
            box-shadow: 0 0 8px {t["accent_glow"]};
            transition: all 100ms ease;
        }}
        scale slider:hover {{
            min-width: 22px;
            min-height: 22px;
        }}

        switch {{
            background: {t["surface2"]};
            border: 1px solid {t["border2"]};
            border-radius: 20px;
        }}
        switch:checked {{
            background: linear-gradient(135deg, {t["accent2"]}, {t["accent"]});
            border-color: {t["accent"]};
        }}
        switch slider {{
            background: {t["text"]};
            border-radius: 50%;
        }}

        .warning-bar {{
            background: rgba(255,107,0,0.08);
            border: 1px solid {t["border"]};
            border-left: 3px solid {t["accent"]};
            border-radius: 12px;
            padding: 10px 16px;
            color: {t["accent"]};
            font-size: 11px;
        }}

        .stat-value {{
            color: {t["text"]};
            font-size: 28px;
            font-weight: 900;
            letter-spacing: -1px;
        }}
        .stat-unit {{
            color: {t["text2"]};
            font-size: 12px;
            font-weight: 600;
        }}

        .profile-chip {{
            background: linear-gradient(135deg, {t["accent_glow"]}, rgba(255,61,0,0.1));
            border: 1px solid {t["border"]};
            border-radius: 20px;
            padding: 4px 12px;
            color: {t["accent"]};
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }}

        separator {{
            background: {t["border2"]};
            min-height: 1px;
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _toggle_theme(self, btn):
        self._dark_mode = not self._dark_mode
        self._apply_theme()
        icon = "☀" if not self._dark_mode else "☾"
        btn.set_label(icon)

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self._pages = {}
        self._nav_buttons = {}
        self._active_page = "dashboard"

        # Outer box: titlebar + content
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(outer)

        # Header bar with window controls
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(True)
        header.set_decoration_layout("close,minimize,maximize:")
        title_lbl = Gtk.Label()
        title_lbl.set_markup('<span weight="bold" color="#FF5000">⬡</span> PredatorSense Linux')
        header.set_title_widget(title_lbl)
        header.add_css_class("flat")

        # Profile cycle button in headerbar
        self._profile_cycle_btn = Gtk.Button()
        self._profile_cycle_btn.set_tooltip_text("Cycle Thermal Profile")
        self._profile_cycle_lbl = Gtk.Label()
        current_p = sysfs_read(PLATFORM_PROFILE) or "balanced"
        p_icons = {"performance":"🔥","balanced-performance":"⚡","balanced":"⚖","low-power":"🤫"}
        p_names = {"performance":"Turbo","balanced-performance":"Performance","balanced":"Balanced","low-power":"Quiet"}
        p_icon = p_icons.get(current_p, "⚖")
        p_name = p_names.get(current_p, current_p)
        self._profile_cycle_lbl.set_markup(f'<span color="#FF6B00" weight="bold">{p_icon}  {p_name}</span>')
        self._profile_cycle_btn.set_child(self._profile_cycle_lbl)
        self._profile_cycle_btn.add_css_class("flat")
        self._profile_cycle_btn.connect("clicked", self._cycle_profile)
        header.pack_end(self._profile_cycle_btn)

        # Theme toggle button
        self._theme_btn = Gtk.Button(label="☾")
        self._theme_btn.set_tooltip_text("Toggle Light/Dark Mode")
        self._theme_btn.add_css_class("flat")
        self._theme_btn.connect("clicked", self._toggle_theme)
        header.pack_end(self._theme_btn)

        # Quit button — fully exit the app
        quit_btn = Gtk.Button(label="✕ Quit")
        quit_btn.set_tooltip_text("Quit PredatorSense (closing window keeps key listener running)")
        quit_btn.add_css_class("flat")
        quit_btn.connect("clicked", lambda b: self.get_application()._quit())
        header.pack_start(quit_btn)

        outer.append(header)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        root.set_vexpand(True)
        outer.append(root)

        # Sidebar
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sidebar.add_css_class("sidebar")
        sidebar.set_size_request(200, -1)
        sidebar.set_margin_top(12)
        sidebar.set_margin_bottom(12)
        sidebar.set_margin_start(8)
        sidebar.set_margin_end(8)

        # Custom SVG-style logo drawn as a DrawingArea
        logo_canvas = Gtk.DrawingArea()
        logo_canvas.set_content_width(180)
        logo_canvas.set_content_height(64)
        logo_canvas.set_draw_func(self._draw_logo)
        logo_canvas.set_margin_bottom(16)
        sidebar.append(logo_canvas)

        # Nav items with custom SVG icons
        nav_items = [
            ("dashboard", self._icon_dashboard, "Dashboard"),
            ("fans",      self._icon_fan,       "Fan Control"),
            ("thermal",   self._icon_thermal,   "Thermal"),
            ("keyboard",  self._icon_keyboard,  "Keyboard"),
            ("battery",   self._icon_battery,   "Battery"),
            ("display",   self._icon_display,   "Display"),
            ("system",    self._icon_system,    "System"),
        ]
        for page_id, icon_fn, label in nav_items:
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            btn_box.set_margin_start(4)
            # Icon canvas
            icon_canvas = Gtk.DrawingArea()
            icon_canvas.set_content_width(20)
            icon_canvas.set_content_height(20)
            icon_canvas.set_draw_func(lambda a, cr, w, h, fn=icon_fn: fn(cr, w, h))
            icon_canvas.set_valign(Gtk.Align.CENTER)
            lbl = Gtk.Label(label=label)
            lbl.set_halign(Gtk.Align.START)
            btn_box.append(icon_canvas)
            btn_box.append(lbl)
            btn = Gtk.Button()
            btn.set_child(btn_box)
            btn.add_css_class("nav-btn")
            btn.set_halign(Gtk.Align.FILL)
            btn.connect("clicked", self._on_nav, page_id)
            sidebar.append(btn)
            self._nav_buttons[page_id] = btn

        # Driver status at bottom of sidebar
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        sidebar.append(spacer)
        sidebar.append(Gtk.Separator())
        self._driver_status = Gtk.Label()
        self._driver_status.set_margin_top(8)
        self._driver_status.set_margin_start(8)
        self._driver_status.set_margin_bottom(4)
        self._driver_status.set_halign(Gtk.Align.START)
        self._driver_status.set_wrap(True)
        self._driver_status.set_max_width_chars(24)
        sidebar.append(self._driver_status)
        self._update_driver_status()

        root.append(sidebar)

        # Page stack with smooth transitions
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_transition_duration(250)
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)

        scroll_pages = {
            "dashboard": self._build_dashboard(),
            "fans":      self._build_fans(),
            "thermal":   self._build_thermal(),
            "keyboard":  self._build_keyboard(),
            "battery":   self._build_battery(),
            "display":   self._build_display(),
            "system":    self._build_system(),
        }
        for name, page in scroll_pages.items():
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.set_child(page)
            self._stack.add_named(sw, name)
            self._pages[name] = page

        root.append(self._stack)
        self._navigate("dashboard")

    # ── Custom SVG-style icon draw functions ────────────────────────────────
    def _icon_color(self, active=False):
        if active:
            return (1.0, 0.42, 0.0)
        return (0.6, 0.65, 0.7) if self._dark_mode else (0.4, 0.45, 0.5)

    def _icon_dashboard(self, cr, w, h):
        import math
        c = self._icon_color()
        cr.set_source_rgba(*c, 0.9)
        cr.set_line_width(1.5)
        # 4 small squares
        for i, (x, y) in enumerate([(1,1),(10,1),(1,10),(10,10)]):
            cr.rectangle(x, y, 8, 8)
        cr.stroke()

    def _icon_fan(self, cr, w, h):
        import math
        c = self._icon_color()
        cr.set_source_rgba(*c, 0.9)
        cr.set_line_width(1.5)
        cx, cy = w/2, h/2
        cr.arc(cx, cy, 2.5, 0, 2*math.pi)
        cr.fill()
        for i in range(4):
            angle = i * math.pi/2
            cr.save()
            cr.translate(cx, cy)
            cr.rotate(angle)
            cr.arc(5, 0, 4, math.pi*0.7, math.pi*1.8)
            cr.stroke()
            cr.restore()

    def _icon_thermal(self, cr, w, h):
        import math
        c = self._icon_color()
        cr.set_source_rgba(*c, 0.9)
        cr.set_line_width(1.5)
        # Flame shape
        cx = w/2
        cr.move_to(cx, 2)
        cr.curve_to(cx+5, 5, cx+7, 10, cx+4, 14)
        cr.curve_to(cx+6, 11, cx+3, 9, cx+2, 12)
        cr.curve_to(cx+2, 8, cx-2, 8, cx-2, 12)
        cr.curve_to(cx-3, 9, cx-6, 11, cx-4, 14)
        cr.curve_to(cx-7, 10, cx-5, 5, cx, 2)
        cr.stroke()

    def _icon_keyboard(self, cr, w, h):
        c = self._icon_color()
        cr.set_source_rgba(*c, 0.9)
        cr.set_line_width(1.5)
        cr.rectangle(1, 5, w-2, h-8)
        cr.stroke()
        for row, keys in enumerate([(4, 1.5), (5, 1.5), (3, 1.5)]):
            n, _ = keys
            for k in range(n):
                x = 3 + k * (w-6)/n
                y = 8 + row * 3.5
                cr.rectangle(x, y, (w-10)/n, 2.5)
                cr.fill()

    def _icon_battery(self, cr, w, h):
        c = self._icon_color()
        cr.set_source_rgba(*c, 0.9)
        cr.set_line_width(1.5)
        cr.rectangle(1, 6, w-4, h-12)
        cr.stroke()
        cr.rectangle(w-3, 8, 2.5, h-16)
        cr.fill()
        cr.rectangle(3, 8, (w-10)*0.7, h-16)
        cr.set_source_rgba(0.0, 0.9, 0.6, 0.9)
        cr.fill()

    def _icon_display(self, cr, w, h):
        c = self._icon_color()
        cr.set_source_rgba(*c, 0.9)
        cr.set_line_width(1.5)
        cr.rectangle(1, 2, w-2, h-6)
        cr.stroke()
        cr.move_to(w/2-4, h-3)
        cr.line_to(w/2+4, h-3)
        cr.line_to(w/2+6, h-1)
        cr.line_to(w/2-6, h-1)
        cr.close_path()
        cr.fill()

    def _icon_system(self, cr, w, h):
        import math
        c = self._icon_color()
        cr.set_source_rgba(*c, 0.9)
        cr.set_line_width(1.5)
        cx, cy = w/2, h/2
        cr.arc(cx, cy, 3, 0, 2*math.pi)
        cr.stroke()
        for i in range(8):
            angle = i * math.pi/4
            x1 = cx + 4.5 * math.cos(angle)
            y1 = cy + 4.5 * math.sin(angle)
            x2 = cx + 8 * math.cos(angle)
            y2 = cy + 8 * math.sin(angle)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

    def _draw_logo(self, area, cr, w, h):
        """Draw the custom Predator-style logo."""
        import math
        # Hexagon icon
        cx, cy = 22, h/2
        r = 16
        cr.set_source_rgba(1.0, 0.42, 0.0, 1.0)
        cr.set_line_width(2)
        for i in range(6):
            angle = math.pi/6 + i * math.pi/3
            x = cx + r * math.cos(angle)
            y = cy + r * math.sin(angle)
            if i == 0: cr.move_to(x, y)
            else: cr.line_to(x, y)
        cr.close_path()
        cr.set_source_rgba(1.0, 0.42, 0.0, 0.15)
        cr.fill_preserve()
        cr.set_source_rgba(1.0, 0.42, 0.0, 1.0)
        cr.set_line_width(1.5)
        cr.stroke()
        # P letter inside hex
        cr.set_source_rgba(1.0, 0.42, 0.0, 1.0)
        cr.select_font_face("Monospace", 0, 1)
        cr.set_font_size(14)
        ext = cr.text_extents("P")
        cr.move_to(cx - ext.width/2, cy + ext.height/2)
        cr.show_text("P")
        # PREDATOR text
        txt_color = (0.94, 0.96, 0.98) if self._dark_mode else (0.05, 0.07, 0.1)
        cr.set_source_rgba(*txt_color, 1.0)
        cr.select_font_face("Monospace", 0, 1)
        cr.set_font_size(13)
        cr.move_to(44, h/2 - 4)
        cr.show_text("PREDATOR")
        cr.set_source_rgba(1.0, 0.42, 0.0, 0.8)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(8)
        cr.move_to(44, h/2 + 9)
        cr.show_text("PHN16S-71 · CachyOS")

    # ── Navigation ──────────────────────────────────────────────────────────
    def _on_nav(self, btn, page_id):
        self._navigate(page_id)

    def _navigate(self, page_id):
        for pid, btn in self._nav_buttons.items():
            if pid == page_id:
                btn.add_css_class("active")
            else:
                btn.remove_css_class("active")
        self._stack.set_visible_child_name(page_id)
        self._active_page = page_id

    # ── Driver status ────────────────────────────────────────────────────────
    def _update_driver_status(self):
        if os.path.exists(PREDATOR_BASE):
            self._driver_status.set_markup(
                '<span color="#00FF88" size="9000">● Driver loaded</span>'
            )
        else:
            self._driver_status.set_markup(
                '<span color="#FF4444" size="9000">● Driver not found\nRun installer first</span>'
            )

    # ── Dashboard ────────────────────────────────────────────────────────────
    def _build_dashboard(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(24); box.set_margin_bottom(24)
        box.set_margin_start(24); box.set_margin_end(24)

        hdr = Gtk.Label()
        hdr.set_markup('<span font="20" weight="bold">System Monitor</span>')
        hdr.set_halign(Gtk.Align.START)
        box.append(hdr)

        # Warning if no driver
        if not os.path.exists(PREDATOR_BASE):
            warn = Gtk.Label()
            warn.set_markup(
                '⚠ <b>linuwu_sense driver not loaded.</b> Fan/RGB controls will be read-only.\n'
                'Run the installer script to set up the kernel module.'
            )
            warn.add_css_class("warning-bar")
            warn.set_wrap(True)
            warn.set_xalign(0)
            box.append(warn)

        # Gauge row
        gauge_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        gauge_row.set_homogeneous(True)

        self._gauge_cpu  = self._gauge_card("CPU",   GaugeWidget("UTIL", (0.0, 0.83, 1.0),  120))
        self._gauge_ctemp= self._gauge_card("CPU °C",GaugeWidget("TEMP", (1.0, 0.42, 0.0), 120))
        self._gauge_gpu  = self._gauge_card("GPU",   GaugeWidget("UTIL", (0.0, 0.9,  0.55), 120))
        self._gauge_gtemp= self._gauge_card("GPU °C",GaugeWidget("TEMP", (1.0, 0.72, 0.0), 120))
        self._gauge_ram  = self._gauge_card("RAM",   GaugeWidget("USE",  (0.6, 0.2,  1.0),  120))
        self._gauge_bat  = self._gauge_card("BAT",   GaugeWidget("PCT",  (0.0, 0.9,  0.6),  120))
        self._all_gauges = [
            self._gauge_cpu[1], self._gauge_ctemp[1],
            self._gauge_gpu[1], self._gauge_gtemp[1],
            self._gauge_ram[1], self._gauge_bat[1],
        ]

        for card in [self._gauge_cpu, self._gauge_ctemp, self._gauge_gpu,
                     self._gauge_gtemp, self._gauge_ram, self._gauge_bat]:
            gauge_row.append(card[0])
        box.append(gauge_row)

        # Info grid
        info_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        info_card.add_css_class("card")

        grid = Gtk.Grid()
        grid.set_row_spacing(10)
        grid.set_column_spacing(32)

        self._info_labels = {}
        rows = [
            ("GPU Power",   "gpu_power", "W"),
            ("GPU Clock",   "gpu_clock", "MHz"),
            ("Fan CPU",     "fan_cpu",   "%"),
            ("Fan GPU",     "fan_gpu",   "%"),
            ("Battery",     "battery_status", ""),
            ("Thermal Mode","thermal",   ""),
        ]
        for i, (name, key, unit) in enumerate(rows):
            col = (i % 3) * 2
            row = i // 3
            nl = Gtk.Label(label=name)
            nl.add_css_class("sub-label")
            nl.set_halign(Gtk.Align.START)
            vl = Gtk.Label(label="–")
            vl.set_markup(f'<span weight="bold">–</span>')
            vl.set_halign(Gtk.Align.START)
            grid.attach(nl, col, row * 2, 1, 1)
            grid.attach(vl, col, row * 2 + 1, 1, 1)
            self._info_labels[key] = (vl, unit)

        info_card.append(grid)
        box.append(info_card)
        return box

    def _gauge_card(self, title, gauge):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("card-accent")
        card.set_halign(Gtk.Align.FILL)
        lbl = Gtk.Label(label=title)
        lbl.add_css_class("section-title")
        card.append(lbl)
        card.append(gauge)
        return card, gauge

    # ── Fan Control ──────────────────────────────────────────────────────────
    def _build_fans(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(24); box.set_margin_bottom(24)
        box.set_margin_start(24); box.set_margin_end(24)

        hdr = Gtk.Label()
        hdr.set_markup('<span font="20" weight="bold">Fan Control</span>')
        hdr.set_halign(Gtk.Align.START)
        box.append(hdr)

        # Preset buttons
        preset_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        preset_card.add_css_class("card")
        pl = Gtk.Label(label="QUICK PRESETS")
        pl.add_css_class("section-title")
        pl.set_halign(Gtk.Align.START)
        preset_card.append(pl)

        preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._preset_btns = {}
        for name in PRESET_PROFILES:
            btn = Gtk.Button(label=name)
            btn.add_css_class("preset-btn")
            btn.connect("clicked", self._on_preset, name)
            preset_row.append(btn)
            self._preset_btns[name] = btn
        preset_card.append(preset_row)
        box.append(preset_card)

        # Fan sliders
        fan_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        fan_card.add_css_class("card")

        self._fan_cpu_slider, self._fan_cpu_val = self._fan_slider(
            "CPU Fan", "fan_cpu", self.config.get("fan_cpu", 50))
        self._fan_gpu_slider, self._fan_gpu_val = self._fan_slider(
            "GPU Fan", "fan_gpu", self.config.get("fan_gpu", 50))

        fan_card.append(self._fan_cpu_slider)
        fan_card.append(self._fan_gpu_slider)

        apply_btn = Gtk.Button(label="Apply Fan Speeds")
        apply_btn.add_css_class("preset-btn")
        apply_btn.set_halign(Gtk.Align.END)
        apply_btn.connect("clicked", self._apply_fans)
        fan_card.append(apply_btn)
        box.append(fan_card)
        return box

    def _fan_slider(self, label, key, default):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        lbl = Gtk.Label(label=label)
        lbl.set_markup(f'<span weight="600">{label}</span>')
        lbl.set_halign(Gtk.Align.START)
        lbl.set_hexpand(True)
        val_lbl = Gtk.Label(label=f"{default}%")
        val_lbl.set_markup(f'<span color="#FF5000" weight="bold">{default}%</span>')
        header.append(lbl)
        header.append(val_lbl)

        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        scale.set_value(default)
        scale.set_hexpand(True)
        scale.set_draw_value(False)

        def on_change(s):
            v = int(s.get_value())
            val_lbl.set_markup(f'<span color="#FF5000" weight="bold">{v}%</span>')
            self.config[key] = v

        scale.connect("value-changed", on_change)
        container.append(header)
        container.append(scale)
        return container, val_lbl

    def _on_preset(self, btn, name):
        for b in self._preset_btns.values():
            b.remove_css_class("active")
        btn.add_css_class("active")
        preset = PRESET_PROFILES.get(name)
        if preset:
            cpu, gpu = map(int, preset["fan"].split(","))
            # Update sliders
            for child in self._fan_cpu_slider:
                if isinstance(child, Gtk.Scale):
                    child.set_value(cpu)
            for child in self._fan_gpu_slider:
                if isinstance(child, Gtk.Scale):
                    child.set_value(gpu)
            self._apply_fans(None)
            # Apply thermal
            sysfs_write(THERMAL_PATH, preset["thermal"])
            # Apply LCD
            sysfs_write(LCD_OVERRIDE, "1" if preset["lcd"] else "0")

    def _apply_fans(self, btn):
        cpu = self.config.get("fan_cpu", 50)
        gpu = self.config.get("fan_gpu", 50)
        sysfs_write(FAN_SPEED, f"{cpu},{gpu}")
        self._save_config()

    # ── Thermal ──────────────────────────────────────────────────────────────
    def _build_thermal(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(24); box.set_margin_bottom(24)
        box.set_margin_start(24); box.set_margin_end(24)

        hdr = Gtk.Label()
        hdr.set_markup('<span font="20" weight="bold">Thermal Profiles</span>')
        hdr.set_halign(Gtk.Align.START)
        box.append(hdr)

        # AC warning
        bat_status = sysfs_read("/sys/class/power_supply/BAT0/status") or ""
        on_battery = bat_status.lower() not in ("charging", "full", "not charging")
        ac_warn = Gtk.Label()
        ac_warn.set_markup(
            "ℹ  <b>Turbo and Performance modes require AC power (charger plugged in).</b>"
        )
        ac_warn.add_css_class("warning-bar")
        ac_warn.set_wrap(True)
        ac_warn.set_xalign(0)
        box.append(ac_warn)

        current = sysfs_read(THERMAL_PATH) or self.config.get("thermal", "balanced")

        profile_cards = {
            "performance":          ("🔥  Turbo",       "Max CPU/GPU clocks, fans at full speed. AC power required."),
            "balanced-performance": ("⚡  Performance",  "High clocks and fan speeds for gaming. AC power required."),
            "balanced":             ("⚖  Balanced",     "Balances performance and noise. Works on battery and AC."),
            "low-power":            ("🤫  Quiet",        "Minimizes noise for light tasks. Works on battery and AC."),
        }

        self._thermal_btns = {}
        for pid, (title, desc) in profile_cards.items():
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.add_css_class("card")

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            text_box.set_hexpand(True)
            t_lbl = Gtk.Label()
            t_lbl.set_markup(f'<span weight="bold" font="14">{title}</span>')
            t_lbl.set_halign(Gtk.Align.START)
            d_lbl = Gtk.Label(label=desc)
            d_lbl.add_css_class("sub-label")
            d_lbl.set_halign(Gtk.Align.START)
            d_lbl.set_wrap(True)
            text_box.append(t_lbl)
            text_box.append(d_lbl)

            apply_btn = Gtk.Button(label="Activate")
            apply_btn.add_css_class("preset-btn")
            apply_btn.set_valign(Gtk.Align.CENTER)
            apply_btn.connect("clicked", self._set_thermal, pid)
            if pid == current:
                apply_btn.add_css_class("active")
                apply_btn.set_label("Active ✓")

            row.append(text_box)
            row.append(apply_btn)
            card.append(row)
            box.append(card)
            self._thermal_btns[pid] = apply_btn

        return box

    def _set_thermal(self, btn, profile):
        sysfs_write(PLATFORM_PROFILE, profile)
        # Also apply matching fan speed for this profile
        if profile in PROFILE_FAN_SPEEDS:
            cpu, gpu = PROFILE_FAN_SPEEDS[profile]
            sysfs_write(FAN_SPEED, f"{cpu},{gpu}")
            self.config["fan_cpu"] = cpu
            self.config["fan_gpu"] = gpu
        self.config["thermal"] = profile
        self._save_config()
        self._sync_profile_ui(profile)

    def _sync_profile_ui(self, profile):
        """Sync all profile-related UI to the given profile name."""
        for pid, b in getattr(self, "_thermal_btns", {}).items():
            if pid == profile:
                b.add_css_class("active")
                b.set_label("Active ✓")
            else:
                b.remove_css_class("active")
                b.set_label("Activate")
        # Display names matching the thermal page exactly
        icons = {"performance": "🔥", "balanced-performance": "⚡", "balanced": "⚖", "low-power": "🤫"}
        names = {"performance": "Turbo", "balanced-performance": "Performance", "balanced": "Balanced", "low-power": "Quiet"}
        icon = icons.get(profile, "⚖")
        name = names.get(profile, profile.title())
        if hasattr(self, "_profile_cycle_lbl"):
            self._profile_cycle_lbl.set_markup(
                f'<span color="#FF6B00" weight="bold">{icon}  {name}</span>'
            )

    def _on_ac_changed(self, on_ac):
        """Show/hide battery warning on thermal page when AC state changes."""
        if hasattr(self, "_ac_warning_bar"):
            self._ac_warning_bar.set_visible(not on_ac)

    def _cycle_profile(self, btn):
        profiles = ["low-power", "balanced", "balanced-performance", "performance"]
        current = sysfs_read(PLATFORM_PROFILE) or "balanced"
        try:
            idx = profiles.index(current)
        except ValueError:
            idx = 1
        next_profile = profiles[(idx + 1) % len(profiles)]
        sysfs_write(PLATFORM_PROFILE, next_profile)
        # Apply matching fan speed
        if next_profile in PROFILE_FAN_SPEEDS:
            cpu, gpu = PROFILE_FAN_SPEEDS[next_profile]
            sysfs_write(FAN_SPEED, f"{cpu},{gpu}")
            self.config["fan_cpu"] = cpu
            self.config["fan_gpu"] = gpu
        self.config["thermal"] = next_profile
        self._save_config()
        self._sync_profile_ui(next_profile)

    # ── Keyboard RGB ─────────────────────────────────────────────────────────
    def _build_keyboard(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(24); box.set_margin_bottom(24)
        box.set_margin_start(24); box.set_margin_end(24)

        hdr = Gtk.Label()
        hdr.set_markup('<span font="20" weight="bold">Keyboard</span>')
        hdr.set_halign(Gtk.Align.START)
        box.append(hdr)

        # Backlight timeout (supported via sysfs)
        timeout_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        timeout_card.add_css_class("card")
        tl = Gtk.Label(label="KEYBOARD BACKLIGHT")
        tl.add_css_class("section-title")
        tl.set_halign(Gtk.Align.START)
        timeout_card.append(tl)

        timeout_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        tll = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tll.set_hexpand(True)
        tl1 = Gtk.Label()
        tl1.set_markup('<span weight="bold">Auto-off after 30s idle</span>')
        tl1.set_halign(Gtk.Align.START)
        tl2 = Gtk.Label(label="Turns off keyboard backlight when idle to save power.")
        tl2.add_css_class("sub-label")
        tl2.set_halign(Gtk.Align.START)
        tll.append(tl1); tll.append(tl2)
        self._timeout_sw = Gtk.Switch()
        self._timeout_sw.set_active(self.config.get("backlight_timeout", False))
        self._timeout_sw.set_valign(Gtk.Align.CENTER)
        self._timeout_sw.connect("state-set", self._on_timeout)
        timeout_row.append(tll)
        timeout_row.append(self._timeout_sw)
        timeout_card.append(timeout_row)
        box.append(timeout_card)

        # Boot animation/sound (supported)
        boot_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        boot_card.add_css_class("card")
        bl = Gtk.Label(label="BOOT ANIMATION & SOUND")
        bl.add_css_class("section-title")
        bl.set_halign(Gtk.Align.START)
        boot_card.append(bl)

        boot_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bll = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bll.set_hexpand(True)
        bl1 = Gtk.Label()
        bl1.set_markup('<span weight="bold">Boot Animation &amp; Sound</span>')
        bl1.set_halign(Gtk.Align.START)
        bl2 = Gtk.Label(label="Enable/disable the Predator boot animation and startup sound.")
        bl2.add_css_class("sub-label")
        bl2.set_halign(Gtk.Align.START)
        bll.append(bl1); bll.append(bl2)
        boot_val = sysfs_read(BOOT_ANIM_SOUND)
        self._boot_anim_sw = Gtk.Switch()
        self._boot_anim_sw.set_active(boot_val == "1")
        self._boot_anim_sw.set_valign(Gtk.Align.CENTER)
        self._boot_anim_sw.connect("state-set", self._on_boot_anim)
        boot_row.append(bll)
        boot_row.append(self._boot_anim_sw)
        boot_card.append(boot_row)
        box.append(boot_card)

        # RGB info card
        rgb_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        rgb_card.add_css_class("card")
        rl = Gtk.Label(label="PER-KEY RGB")
        rl.add_css_class("section-title")
        rl.set_halign(Gtk.Align.START)
        rgb_card.append(rl)
        ri = Gtk.Label(
            label="PHN16S-71 has per-key RGB. The linuwu_sense module does not expose "
                  "per-key RGB via sysfs on this model. Use Fn+F7/F8 to cycle hardware presets. "
                  "Backlight timeout and boot animation are controllable above."
        )
        ri.set_wrap(True)
        ri.set_xalign(0)
        rgb_card.append(ri)
        box.append(rgb_card)

        # Profile button card
        profile_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        profile_card.add_css_class("card")
        pl = Gtk.Label(label="PROFILE BUTTON")
        pl.add_css_class("section-title")
        pl.set_halign(Gtk.Align.START)
        profile_card.append(pl)

        self._profile_btn_status = Gtk.Label(
            label="The Predator profile button cycles thermal profiles in hardware. "
                  "Press it and the Thermal Profile page updates automatically."
        )
        self._profile_btn_status.set_wrap(True)
        self._profile_btn_status.set_xalign(0)
        profile_card.append(self._profile_btn_status)

        self._current_profile_lbl = Gtk.Label()
        self._current_profile_lbl.set_markup(
            f'<span font="16" color="#FF5000" weight="bold">Current: {sysfs_read(PLATFORM_PROFILE) or "unknown"}</span>'
        )
        self._current_profile_lbl.set_halign(Gtk.Align.START)
        profile_card.append(self._current_profile_lbl)
        box.append(profile_card)

        return box

    def _on_timeout(self, sw, state):
        sysfs_write(BACKLIGHT_TO, "1" if state else "0")
        self.config["backlight_timeout"] = state
        self._save_config()

    def _on_boot_anim(self, sw, state):
        sysfs_write(BOOT_ANIM_SOUND, "1" if state else "0")

    # ── Battery ──────────────────────────────────────────────────────────────
    def _build_battery(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(24); box.set_margin_bottom(24)
        box.set_margin_start(24); box.set_margin_end(24)

        hdr = Gtk.Label()
        hdr.set_markup('<span font="20" weight="bold">Battery</span>')
        hdr.set_halign(Gtk.Align.START)
        box.append(hdr)

        limit_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        limit_card.add_css_class("card")

        r1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        ll = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        ll.set_hexpand(True)
        l1 = Gtk.Label()
        l1.set_markup('<span weight="bold">Battery Limiter (80%)</span>')
        l1.set_halign(Gtk.Align.START)
        l2 = Gtk.Label(label="Limits charging to 80% to extend long-term battery health.")
        l2.add_css_class("sub-label")
        l2.set_halign(Gtk.Align.START)
        l2.set_wrap(True)
        ll.append(l1); ll.append(l2)
        self._bat_limit_sw = Gtk.Switch()
        self._bat_limit_sw.set_active(self.config.get("battery_limit", False))
        self._bat_limit_sw.set_valign(Gtk.Align.CENTER)
        self._bat_limit_sw.connect("state-set", self._on_bat_limit)
        r1.append(ll); r1.append(self._bat_limit_sw)
        limit_card.append(r1)
        box.append(limit_card)

        cal_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        cal_card.add_css_class("card")
        cl1 = Gtk.Label()
        cl1.set_markup('<span weight="bold">Battery Calibration</span>')
        cl1.set_halign(Gtk.Align.START)
        cl2 = Gtk.Label(label="Runs a full charge-discharge cycle to recalibrate battery gauge.\nPlug in charger before starting.")
        cl2.add_css_class("sub-label")
        cl2.set_halign(Gtk.Align.START)
        cl2.set_wrap(True)
        cal_btn = Gtk.Button(label="Start Calibration")
        cal_btn.add_css_class("preset-btn")
        cal_btn.set_halign(Gtk.Align.START)
        cal_btn.connect("clicked", self._on_cal)
        cal_card.append(cl1); cal_card.append(cl2); cal_card.append(cal_btn)
        box.append(cal_card)

        usb_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        usb_card.add_css_class("card")
        ul1 = Gtk.Label()
        ul1.set_markup('<span weight="bold">USB Charging (Sleep)</span>')
        ul1.set_halign(Gtk.Align.START)
        ul2 = Gtk.Label(label="Allow USB ports to charge devices while laptop is sleeping.")
        ul2.add_css_class("sub-label")
        ul2.set_halign(Gtk.Align.START)

        usb_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        usb_lbl = Gtk.Label(label="USB charging power:")
        usb_lbl.add_css_class("sub-label")
        self._usb_combo = Gtk.DropDown.new_from_strings(["Off", "5W", "10W", "20W", "45W"])
        self._usb_combo.set_selected(2)
        usb_row.append(usb_lbl); usb_row.append(self._usb_combo)

        usb_apply = Gtk.Button(label="Apply")
        usb_apply.add_css_class("preset-btn")
        usb_apply.connect("clicked", self._on_usb_charge)
        usb_card.append(ul1); usb_card.append(ul2)
        usb_card.append(usb_row); usb_card.append(usb_apply)
        box.append(usb_card)
        return box

    def _on_bat_limit(self, sw, state):
        sysfs_write(BATTERY_LIMIT, "1" if state else "0")
        self.config["battery_limit"] = state
        self._save_config()

    def _on_cal(self, btn):
        sysfs_write(BATTERY_CAL, "1")

    def _on_usb_charge(self, btn):
        watt_map = [0, 5, 10, 20, 45]
        idx = self._usb_combo.get_selected()
        sysfs_write(USB_CHARGING, str(watt_map[idx]))

    # ── Display ──────────────────────────────────────────────────────────────
    def _build_display(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(24); box.set_margin_bottom(24)
        box.set_margin_start(24); box.set_margin_end(24)

        hdr = Gtk.Label()
        hdr.set_markup('<span font="20" weight="bold">Display</span>')
        hdr.set_halign(Gtk.Align.START)
        box.append(hdr)

        lcd_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        lcd_card.add_css_class("card")
        lcd_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        lcd_lbl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        lcd_lbl_box.set_hexpand(True)
        l1 = Gtk.Label()
        l1.set_markup('<span weight="bold">LCD Override (MUX Switch)</span>')
        l1.set_halign(Gtk.Align.START)
        l2 = Gtk.Label(label="Reduces LCD latency and minimizes ghosting. Requires re-login.")
        l2.add_css_class("sub-label")
        l2.set_halign(Gtk.Align.START)
        l2.set_wrap(True)
        lcd_lbl_box.append(l1); lcd_lbl_box.append(l2)
        self._lcd_sw = Gtk.Switch()
        lcd_val = sysfs_read(LCD_OVERRIDE)
        self._lcd_sw.set_active(lcd_val == "1")
        self._lcd_sw.set_valign(Gtk.Align.CENTER)
        self._lcd_sw.connect("state-set", self._on_lcd)
        lcd_row.append(lcd_lbl_box); lcd_row.append(self._lcd_sw)
        lcd_card.append(lcd_row)
        box.append(lcd_card)

        # GPU mode (envycontrol)
        gpu_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        gpu_card.add_css_class("card")
        gl = Gtk.Label(label="GPU MODE (ENVYCONTROL)")
        gl.add_css_class("section-title")
        gl.set_halign(Gtk.Align.START)
        gpu_card.append(gl)

        gpu_desc = {
            "integrated":  ("Integrated Only", "Use only Intel GPU.\nBest battery life."),
            "hybrid":      ("Hybrid (Recommended)", "iGPU default, NVIDIA on-demand.\nBalance of battery and performance."),
            "nvidia":      ("NVIDIA Only", "Force discrete NVIDIA GPU.\nMax performance, high power draw."),
        }
        self._gpu_btns = {}
        for mode, (title, desc) in gpu_desc.items():
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            tb.set_hexpand(True)
            tl = Gtk.Label()
            tl.set_markup(f'<span weight="bold">{title}</span>')
            tl.set_halign(Gtk.Align.START)
            dl = Gtk.Label(label=desc)
            dl.add_css_class("sub-label")
            dl.set_halign(Gtk.Align.START)
            dl.set_wrap(True)
            tb.append(tl); tb.append(dl)
            btn = Gtk.Button(label="Set")
            btn.add_css_class("preset-btn")
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect("clicked", self._set_gpu_mode, mode)
            row.append(tb); row.append(btn)
            gpu_card.append(row)
            self._gpu_btns[mode] = btn

        box.append(gpu_card)
        return box

    def _on_lcd(self, sw, state):
        sysfs_write(LCD_OVERRIDE, "1" if state else "0")

    def _set_gpu_mode(self, btn, mode):
        try:
            subprocess.Popen(["pkexec", "envycontrol", "--switch", mode])
        except Exception:
            pass

    # ── System ───────────────────────────────────────────────────────────────
    def _build_system(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(24); box.set_margin_bottom(24)
        box.set_margin_start(24); box.set_margin_end(24)

        hdr = Gtk.Label()
        hdr.set_markup('<span font="20" weight="bold">System Info</span>')
        hdr.set_halign(Gtk.Align.START)
        box.append(hdr)

        specs = [
            ("Model",      "Acer Predator PHN16S-71"),
            ("CPU",        "Intel Core Ultra 9 275HX (24 cores)"),
            ("GPU",        "NVIDIA GeForce RTX 5070 Ti Laptop"),
            ("iGPU",       "Intel Arrow Lake-S"),
            ("RAM",        "32.0 GiB"),
            ("OS",         "CachyOS (Arch-based)"),
            ("Kernel",     "Linux 7.0.3-1-cachyos"),
            ("Desktop",    "GNOME 50 / Wayland"),
            ("Firmware",   "V1.26"),
            ("Driver",     "linuwu_sense (Linuwu-Sense)"),
        ]

        info_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        info_card.add_css_class("card")
        il = Gtk.Label(label="HARDWARE SPECIFICATIONS")
        il.add_css_class("section-title")
        il.set_halign(Gtk.Align.START)
        info_card.append(il)

        for k, v in specs:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            kl = Gtk.Label(label=k)
            kl.add_css_class("sub-label")
            kl.set_size_request(130, -1)
            kl.set_halign(Gtk.Align.START)
            vl = Gtk.Label(label=v)
            vl.set_markup(f'<span>{v}</span>')
            vl.set_halign(Gtk.Align.START)
            vl.set_selectable(True)
            row.append(kl); row.append(vl)
            info_card.append(row)
        box.append(info_card)

        # Quick actions
        act_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        act_card.add_css_class("card")
        al = Gtk.Label(label="QUICK ACTIONS")
        al.add_css_class("section-title")
        al.set_halign(Gtk.Align.START)
        act_card.append(al)

        actions = [
            ("Reload Driver",     self._reload_driver),
            ("Check Driver Status",self._check_driver),
            ("Open System Monitor",self._open_sysmon),
        ]
        act_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, cb in actions:
            btn = Gtk.Button(label=label)
            btn.add_css_class("preset-btn")
            btn.connect("clicked", cb)
            act_row.append(btn)
        act_card.append(act_row)
        box.append(act_card)
        return box

    def _reload_driver(self, btn):
        subprocess.Popen(["pkexec", "bash", "-c",
            "modprobe -r linuwu_sense; modprobe linuwu_sense"])

    def _check_driver(self, btn):
        try:
            out = subprocess.check_output(["lsmod"], text=True)
            loaded = "linuwu_sense" in out
            dlg = Adw.MessageDialog.new(self,
                "Driver Status",
                f"linuwu_sense: {'✓ Loaded' if loaded else '✗ Not loaded'}")
            dlg.add_response("ok", "OK")
            dlg.present()
        except Exception:
            pass

    def _open_sysmon(self, btn):
        for app in ["gnome-system-monitor", "plasma-systemmonitor", "htop"]:
            try:
                subprocess.Popen([app]); return
            except Exception:
                pass

    # ── Sensor loop ──────────────────────────────────────────────────────────
    def _start_sensor_loop(self):
        def loop():
            while True:
                data = read_sensors()
                GLib.idle_add(self._update_ui, data)
                time.sleep(2)

        t = threading.Thread(target=loop, daemon=True)
        t.start()

        # Watch for AC plug/unplug events
        def ac_watcher():
            last_ac = None
            while True:
                try:
                    status = sysfs_read("/sys/class/power_supply/BAT0/status") or ""
                    on_ac = status.lower() in ("charging", "full", "not charging")
                    if on_ac != last_ac:
                        last_ac = on_ac
                        GLib.idle_add(self._on_ac_changed, on_ac)
                except Exception:
                    pass
                time.sleep(3)

        acw = threading.Thread(target=ac_watcher, daemon=True)
        acw.start()

        # Listen for KEY_PRESENTATION (code 425) to cycle profiles
        kl = threading.Thread(target=self._key_listener, daemon=True)
        kl.start()

    def _key_listener(self):
        """Listen for KEY_PRESENTATION (425) on /dev/input/event2."""
        if not HAS_EVDEV:
            return
        import evdev
        KEY_PRESENTATION = 425
        while True:
            try:
                device = evdev.InputDevice("/dev/input/event2")
                for event in device.read_loop():
                    if event.type == evdev.ecodes.EV_KEY and event.code == KEY_PRESENTATION and event.value == 1:
                        GLib.idle_add(self._cycle_profile, None)
            except PermissionError:
                time.sleep(5)
            except Exception:
                time.sleep(2)

    def _on_profile_changed_externally(self, profile):
        """Called when profile button changes the thermal profile."""
        # Update thermal page buttons
        for pid, b in getattr(self, "_thermal_btns", {}).items():
            if pid == profile:
                b.add_css_class("active")
                b.set_label("Active ✓")
            else:
                b.remove_css_class("active")
                b.set_label("Activate")
        # Update keyboard page label
        if hasattr(self, "_current_profile_lbl"):
            self._current_profile_lbl.set_markup(
                f'<span font="16" color="#FF5000" weight="bold">Current: {profile}</span>'
            )
        self.config["thermal"] = profile
        self._save_config()

    def _update_ui(self, data):
        # Gauges
        cpu_u = data.get("cpu_util", 0) or 0
        self._gauge_cpu[1].set_value(cpu_u, f"{cpu_u}%")

        ct = data.get("cpu_temp")
        if ct:
            self._gauge_ctemp[1].set_value(min(ct, 100), f"{ct:.0f}°")

        gpu_u = data.get("gpu_util", 0) or 0
        self._gauge_gpu[1].set_value(gpu_u, f"{gpu_u}%")

        gt = data.get("gpu_temp")
        if gt:
            self._gauge_gtemp[1].set_value(min(gt, 100), f"{gt:.0f}°")

        ram_p = data.get("ram_pct", 0) or 0
        ram_u = data.get("ram_used_gb", 0) or 0
        ram_t = data.get("ram_total_gb", 0) or 0
        self._gauge_ram[1].set_value(ram_p, f"{ram_u}G")

        bat_p = data.get("battery_pct")
        if bat_p is not None:
            self._gauge_bat[1].set_value(bat_p, f"{bat_p}%")

        # Real fan RPM display in info grid
        for key, (lbl, unit) in self._info_labels.items():
            val = data.get(key)
            if key == "fan_cpu":
                rpm = data.get("fan1_rpm")
                val = f"{rpm} RPM" if rpm else (f"{data.get('fan_cpu', '–')}%" if data.get('fan_cpu') else "–")
                unit = ""
            elif key == "fan_gpu":
                rpm = data.get("fan2_rpm")
                val = f"{rpm} RPM" if rpm else (f"{data.get('fan_gpu', '–')}%" if data.get('fan_gpu') else "–")
                unit = ""
            elif key == "thermal":
                raw = data.get("thermal", "–")
                names = {"performance": "Turbo", "balanced-performance": "Performance",
                         "balanced": "Balanced", "low-power": "Quiet"}
                val = names.get(raw, raw)
                unit = ""
            if val is not None:
                text = f"{val}{unit}" if unit else str(val)
                lbl.set_markup(f'<span weight="bold">{text}</span>')


def main():
    app = PredatorApp()
    return app.run(sys.argv)

if __name__ == "__main__":
    sys.exit(main())
