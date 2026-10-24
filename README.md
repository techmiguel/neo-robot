# NEO — Embedded Voice Assistant

NEO is an embedded voice assistant. An **ESP32-S3** acts as the audio and interaction
interface (microphone, speaker, OLED screen, button), while a **Python server** handles
the heavy processing: transcription (STT), intent deduction, and voice synthesis (TTS).

The user wakes NEO by saying **"Hola NEO"**, then asks questions hands-free. NEO responds
through the speaker. After a period of silence, it returns to rest until the next wake word.

```
   ┌──────────────┐   audio PCM    ┌───────────────────────────────────────┐
   │  ESP32-S3    │ ─────────────▶ │            Python Server              │
   │  (interface) │ ◀───────────── │  STT → intent → handler/LLM → TTS     │
   └──────────────┘   audio PCM    └───────────────────────────────────────┘
   mic · speaker ·      WS            Groq Whisper · Groq LLM · edge-tts
   OLED · button                      APIs: weather, crypto, news, El Toque
```

## Architecture

**Local-first with edge inference:**

- **On the ESP32 (local):** a very lightweight TensorFlow Lite Micro model (15 KB, int8)
  detects **only the wake word** "Hola NEO". Once confirmed, NEO wakes up, greets with
  a pre-recorded "¡Hola!", and records the user's free-form query.
- **On the server:** transcribes the audio (Whisper), **deduces intent** with keywords
  first and LLM as fallback, executes the corresponding handler (or free response),
  and synthesizes voice (edge-tts).
- **Local-first connection:** the ESP32 tries the LAN server (your PC) first; if it
  doesn't respond, it falls back to the cloud deployment (Hugging Face Spaces).

Deliberate design: the local classifier only recognizes the wake word. Commands live
on the server (Python), so adding or changing commands doesn't require reflashing the
firmware.

### Conversation flow

1. **REST** — OLED screen off (power saving); microphone + inference listening.
2. **"Hola NEO"** — local model detects it; NEO turns on the screen (animated eyes +
   connection status) and says **"¡Hola!"**.
3. **CONVERSATION** — hands-free: records a question, sends it, plays the response,
   and listens again.
4. **Silence > 10s** — NEO returns to REST and requires the wake word again.

## Hardware

Base board: **Freenove ESP32-S3 WROOM CAM** (FNK0085) + **GPIO Extension Board**.

| Peripheral | Bus | Pins (GPIO) |
|------------|-----|-------------|
| INMP441 Microphone | I2S_NUM_0 | WS=1, SCK=3, SD=14 |
| PCM5100A+PAM8403 DAC+amp | I2S_NUM_1 | BCK=21, LCK=47, DIN=41, SCK→GND |
| SSD1306 OLED | I2C | SDA=46, SCL=42 (addr 0x3C) |
| Trigger button | GPIO 0 | onboard BOOT button |

> The board's camera (GPIO 4–18), SD (38–40), and PSRAM (35–37) are reserved.
> Full wiring details are in `firmware/CLAUDE.md`.

## Repository structure

```
neo/
├── firmware/          # C++ (PlatformIO + Arduino) for ESP32-S3
│   ├── src/
│   │   ├── audio/       # microphone, speaker, MFCC, voice ack
│   │   ├── display/     # OLED + animated eyes (Face)
│   │   ├── network/     # WiFi manager + WebSocket client
│   │   ├── commands/    # dispatcher + TFLite inference (wake word)
│   │   ├── models/      # generated headers: wake_word_model.h, vocabulary.h
│   │   └── demos/       # hw_test, loopback, wake_word, eyes, speaker
│   ├── tools/           # capture, training, and generation scripts
│   └── platformio.ini
├── servidor/          # Python: STT + intent + LLM + TTS + WebSocket
│   └── src/
│       ├── stt/  llm/  tts/  server/  commands/
├── docs/              # guides, hardware specs, design docs
└── ROADMAP.md         # phases and status of each module
```

## Getting started

### Server (Python ≥ 3.10)

```bash
cd servidor
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -e .
cp .env.example .env                                 # add your API keys
python -m src.server.ws_server                       # listens on ws://0.0.0.0:8765
```

Required environment variables (see `servidor/.env.example`): `GROQ_API_KEY`,
`OPENWEATHER_API_KEY`, `NEWSAPI_KEY`, `ELTOQUE_API_KEY`.

### Firmware (PlatformIO)

```bash
cd firmware
pio run -e esp32dev --target upload      # compiles and flashes main firmware
pio device monitor -e esp32dev -b 115200
```

Available environments:

| Env | Purpose |
|-----|---------|
| `esp32dev` | Full firmware (wake word + WebSocket + audio) |
| `hw_test` | Hardware test: OLED, mic, speaker, button |
| `loopback_test` | Records from mic and plays through speaker |
| `wake_word_test` | Wake word inference without server |
| `dataset_capture` | Audio capture for training |
| `demo_ojos` / `demo_bocina` | Animation and playback demos |

### Training the wake word

```bash
cd firmware
pio run -e dataset_capture --target upload
python tools/capture_dataset.py --port COM8          # records samples per class
python tools/train_model.py                          # trains and exports TFLite
python tools/gen_vocabulario.py --umbrales models/umbrales.json
python tools/tflite_to_header.py                     # generates src/models/*.h
```

The vocabulary (classes, phrases, thresholds) is defined in `tools/vocabulario.json`
and is the single source of truth shared between capture firmware, training, and
inference.

## Commands NEO recognizes

After the wake word, NEO deduces intent from the transcribed audio:

| Intent (keywords) | Action | Source |
|-------------------|--------|--------|
| weather / time / temperature | Current weather | OpenWeatherMap |
| dollar / rate / euro / El Toque | Informal CUP rates | El Toque API |
| bitcoin / ethereum / crypto | Crypto price | CoinGecko |
| news / headlines | Latest news | NewsAPI |
| anything else | Free response | LLM (Groq) |

## Design decisions

### Why local-first?

The ESP32 tries the LAN server first (your PC) before falling back to the cloud
(Hugging Face Spaces). This gives:
- **Lower latency** on local network (no internet round-trip)
- **Privacy** for sensitive queries (stays on your network)
- **Resilience** if internet goes down (local server still works)

### Why wake-word-only local model?

A multi-command local classifier would require:
- Recording a dataset for each command phrase
- Retraining and reflashing the firmware for every change

With wake-word-only local inference, commands live on the server (Python) and can
be extended without reflashing. The trade-off is that every query requires network
connectivity after the wake word.

### Why two I2S buses?

The ESP32-S3 has two I2S peripherals. We use:
- **I2S_NUM_0** for the microphone (input)
- **I2S_NUM_1** for the DAC+amplifier (output)

Sharing a single bus between input and output would require complex time-division
multiplexing and risk audio glitches. Two buses keep things simple and reliable.

### Why SRAM for MFCC buffers (not PSRAM)?

The ESP32-S3 has 8 MB of PSRAM (octal), but accessing it during WiFi activity causes
random access delays that trigger the task watchdog (5s timeout). The MFCC extraction
processes 148 frames of audio, and with WiFi active, PSRAM access stalls the IDLE
task. Solution: allocate MFCC buffers and TFLite arena in **internal SRAM** (slower
but deterministic timing).

### Why intent detection by keywords first?

The server tries keyword matching before falling back to the LLM:
- **Faster** for common commands (no LLM latency)
- **Cheaper** (no API tokens for "what's the weather?")
- **More reliable** (regex doesn't hallucinate)

The LLM is only used for free-form queries that don't match any keyword pattern.

## Failure modes

| Scenario | What happens | User experience |
|----------|--------------|-----------------|
| **No server** (LAN + cloud down) | ESP32 shows "WS lost" on OLED, returns to REST | Wake word still works, but queries get no response |
| **No network** (WiFi down) | ESP32 tries to reconnect, shows "No WiFi..." on OLED | Wake word still works locally, but queries fail |
| **Empty LLM response** | Server guard: returns "No tengo una respuesta clara para eso." | User hears fallback message instead of silence |
| **Wake word false positive** | Model threshold (0.7618) filters most false positives; single confirmation (CONF_MINIMAS=1) | Rare false wakes; user can ignore and wait for 10s timeout |
| **STT timeout** | Groq API timeout → exception caught, error sent to ESP32 | OLED shows "Server error", returns to REST |
| **TTS failure** | edge-tts exception → error sent to ESP32 | OLED shows "Server error", returns to REST |

## Security & limitations

### Security

- **API keys** stored in `.env` (server) and `secrets.h` (firmware), both gitignored.
- **WebSocket** has no authentication; assumes trusted LAN. For public deployments,
  add token-based auth or TLS client certificates.
- **No encryption on LAN**; WebSocket uses `ws://` locally, `wss://` for cloud (HF).
- **No user authentication**; anyone on the LAN can send queries.

### Limitations

- **No conversation memory** (yet). Each query is independent. See
  [docs/diseno-memoria.md](docs/diseno-memoria.md) for the design evaluation.
- **Battery power is marginal**. NEO runs from one 18650 cell through an MT3608 boost
  converter into its 5V pin, but the converter cannot hold 5 V above ~350 mA: the line
  sags to ~3.8 V when the speaker starts and the ESP32-S3 can reset (brownout). Peaks
  of ~0.8 A were measured while speaking, so the supply needs ≥ 1 A at 5 V (e.g. 2S
  cells with a buck converter).
- **No OTA updates**. Firmware must be flashed via USB. OTA could be added but isn't
  critical for a prototype.
- **Single language** (Spanish). The STT, LLM prompt, and TTS are all Spanish-only.
  Adding multilingual support would require changes across the pipeline.
- **Local profile is less accurate than the cloud one.** The server can run fully
  local (Faster-Whisper small + Ollama `qwen2.5:3b` + Piper) or in the cloud (Groq +
  edge-tts); locally the transcription error rate is higher and the small LLM makes
  factual mistakes.

## Measured results

All numbers come from the board, not from simulation. Raw data and method are linked.

**Wake word "Hola NEO"** (two speakers, CNN int8 on the ESP32-S3;
[method](firmware/models/experimentos/2026-10-20/RESUMEN.md))

| Metric | Value |
|---|---|
| Test accuracy (int8, 302 clips) | 95.7 % |
| True positive rate / false positive rate (threshold 0.7618) | 95.6 % / 0.6 % |
| Detection latency on the board, end of phrase → confirmed ([data](docs/metrics/latencia_wake_20261023/)) | **3.33 s** median (p90 3.38 s), of which inference 2.6 s |

**Conversation latency**, end of recording → full reply received, same audio sent to both
profiles, 31 phrases read to the board ([data](docs/metrics/validacion_20261023/))

| Profile | Word error rate | Intent accuracy | Free questions, median (p90) | Commands, median (p90) |
|---|---|---|---|---|
| Local (Whisper small + qwen2.5:3b + Piper) | 18.5 % | 96.8 % | 7.0 s (9.5 s) | 3.6 s (5.7 s) |
| Cloud (Groq + edge-tts) | 10.8 % | 100 % | 7.2 s (54 s, VPN spikes) | 5.2 s (7.7 s) |

**Power draw at 5 V per state** (INA219 on NEO's 5V pin, preliminary: one 5.5-min
session with 12 question/answer turns; [method](docs/experimento-consumo.md),
[data](docs/metrics/consumo_20261024_preliminar/))

| State | Mean current | Peak (0.53 ms) | Mean power |
|---|---|---|---|
| Rest (screen off, listening for the wake word) | 119 mA | 249 mA | 0.60 W |
| Wake word capture + inference | 137 mA | 255 mA | 0.69 W |
| Active listening | 131 mA | 634 mA | 0.65 W |
| Sending audio over WiFi | 153 mA | 408 mA | 0.76 W |
| Waiting for the reply | 135 mA | 497 mA | 0.67 W |
| Speaking (speaker on) | 302 mA | 797 mA | 1.44 W |

![Current during one interaction](docs/metrics/consumo_20261024_preliminar/traza_interaccion.png)

## Development notes

- Random PSRAM access during MFCC extraction with active WiFi triggered the *task
  watchdog*; inference buffers are allocated in **internal SRAM**.
- The local model is kept small (channels 8/16/32) so inference takes ~2.6 s and
  doesn't crash the core; that inference is 78 % of the wake word latency.
- Groq's reasoning models need `max_tokens` set high; low values cause empty content
  responses.

---

See `ROADMAP.md` for detailed phase status and `firmware/CLAUDE.md` /
`servidor/CLAUDE.md` for component-specific conventions.
