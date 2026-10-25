---
title: NEO Servidor
emoji: 🤖
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
app_port: 7860
---

# NEO — Servidor WebSocket

Servidor de voz para [NEO](https://github.com/techmiguel/neo-robot), el asistente de voz
con ESP32-S3. Pipeline: STT (Groq Whisper) → intención por palabras clave → comando o LLM
(Groq `openai/gpt-oss-20b`) → TTS (edge-tts), con la respuesta en streaming.

Este Space es el respaldo en la nube; la placa usa primero el servidor de la red local.
Para ejecutarlo en tu PC (perfiles `local` con Ollama y faster-whisper, o `nube`), sigue el
[README del repositorio](https://github.com/techmiguel/neo-robot#quick-start).

## Secrets requeridos

Configurar en **Settings → Variables and secrets** del Space:

| Variable | Descripción |
|----------|-------------|
| `GROQ_API_KEY` | API key de Groq (groq.com) |
| `OPENWEATHER_API_KEY` | API key de OpenWeatherMap |
| `NEWSAPI_KEY` | API key de NewsAPI |
| `ELTOQUE_API_KEY` | JWT de El Toque (tasas CUP) |
| `WS_MODO` | `pipeline` para producción |

## Protocolo WebSocket

Conectar a `wss://YOUR_USERNAME-neo-servidor.hf.space`

- ESP32 → servidor: chunks PCM binarios + `{"cmd":"fin_grabacion"}`
- Servidor → ESP32: `{"cmd":"procesando"}` + chunks PCM + `{"cmd":"fin_respuesta"}`

La respuesta se envía en streaming: el LLM genera token a token, el texto se
corta en frases/cláusulas (`src/tts/segmentador.py`) y cada fragmento se
sintetiza y envía en cuanto está listo, mientras el LLM sigue generando. El
firmware empieza a reproducir con ~256 ms de audio en buffer, sin esperar a
`fin_respuesta`. La métrica `durations.primer_audio` del JSONL de timing mide
el tiempo desde que llega el audio del usuario hasta que sale el primer audio
de respuesta. Detalles en `docs/streaming-latencia.md`.
