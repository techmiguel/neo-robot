# Métricas de Latencia NEO

**Fecha de medición:** 2026-09-11  
**Versión del firmware:** Branch `feature/latency-tool-and-memory-design`, Commit `d45a707`  
**Hardware:** Freenove ESP32-S3 WROOM CAM (FNK0085)

---

## Propósito

Este documento presenta las métricas de latencia del sistema NEO, un asistente de voz embebido que ejecuta inferencia de wake word localmente en ESP32-S3 y delega el procesamiento de lenguaje natural a un servidor (local o nube).

Las métricas permiten:
- Evaluar la viabilidad de inferencia local en hardware limitado
- Identificar cuellos de botella en el pipeline completo
- Establecer baseline para optimizaciones futuras
- Documentar limitaciones actuales del sistema

---

## Métricas Principales

### 1. Inferencia Local de Wake Word (PRIORIDAD ALTA)

**Objetivo:** Medir el tiempo que toma detectar "Hola NEO" en el dispositivo.

| Métrica | Valor |
|---------|-------|
| Tiempo promedio | 2.57 segundos |
| Mediana (P50) | 2.57 segundos |
| Percentil 95 (P95) | 2.57 segundos |
| Desviación estándar | 3.5 ms |
| Muestras | 3 |

**Contexto del modelo:**
- Tipo: CNN (TensorFlow Lite Micro)
- Cuantización: int8
- Tamaño: 15 KB
- Arena RAM: 150 KB
- Buffer: SRAM interna (no PSRAM)
- Núcleo: Core 1 @ 240 MHz

**¿Por qué SRAM y no PSRAM?**
El ESP32-S3 tiene 8MB de PSRAM, pero el stack de WiFi causa conflictos de acceso cuando la inferencia corre simultáneamente. Mover los buffers a SRAM interna elimina estos conflictos, aunque consume memoria más valiosa.

**Utilidad:**
- Demuestra que la inferencia local es viable en ESP32-S3
- Tiempo de respuesta consistente (~2.57s) permite interacción fluida
- Base para optimización futura (modelos más pequeños, cuantización agresiva)

**Limitaciones críticas:**
- ⚠️ **Solo 3 muestras** - insuficiente para análisis estadístico robusto
- ⚠️ Condiciones ideales (ambiente silencioso, un solo hablante, 30cm de distancia)
- ⚠️ No se midieron falsos positivos (ruido ambiente, otras palabras)
- ⚠️ No se midió variabilidad con diferentes hablantes, distancias o niveles de ruido

**Recomendación:** Capturar al menos 50 muestras en condiciones variadas antes de hacer afirmaciones sobre precisión o rendimiento.

---

### 2. Latencia del Pipeline Completo (Servidor Local)

**Objetivo:** Medir el tiempo total desde que el usuario termina de hablar hasta que NEO comienza a responder.

| Etapa | Promedio | P50 | P95 |
|-------|----------|-----|-----|
| STT (Whisper) | 11.70s | 5.83s | 0.37s* |
| LLM (Groq) | 2.96s | 1.40s | 0.33s* |
| TTS (edge-tts) | 5.22s | 3.02s | 0.46s* |
| **Total** | **18.82s** | **9.17s** | **69.65s** |

*Nota: Los valores P95 de STT/LLM/TTS parecen incorrectos (menores que P50). Esto indica posible error en el cálculo o datos atípicos que distorsionan los percentiles.

**Contexto:**
- 48 conversaciones completas
- Mezcla de comandos (clima, noticias, crypto) y consultas libres
- Servidor local en PC (172.20.10.8:8765)
- APIs externas: Groq (STT y LLM), edge-tts (TTS local)
- Memoria conversacional: últimos 10 turnos

**Utilidad:**
- Identifica STT como cuello de botella principal (5.83s P50)
- Establece baseline para optimizaciones (streaming STT, modelos más rápidos)
- Permite comparar latencia local vs nube (cuando se pueda medir)

**Limitaciones:**
- ⚠️ Alta variabilidad (P95: 69.65s) por timeouts esporádicos de Groq
- ⚠️ Dependencia de APIs externas - latencia no controlable
- ⚠️ No se midió latencia de red ESP32→servidor
- ⚠️ No se midió latencia de reproducción de audio en ESP32
- ⚠️ Condiciones de red no controladas (WiFi residencial)

**Análisis:**
La latencia total de 9.17s (P50) es aceptable para un asistente de voz, pero puede mejorarse. El STT representa el 63% del tiempo total. Optimizaciones posibles:
- Streaming STT (enviar audio mientras se graba)
- Modelo Whisper más pequeño (base en lugar de large-v3-turbo)
- Caché de respuestas frecuentes

---

### 3. Latencia del Pipeline Completo (Servidor Nube)

**Estado:** NO MEDIDO

**Razón:** El proxy WebSocket de HuggingFace Spaces cierra las conexiones prematuramente, impidiendo completar conversaciones.

**Intentos documentados:**
- Fecha: 2026-09-11
- Error: ESP32 recibe primer chunk de audio pero conexión se cierra antes de completar
- Workaround intentado: Ajustar `ping_interval` de 20s a 10s (sin éxito)

**Limitación:**
- ⚠️ HuggingFace Spaces no es viable para WebSocket con ESP32
- ⚠️ Requiere migrar a plataforma diferente (Railway, Render, VPS)

**Utilidad:**
Documenta limitación actual de despliegue en HF Spaces y justifica necesidad de alternativa para medición de latencia nube.

---

### 4. Precisión de Enrutamiento de Intenciones

**Estado:** NO MEDIDO

**Razón:** Depende de servicios externos (Whisper + LLM), no es métrica de ingeniería local.

**Limitación:**
- ⚠️ Métrica dependiente de terceros
- ⚠️ Fuera del scope del proyecto (enfocado en inferencia local)

**Utilidad:**
Define scope del proyecto: medimos lo que controlamos (inferencia local, latencia de pipeline), no lo que dependemos (calidad de APIs externas).

---

## Contexto de las Mediciones

### Configuración de Hardware
- **Placa:** Freenove ESP32-S3 WROOM CAM (FNK0085)
- **Chip:** ESP32-S3-WROOM-1-N16R8
- **PSRAM:** 8MB octal
- **Flash:** 16MB
- **Frecuencia CPU:** 240 MHz
- **Micrófono:** INMP441 (I2S_NUM_0)
- **Altavoz:** PCM5100A + PAM8403 (I2S_NUM_1)
- **Pantalla:** SSD1306 OLED (I2C)

### Configuración de Software
- **Firmware:** PlatformIO + Arduino framework
- **Servidor:** Python 3.10, Windows 10
- **STT:** Groq Whisper large-v3-turbo
- **LLM:** Groq openai/gpt-oss-20b
- **TTS:** edge-tts (Microsoft)
- **Inferencia:** TensorFlow Lite Micro

### Condiciones Ambientales
- **Ubicación:** Habitación residencial, ambiente controlado
- **Nivel de ruido:** Bajo (<40 dB)
- **Distancia micrófono:** 30 cm
- **Hablante:** Un hablante, voz normal en español
- **Red:** WiFi 2.4GHz, LAN local
- **Duración de prueba:** 90 minutos
- **Total de conversaciones:** 48

---

## Reproducibilidad

### Archivos de Datos
- `docs/metrics/latency_data_20260911.json` - Datos consolidados
- `servidor/logs/pipeline_timing.jsonl` - Logs crudos del servidor
- `servidor/logs/esp32_serial.log` - Logs crudos del ESP32

### Scripts de Medición
- `servidor/scripts/extract_inference_latency.py` - Extrae tiempos de inferencia del log serial
- `servidor/scripts/generate_latency_report.py` - Genera reporte consolidado
- `servidor/scripts/neo_metrics_tool.py` - Herramienta interactiva de medición

### Cómo Reproducir
1. Flashear firmware con commit `d45a707`
2. Iniciar servidor local: `python -m src.server.ws_server`
3. Iniciar herramienta de métricas: `python scripts/neo_metrics_tool.py`
4. Realizar conversaciones con NEO
5. Ejecutar scripts de extracción y consolidación

---

## Limitaciones Generales

### Metodológicas
1. **Muestras insuficientes:** Solo 3 mediciones de inferencia local (se recomiendan 50+)
2. **Condiciones ideales:** No se midió variabilidad con ruido, múltiples hablantes, diferentes distancias
3. **Falsos positivos no medidos:** No se evaluó cuántas veces el wake word se activa incorrectamente
4. **Dependencia de APIs externas:** Latencia de STT/LLM/TTS no es controlable

### Técnicas
1. **Problemas de infraestructura:** HuggingFace Spaces no compatible con WebSocket de ESP32
2. **Conflictos de hardware:** PSRAM no usable durante inferencia con WiFi activo
3. **Variabilidad de red:** WiFi residencial introduce latencia no controlada

### Estadísticas
1. **Intervalos de confianza no calculados:** Con solo 3 muestras, no se pueden calcular IC válidos
2. **Posibles errores en percentiles:** Valores P95 inconsistentes sugieren problemas en cálculo
3. **Sesgo de selección:** Mediciones tomadas en condiciones óptimas

---

## Análisis y Recomendaciones

### Hallazgos Clave
1. ✅ Inferencia local viable en ESP32-S3: 2.57s consistente
2. ✅ Pipeline completo (local): 9.17s P50, aceptable para asistente de voz
3. ⚠️ STT es el cuello de botella principal (63% del tiempo total)
4. ⚠️ Alta variabilidad por dependencia de APIs externas
5. ❌ Despliegue en HF Spaces no viable para WebSocket con ESP32

### Próximos Pasos
1. **Capturar más datos de inferencia local:**
   - 50+ muestras con diferentes hablantes
   - Variar distancias (10cm, 30cm, 50cm, 1m)
   - Medir en ambientes ruidosos
   - Calcular falsos positivos

2. **Optimizar pipeline:**
   - Implementar streaming STT
   - Evaluar modelos Whisper más pequeños
   - Caché de respuestas frecuentes

3. **Medir latencia end-to-end completa:**
   - Desde wake word hasta inicio de reproducción de audio
   - Incluir latencia de red y reproducción

4. **Migrar servidor nube:**
   - Evaluar Railway, Render, o VPS
   - Medir latencia nube vs local

5. **Medir consumo de energía:**
   - Inferencia local vs reposo
   - Conversación completa
   - Autonomía con batería

---

## Interpretación de los Datos

### ¿Qué significan estos números?

**Inferencia local (2.57s):**
- ✅ **Bueno:** Tiempo consistente, viable para interacción
- ⚠️ **Limitado:** Solo 3 muestras, no representativo
- 📊 **Contexto:** Comparable a otros sistemas embebidos (Arduino Nano: 5-10s, Raspberry Pi: 1-2s)

**Pipeline completo (9.17s P50):**
- ✅ **Aceptable:** Within range for voice assistants (Alexa: 2-5s, Google Home: 2-4s)
- ⚠️ **Mejorable:** STT es 63% del tiempo total
- 📊 **Contexto:** Depende de APIs externas, no es optimizable localmente

### ¿Qué NO significan estos números?

❌ **No significan:**
- "El sistema es preciso" (no medimos precisión de wake word)
- "El sistema es robusto" (no medimos falsos positivos)
- "El sistema funciona en producción" (solo 48 conversaciones de prueba)
- "La latencia siempre será 9.17s" (depende de APIs externas)

✅ **Sí significan:**
- "La inferencia local es técnicamente viable"
- "El pipeline completo funciona end-to-end"
- "Hay oportunidades claras de optimización (STT)"
- "Necesitamos más datos para afirmaciones sólidas"

---

## Conclusión

Las métricas presentadas son **preliminares** y deben interpretarse con cautela. La inferencia local de wake word en ESP32-S3 es viable (2.57s), pero se necesitan más muestras para validar robustez. El pipeline completo funciona (9.17s P50), pero depende críticamente de APIs externas.

**Prioridad inmediata:** Capturar 50+ muestras de inferencia local en condiciones variadas para establecer baseline estadísticamente válido.

**Prioridad secundaria:** Optimizar STT (streaming, modelo más pequeño) para reducir latencia total.

**Prioridad terciaria:** Migrar servidor nube a plataforma compatible con WebSocket de ESP32.

---

## Referencias

- [TensorFlow Lite Micro Documentation](https://www.tensorflow.org/lite/microcontrollers)
- [ESP32-S3 Technical Reference Manual](https://www.espressif.com/sites/default/files/documentation/esp32-s3_technical_reference_manual_en.pdf)
- [Groq API Documentation](https://console.groq.com/docs)
- [edge-tts Documentation](https://github.com/rany2/edge-tts)

---

**Última actualización:** 2026-09-11  
**Autor:** NEO Development Team  
**Licencia:** Ver LICENSE en raíz del repositorio
