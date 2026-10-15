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

## Modo local (STT + LLM sin nube)

Ollama no transcribe audio (solo ejecuta modelos de texto), así que el
procesamiento local se reparte en dos motores:

1. STT: faster-whisper en CPU (`STT_PROVIDER=local`).
2. LLM: Ollama con `qwen2.5-coder:3b` (`LLM_PROVIDER=ollama`).

El TTS sigue siendo edge-tts (requiere internet); no es local todavía.

```bash
pip install -e ".[local]"
ollama pull qwen2.5-coder:3b
ollama serve &
cp .env.example .env   # y fijar STT_PROVIDER=local, LLM_PROVIDER=ollama
python -m src.server.ws_server
```

Al arrancar en modo `pipeline` se precargan Whisper y el modelo de Ollama.
`qwen2.5-coder:3b` está afinado para código; en conversación en español rinde
peor que `qwen2.5:3b-instruct` (basta cambiar `OLLAMA_MODEL`).
