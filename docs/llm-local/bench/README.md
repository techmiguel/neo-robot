# Banco de pruebas del LLM local de NEO

Evalúa modelos GGUF con el system prompt y los casos de uso reales de NEO. El
análisis y las conclusiones están en `../README.md`.

| Archivo | Contenido |
|---|---|
| `prompts.py` | System prompt de NEO y los 47 casos (chat, multiturno, tareas estructuradas) |
| `run_eval.py` | Levanta `llama-server` con un GGUF, ejecuta los casos y guarda `results/<modelo>[.sN].jsonl` |
| `judge.py` | Juez estricto por reglas (hechos, razonamiento, honestidad, multiturno, formato TTS, JSON); agrega semillas |
| `score.py` | Métricas de formato y un verificador laxo por palabras clave (solo referencia) |
| `side_by_side.py` | Vuelca respuestas de varios modelos pregunta por pregunta, para revisión manual |
| `results/` | Respuestas crudas con tiempos, `bench.jsonl` (salida de `llama-bench`) y `judge.json` |

## Uso

1. Compilar llama.cpp solo con AVX2 para emular un i5 de 8.ª generación:

   ```bash
   git clone --depth 1 https://github.com/ggml-org/llama.cpp
   cmake -S llama.cpp -B llama.cpp/build -DGGML_NATIVE=OFF -DGGML_AVX2=ON -DGGML_FMA=ON \
     -DGGML_F16C=ON -DGGML_AVX512=OFF -DGGML_AVX_VNNI=OFF -DGGML_AMX_TILE=OFF \
     -DGGML_AMX_INT8=OFF -DCMAKE_BUILD_TYPE=Release
   cmake --build llama.cpp/build -j --target llama-server llama-bench
   ```

2. Descargar un GGUF y evaluarlo. El nombre debe empezar por una clave de
   `SAMPLING` en `run_eval.py`, que determina el muestreo:

   ```bash
   export LLAMA_SERVER=llama.cpp/build/bin/llama-server
   python3 run_eval.py gemma4-e4b-qat models/gemma-4-E4B_q4_0-it.gguf
   python3 run_eval.py gemma4-e4b-qat models/gemma-4-E4B_q4_0-it.gguf --seed 7
   python3 run_eval.py lfm2.5-8b-a1b models/LFM2.5-8B-A1B-Q4_K_M.gguf --think
   ```

3. Puntuar:

   ```bash
   python3 judge.py
   python3 side_by_side.py gemma4-e4b-qat qwen2.5-3b
   ```

Para medir directamente en la PC del servidor con Ollama, basta con
`ollama run gemma4:e4b --verbose` y comparar `eval rate` con la columna
`gen_tok_s` de `judge.py`.
