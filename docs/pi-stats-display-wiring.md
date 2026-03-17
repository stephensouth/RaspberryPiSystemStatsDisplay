# Pi Stats Display Wiring

Wiring for a 128x32 I2C OLED, one momentary button, and one WS2812B status LED.

## OLED (SSD1306 I2C)

| Pi GPIO (BCM) | Physical pin | OLED pin |
|---|---:|---|
| 3.3V | 1 | VIN |
| GND | 6 | GND |
| GPIO2 (SDA) | 3 | SDA |
| GPIO3 (SCL) | 5 | SCL |

## Button

Default active-low wiring:

| Pi GPIO (BCM) | Physical pin | Button |
|---|---:|---|
| GPIO22 (or configured pin) | 15 | one leg |
| GND | 14/9/etc | other leg |

If using active-high, wire GPIO pin to 3.3V instead, and set `PI_STATS_BUTTON_ACTIVE_LOW=0`.

## WS2812B LED

| Pi GPIO (BCM) | Physical pin | LED |
|---|---:|---|
| GPIO18 | 12 | DIN |
| 5V | 2 or 4 | VDD |
| GND | 6/9/etc | GND |

Use a 3.3V->5V level shifter on DIN for best reliability.

