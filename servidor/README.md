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
