# NEO — asistente de voz en español con ESP32-S3, palabra de activación offline y LLM local

[![Tests](https://github.com/techmiguel/neo-robot/actions/workflows/ci.yml/badge.svg)](https://github.com/techmiguel/neo-robot/actions/workflows/ci.yml)
[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-blue.svg)](LICENSE)

**NEO** es un altavoz inteligente de código abierto que puedes montar tú mismo con un
**ESP32-S3**. Le dices **«Hola NEO»** y un modelo **TinyML** de 15 KB (TensorFlow Lite
Micro, int8) reconoce la **palabra de activación en el propio chip, sin internet**. Luego le
preguntas lo que quieras, con las manos libres: un servidor Python en tu PC transcribe con
**Whisper**, responde con un **LLM local (Ollama: Gemma, Qwen)** o en la nube (Groq) y NEO
contesta por el altavoz con **síntesis de voz en streaming**.

Es una alternativa a Alexa o Google Home que respeta tu privacidad y que puedes modificar.
Todas las cifras están **medidas en la placa real**, con los datos en el repositorio.

## Qué tiene

- **Palabra de activación offline en un microcontrolador:** CNN sobre MFCC, int8, con los
  kernels SIMD de ESP-NN. 0,32–0,40 s por inferencia y ~1,1 s desde que terminas de decir
  «Hola NEO» hasta que responde. Exactitud en test: 95,7 %. Incluye todo el entrenamiento.
- **Local primero:** la placa habla con tu PC en la red local y, si no está, con una copia
  en la nube. El servidor puede ir **todo en local** (faster-whisper + Ollama) o con los
  planes gratuitos de Groq y edge-tts.
- **Respuesta en streaming:** el texto del LLM se corta en frases, cada una se sintetiza y
  se envía en cuanto está lista, y la placa empieza a hablar con 256 ms de audio en buffer.
- **Comandos sin LLM:** clima, criptomonedas, noticias de tecnología y **tasas del mercado
  informal en Cuba (El Toque)**, por palabras clave y API reales.
- **Aguanta redes malas:** frases pregrabadas avisan si falla la wifi, el servidor o
  internet. La wifi se apaga tras 10 min de reposo y la CPU baja a 80 MHz, mientras la
  palabra de activación sigue escuchando.

## Empezar

Hardware: ESP32-S3 Freenove WROOM CAM (N8R8), micrófono INMP441, módulo DAC
PCM5100A + amplificador PAM8403, altavoz de 8 Ω y pantalla OLED SSD1306. Cableado en
[docs/hardware.md](docs/hardware.md).

**Servidor** (Python 3.10 o superior):

```bash
git clone https://github.com/techmiguel/neo-robot.git
cd neo-robot/servidor
python -m venv .venv
.venv\Scripts\activate             # en macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"            # y ".[local]" para el perfil local
copy .env.example .env             # en macOS/Linux: cp; añade GROQ_API_KEY
python -m src.server.ws_server --perfil nube     # o --perfil local (Ollama + faster-whisper)
```

**Firmware** ([PlatformIO](https://platformio.org/install)):

```bash
cd neo-robot/firmware
copy src\config_local.example.h src\config_local.h   # pon la IP de tu PC en NEO_SERVIDOR_HOST
pio run -e esp32dev --target upload
pio device monitor -e esp32dev
```

**Primer arranque:** NEO abre la red wifi **`NEO-Config`**; conéctate desde el móvil, abre
<http://192.168.4.1> y dale tu red. Después di «Hola NEO» y pregunta: *«¿Cuál es la capital
de Japón?»*, *«¿Va a llover mañana en La Habana?»*, *«¿A cuánto está el dólar?»*.

El modelo se entrenó con dos voces. Si no reconoce la tuya, pulsa el botón BOOT para
preguntar sin palabra de activación, o
[entrénalo con tu voz](README.md#train-the-wake-word-on-your-voice).

## Resultados medidos

| Sesión (31 frases leídas a la placa) | WER sin tildes | Intención | Preguntas libres (mediana) |
|---|---|---|---|
| 24/10, nube: Groq Whisper + gpt-oss-20b + edge-tts | 3,1 % | 96,8 % | 5,7 s |
| 24/10, local: Whisper small + qwen2.5:3b + edge-tts | 6,2 % | 96,8 % | 8,8 s |
| 25/10, local: Whisper small + gemma4:e2b en streaming | **5,1 %** | **100 %** | 18,0 s con el prompt largo* |

\* gemma4:e2b reprocesa el system prompt en cada pregunta: el de 409 tokens costaba ~8 s.
El perfil local usa ahora uno de 139 tokens (2,7–3,3 s en Ollama; falta medirlo de punta a
punta). Análisis completo en
[docs/metrics/validacion_gemma4_streaming/ANALISIS.md](docs/metrics/validacion_gemma4_streaming/ANALISIS.md).

## Documentación

La documentación de diseño, los experimentos y las métricas están en español, en
[`docs/`](docs/), y el estado del proyecto en el [ROADMAP](ROADMAP.md). La guía completa
en inglés, con la arquitectura, los modos de fallo y el banco de pruebas, está en el
[README](README.md).

Licencia [MIT](LICENSE). ¿Quieres contribuir? Lee [CONTRIBUTING.md](CONTRIBUTING.md).
