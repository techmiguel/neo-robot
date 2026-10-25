"""Banco de pruebas de NEO: casos que reflejan el uso real del servidor.

Cada caso: id, categoría, mensajes (sin el system prompt de NEO, que se antepone
salvo en tareas con system propio) y un verificador opcional.
"""

NEO_SYSTEM = (
    "Soy NEO, un robot asistente que vive en un ESP32-S3. "
    "Tengo personalidad directa, un toque sarcástico pero siempre útil. "
    "Respondo en español con UNA sola oración de máximo 20 palabras. "
    "No me enrolló, no pido disculpas, no uso muletillas. "
    "Si algo es obvio, lo digo. Si no sé, lo admito sin rodeos. "
    "Mi objetivo: ser el asistente más eficiente del mundo embebido."
)

# expect: lista de alternativas; cada alternativa es una lista de subcadenas
# (en minúsculas, sin tildes) que deben aparecer TODAS. Basta con que una
# alternativa se cumpla.
CHAT = [
    # Conocimiento general (lo que STT entrega: sin signos a veces)
    ("k01", "conocimiento", "¿qué es la fotosíntesis?", [["luz"], ["sol"]]),
    ("k02", "conocimiento", "cuál es la capital de australia", [["canberra"]]),
    ("k03", "conocimiento", "¿quién escribió cien años de soledad?", [["garcia marquez"], ["gabo"]]),
    ("k04", "conocimiento", "¿a qué temperatura hierve el agua al nivel del mar?", [["100"], ["cien"]]),
    ("k05", "conocimiento", "¿cuántos planetas tiene el sistema solar?", [["ocho"], ["8"]]),
    ("k06", "conocimiento", "¿quién fue josé martí?", [["cuba"], ["cubano"], ["poeta"]]),
    ("k07", "conocimiento", "¿cuál es el río más largo de sudamérica?", [["amazonas"]]),
    ("k08", "conocimiento", "¿por qué el cielo es azul?", [["dispers"], ["rayleigh"], ["luz azul"]]),
    ("k09", "conocimiento", "¿en qué año llegó colón a américa?", [["1492"]]),
    ("k10", "conocimiento", "¿qué es un microcontrolador?", [["chip"], ["circuito"], ["procesador"], ["computadora"]]),
    ("k11", "conocimiento", "¿cuál es el hueso más largo del cuerpo humano?", [["femur"]]),
    ("k12", "conocimiento", "¿qué gas exhalamos al respirar?", [["dioxido de carbono"], ["co2"], ["carbono"]]),
    # Razonamiento / cálculo simple
    ("r01", "razonamiento", "¿cuánto es 17 por 23?", [["391"]]),
    ("r02", "razonamiento", "si tengo 3 manzanas y me como una, ¿cuántas me quedan?", [["dos"], ["2"]]),
    ("r03", "razonamiento", "¿cuántos minutos hay en tres horas y media?", [["210"], ["doscientos diez"]]),
    ("r04", "razonamiento", "convierte 30 grados celsius a fahrenheit", [["86"]]),
    ("r05", "razonamiento", "¿qué pesa más, un kilo de plumas o un kilo de hierro?", [["igual"], ["mismo"], ["ninguno"], ["ambos"]]),
    ("r06", "razonamiento", "si hoy es lunes, ¿qué día será dentro de diez días?", [["jueves"]]),
    # Prácticos / cotidianos
    ("p01", "practico", "dame un consejo rápido para dormir mejor", None),
    ("p02", "practico", "¿cómo hago un café cubano?", None),
    ("p03", "practico", "recomiéndame una película para esta noche", None),
    ("p04", "practico", "cuéntame un chiste corto", None),
    ("p05", "practico", "estoy aburrido", None),
    # Honestidad: lo que un modelo offline no puede saber
    ("h01", "honestidad", "¿quién ganó el partido de anoche?", None),
    ("h02", "honestidad", "¿qué hora es ahora mismo?", None),
    ("h03", "honestidad", "¿cuál es la última noticia de hoy?", None),
    ("h04", "honestidad", "¿cuánto cuesta el dólar hoy en cuba?", None),
    # Robustez a transcripción imperfecta del STT
    ("s01", "stt_ruido", "oye neo este que es un agujero negro", [["gravedad"], ["luz"]]),
    ("s02", "stt_ruido", "como se dise hola en ingles", [["hello"]]),
    # Personalidad
    ("y01", "personalidad", "¿quién eres?", [["neo"]]),
    ("y02", "personalidad", "¿eres más listo que alexa?", None),
    ("y03", "personalidad", "explícame la teoría de la relatividad con todo detalle", None),
]

# Multi-turno: historial previo + pregunta final que depende del contexto.
MULTITURN = [
    ("m01", "multiturno",
     [("user", "me llamo carlos"),
      ("assistant", "Mucho gusto, Carlos, aquí NEO, listo para lo que necesites."),
      ("user", "¿cómo me llamo?")],
     [["carlos"]]),
    ("m02", "multiturno",
     [("user", "¿cuál es la capital de francia?"),
      ("assistant", "París, obviamente."),
      ("user", "¿y cuántos habitantes tiene aproximadamente?")],
     [["millon"]]),
    ("m03", "multiturno",
     [("user", "voy a hacer arroz con pollo"),
      ("assistant", "Buena elección, solo no lo quemes."),
      ("user", "¿cuánto tiempo lo dejo al fuego?")],
     [["minuto"]]),
    ("m04", "multiturno",
     [("user", "mi perro se llama rocky"),
      ("assistant", "Rocky, nombre de campeón; espero que no muerda."),
      ("user", "¿qué le puedo dar de comer?"),
      ("assistant", "Pienso de calidad, carne cocida y nada de chocolate."),
      ("user", "¿cómo se llama mi perro?")],
     [["rocky"]]),
]

# Tareas estructuradas (docs/comandos.txt): system propio, salida verificable.
TASKS = [
    ("t01", "json_timer",
     "Extrae la duración pedida por el usuario y responde SOLO con JSON "
     "de la forma {\"segundos\": <entero>}. Sin texto adicional.",
     "pon un temporizador de cinco minutos", {"segundos": 300}),
    ("t02", "json_timer",
     "Extrae la duración pedida por el usuario y responde SOLO con JSON "
     "de la forma {\"segundos\": <entero>}. Sin texto adicional.",
     "avísame en una hora y media", {"segundos": 5400}),
    ("t03", "json_timer",
     "Extrae la duración pedida por el usuario y responde SOLO con JSON "
     "de la forma {\"segundos\": <entero>}. Sin texto adicional.",
     "temporizador de 90 segundos para los huevos", {"segundos": 90}),
    ("t04", "json_timer",
     "Extrae la duración pedida por el usuario y responde SOLO con JSON "
     "de la forma {\"segundos\": <entero>}. Sin texto adicional.",
     "cuenta dos minutos y medio", {"segundos": 150}),
    ("t05", "intent",
     "Clasifica la petición en una de estas intenciones: clima, cripto, noticias, "
     "toque, temporizador, traducir, libre. Responde SOLO con JSON "
     "{\"intencion\": \"<valor>\"}.",
     "necesito saber si va a llover mañana en santiago", {"intencion": "clima"}),
    ("t06", "intent",
     "Clasifica la petición en una de estas intenciones: clima, cripto, noticias, "
     "toque, temporizador, traducir, libre. Responde SOLO con JSON "
     "{\"intencion\": \"<valor>\"}.",
     "a cómo está el bitcoin", {"intencion": "cripto"}),
    ("t07", "intent",
     "Clasifica la petición en una de estas intenciones: clima, cripto, noticias, "
     "toque, temporizador, traducir, libre. Responde SOLO con JSON "
     "{\"intencion\": \"<valor>\"}.",
     "cómo se dice buenos días en francés", {"intencion": "traducir"}),
    ("t08", "intent",
     "Clasifica la petición en una de estas intenciones: clima, cripto, noticias, "
     "toque, temporizador, traducir, libre. Responde SOLO con JSON "
     "{\"intencion\": \"<valor>\"}.",
     "escríbeme un poema sobre el mar", {"intencion": "libre"}),
    ("t09", "traducir",
     "Traduce al español el texto del usuario. Devuelve únicamente la traducción, "
     "sin explicaciones.",
     "The weather is nice today, let's go to the beach.", ["playa"]),
    ("t10", "traducir",
     "Traduce al español el texto del usuario. Devuelve únicamente la traducción, "
     "sin explicaciones.",
     "Please turn off the lights before leaving the room.", ["luces", "apaga"]),
    ("t11", "resumir",
     "Resume la noticia en máximo dos oraciones en español, para leer en voz alta.",
     "Titular: La NASA confirma el lanzamiento de la misión Artemis para la próxima "
     "primavera. Descripción: La agencia espacial estadounidense anunció que la "
     "misión tripulada que orbitará la Luna despegará desde Florida tras superar "
     "las pruebas finales del cohete SLS y de la cápsula Orion.", ["luna"]),
]
