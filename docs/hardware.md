# Hardware: parts and wiring

Everything NEO needs fits on a breadboard. The firmware targets the **ESP32-S3** and
uses two I2S buses (microphone in, DAC out) plus I2C for the screen.

## Parts

| Part | Role | Notes |
|---|---|---|
| **Freenove ESP32-S3 WROOM CAM** (FNK0085), ESP32-S3-WROOM-1-**N8R8** | Main board | 8 MB flash, 8 MB octal PSRAM. Any ESP32-S3 with ≥ 8 MB flash and PSRAM should work if you adapt the pins. In PlatformIO: `board = esp32-s3-devkitc-1`. |
| GPIO extension board for the Freenove | Breadboard access | Optional. |
| **INMP441** I2S MEMS microphone | Audio in | 3.3 V. |
| **PCM5100A + PAM8403** module (I2S DAC + class-D amp) | Audio out | 5 V. Sold as one module. |
| Speaker 8 Ω, 2 W | Audio out | Wired differentially, see below. |
| **SSD1306** OLED, 128 × 64, I2C | Animated eyes and status | 3.3 V, address `0x3C`. |
| USB cable | Power, flashing, serial log | The board's BOOT button doubles as the push-to-talk button. |

To solder everything on a 7 × 9 cm perfboard instead, see
[montaje-placa-perforada.md](montaje-placa-perforada.md) (Spanish: layout, wiring and checks).

A custom 31 × 43 mm PCB that replaces the breadboard (**NEO Lite**: ESP32-S3, USB-C,
MAX98357A amplifier, JLCPCB SMT assembly) is designed and ready to order in
[`hardware/neo-lite/`](../hardware/neo-lite/). It has not been fabricated or tested yet.

![NEO Lite PCB, top render](../hardware/neo-lite/docs/img/fase6_render_top.png)

## Wiring

### INMP441 microphone → I2S_NUM_0

| INMP441 | ESP32-S3 |
|---|---|
| WS | GPIO 1 |
| SCK | GPIO 3 |
| SD | GPIO 14 |
| L/R | GND (left channel) |
| VDD | 3.3 V |
| GND | GND |

### PCM5100A + PAM8403 DAC/amplifier → I2S_NUM_1

| Module | ESP32-S3 |
|---|---|
| BCK | GPIO 21 |
| LCK | GPIO 47 |
| DIN | GPIO 41 |
| **SCK** | **GND**: this enables the PCM5100A's internal PLL. Without it the DAC receives I2S but outputs nothing. |
| VCC | 5 V |
| GND | GND |

Connect the speaker between **L+ and L−** (or R+ and R−). The PAM8403 output is bridged
(BTL): **neither speaker wire may touch GND**.

### SSD1306 OLED → I2C

| OLED | ESP32-S3 |
|---|---|
| SDA | GPIO 46 |
| SCL | GPIO 42 |
| VCC | 3.3 V |
| GND | GND |

### Button

The onboard **BOOT** button (GPIO 0): a short press records a question without the
wake word; a 1.5 s press asks for the informal USD rate (El Toque).

## Things that will bite you

- **Two I2S buses, never one.** The microphone uses I2S_NUM_0 and the DAC I2S_NUM_1.
  Sharing a bus between input and output needs time multiplexing and glitches.
- **Pins reserved by the Freenove board:** GPIO 0 (BOOT), 2 (LED), 4–18 (camera),
  19–20 (USB), 35–37 (octal PSRAM), 38–40 (SD card), 43–44 (UART0), 48 (RGB LED).
  The ESP32-S3 has no GPIO 22–34, so pinouts copied from the classic ESP32 do not apply.
- **Flash is 8 MB** on the N8R8 module. The firmware uses `default_8MB.csv`
  (3.25 MB app); the prerecorded phrases take ~1.1 MB of it.
- **Power:** speaking peaks at ~0.8 A at 5 V (see [power measurements](metrics/consumo_20261024_preliminar/)).
  A single 18650 cell through an MT3608 boost converter sags to ~3.8 V and the
  ESP32-S3 resets. Use a supply that holds ≥ 1 A at 5 V.
- **Inference buffers live in internal SRAM, not PSRAM.** With WiFi active, random PSRAM
  access during MFCC extraction stalled the idle task and tripped the watchdog.
