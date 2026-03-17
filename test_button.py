#!/usr/bin/env python3
"""
Quick test: does the Pi see the button on the configured GPIO?
Run: sudo .venv/bin/python test_button.py
Press the button; you should see "Button pressed" and "Button released" in the terminal.
If nothing appears, check: GPIO number (.env PI_STATS_BUTTON_GPIO), wiring (one leg to GPIO, other to GND).
"""

import os
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

GPIO = int(os.environ.get("PI_STATS_BUTTON_GPIO", "17"))

def main():
    try:
        import RPi.GPIO as GPIO_LIB
    except ImportError:
        print("RPi.GPIO not installed. Install python3-rpi.gpio.", file=sys.stderr)
        sys.exit(1)

    GPIO_LIB.setwarnings(False)
    GPIO_LIB.setmode(GPIO_LIB.BCM)
    GPIO_LIB.setup(GPIO, GPIO_LIB.IN, pull_up_down=GPIO_LIB.PUD_UP)

    print(f"Listening on BCM GPIO {GPIO}.")
    print("Button: one leg to this GPIO, other leg to GND. Press Ctrl+C to exit.")
    print("State: 1 = released/open, 0 = pressed/grounded")
    last = GPIO_LIB.input(GPIO)
    print(f"Initial state: {last}")
    try:
        while True:
            cur = GPIO_LIB.input(GPIO)
            if cur != last:
                if cur == 0:
                    print("Button pressed")
                else:
                    print("Button released")
                print(f"Raw state now: {cur}")
                last = cur
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO_LIB.cleanup(GPIO)

if __name__ == "__main__":
    main()
