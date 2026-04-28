FROM python:3.11-slim

WORKDIR /app

# Instala dependencias declaradas en pyproject.toml
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "groq>=0.9.0" \
    "edge-tts>=6.1.9" \
    "miniaudio>=1.58" \
    "requests>=2.31.0" \
    "websockets>=12.0" \
    "python-dotenv>=1.0.0"

# Copia el código fuente (las API keys vienen de HF Secrets, no del .env)
COPY src/ ./src/

# HF Spaces requiere puerto 7860
ENV WS_PORT=7860
EXPOSE 7860

CMD ["python", "-m", "src.server.ws_server"]
