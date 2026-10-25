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

Servidor de voz para el robot NEO (ESP32-S3).  
Pipeline: STT (Groq Whisper) → LLM (Groq LLaMA) → TTS (edge-tts).

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
