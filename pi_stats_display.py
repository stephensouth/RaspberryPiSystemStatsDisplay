#!/usr/bin/env python3
"""
Raspberry Pi stats display for 128x32 I2C OLED (e.g. Adafruit PiOLED).
- Momentary button: press to turn on / show main stats; hold 3s to show USB drive stats.
- WS2812B LED: overall load indicator (green -> yellow -> orange -> red flashing).
- Compatible with Raspberry Pi 3, 4, and 5.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    # Fallback loader so .env still works without python-dotenv installed.
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"' ")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            pass

# -----------------------------------------------------------------------------
# Configuration (override via env or .env)
# -----------------------------------------------------------------------------
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 32
BUTTON_GPIO = int(os.environ.get("PI_STATS_BUTTON_GPIO", "17"))  # BCM 17
LED_GPIO = int(os.environ.get("PI_STATS_LED_GPIO", "18"))        # BCM 18 (PWM for WS2812B)
LED_COUNT = int(os.environ.get("PI_STATS_LED_COUNT", "1"))       # number of WS2812B LEDs
DISPLAY_IDLE_OFF_SECONDS = float(os.environ.get("PI_STATS_DISPLAY_IDLE_OFF", "60"))
SCREEN_ROTATE_SECONDS = float(os.environ.get("PI_STATS_SCREEN_ROTATE_SECONDS", "4.2"))
LABEL_FONT_SIZE = int(os.environ.get("PI_STATS_LABEL_FONT_SIZE", "8"))
VALUE_FONT_SIZE = int(os.environ.get("PI_STATS_VALUE_FONT_SIZE", "18"))
I2C_ADDRESS = int(os.environ.get("PI_STATS_OLED_I2C_ADDR", "0x3C"), 16)
DEBUG_FORCE_MAIN_VIEW = os.environ.get("PI_STATS_DEBUG_FORCE_MAIN_VIEW", "0") == "1"
BUTTON_ACTIVE_LOW = os.environ.get("PI_STATS_BUTTON_ACTIVE_LOW", "1") == "1"

# View state
VIEW_OFF = "off"
VIEW_MAIN = "main"
VIEW_USB = "usb"

# LED load levels (0-100 stress) -> (name, (R,G,B), flash_interval_sec, 0=solid)
LED_LEVELS = [
    (8, (0, 80, 0), 0),           # dark green
    (16, (0, 150, 0), 0),         # medium green
    (24, (100, 255, 100), 0),     # light green
    (32, (200, 255, 100), 0),     # light yellow
    (40, (220, 220, 0), 0),       # medium yellow
    (48, (180, 180, 0), 0),       # dark yellow
    (56, (255, 180, 100), 0),     # light orange
    (64, (255, 140, 0), 0),       # medium orange
    (72, (200, 100, 0), 0),       # dark orange
    (80, (255, 100, 100), 1.0),   # slow flashing light red
    (88, (255, 50, 50), 0.4),     # flashing medium red
    (101, (150, 0, 0), 0.15),     # fast flashing dark red
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# System stats (Linux, Pi 3/4/5)
# -----------------------------------------------------------------------------
def get_ip() -> str:
    try:
        out = subprocess.check_output(
            ["hostname", "-I"],
            text=True,
            timeout=2,
        )
        return out.split()[0].strip() if out.split() else "N/A"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, IndexError):
        return "N/A"


def get_cpu_load() -> str:
    try:
        with open("/proc/loadavg", "r") as f:
            load = f.read().split()[0]
        return load
    except OSError:
        return "N/A"


def get_cpu_load_1m() -> float:
    """Return the 1-minute CPU load average."""
    try:
        with open("/proc/loadavg", "r") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def get_cpu_throttle_line() -> str:
    """
    CPU throttle rate based on current/max CPU frequency.
    Example: "CPU Thr:67% 1200MHz"
    """
    try:
        cur_khz = None
        max_khz = None
        # Try policy0 first (modern kernels), then cpu0 fallback.
        for cur_path, max_path in (
            ("/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq", "/sys/devices/system/cpu/cpufreq/policy0/cpuinfo_max_freq"),
            ("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"),
        ):
            if Path(cur_path).exists() and Path(max_path).exists():
                cur_khz = int(Path(cur_path).read_text().strip())
                max_khz = int(Path(max_path).read_text().strip())
                break
        if not cur_khz or not max_khz:
            return "CPU Thr:N/A"
        rate_pct = (cur_khz / max_khz) * 100 if max_khz > 0 else 0.0
        cur_mhz = int(round(cur_khz / 1000))
        return f"CPU Thr:{rate_pct:.0f}% {cur_mhz}MHz"
    except (OSError, ValueError):
        return "CPU Thr:N/A"


def get_memory_stats() -> tuple[str, str, float]:
    """Returns (used_str, total_str, pct)."""
    try:
        with open("/proc/meminfo", "r") as f:
            lines = f.read().splitlines()
        mem = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.strip().split()[0])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        used = total - avail
        if total <= 0:
            return "0", "0", 0.0
        pct = (used / total) * 100
        return f"{used // 1024}", f"{total // 1024}", pct
    except OSError:
        return "0", "0", 0.0


def get_disk_stats(mount_point: str = "/") -> tuple[str, str, float] | None:
    """Returns (used_gb_str, total_gb_str, pct) or None."""
    try:
        out = subprocess.check_output(
            ["df", "-B", "1G", "--output=used,size,pcent", mount_point],
            text=True,
            timeout=2,
        )
        lines = out.strip().splitlines()
        if len(lines) < 2:
            return None
        parts = lines[1].split()
        if len(parts) < 3:
            return None
        used_gb = int(parts[0])
        total_gb = int(parts[1])
        pct_str = parts[2].replace("%", "")
        pct = float(pct_str) if pct_str else 0.0
        return str(used_gb), str(total_gb), pct
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def get_disk_stats_mb(mount_point: str = "/") -> tuple[int, int, float] | None:
    """Returns (used_mb, total_mb, pct) or None."""
    try:
        out = subprocess.check_output(
            ["df", "-B", "1M", "--output=used,size,pcent", mount_point],
            text=True,
            timeout=2,
        )
        lines = out.strip().splitlines()
        if len(lines) < 2:
            return None
        parts = lines[1].split()
        if len(parts) < 3:
            return None
        used_mb = int(parts[0])
        total_mb = int(parts[1])
        pct = float(parts[2].replace("%", ""))
        return used_mb, total_mb, pct
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def get_usb_drives() -> list[tuple[str, str, str, float]]:
    """
    Returns list of (mount_point, used_gb, total_gb, pct) for removable/USB block devices.
    Uses /sys/block/*/removable and mount info; also includes /media and /mnt mounts.
    """
    result: list[tuple[str, str, str, float]] = []
    seen: set[str] = set()
    block = Path("/sys/block")
    if block.exists():
        for dev_dir in block.iterdir():
            name = dev_dir.name
            if not (name.startswith("sd") or name.startswith("nvme")):
                continue
            removable = dev_dir / "removable"
            if not removable.exists():
                continue
            try:
                if removable.read_text().strip() != "1":
                    continue
            except OSError:
                continue
            for part_dir in block.iterdir():
                if part_dir.name == name or not part_dir.name.startswith(name):
                    continue
                try:
                    with open("/proc/mounts", "r") as f:
                        for line in f:
                            parts = line.split()
                            if len(parts) < 2:
                                continue
                            dev_node, mount_point = parts[0], parts[1]
                            if "/dev/" + part_dir.name in dev_node or dev_node.endswith(part_dir.name):
                                disk = get_disk_stats(mount_point)
                                if disk and mount_point not in seen:
                                    used_gb, total_gb, pct = disk
                                    result.append((mount_point, used_gb, total_gb, pct))
                                    seen.add(mount_point)
                                break
                except OSError:
                    pass
    try:
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                mount_point = parts[1]
                if mount_point == "/":
                    continue
                if not (mount_point.startswith("/media") or mount_point.startswith("/mnt")):
                    continue
                disk = get_disk_stats(mount_point)
                if disk and mount_point not in seen:
                    used_gb, total_gb, pct = disk
                    result.append((mount_point, used_gb, total_gb, pct))
                    seen.add(mount_point)
    except OSError:
        pass
    return result


def get_stress_score() -> float:
    """0-100 score from CPU load (1-min), memory %, and root disk %."""
    try:
        with open("/proc/loadavg", "r") as f:
            load1 = float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        load1 = 0.0
    _, _, mem_pct = get_memory_stats()
    root = get_disk_stats("/")
    disk_pct = root[2] if root else 0.0
    # Normalize: assume 4 cores, so load 4.0 = 100%; cap load contribution at 50, mem 25, disk 25
    load_score = min(100, (load1 / 4.0) * 50) if load1 else 0
    mem_score = min(100, mem_pct * 0.25)
    disk_score = min(100, disk_pct * 0.25)
    return min(100.0, load_score + mem_score + disk_score)


# -----------------------------------------------------------------------------
# WS2812B status LED
# -----------------------------------------------------------------------------
def _led_level_for_stress(stress: float) -> tuple[tuple[int, int, int], float]:
    for threshold, rgb, interval in LED_LEVELS:
        if stress < threshold:
            return rgb, interval
    return (150, 0, 0), 0.15


_led_strip = None
_led_lock = threading.Lock()


def led_init() -> bool:
    global _led_strip
    # Prefer rpi_ws281x (Pi 3/4; Pi 5 may need kernel module or use neopixel)
    try:
        from rpi_ws281x import Adafruit_NeoPixel
        strip = Adafruit_NeoPixel(
            LED_COUNT,
            LED_GPIO,
            freq_hz=800000,
            dma=10,
            invert=False,
            brightness=180,
            channel=0,
            strip_type=0,  # WS2812
        )
        strip.begin()
        _led_strip = ("rpi_ws281x", strip, None)
        return True
    except Exception as e:
        log.warning("WS2812B rpi_ws281x failed: %s", e)
    # Fallback: Blinka NeoPixel (e.g. Pi 5 with rp1 overlay)
    try:
        import board
        import neopixel
        pin = getattr(board, f"D{LED_GPIO}", None) or getattr(board, "D18", None)
        if pin is None:
            pin = board.D18
        pixel = neopixel.NeoPixel(pin, LED_COUNT, brightness=0.7, auto_write=True)
        _led_strip = ("neopixel", pixel, None)
        return True
    except Exception as e:
        log.warning("WS2812B neopixel failed: %s", e)
    return False


def led_set_color(r: int, g: int, b: int) -> None:
    with _led_lock:
        if _led_strip is None:
            return
        kind, strip, _ = _led_strip
        if kind == "rpi_ws281x":
            from rpi_ws281x import Color
            c = Color(r, g, b)
            for i in range(LED_COUNT):
                strip.setPixelColor(i, c)
            strip.show()
        elif kind == "neopixel":
            strip.fill((r, g, b))


def led_off() -> None:
    led_set_color(0, 0, 0)


# -----------------------------------------------------------------------------
# OLED display
# -----------------------------------------------------------------------------
_disp = None
_font = None
_font_main = None
_font_label = None
_font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def display_init() -> bool:
    global _disp, _font, _font_main, _font_label
    try:
        import busio
        from board import SCL, SDA
        import adafruit_ssd1306
        from PIL import Image, ImageDraw, ImageFont
        i2c = busio.I2C(SCL, SDA)
        _disp = adafruit_ssd1306.SSD1306_I2C(DISPLAY_WIDTH, DISPLAY_HEIGHT, i2c, addr=I2C_ADDRESS)
        _disp.fill(0)
        _disp.show()
        _font = ImageFont.load_default()
        try:
            _font_main = ImageFont.truetype(_font_path, VALUE_FONT_SIZE)
        except Exception:
            _font_main = _font
        try:
            _font_label = ImageFont.truetype(_font_path, LABEL_FONT_SIZE)
        except Exception:
            _font_label = _font
        return True
    except Exception as e:
        log.warning("OLED init failed: %s", e)
        return False


def display_show_lines(
    lines: list[str],
    *,
    line_height: int = 8,
    use_main_font: bool = False,
) -> None:
    if _disp is None or _font is None:
        return
    try:
        from PIL import Image, ImageDraw
        image = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT), outline=0, fill=0)
        font = _font_main if use_main_font and _font_main is not None else _font
        y = 0
        max_lines = max(1, DISPLAY_HEIGHT // max(1, line_height))
        for line in lines[:max_lines]:
            if line:
                draw.text((0, y), line[:21], font=font, fill=255)
            y += line_height
        _disp.image(image)
        _disp.show()
    except Exception as e:
        log.debug("display_show_lines: %s", e)


def _truncate_to_width(draw, text: str, font, max_w: int) -> str:
    """Trim text to fit width, adding ellipsis when needed."""
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    if (right - left) <= max_w:
        return text
    ellipsis = "..."
    trimmed = text
    while trimmed:
        candidate = trimmed + ellipsis
        l2, _, r2, _ = draw.textbbox((0, 0), candidate, font=font)
        if (r2 - l2) <= max_w:
            return candidate
        trimmed = trimmed[:-1]
    return ellipsis


def display_show_stat_screen(label: str, value: str) -> None:
    """Render label in top quarter and large value in bottom two-thirds."""
    if _disp is None or _font is None:
        return
    try:
        from PIL import Image, ImageDraw

        image = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT), outline=0, fill=0)

        # Label area: top quarter (~8 px).
        label_font = _font_label if _font_label is not None else _font
        label = _truncate_to_width(draw, label, label_font, DISPLAY_WIDTH - 2)
        l_left, l_top, l_right, l_bottom = draw.textbbox((0, 0), label, font=label_font)
        lw = l_right - l_left
        lh = l_bottom - l_top
        lx = max(0, (DISPLAY_WIDTH - lw) // 2 - l_left)
        ly = max(0, (8 - lh) // 2 - l_top)
        draw.text((lx, ly), label, font=label_font, fill=255)

        # Value area: bottom two-thirds (~22 px), starts near y=9.
        value_y0 = 9
        value_h = DISPLAY_HEIGHT - value_y0
        value_font = _font_main if _font_main is not None else _font
        value = _truncate_to_width(draw, value, value_font, DISPLAY_WIDTH - 2)
        v_left, v_top, v_right, v_bottom = draw.textbbox((0, 0), value, font=value_font)
        vw = v_right - v_left
        vh = v_bottom - v_top
        vx = max(0, (DISPLAY_WIDTH - vw) // 2 - v_left)
        # subtract v_top so baseline/ascent is accounted for correctly.
        vy = value_y0 + max(0, (value_h - vh) // 2) - v_top
        draw.text((vx, vy), value, font=value_font, fill=255)

        _disp.image(image)
        _disp.show()
    except Exception as e:
        log.debug("display_show_stat_screen: %s", e)


def display_off() -> None:
    if _disp is not None:
        try:
            _disp.fill(0)
            _disp.show()
        except Exception:
            pass


# BCM to physical pin (40-pin header) for log messages
_BCM_TO_PHYSICAL = {
    2: 3, 3: 5, 4: 7, 17: 11, 27: 13, 22: 15, 23: 16, 24: 18, 25: 22, 5: 29, 6: 31,
    12: 32, 13: 33, 19: 35, 26: 37, 16: 36, 20: 38, 21: 40, 7: 26, 8: 24, 9: 21, 10: 19,
    11: 23, 14: 8, 15: 10, 18: 12,
}


def _bcm_to_physical(bcm: int) -> int:
    return _BCM_TO_PHYSICAL.get(bcm, bcm)


# -----------------------------------------------------------------------------
# Main loop: view state, button, display, LED
# -----------------------------------------------------------------------------
def main() -> None:
    view = VIEW_MAIN if DEBUG_FORCE_MAIN_VIEW else VIEW_OFF
    session_started_at = time.time() if DEBUG_FORCE_MAIN_VIEW else 0.0
    last_button_press = 0.0
    led_flash_on = True
    led_last_flash = 0.0

    if not display_init():
        log.error("No display available. Exiting.")
        sys.exit(1)
    log.info("OLED initialized on I2C addr %s", hex(I2C_ADDRESS))

    # Brief splash so you can confirm the display works (button turns it on after)
    display_show_lines(["Pi Stats Display", "Press button", "to start", ""])
    time.sleep(2)
    if not DEBUG_FORCE_MAIN_VIEW:
        display_off()

    led_ok = led_init()
    if not led_ok:
        log.info("LED disabled; continuing without status LED.")

    try:
        import RPi.GPIO as GPIO
    except ImportError:
        log.error("RPi.GPIO not installed. Install python3-rpi.gpio and use --system-site-packages venv.")
        sys.exit(1)

    # Direct RPi.GPIO polling is more reliable across Pi images than callback backends.
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(
        BUTTON_GPIO,
        GPIO.IN,
        pull_up_down=GPIO.PUD_UP if BUTTON_ACTIVE_LOW else GPIO.PUD_DOWN,
    )
    raw_level = GPIO.input(BUTTON_GPIO)
    button_was_pressed = False
    press_started_at = 0.0
    last_raw_level = raw_level
    last_edge_at = 0.0

    log.info(
        "Running. Button on BCM GPIO %s (physical pin %s). Initial raw=%s (0=pressed/grounded, 1=released). "
        "ActiveLow=%s. Press = start/restart session. Stat screens rotate every %ss. Session off after %ss. Debug force main view=%s",
        BUTTON_GPIO,
        _bcm_to_physical(BUTTON_GPIO),
        raw_level,
        BUTTON_ACTIVE_LOW,
        SCREEN_ROTATE_SECONDS,
        DISPLAY_IDLE_OFF_SECONDS,
        DEBUG_FORCE_MAIN_VIEW,
    )

    try:
        while True:
            now = time.time()
            stress = get_stress_score()

            # Button polling (active-low with pull-up).
            raw_level = GPIO.input(BUTTON_GPIO)
            is_pressed = (raw_level == 0) if BUTTON_ACTIVE_LOW else (raw_level == 1)
            edge_changed = raw_level != last_raw_level
            if edge_changed and (now - last_edge_at) >= 0.06:
                last_edge_at = now
                last_raw_level = raw_level
                log.info("Button edge raw=%s pressed=%s", raw_level, is_pressed)
                # Wake/start on edge even if polarity is mis-set; restart session on pressed edge.
                if view == VIEW_OFF:
                    view = VIEW_MAIN
                    session_started_at = now
                    log.info("Button edge woke display")
            if is_pressed and not button_was_pressed:
                button_was_pressed = True
                press_started_at = now
                last_button_press = now
                log.info("Button pressed (view was %s)", view)
                if view == VIEW_OFF:
                    view = VIEW_MAIN
                    session_started_at = now
                else:
                    # Restart the rotation/timer on each press while active.
                    session_started_at = now
                    view = VIEW_MAIN

            if (not is_pressed) and button_was_pressed:
                button_was_pressed = False
                press_started_at = 0.0
                log.info("Button released")

            # Session timeout: turn display off after configured duration.
            if view != VIEW_OFF and session_started_at > 0 and (now - session_started_at) > DISPLAY_IDLE_OFF_SECONDS:
                view = VIEW_OFF
                display_off()
                if led_ok:
                    led_off()

            if view == VIEW_OFF:
                time.sleep(0.1)
                continue

            # Update LED (with flash for red levels)
            if led_ok:
                rgb, flash_interval = _led_level_for_stress(stress)
                if flash_interval > 0:
                    if now - led_last_flash >= flash_interval:
                        led_last_flash = now
                        led_flash_on = not led_flash_on
                    if led_flash_on:
                        led_set_color(*rgb)
                    else:
                        led_off()
                else:
                    led_set_color(*rgb)

            # Build one-line rotating screens.
            ip = get_ip()
            mem_used, mem_total, mem_pct = get_memory_stats()
            cpu_load_1m = get_cpu_load_1m()
            root_mb = get_disk_stats_mb("/")
            usb = get_usb_drives()
            cores = max(1, os.cpu_count() or 1)
            cpu_pct_1m = min(999, max(0, int(round((cpu_load_1m / cores) * 100))))

            screens: list[tuple[str, str]] = []
            screens.append(("IP", ip))
            screens.append(("CPU", f"{cpu_pct_1m}%"))
            screens.append(("MEM", f"{mem_used}/{mem_total}MB {mem_pct:.0f}%"))
            if root_mb:
                used_mb, total_mb, pct = root_mb
                # Screen 4: full MB values.
                screens.append(("DSK", f"{used_mb}/{total_mb}MB {pct:.0f}%"))
            else:
                screens.append(("DSK", "N/A"))

            if not usb:
                screens.append(("USB", "No drives"))
            else:
                for idx, (mount, used_gb, total_gb, pct) in enumerate(usb, start=1):
                    label = Path(mount).name or mount
                    screens.append((f"USB{idx}", f"{used_gb}/{total_gb}G {pct:.0f}%"))
                    screens.append(("DEV", label))

            rotate = SCREEN_ROTATE_SECONDS if SCREEN_ROTATE_SECONDS > 0 else 4.2
            elapsed = (now - session_started_at) if session_started_at > 0 else 0.0
            screen_idx = int(elapsed / rotate) % max(1, len(screens))
            scr_label, scr_value = screens[screen_idx]
            display_show_stat_screen(scr_label, scr_value)

            time.sleep(0.2)
    finally:
        GPIO.cleanup(BUTTON_GPIO)


if __name__ == "__main__":
    main()
