# Pi Stats Display

Raspberry Pi system stats on a **128×32 I2C OLED** (e.g. [Adafruit PiOLED](https://learn.adafruit.com/adafruit-pioled-128x32-mini-oled-for-raspberry-pi/usage)), with a **momentary button** and optional **WS2812B status LED**. Supports **Pi 3, 4, and 5**.

## Features

- **Rotating single-line screens**: Each stat line is its own screen (IP, CPU throttle rate, memory, disk, and USB details), rotating one line at a time.
- **CPU + RAM stats**: CPU screen shows 1-minute load as a percent; MEM screen shows used/total MB with current %.
- **Momentary button**: Press once to start a 60-second session (configurable). During the session, stat screens auto-rotate every 4.2 seconds (configurable), then the display turns off.
- **WS2812B LED**: Overall “stress” (CPU + memory + disk) as a color gradient: dark green (light load) → green → yellow → orange → red, with slow/medium/fast flashing red at high load. When USB storage (sd*) is accessed, the LED enters a 4.2 s cycle: blue for 2.1 s, then the current load color for 2.1 s, repeating until I/O has been idle for a few seconds.

## Hardware

| Component        | Notes |
|------------------|--------|
| OLED             | 128×32 I2C SSD1306 (e.g. Adafruit PiOLED at 0x3C). |
| Momentary button | One leg to the **button GPIO** (see `PI_STATS_BUTTON_GPIO` in .env), other to **GND**. Enable internal pull-up in software. |
| WS2812B LED      | Data to the **LED GPIO** (see `PI_STATS_LED_GPIO` in .env). Pi 5: see [Pi 5 notes](#raspberry-pi-5) below. |

### Wiring

- **OLED**: I2C (SDA/SCL and power). On Pi: SDA = GPIO 2, SCL = GPIO 3; 3.3 V and GND.
- **Button**: One pin to the **button GPIO** (configurable in .env), other to **GND**. No external resistor; script uses internal pull-up.
- **WS2812B**: Data In → the **LED GPIO** (configurable in .env), 5 V and GND. Use a level shifter if the strip is 5 V and the Pi is 3.3 V for reliability.

See [docs/pi-stats-display-wiring.md](docs/pi-stats-display-wiring.md) for wiring notes.

## Setup (Raspberry Pi OS)

### 1. Enable I2C

```bash
sudo raspi-config
# Interface Options → I2C → Enable
sudo reboot
```

After reboot, plug in the OLED and check:

```bash
sudo i2cdetect -y 1
# Expect 0x3c (or your display address).
```

### 2. Install system packages

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv python3-pil i2c-tools
```

### 3. Get the code on the Pi

Clone this repository on your Pi (or copy the folder), then continue below.

### 4. Python environment (on the Pi)

```bash
cd pi_stats_display
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. Configure (optional)

```bash
cp .env.example .env
# Edit .env: GPIO pins, rotate/timeout values, I2C address, LED count.
```

### 6. Run

**Must run with access to GPIO and I2C** (usually root or `gpio`/`i2c` group):

```bash
sudo .venv/bin/python pi_stats_display.py
```

Or install and run as a systemd service (see [Run on boot](#run-on-boot) below).

## Troubleshooting

### Display never turns on when I press the button

1. **Confirm the display works**  
   When you start the script, the OLED should show “Pi Stats Display / Press button / to start” for 2 seconds, then go blank. If you never see that, the OLED or I2C isn’t working (check wiring, I2C enabled, `sudo i2cdetect -y 1` shows `0x3c`).

2. **Confirm the button is seen by the Pi**  
   Run the button test (same GPIO and permissions as the main script):
   ```bash
   cd pi_stats_display
   sudo .venv/bin/python test_button.py
   ```
   Press the button. You should see `Button pressed` and `Button released` in the terminal. If you don’t:
   - **Wiring**: One button leg must go to the **button GPIO** (see `PI_STATS_BUTTON_GPIO` in .env), the other to **GND** (e.g. pin 9). Not 3.3 V.
   - **GPIO number**: Set `PI_STATS_BUTTON_GPIO` in `.env` to the **BCM** number for your pin (e.g. `27` for physical 13). See a [GPIO map](https://pinout.xyz/).

3. **Run the main script in the foreground**  
   So you can see logs when the button is pressed:
   ```bash
   sudo .venv/bin/python pi_stats_display.py
   ```
   You should see a line like `Button pressed (view was off)` when you press the button. If the display still stays off, the log will confirm whether the press was detected.

4. **Permissions**  
   GPIO usually needs root or the `gpio` group. Use `sudo` when running the script (or run the service as root as in the example).

## Configuration (env)

| Variable | Default | Description |
|----------|---------|-------------|
| `PI_STATS_BUTTON_GPIO` | 17 | BCM GPIO for momentary button. |
| `PI_STATS_LED_GPIO` | 18 | BCM GPIO for WS2812B data. |
| `PI_STATS_LED_COUNT` | 1 | Number of LEDs. |
| `PI_STATS_LED_USB_ACTIVITY_IDLE_SECONDS` | 5.0 | Seconds with no sd* I/O before leaving USB mode. |
| `PI_STATS_LED_USB_CYCLE_SECONDS` | 4.2 | USB mode cycle length (load 2.1s + blue 2.1s). |
| `PI_STATS_LED_USB_LOAD_SECONDS` | 2.1 | Seconds per cycle to show load color in USB mode. |
| `PI_STATS_LED_USB_BLUE_R/G/B` | 0, 0, 200 | RGB for blue phase when USB is active. |
| `PI_STATS_SCREEN_ROTATE_SECONDS` | 4.2 | Auto-rotate interval for stat screens. |
| `PI_STATS_LABEL_FONT_SIZE` | 8 | Fixed label font size (top quarter). |
| `PI_STATS_VALUE_FONT_SIZE` | 18 | Fixed value font size (bottom area). |
| `PI_STATS_DISPLAY_IDLE_OFF` | 60 | Display off after this many seconds idle. |
| `PI_STATS_OLED_I2C_ADDR` | 0x3C | OLED I2C address (hex). |
| `PI_STATS_DEBUG_FORCE_MAIN_VIEW` | 0 | Set to `1` to force main screen for troubleshooting. |

## Run on boot (systemd)

Copy the example unit and enable it:

```bash
sudo cp pi_stats_display.service.example /etc/systemd/system/pi_stats_display.service
# Edit ExecStart= to match your repo path and venv.
sudo systemctl daemon-reload
sudo systemctl enable --now pi_stats_display
```

## Raspberry Pi 5

- **OLED and button**: Work on Pi 5. I2C and GPIO (via gpiozero/lgpio) are supported. If you see GPIO chip errors, see [gpiozero Pi 5 notes](https://github.com/gpiozero/gpiozero/issues/1166) (e.g. chip number workaround).
- **WS2812B**: The `rpi_ws281x` library does not support Pi 5’s RP1 by default. Options:
  1. Use the **experimental Pi 5 branch** (kernel module + device tree overlay): [rpi_ws281x Pi 5 Support](https://github.com/jgarff/rpi_ws281x/wiki/Raspberry-Pi-5-Support). Use GPIO 12, 13, 14, or 15 as documented.
  2. Or run without the LED: the script will log a warning and continue with OLED and button only.

## LED load levels

Rough mapping of combined CPU/memory/disk “stress” (0–100) to color and flash:

| Level | Color | Flash |
|-------|--------|--------|
| Low   | Dark green → medium green → light green | Solid |
| Medium| Light yellow → dark yellow | Solid |
| High  | Light orange → dark orange | Solid |
| Critical | Light red → medium red → dark red | Slow → medium → fast |

## License

MIT.
