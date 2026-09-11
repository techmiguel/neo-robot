# NEO — Robot Asistente de Voz

NEO es un asistente de voz embebido. Un **ESP32-S3** actúa como interfaz de audio e
interacción (micrófono, altavoz, pantalla OLED, botón), mientras un **servidor Python**
provee el procesamiento pesado: transcripción (STT), comprensión y deducción de
intención, y síntesis de voz (TTS).

El usuario despierta a NEO diciendo **"Hola NEO"**, y a partir de ahí puede hacer
varias preguntas en modo manos libres. NEO responde por el altavoz. Tras un periodo
de silencio, vuelve a reposar hasta el siguiente wake word.

```
   ┌──────────────┐   audio PCM    ┌───────────────────────────────────────┐
   │  ESP32-S3    │ ─────────────▶ │            Servidor Python            │
   │  (interfaz)  │ ◀───────────── │  STT → intención → handler/LLM → TTS  │
   └──────────────┘   audio PCM    └───────────────────────────────────────┘
   mic · speaker ·      WS            Groq Whisper · Groq LLM · edge-tts
   OLED · botón                      APIs: clima, cripto, noticias, El Toque
```

## Arquitectura

**Local-first e inferencia en el borde:**

- **En el ESP32 (local):** un modelo TensorFlow Lite Micro muy ligero (15 KB, int8)
  detecta **solo el wake word** "Hola NEO". Al confirmarse, NEO sale del reposo,
  saluda con un "¡Hola!" pregrabado y graba la consulta libre del usuario.
- **En el servidor:** transcribe el audio (Whisper), **deduce la intención** con
  keywords primero y LLM como respaldo, ejecuta el handler correspondiente (o una
  respuesta libre) y sintetiza la voz (edge-tts).
- **Conexión local-first:** el ESP32 intenta primero el servidor en la LAN (tu PC);
  si no responde, cae al despliegue en la nube (Hugging Face Spaces).

Diseño deliberado: el clasificador local solo reconoce el wake word. Los comandos
viven en el servidor (Python), así que añadir o cambiar comandos no requiere
reflashear el firmware.

### Flujo de conversación

1. **REPOSO** — pantalla OLED apagada (ahorro); micrófono + inferencia escuchando.
2. **"Hola NEO"** — el modelo local lo detecta; NEO enciende la pantalla (ojos
   animados + estado de conexión arriba) y dice **"¡Hola!"**.
3. **CONVERSACIÓN** — manos libres: graba una pregunta, la envía, reproduce la
   respuesta, y vuelve a escuchar.
4. **Silencio > 10 s** — NEO regresa al REPOSO y exige el wake word de nuevo.

## Hardware

Placa base: **Freenove ESP32-S3 WROOM CAM** (FNK0085) + **GPIO Extension Board**.

| Periférico | Bus | Pines (GPIO) |
|------------|-----|--------------|
| Micrófono INMP441 | I2S_NUM_0 | WS=1, SCK=3, SD=14 |
| DAC+amp PCM5100A + PAM8403 | I2S_NUM_1 | BCK=21, LCK=47, DIN=41, SCK→GND |
| OLED SSD1306 | I2C | SDA=46, SCL=42 (addr 0x3C) |
| Botón de disparo | GPIO 0 | botón BOOT onboard |

> La cámara (GPIO 4–18), la SD (38–40) y la PSRAM (35–37) de la placa quedan
> reservadas. El detalle completo del conexionado está en `firmware/CLAUDE.md`.

## Estructura del repositorio

```
neo/
├── firmware/          # C++ (PlatformIO + Arduino) para el ESP32-S3
│   ├── src/
│   │   ├── audio/       # micrófono, speaker, MFCC, ack de voz
│   │   ├── display/     # OLED + animación de ojos (Face)
│   │   ├── network/     # WiFi manager + cliente WebSocket
│   │   ├── commands/    # dispatcher + inferencia TFLite (wake word)
│   │   ├── models/      # headers generados: modelo_wake_word.h, vocabulario.h
│   │   └── demos/       # hw_test, loopback, wake_word, ojos, bocina
│   ├── tools/           # scripts de captura, entrenamiento y generación
│   └── platformio.ini
├── servidor/          # Python: STT + intención + LLM + TTS + WebSocket
│   └── src/
│       ├── stt/  llm/  tts/  server/  commands/
├── docs/              # guías y fichas de hardware
└── ROADMAP.md         # fases y estado de cada módulo
```

## Puesta en marcha

### Servidor (Python ≥ 3.10)

```bash
cd servidor
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -e .
cp .env.example .env                                 # añade tus API keys
python -m src.server.ws_server                       # escucha en ws://0.0.0.0:8765
```

Variables de entorno necesarias (ver `servidor/.env.example`): `GROQ_API_KEY`,
`OPENWEATHER_API_KEY`, `NEWSAPI_KEY`, `ELTOQUE_API_KEY`.

### Firmware (PlatformIO)

```bash
cd firmware
pio run -e esp32dev --target upload      # compila y flashea el firmware principal
pio device monitor -e esp32dev -b 115200
```

Entornos disponibles:

| Env | Propósito |
|-----|-----------|
| `esp32dev` | Firmware completo (wake word + WebSocket + audio) |
| `hw_test` | Test de hardware: OLED, mic, speaker, botón |
| `loopback_test` | Graba del mic y reproduce por el speaker |
| `wake_word_test` | Inferencia de wake word sin servidor |
| `dataset_capture` | Captura de audio para entrenar |
| `demo_ojos` / `demo_bocina` | Demos de animación y reproducción |

### Entrenar el wake word

```bash
cd firmware
pio run -e dataset_capture --target upload
python tools/capture_dataset.py --port COM8          # graba muestras por clase
python tools/train_model.py                          # entrena y exporta TFLite
python tools/gen_vocabulario.py --umbrales models/umbrales.json
python tools/tflite_to_header.py                     # genera src/models/*.h
```

El vocabulario (clases, frases, umbrales) se define en `tools/vocabulario.json` y es
la fuente única de verdad compartida entre el firmware de captura, el entrenamiento
y la inferencia.

## Comandos que reconoce NEO

Después del wake word, NEO deduce la intención del audio transcrito:

| Intención (keywords) | Acción | Fuente |
|----------------------|--------|--------|
| clima / tiempo / temperatura | Clima actual | OpenWeatherMap |
| dólar / tasa / euro / El Toque | Tasas informales CUP | El Toque API |
| bitcoin / ethereum / cripto | Precio de cripto | CoinGecko |
| noticias / titulares | Últimas noticias | NewsAPI |
| cualquier otra cosa | Respuesta libre | LLM (Groq) |

## Notas de desarrollo

- El acceso aleatorio a PSRAM durante la extracción MFCC con WiFi activo disparaba el
  *task watchdog*; los buffers de inferencia se asignan en **SRAM interna**.
- El modelo local se mantiene pequeño (canales 8/16/32) para que la inferencia dure
  ~2.7 s y no estrelle el core.
- Los modelos de razonamiento de Groq necesitan `max_tokens` amplio; con valores bajos
  devuelven contenido vacío.

---

Ver `ROADMAP.md` para el estado detallado por fases y `firmware/CLAUDE.md` /
`servidor/CLAUDE.md` para las convenciones de cada componente.
