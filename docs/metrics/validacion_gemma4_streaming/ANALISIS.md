# Análisis: gemma4:e2b + respuesta en streaming (25/10)

Dos sesiones el mismo día:

1. **11:52, tres variantes** (`gemma`, `gemma-completa`, `qwen-ref`): `informe.md` y
   `resultados.csv` de esta carpeta. Es la que se analiza a partir de «Configuración».
2. **13:10, solo `gemma` en streaming**, con el firmware nuevo (calibración del VAD por
   percentil) y el prompt nuevo de NEO: [`sesion_1310/`](sesion_1310/). Su análisis está en la
   sección siguiente.

## Segunda sesión (13:10): solo gemma, firmware y prompt nuevos

**Resumen.**

- **La captura queda arreglada:** WER del 5,1 % (11,1 % en la primera sesión, 6,2 % local
  el 24/10) e intención correcta en el 100 % de los casos.
- **La latencia empeoró por el prompt nuevo:** primer token en 11,4 s, frente a 2,9 s en
  `gemma-completa` con el prompt antiguo.
- **El streaming ahora sí parte las respuestas:** adelanta el primer audio ~1,9 s.
- Hubo una caída de red de 13:53 a 14:00, y el monitor de la placa se congeló a las 13:45.

### Qué cambió respecto a la primera sesión

| | 11:52 | 13:10 |
|---|---|---|
| Variantes | 3, en serie (sesgo de orden) | solo `gemma`; qwen descargado de Ollama |
| Firmware | calibración del VAD por media | **percentil 25** (`a05d7b7`) |
| System prompt | antiguo (118 tokens) | **nuevo, personaje con ejemplos (409 tokens)** (`d781ce3`) |
| WER | criterio con tildes | **sin tildes** (`c335ff6`) |
| Ritmo | ~30 s por frase | ~33 s por frase (el LLM es más lento), con una pausa de 74 min antes de c05 |

### Transcripción: la captura queda arreglada

| | 13:10 | 11:52 | 24/10 local |
|---|---|---|---|
| WER (sin tildes) | **5,1 %** | 11,1 % | 6,2 % |
| WER con tildes | 7,2 % | 14,0 % | 9,7 % |
| CER | 1,4 % | 6,7 % | 1,4 % |
| Frases exactas | 74,2 % | 60,6 % | 80,6 % |
| Intención correcta | **100 %** | 97,0 % | — |
| Inicios perdidos | **1** (c03 «aguanto está el dólar») | 8 | 2–3 |
| Alucinaciones sobre ruido | 1 (f03/1, descartado) | 3 | — |

- **Calibración.** El ruido calibrado sale ahora 15–16 en todos los turnos, que es el mínimo
  (`VAD_RUIDO_MIN`). En la primera sesión salía 18–203. El umbral de inicio queda fijo en
  90–96.
- **El fin de la grabación sigue bien:** 2,9–4,2 s, siempre por «Silencio prolongado» salvo
  una vez.
- **Un falso disparo.** Esa excepción es f03/1 (13:15:40): el VAD se disparó, cortó por «Sin
  voz útil» a los 2,98 s y Whisper transcribió «Subtítulos por la comunidad de Amara.org». Con
  un umbral más bajo, un ruido puede abrir la grabación. Si se repite, conviene subir
  `VAD_RUIDO_MIN` (por ejemplo a 25, umbral 150), que sigue muy por debajo de los 1220 del
  fallo original.
- **Errores restantes:** «Explígame» (×2), «recomiendan» y «que gome» son pronunciación o
  terminación, no cortes de la captura.

### Latencia: el prompt nuevo cuesta ~8,5 s de primer token

Preguntas libres, mediana. Sin las 5 frases de la caída de red, n = 20:

| Tramo | 13:10 gemma (streaming) | 11:52 gemma-completa | 11:52 gemma corregida |
|---|---|---|---|
| STT | 2,38 | 2,43 | — |
| LLM, primer token | **11,39** | 2,89 | ~2,9 |
| LLM, respuesta completa | 14,44 | 4,69 | — |
| TTS del primer fragmento | 2,89 | 2,99 | 2,99 |
| Empieza a hablar (servidor) | **18,01** | 10,40 | 9,88 |
| Palabras por respuesta | 16 | 10,5 | 10,5 |
| Fragmentos de TTS | 2 | 1 | 1 |

Medido directamente en Ollama con gemma4:e2b, tres preguntas distintas cada vez:

| System prompt | Tokens de prompt | Tiempo de prompt |
|---|---|---|
| Nuevo (personaje + 4 ejemplos) | 409 | 8,4–11,6 s |
| Antiguo | 118 | 2,7–3,2 s |

**Ollama no reutiliza el system prompt entre preguntas distintas con gemma4:e2b.** En la
primera sesión solo lo reutilizaba cuando la petición era idéntica. Por eso los 291 tokens de
más se pagan en cada pregunta, a ~37 tokens/s. Además, la respuesta sale más larga: 16
palabras frente a 10,5, y la generación completa pasa de 4,7 a 14,4 s. **Con este i5, el
prompt nuevo no es viable para el perfil local.** En la nube (Groq) no importa.

Hay dos salidas, y ninguna está aplicada todavía:

- **Un prompt corto para el perfil local:** el mismo personaje y las mismas reglas, sin los
  ejemplos, que son ~200 tokens. Se puede poner en `NEO_SYSTEM_PROMPT` del perfil.
- **Medir si qwen2.5:3b reutiliza el prefijo.** En la primera sesión, qwen procesó 49 tokens
  en 1,0–1,7 s.

**Streaming.** Con respuestas de 16 palabras, la mediana es de 2 fragmentos y el audio sigue
llegando 2,8 s después del primero. Si se esperara la respuesta completa, NEO empezaría a
hablar al terminar el LLM más el TTS de la oración entera, ~3,1 s medidos con 17 palabras:
unos 19,9 s. Con streaming empezó a los 18,0 s: **~1,9 s de ganancia**. Es más que en la
primera sesión (0,4 s), porque ahora las respuestas sí se parten. El primer fragmento sale
1,0 s después del primer token.

### En la placa

El log solo cubre hasta las 13:45:41, cuando el monitor se congeló (6 turnos; la placa siguió
funcionando). Es la segunda vez que pasa, tras 24–35 min de monitor en el panel Terminal de
la app. Para la próxima sesión conviene lanzarlo en una ventana de PowerShell aparte.

| Tramo (n = 5) | Mediana | p90 |
|---|---|---|
| Espera de silencio del VAD | 1,50 | 1,50 |
| Subida por WiFi | 0,61 | 0,67 |
| Servidor + red hasta el primer audio | 18,02 | 22,91 |
| Primer audio → empieza a sonar | 0,02 | 0,02 |
| **Percibida total** | **20,14** | 25,00 |

- **La reproducción progresiva funciona:** empieza 20 ms después del primer audio, unos 2,6 s
  antes de que llegue `fin_respuesta`. Hubo 0 esperas por datos en 5 de 6 respuestas y 1 en
  la otra.
- **Wake word:** del fin de «Hola NEO» a la confirmación pasan 1,09 s de mediana (n = 5),
  igual que el 24/10 (1,11 s).

### Caída de red (13:53–14:00)

El PC perdió el DNS (`getaddrinfo failed`). Cada consulta esperaba ~10 s y fallaba:

- **Comandos c01–c04:** respondieron «No pude conectarme al servicio de clima» y similares.
- **TTS:** edge-tts cayó a Piper.
- **Preguntas f20–f24:** TTS de 20–30 s.

El informe cuenta c01–c04 como «intención correcta» y sin errores, porque la intención sí se
detectó y el error se dijo en voz alta. Las latencias de comandos de esta sesión no valen:
3 de 7 son válidas y el TTS de c05–c07, a las 15:14, todavía fue lento (9,7 s).

### Siguiente

1. Prompt corto para el perfil local y repetir solo las 24 preguntas libres; el objetivo es
   volver a ~10 s en «Empieza a hablar» con la ganancia del streaming.
2. Monitor de la placa fuera del panel Terminal de la app.
3. Si vuelve a haber alucinaciones sobre ruido, `VAD_RUIDO_MIN` a 25.

---

## Primera sesión (11:52): tres variantes

Sesión `servidor/logs/panel/20261025_115254`, 31 frases del corpus leídas a la placa
(33 intentos válidos), variantes `gemma` (streaming, la que oyó la placa),
`gemma-completa` y `qwen-ref`. Plan e hipótesis en [`PLAN.md`](PLAN.md); referencia en
[`../validacion_20261024/`](../validacion_20261024/). `informe.md` es el que generó el panel a
las 12:39. `resultados.csv` tiene además c07/2 y c07/3, grabados a las 12:49, después del
informe: son ruido que Whisper transcribe como «Subtítulos realizados por la comunidad de
Amara.org». Aquí no se cuentan.

**Resumen.** Esta sesión no permite medir bien ni el streaming ni el modelo:

- El orden de las variantes penaliza a `gemma` unos 2,9 s en el primer token.
- La sección de la placa salió vacía: el monitor se cerró a las 11:30.
- La captura perdió el inicio de muchas frases.

Corregido el sesgo, el streaming adelanta el primer audio unos **0,4 s** en preguntas libres
y **1,3 s** en noticias. Las dos palancas grandes no son el streaming: son el coste fijo de
edge-tts (~1,9 s por llamada) y la captura. Hay que repetir la sesión (ver al final).

### Configuración frente al 24/10

| | 24/10 (local) | 25/10 |
|---|---|---|
| STT | whisper-small | whisper-small (`--whisper-model`, el `.env` tiene base) |
| LLM | qwen2.5:3b, completa | las tres variantes del plan, `think: false`, `num_ctx` 2048, `num_predict` 96 |
| TTS | edge-tts Manuel | igual |
| System prompt | el de la rama del 24/10 | el antiguo («Soy NEO… sarcástico»): el prompt nuevo seguía sin commitear |
| Firmware | reproduce al recibir `fin_respuesta` | reproducción progresiva (colchón de 256 ms) |
| Ritmo | ~15 s entre frases, la placa seguía en conversación | ~30 s por frase: la placa volvía a reposo y cada pregunta empezaba con «Hola NEO» |

### 1. «Empieza a hablar» y latencia percibida

Preguntas libres, mediana (p90), en segundos, desde `fin_grabacion`:

| | gemma | gemma-completa | qwen-ref | 24/10 local |
|---|---|---|---|---|
| Empieza a hablar | 12,75 (18,35) | 10,49 (14,66) | 9,65 (11,87) | 8,76 (respuesta completa) |
| STT | 2,36 | 2,43 | 2,55 | 2,34 |
| LLM, primer token | 5,92 | 2,89 | 2,73 | — |
| LLM, respuesta completa | 7,87 | 4,69 | 3,96 | 3,74 |
| TTS | 3,35 | 3,11 | 2,98 | 2,49 |

**Las cifras de `gemma` no son comparables tal cual: el orden de las variantes la penaliza.**
El panel procesa cada frase en orden `gemma` → `gemma-completa` → `qwen-ref`, y cada consulta
abre una conexión nueva, sin historial. Por eso `gemma` siempre va justo después de qwen y
`gemma-completa` justo después de `gemma`, con el mismo modelo y exactamente el mismo prompt.
Medido directamente en Ollama, alternando modelos como el panel:

| Petición | Recarga de páginas | Prompt (45 tokens) | Generación |
|---|---|---|---|
| gemma justo después de qwen | 0,66–5,01 s | 1,11–2,53 s | ~7 tokens/s |
| la misma petición, otra vez | 0,65–1,80 s | 0,23–0,46 s (caché de prefijo) | ~7 tokens/s |

Con 16 GB, tres Whisper cargados y los dos modelos, Windows saca de RAM parte de gemma mientras
trabaja qwen (`ollama ps` muestra gemma con solo 1,0 GB residente). La siguiente consulta la
relee del disco, y la de detrás encuentra el prompt ya procesado. Ese es el escenario que
avisaba el plan (punto 3). Se ve en el p90 y en f06, con 40,9 s de primer token.

Corrección frase a frase: al primer audio de `gemma` se le resta la diferencia de primer
token frente a `gemma-completa` (mediana 2,91 s):

| | Empieza a hablar (mediana, n = 25) |
|---|---|
| gemma, medido | 12,75 s |
| gemma, sin el sesgo de orden | **9,88 s** |
| gemma-completa | 10,48 s |
| Ganancia del streaming (mediana por frase) | **0,44 s** |

**Latencia percibida en la placa:** no hay datos de esta sesión. `pio device monitor` dejó de
escribir `firmware/logs/device-monitor-261025-110604.log` a las 11:30, antes de que empezara
la sesión (11:52). De la sesión anterior (`20261025_111116`, gemma en streaming) el log tiene
dos turnos. En ambos, de `grabacion_fin` a `playback_inicio` pasaron 12,1 s, que con los 1,5 s
del VAD dan **13,6–13,7 s percibidos**. Fue con gemma recién cargada y el mismo sesgo de orden.

### 2. Primer token frente a respuesta completa

- `gemma`: el primer token llega 1,9 s antes del final (5,92 frente a 7,87). En
  `gemma-completa`, 1,8 s antes (2,89 frente a 4,69). **El modelo no razona:** sin
  `message.thinking`, `eval_count` de 10–20 tokens. Lo que ocurre es que genera lento,
  a ~7 tokens/s en este i5, no a «decenas de tokens/s».
- De primer token a primer fragmento listo pasan 1,5 s en `gemma` (≥ 5 palabras hasta
  una coma, o la oración entera).
- **En 20 de 32 respuestas libres hubo un solo fragmento.** Son una oración de unas 10
  palabras, sin `;` y sin coma después de la quinta palabra, así que el primer fragmento era
  la respuesta entera. De ahí la mediana de 0,02 s entre el primer audio y el final.
  En las 12 respuestas que sí se partieron, el LLM siguió generando 0,96 s después del
  primer fragmento, y ese es el máximo que puede ahorrar el streaming.
- **edge-tts tiene ~1,9 s de coste fijo por llamada.** Medido desde este PC (salida por
  Miami, 118 ms a Groq): el primer trozo de audio llega a los 1,85 s con 1 palabra, 1,89 s
  con 6 y 2,21 s con 17, y el audio termina a los 2,3–3,1 s. El TTS del primer fragmento
  (`tts_start` → `primer_audio`) es de 2,99 s, igual que el de la respuesta entera en
  `gemma-completa`. Partir en fragmentos no abarata el TTS: cada fragmento vuelve a pagar
  esos ~2 s, que es la incertidumbre que señalaba el plan.

**Comandos.** En noticias (4 fragmentos), `gemma` empieza a hablar a los 7,0 s y
`gemma-completa` a los 8,3 s: 1,3 s menos. Pero el streaming entrega el último fragmento a los
16,7 s, frente a los 8,3 s de una sola llamada, porque cada fragmento vuelve a pagar el coste
fijo de edge-tts. Mientras la placa reproduzca más rápido de lo que llegan los fragmentos, eso
se oye como pausas entre frases; de noticias no hay log de la placa para comprobarlo. Clima,
toque y cripto son un solo fragmento y no cambian (5,7–6,6 s).

### 3. WER e intención

**Criterio rectificado:** desde el 25/10 el WER, el CER y las frases exactas se calculan **sin
tildes** (`metricas.py`); el WER con tildes queda como fila aparte, para comparar con lo
anterior. El informe de esta carpeta se generó antes del cambio: su «WER» es el criterio
antiguo, con tildes, y su «WER sin tildes» es el nuevo.

| | 25/10 (las 3 variantes, mismo audio) | 24/10 local | 24/10 nube |
|---|---|---|---|
| WER (sin tildes) | **11,1 %** | 6,2 % | 3,1 % |
| WER con tildes | 14,0 % | 9,7 % | 4,6 % |
| CER (sin tildes) | 6,7 % | 1,4 % | 1,1 % |
| Frases exactas (sin tildes) | 60,6 % | 80,6 % | 90,3 % |
| Intención correcta | 97,0 % (falla f16, «Hola Nio») | — | — |

El STT era el mismo, así que el empeoramiento viene de la captura, no del pipeline (punto 4
del plan):

- **Se perdió el inicio en 8 intentos**, frente a 2–3 el 24/10: f02 «escribió Don Quijote»,
  f05 «el planeta más grande», f17 «se forman los huracanes», f23 «que está hecho el sol»,
  f11 «comiéndame» (×2), f15 «Seguimos unas frases» y «para empezar el día».
- **3 alucinaciones de Whisper sobre audio casi vacío:** «Bienvenido y hasta el próximo vídeo»,
  «¡Suscríbete!» y «Subtítulos realizados por la comunidad de Amara.org».
- **f16/2, «Hola Nio»:** se grabó el «Hola NEO» como pregunta, porque la placa seguía
  escuchando cuando se volvió a decir la palabra de activación.

**Causa: la calibración del VAD.** El pre-roll de 300 ms sigue en el firmware; lo que cambió
fue el ritmo. Con ~30 s por frase, la placa volvía a reposo, y cada pregunta empezaba con «Hola
NEO» → saludo → 0,5 s de calibración del ruido → escucha. Si la persona empieza a hablar justo
tras el saludo, la calibración promedia su voz como si fuera ruido. A las 11:20:10, por
ejemplo, el ruido base salió de 203 (lo normal es 55–60), el umbral de inicio quedó en 1220 y
el VAD no oyó la frase. Con un umbral inflado, la voz solo lo supera ya entrada la frase, y
300 ms de pre-roll no alcanzan para recuperar el principio.

**Arreglo** (`firmware/src/main.cpp`, compilado pero sin flashear): la calibración usa el
percentil 25 de los 32 bloques en vez de la media. El ruido de fondo está en casi todos los
bloques, y la voz que entra en parte de la ventana ya no lo infla.

### 4. Esperas por datos en la placa

Solo hay log de los dos turnos de la sesión anterior: **0 esperas por datos en ambos.** En el
primero, la reproducción empezó 2,9 s antes de que llegara `fin_respuesta`. En el segundo,
llegaron 20 KB de golpe y `fin_respuesta` 150 ms después. La reproducción progresiva del
firmware funciona. Con un solo fragmento por respuesta no hay huecos que esperar; los habría
en noticias, pero de esas no hay log.

### 5. Calidad de las respuestas

- **Cambios de idioma: ninguno** en 35 respuestas por variante, tampoco en qwen2.5:3b (2 de 24 el 24/10).
  Desde esta rama, `ask()` repite la pregunta si el modelo cambia de alfabeto, y `ask_stream()`
  filtra las letras de otro alfabeto, porque lo que ya suena no se puede repetir.
- **Cortes de entonación:** 12 respuestas de `gemma` se partieron. La mayoría cortan en `;`
  («Tokio es la capital de Japón;» | «es bastante obvio.»), que es un corte natural. El
  corte malo es f04: «Las plantas usan luz solar,» | «agua y dióxido de carbono…» parte una
  enumeración. f05 y f13 cortan en una coma antes de una coletilla («…del sistema solar,» |
  «sin lugar a dudas.»), que suena aceptable. Hay que escucharlas para confirmarlo, en
  `servidor/logs/panel/20261025_115254/respuestas/f04_1_gemma.wav` y similares. Con el ahorro
  medido (≤ 1 s), subir `TTS_MIN_PALABRAS_COMA` cuesta poco.
- **El Toque:** c04 respondió «No encontré la tasa para EUR». El Toque publica el euro como
  `ECU`; ya está corregido (`router.py`, `toque.py`) y verificado contra la API: «El euro está
  a 930 pesos cubanos». Además, las tasas se leen «835» y no «835.0».

### Hipótesis del plan

| Hipótesis | Resultado |
|---|---|
| gemma4:e2b no razona con `think: false` | **Se cumple:** sin `thinking`, 10–20 tokens por respuesta. |
| `gemma-completa` ≈ `qwen-ref` en latencia; el modelo cambia la calidad, no la velocidad | **Casi:** 10,49 frente a 9,65 s. gemma genera algo más (10,5 palabras de mediana frente a 7,5) y su LLM completo tarda 0,7 s más. La calidad no se evaluó con la placa. |
| El streaming adelanta «Empieza a hablar» 2–3,5 s, hasta 5–6,5 s | **No se cumple:** 0,44 s una vez corregido el sesgo (9,9 s). Las respuestas de una oración casi nunca se parten, y edge-tts cobra ~1,9 s por fragmento. En noticias, 1,3 s menos hasta la primera palabra, a cambio de terminar 8 s más tarde. |
| Lo que queda lo dominan el STT (~2,3 s) y el VAD (1,5 s) | **En parte:** STT 2,4 s, LLM hasta el primer fragmento ~4,5 s sin el sesgo, TTS del primer fragmento 3,0 s. El TTS por llamada pesa tanto como el STT. |

### Qué cambia y siguientes pasos

1. **Repetir la sesión** con el firmware nuevo (calibración por percentil), el monitor abierto
   toda la sesión (`--port COM8`) y, para no sesgar, **una sola variante de gemma por sesión**:
   gemma en streaming en una y gemma completa en otra, cada una con el mismo PC en reposo.
   Mientras dos variantes compartan modelo en la misma sesión, la segunda se beneficia de la
   caché de la primera.
2. **El TTS es la palanca:** con edge-tts, que cobra ~1,9 s antes del primer trozo, conviene
   reenviar a la placa el audio de cada llamada a medida que llega, en vez de esperar al
   fragmento entero (ahorra 0,5–0,9 s por fragmento), o usar Piper para el primer fragmento.
3. Subir `TTS_MIN_PALABRAS_COMA` (por ejemplo a 7) para no partir enumeraciones como f04.
4. Pasar el panel a escribir en `firmware/logs/` y no dar por buena una sesión sin log de la
   placa: el informe debería avisarlo arriba, no al final.
