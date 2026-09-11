# Diseño de memoria conversacional para NEO

## Estado actual

NEO no tiene memoria conversacional. Cada consulta es independiente: el LLM recibe
solo el system prompt + la pregunta actual, sin contexto de turnos anteriores.

Esto funciona para consultas aisladas ("¿cómo está el clima?"), pero falla en
conversaciones multi-turno ("¿y mañana?", "¿en euros?", "dame más detalles").

## Objetivo

Agregar memoria conversacional **sin costo adicional** (Groq free tier) que permita
a NEO mantener contexto dentro de una sesión de conversación (entre wake word y
silencio de 10s), **sin aumentar la latencia perceptiblemente**.

## Análisis detallado de opciones

### Opción A: Historial en RAM por sesión (ventana deslizante)

**Descripción:** mantener una lista de turnos (usuario + asistente) en memoria del
servidor, keyeada por `session_id` del WebSocket. Ventana deslizante de últimos N
turnos o tope de tokens.

#### Ventajas
- **Costo cero en infraestructura**: Groq free tier permite 30K tokens/min. Con 5
  turnos × ~50 tokens = 250 tokens extra por consulta, estamos muy por debajo del límite.
- **Coherencia con el firmware**: la ventana de conversación de 10s del ESP32 define
  el alcance natural de una "sesión". La memoria del servidor debería alinearse con esto.
- **Implementación trivial**: dict en Python, sin persistencia, sin esquema de BD.
  ~30 líneas de código.
- **Privacidad**: nada se guarda en disco, todo en RAM.
- **Latencia mínima**: los tokens extra agregan ~50-100ms al LLM (medible pero no
  perceptible para el usuario).

#### Desventajas
- **Se pierde al reiniciar el servidor**: no hay persistencia.
- **No funciona entre sesiones**: cada wake word es una sesión nueva.
- **Memory leak potencial**: si no se limpian las sesiones al cerrar WebSocket, el
  dict crece indefinidamente.

#### Limitaciones técnicas
- **Tope de tokens**: Groq tiene límite de contexto (ej. 8K tokens para gpt-oss-20b).
  Con 5 turnos × 50 tokens = 250 tokens de historial, estamos bien. Pero si el usuario
  hace preguntas largas, puede acercarse al límite.
- **Latencia no lineal**: el LLM es más lento con más tokens de entrada. 250 tokens
  extra ≈ +50-100ms. 1000 tokens extra ≈ +200-400ms.

#### Caso de uso real
```
Usuario: "Hola NEO"
NEO: "¡Hola!"
Usuario: "¿cómo está el clima en La Habana?"
NEO: "28 grados, soleado."
Usuario: "¿y mañana?"  ← necesita contexto de "clima en La Habana"
NEO: "Pronostican 27 grados con lluvias."
Usuario: "¿y en Santiago?"  ← necesita contexto de "clima"
NEO: "29 grados, parcialmente nublado."
```

Sin memoria, el usuario tendría que decir "¿cómo estará el clima mañana en La Habana?"
cada vez.

#### Implementación estimada
```python
# En ws_server.py
sesiones = {}  # session_id → lista de turnos

async def _modo_pipeline(ws, buffer, session_id):
    if session_id not in sesiones:
        sesiones[session_id] = []
    
    historia = sesiones[session_id]
    
    # Transcribir
    transcripcion = await transcribe(buffer)
    
    # Construir mensajes con historial (últimos 5 turnos = 10 mensajes)
    mensajes = [{"role": "system", "content": SYSTEM_PROMPT}]
    mensajes.extend(historia[-10:])
    mensajes.append({"role": "user", "content": transcripcion})
    
    # Llamar LLM con historial
    respuesta = await ask_con_mensajes(mensajes)
    
    # Actualizar historial
    historia.append({"role": "user", "content": transcripcion})
    historia.append({"role": "assistant", "content": respuesta})
    
    # Limpiar turnos viejos si excede tope
    if len(historia) > 10:
        historia[:] = historia[-10:]
```

**Limpieza:** en el handler de WebSocket, al cerrar la conexión:
```python
async def handler(ws):
    session_id = ws.request.path  # o generar UUID
    try:
        # ... lógica normal ...
    finally:
        sesiones.pop(session_id, None)  # limpiar al cerrar
```

**Complejidad:** ~30 líneas de código, 1-2 horas de implementación + testing.

---

### Opción B: SQLite local persistente

**Descripción:** guardar historial en SQLite, keyeado por `session_id` + timestamp.
Permite persistencia entre reinicios del servidor.

#### Ventajas
- **Persistencia**: sobrevive reinicios del servidor.
- **Análisis posterior**: permite exportar conversaciones para debugging o análisis.
- **Multi-sesión**: puede mantener historial de múltiples sesiones activas.

#### Desventajas
- **Complejidad alta**: requiere esquema de BD, migraciones, limpieza de datos viejos.
  ~100 líneas de código + tests.
- **Overhead de I/O**: cada consulta requiere leer/escribir en disco. ~10-50ms extra
  por consulta (medible, pero no crítico).
- **Privacidad**: datos en disco (aunque sea local). Requiere política de retención.
- **Latencia adicional**: el overhead de SQLite se suma al overhead de tokens extra.

#### Limitaciones técnicas
- **Bloqueo de BD**: si múltiples consultas llegan simultáneamente, SQLite puede
  bloquearse (aunque en nuestro caso solo hay una consulta a la vez).
- **Tamaño de BD**: sin limpieza automática, la BD crece indefinidamente.

#### Caso de uso real
Mismos casos que Opción A, pero con persistencia:
```
Usuario: "Hola NEO"
NEO: "¡Hola!"
Usuario: "¿cómo está el clima?"
NEO: "28 grados."
[usuario reinicia el servidor]
Usuario: "Hola NEO"
NEO: "¡Hola!"
Usuario: "¿y mañana?"  ← aún recuerda el contexto anterior
NEO: "Pronostican 27 grados."
```

**¿Vale la pena la persistencia?** Probablemente no. La ventana de conversación del
firmware es de 10s. Si el usuario reinicia el servidor, probablemente empezó una nueva
conversación. La persistencia es un "nice-to-have" pero no crítico.

#### Implementación estimada
```python
import sqlite3
import time

def init_db():
    conn = sqlite3.connect("neo_memory.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS turnos (
            session_id TEXT,
            timestamp REAL,
            role TEXT,
            content TEXT
        )
    """)
    conn.commit()

def guardar_turno(session_id, role, content):
    conn = sqlite3.connect("neo_memory.db")
    conn.execute(
        "INSERT INTO turnos VALUES (?, ?, ?, ?)",
        (session_id, time.time(), role, content)
    )
    conn.commit()

def obtener_historial(session_id, limite=10):
    conn = sqlite3.connect("neo_memory.db")
    cursor = conn.execute(
        "SELECT role, content FROM turnos WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
        (session_id, limite)
    )
    return list(reversed(cursor.fetchall()))

def limpiar_sesiones_viejas(max_age_segundos=3600):
    conn = sqlite3.connect("neo_memory.db")
    conn.execute(
        "DELETE FROM turnos WHERE timestamp < ?",
        (time.time() - max_age_segundos,)
    )
    conn.commit()
```

**Complejidad:** ~100 líneas de código + tests + migraciones, 4-6 horas de implementación.

---

### Opción C: No implementar (status quo)

**Descripción:** mantener NEO sin memoria conversacional. Cada consulta es independiente.

#### Ventajas
- **Simplicidad**: sin complejidad adicional.
- **Latencia mínima**: sin overhead de tokens extra.
- **Cero riesgo**: no hay memory leaks, no hay bugs de concurrencia.

#### Desventajas
- **No soporta conversaciones multi-turno**: el usuario debe repetir contexto.
- **Experiencia de usuario limitada**: parece un asistente "tonto" que no recuerda nada.

#### Limitaciones técnicas
- Ninguna. Es el estado actual.

#### Caso de uso real
```
Usuario: "Hola NEO"
NEO: "¡Hola!"
Usuario: "¿cómo está el clima en La Habana?"
NEO: "28 grados, soleado."
Usuario: "¿y mañana?"
NEO: "No entiendo tu pregunta."  ← no sabe que hablas del clima
```

El usuario tiene que decir "¿cómo estará el clima mañana en La Habana?" cada vez.

---

## Comparación cuantitativa

| Criterio | Opción A (RAM) | Opción B (SQLite) | Opción C (Status quo) |
|----------|----------------|-------------------|----------------------|
| **Complejidad** | Baja (~30 líneas) | Alta (~100 líneas) | Cero |
| **Tiempo de implementación** | 1-2 horas | 4-6 horas | 0 horas |
| **Overhead de latencia** | +50-100ms | +60-150ms | 0ms |
| **Overhead de tokens** | +250 tokens/consulta | +250 tokens/consulta | 0 tokens |
| **Persistencia** | No | Sí | No |
| **Privacidad** | Alta (solo RAM) | Media (disco local) | Alta |
| **Riesgo de bugs** | Bajo (memory leak) | Medio (BD, concurrencia) | Cero |
| **Casos de uso habilitados** | Multi-turno dentro de sesión | Multi-turno + persistencia | Ninguno |

## Análisis de latencia

### Impacto de tokens extra en Groq

Groq es extremadamente rápido (inferencia en ~200-500ms para respuestas cortas). El
overhead de tokens extra es marginal:

| Tokens de historial | Overhead estimado | Perceptible para el usuario |
|---------------------|-------------------|-----------------------------|
| 0 tokens (status quo) | 0ms | N/A |
| 250 tokens (5 turnos) | +50-100ms | No (dentro del ruido) |
| 500 tokens (10 turnos) | +100-200ms | marginalmente |
| 1000 tokens (20 turnos) | +200-400ms | Sí, pero aceptable |

**Conclusión:** con 5 turnos (250 tokens), el overhead es imperceptible. Con 10 turnos
(500 tokens), es marginal. Más de 10 turnos no es recomendable (la conversación se
vuelve confusa de todos modos).

### Impacto de SQLite vs RAM

| Operación | RAM (dict) | SQLite |
|-----------|------------|--------|
| Leer historial | <1ms | 10-50ms |
| Escribir turno | <1ms | 10-50ms |
| Total overhead | <2ms | 20-100ms |

**Conclusión:** el overhead de SQLite es medible pero pequeño comparado con el overhead
de tokens extra (+50-100ms). No es el factor dominante.

## Decisión final

### Recomendación: **Opción A — Historial en RAM por sesión**

#### Justificación

1. **Sensata**: la ventana de conversación del firmware (10s) define el alcance natural
   de una "sesión". La memoria del servidor debería reflejar esto. La persistencia
   (Opción B) no aporta valor real porque el usuario probablemente empieza una nueva
   conversación tras reiniciar el servidor.

2. **Fácil de implementar**: ~30 líneas de código, 1-2 horas. Opción B requiere 4-6
   horas + tests + migraciones.

3. **Sin aumentar latencia perceptiblemente**: el overhead de tokens extra (+50-100ms)
   es imperceptible para el usuario. El overhead de SQLite (+20-100ms) es innecesario.

4. **Costo cero**: Groq free tier maneja los tokens extra sin problema.

5. **Privacidad**: nada se guarda en disco, todo en RAM.

#### Cuándo implementar

**Ahora.** La implementación es trivial (30 líneas) y el beneficio es alto (conversaciones
multi-turno). No hay razón para esperar.

#### Configuración recomendada

- **Ventana deslizante**: últimos 5 turnos (10 mensajes).
- **Tope de tokens**: opcional, pero si se implementa, ~500 tokens máximos.
- **Limpieza**: eliminar sesión del dict al cerrar WebSocket.

#### Métricas de éxito

1. **Latencia**: el overhead de tokens extra no debe aumentar la latencia del LLM en
   más de 100ms (medir con el experimento de latencia).
2. **Coherencia**: pruebas manuales de conversaciones multi-turno ("¿y mañana?",
   "¿en euros?") deben funcionar correctamente.
3. **Limpieza**: las sesiones deben eliminarse del dict al cerrar el WebSocket, sin
   memory leaks tras 100+ sesiones.

## Implementación

**Estado: IMPLEMENTADO**

Ver:
- `servidor/src/server/memory.py` — módulo de memoria conversacional
- `servidor/src/server/ws_server.py` — integración con pipeline
- `servidor/src/llm/client.py` — `ask()` ahora acepta lista de mensajes

### Configuración actual

- **Ventana deslizante**: últimos 10 turnos (5 conversaciones usuario/asistente)
- **Thread-safe**: usa `threading.Lock` para concurrencia
- **Limpieza automática**: sesión se elimina al cerrar WebSocket
- **Solo LLM libre**: handlers de keywords (clima, cripto, etc.) no usan memoria

### Métricas observadas

Pendiente de medir con el experimento de latencia. Se espera:
- Overhead de tokens: ~250 tokens por consulta con historial
- Overhead de latencia: +50-100ms (imperceptible)

## Referencias

- Firmware: ventana de conversación de 10s en `main.cpp` (`CONVERSACION_ESCUCHA_MS`).
- Servidor: pipeline actual en `ws_server.py` (`_modo_pipeline`).
- LLM: system prompt en `llm/client.py` (`SYSTEM_PROMPT`).
