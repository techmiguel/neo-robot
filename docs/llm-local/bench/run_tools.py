"""Banco de herramientas (estilo MCP) para NEO como agente.

Ejecuta un bucle de agente contra llama-server (API OpenAI con `tools`) usando
12 herramientas con esquemas al estilo MCP y resultados simulados deterministas.
Guarda la trayectoria de cada caso en results/tools-<modelo>[.sN].jsonl.

Uso: python3 run_tools.py <nombre> <ruta.gguf> [--think] [--seed N]
Requiere llama-server (llama.cpp); ruta en LLAMA_SERVER.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_eval import PORT, SERVER, sampling_for, wait_ready  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
MAX_PASOS = 5

# Variante elegida tras comparar dos redacciones con Gemma 4 E2B (16/24 frente a
# 9/24): las reglas de formato para voz deben aplicarse solo a la respuesta final;
# si se formulan como norma general, el modelo escribe las llamadas como texto.
AGENT_SYSTEM = (
    "Eres NEO, un asistente de voz con herramientas. Usa las herramientas siempre que "
    "la petición necesite datos actuales o realizar una acción. Tras recibir los "
    "resultados, responde al usuario en español con una o dos oraciones cortas, "
    "directas y con un toque sarcástico. Si una herramienta devuelve un error, dilo "
    "sin inventar datos. Si falta un dato imprescindible, pregúntalo. "
    "Hoy es sábado 25 de octubre de 2026."
)


def tool(name, desc, props, required):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required}}}


S = {"type": "string"}
TOOLS = [
    tool("obtener_clima", "Clima actual de una ciudad: temperatura en °C y estado del cielo.",
         {"ciudad": {**S, "description": "Nombre de la ciudad"}}, ["ciudad"]),
    tool("precio_cripto", "Precio actual en USD de una criptomoneda.",
         {"moneda": {"type": "string", "enum": ["bitcoin", "ethereum", "solana", "cardano"]}},
         ["moneda"]),
    tool("tasa_cambio_cuba", "Tasa de cambio informal en Cuba (El Toque), en CUP por unidad.",
         {"moneda": {"type": "string", "enum": ["USD", "EUR", "MLC"]}}, ["moneda"]),
    tool("titulares_noticias", "Titulares de noticias recientes, opcionalmente por tema.",
         {"tema": {**S, "description": "Tema opcional, p. ej. tecnología"}}, []),
    tool("crear_temporizador", "Crea un temporizador en el robot.",
         {"segundos": {"type": "integer", "description": "Duración en segundos"},
          "etiqueta": {**S, "description": "Nombre opcional"}}, ["segundos"]),
    tool("hora_actual", "Devuelve la hora y la fecha actuales.", {}, []),
    tool("crear_evento", "Crea un evento en el calendario.",
         {"titulo": S, "fecha": {**S, "description": "Formato YYYY-MM-DD"},
          "hora": {**S, "description": "Formato HH:MM, 24 h"}}, ["titulo", "fecha", "hora"]),
    tool("buscar_web", "Busca en internet y devuelve resultados resumidos.",
         {"consulta": S}, ["consulta"]),
    tool("leer_archivo", "Lee un archivo de texto del usuario.",
         {"ruta": {**S, "description": "Ruta o nombre del archivo"}}, ["ruta"]),
    tool("listar_directorio", "Lista el contenido de una carpeta del usuario.",
         {"ruta": S}, ["ruta"]),
    tool("enviar_correo", "Envía un correo electrónico.",
         {"destinatario": S, "asunto": S, "cuerpo": S}, ["destinatario", "asunto", "cuerpo"]),
    tool("controlar_luz", "Enciende o apaga la luz de una habitación.",
         {"habitacion": S, "estado": {"type": "string", "enum": ["encendida", "apagada"]}},
         ["habitacion", "estado"]),
]


def norm(s):
    import unicodedata
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def ejecutar(nombre, args):
    """Resultados simulados deterministas."""
    a = {k: norm(v) for k, v in args.items()}
    if nombre == "obtener_clima":
        c = a.get("ciudad", "")
        if "madrid" in c:
            return {"ciudad": "Madrid", "temperatura_c": 18, "estado": "nublado"}
        if "habana" in c:
            return {"ciudad": "La Habana", "temperatura_c": 31, "estado": "soleado"}
        if "springfield" in c:
            return {"error": "ciudad no encontrada"}
        return {"ciudad": args.get("ciudad"), "temperatura_c": 22, "estado": "despejado"}
    if nombre == "precio_cripto":
        return {"moneda": args.get("moneda"), "precio_usd": {"bitcoin": 67250.5,
                "ethereum": 3120.0}.get(a.get("moneda"), 1.0)}
    if nombre == "tasa_cambio_cuba":
        return {"moneda": args.get("moneda"), "cup": {"usd": 410, "eur": 450, "mlc": 300}
                .get(a.get("moneda"), 0)}
    if nombre == "titulares_noticias":
        return {"titulares": ["Presentan un nuevo chip de inteligencia artificial de bajo consumo",
                              "La NASA confirma la fecha de la misión Artemis"]}
    if nombre == "hora_actual":
        return {"hora": "14:32", "fecha": "2026-10-25"}
    if nombre == "buscar_web":
        return {"resultados": [{"titulo": "Resultado principal",
                                "resumen": "Información encontrada sobre: " + str(args.get("consulta"))}]}
    if nombre == "leer_archivo":
        if "notas" in a.get("ruta", ""):
            return {"contenido": "Comprar leche. Llamar al técnico del aire acondicionado el lunes."}
        return {"error": "archivo no encontrado"}
    if nombre == "listar_directorio":
        return {"elementos": ["informe_octubre.pdf", "notas.txt", "fotos/"]}
    if nombre in ("crear_temporizador", "crear_evento", "enviar_correo", "controlar_luz"):
        return {"ok": True}
    return {"error": "herramienta desconocida"}


# Casos: (id, categoría, historial previo, petición, verificador(calls, final) -> dict)
def calls_named(calls, name):
    return [c for c in calls if c["name"] == name]


def arg(c, k):
    return norm(c["args"].get(k, ""))


def check(**parts):
    return parts


def pide_dato(t):
    """Pide aclaración con pregunta o con una petición explícita de datos."""
    return "?" in t or any(w in norm(t) for w in ("necesito", "dime", "indica", "indicame"))


def has_digit_temp(t):
    import re
    return bool(re.search(r"\d+\s*(°|grados)", t))


CASES = [
    ("t01", "simple", [], "¿qué tiempo hace en Madrid?",
     lambda C, F: check(seleccion=bool(calls_named(C, "obtener_clima")) and len(C) == 1,
                        argumentos=any("madrid" in arg(c, "ciudad") for c in calls_named(C, "obtener_clima")),
                        respuesta="18" in F and "nublad" in norm(F))),
    ("t02", "simple", [], "a cómo está el bitcoin",
     lambda C, F: check(seleccion=bool(calls_named(C, "precio_cripto")) and len(C) == 1,
                        argumentos=any(arg(c, "moneda") == "bitcoin" for c in C),
                        respuesta="67" in F.replace(".", "").replace(",", "") or "sesenta y siete" in norm(F))),
    ("t03", "simple", [], "a cuánto está el euro en el toque",
     lambda C, F: check(seleccion=bool(calls_named(C, "tasa_cambio_cuba")) and len(C) == 1,
                        argumentos=any(arg(c, "moneda") == "eur" for c in C),
                        respuesta="450" in F or "cuatrocientos cincuenta" in norm(F))),
    ("t04", "simple", [], "pon un temporizador de cinco minutos para el arroz",
     lambda C, F: check(seleccion=bool(calls_named(C, "crear_temporizador")) and len(C) == 1,
                        argumentos=any(str(c["args"].get("segundos")) == "300" for c in C))),
    ("t05", "simple", [], "apaga la luz de la cocina",
     lambda C, F: check(seleccion=bool(calls_named(C, "controlar_luz")) and len(C) == 1,
                        argumentos=any("cocina" in arg(c, "habitacion") and arg(c, "estado") == "apagada"
                                       for c in C))),
    ("t06", "simple", [], "¿qué hora es?",
     lambda C, F: check(seleccion=bool(calls_named(C, "hora_actual")) and len(C) == 1,
                        respuesta="14:32" in F or "dos y treinta y dos" in norm(F)
                        or "14 y 32" in F or "catorce" in norm(F))),
    ("t07", "simple", [], "agéndame el dentista mañana a las cinco de la tarde",
     lambda C, F: check(seleccion=bool(calls_named(C, "crear_evento")) and len(C) == 1,
                        argumentos=any(arg(c, "fecha") == "2026-10-26" and arg(c, "hora") in ("17:00", "17:00:00")
                                       and "dentista" in arg(c, "titulo") for c in C))),
    ("t08", "simple", [], "busca en internet quién ganó el balón de oro este año",
     # Reintentar la búsqueda si el resultado no trae la respuesta es aceptable.
     lambda C, F: check(seleccion=bool(C) and all(c["name"] == "buscar_web" for c in C),
                        argumentos=any("balon de oro" in arg(c, "consulta") for c in C))),
    ("t09", "simple", [], "qué hay en mi carpeta de documentos",
     lambda C, F: check(seleccion=bool(calls_named(C, "listar_directorio")) and len(C) == 1,
                        argumentos=any("document" in arg(c, "ruta") for c in C),
                        respuesta=any(w in norm(F) for w in ("notas", "informe", "pdf", "texto")))),
    ("t10", "simple", [], "léeme el archivo notas.txt",
     lambda C, F: check(seleccion=bool(calls_named(C, "leer_archivo")) and len(C) == 1,
                        argumentos=any("notas" in arg(c, "ruta") for c in C),
                        respuesta="leche" in norm(F))),
    ("t11", "simple", [], "dame las noticias de tecnología",
     lambda C, F: check(seleccion=bool(calls_named(C, "titulares_noticias")) and len(C) == 1,
                        respuesta=any(w in norm(F).replace(",", " ").split() for w in ("chip", "ia", "nasa", "artemis"))
                        or "inteligencia artificial" in norm(F) or "espacial" in norm(F))),
    ("t12", "simple", [], "manda un correo a ana@ejemplo.com diciéndole que llego tarde",
     lambda C, F: check(seleccion=bool(calls_named(C, "enviar_correo")) and len(C) == 1,
                        argumentos=any(arg(c, "destinatario") == "ana@ejemplo.com" and "tarde" in arg(c, "cuerpo")
                                       for c in C))),
    ("t13", "sin_herramienta", [], "¿cuánto es 17 por 23?",
     lambda C, F: check(seleccion=not C, respuesta="391" in F)),
    ("t14", "sin_herramienta", [], "cuéntame un chiste corto",
     lambda C, F: check(seleccion=not C, respuesta=len(F) > 10)),
    ("t15", "sin_herramienta", [], "¿quién escribió cien años de soledad?",
     lambda C, F: check(seleccion=not C or all(c["name"] == "buscar_web" for c in C),
                        respuesta="garcia marquez" in norm(F))),
    ("t16", "sin_herramienta", [], "gracias neo, eso es todo",
     lambda C, F: check(seleccion=not C)),
    ("t17", "multiple", [], "qué tiempo hace en La Habana y a cuánto está el dólar",
     lambda C, F: check(seleccion=bool(calls_named(C, "obtener_clima")) and bool(calls_named(C, "tasa_cambio_cuba"))
                        and len(C) == 2,
                        argumentos=any("habana" in arg(c, "ciudad") for c in calls_named(C, "obtener_clima"))
                        and any(arg(c, "moneda") == "usd" for c in calls_named(C, "tasa_cambio_cuba")),
                        respuesta=("31" in F or "treinta y un" in norm(F))
                        and ("410" in F or "cuatrocient" in norm(F)))),
    ("t18", "multiple", [], "enciende la luz del salón y pon un temporizador de diez minutos",
     lambda C, F: check(seleccion=bool(calls_named(C, "controlar_luz")) and bool(calls_named(C, "crear_temporizador"))
                        and len(C) == 2,
                        argumentos=any("salon" in arg(c, "habitacion") and arg(c, "estado") == "encendida"
                                       for c in calls_named(C, "controlar_luz"))
                        and any(str(c["args"].get("segundos")) == "600" for c in calls_named(C, "crear_temporizador")))),
    ("t19", "encadenada", [], "lee notas.txt y mándale un resumen por correo a ana@ejemplo.com",
     lambda C, F: check(seleccion=[c["name"] for c in C] == ["leer_archivo", "enviar_correo"],
                        argumentos=any(arg(c, "destinatario") == "ana@ejemplo.com"
                                       and ("leche" in arg(c, "cuerpo") or "tecnico" in arg(c, "cuerpo"))
                                       for c in calls_named(C, "enviar_correo")))),
    ("t20", "error", [], "¿qué tiempo hace en Springfield?",
     lambda C, F: check(seleccion=bool(calls_named(C, "obtener_clima")),
                        respuesta=not has_digit_temp(F) and ("no" in norm(F).split() or "encontr" in norm(F)))),
    ("t21", "aclaracion", [], "crea un evento en el calendario",
     lambda C, F: check(seleccion=not calls_named(C, "crear_evento"), respuesta=pide_dato(F))),
    ("t22", "aclaracion", [], "pon un temporizador",
     lambda C, F: check(seleccion=not calls_named(C, "crear_temporizador"), respuesta=pide_dato(F))),
    ("t23", "contexto",
     [("user", "¿qué tiempo hace en Madrid?"),
      ("assistant", "En Madrid hay 18 grados y está nublado, así que lleva chaqueta.")],
     "¿y en La Habana?",
     lambda C, F: check(seleccion=bool(calls_named(C, "obtener_clima")) and len(C) == 1,
                        argumentos=any("habana" in arg(c, "ciudad") for c in C),
                        respuesta="31" in F)),
    ("t24", "sin_herramienta", [], "¿cuál es la capital de Australia?",
     lambda C, F: check(seleccion=not C or all(c["name"] == "buscar_web" for c in C),
                        respuesta="canberra" in norm(F))),
]


def post(body):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())


def run_case(hist, peticion, think, sampling, seed):
    msgs = [{"role": "system", "content": AGENT_SYSTEM}]
    msgs += [{"role": ro, "content": c} for ro, c in hist]
    msgs.append({"role": "user", "content": peticion})
    calls, pasos, errores = [], [], 0
    final = ""
    t0 = time.time()
    for _ in range(MAX_PASOS):
        r = post({"messages": msgs, "tools": TOOLS, "max_tokens": 2048 if think else 512,
                  **sampling, "seed": seed, "cache_prompt": True,
                  "chat_template_kwargs": {"enable_thinking": think}})
        msg = r["choices"][0]["message"]
        tm = r["timings"]
        pasos.append({"prompt_n": tm["prompt_n"], "prompt_ms": tm["prompt_ms"],
                      "gen_n": tm["predicted_n"], "gen_ms": tm["predicted_ms"]})
        tcs = msg.get("tool_calls") or []
        if not tcs:
            final = (msg.get("content") or "").strip()
            break
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tcs})
        for tc in tcs:
            fn = tc["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
                res = ejecutar(fn["name"], args)
            except json.JSONDecodeError:
                args, res = {"_raw": fn.get("arguments")}, {"error": "argumentos JSON inválidos"}
                errores += 1
            calls.append({"name": fn["name"], "args": args})
            msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                         "content": json.dumps(res, ensure_ascii=False)})
    return {"calls": calls, "final": final, "pasos": pasos, "wall_s": round(time.time() - t0, 3),
            "json_invalidos": errores}


def main():
    name, gguf = sys.argv[1], sys.argv[2]
    think = "--think" in sys.argv
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 42
    sampling = sampling_for(name)
    tag = f"tools-{name}" + ("" if seed == 42 else f".s{seed}")
    log = open(os.path.join(BASE, "results", f"{tag}.server.log"), "w")
    proc = subprocess.Popen([SERVER, "-m", gguf, "-t", "4", "-c", "8192", "--port", str(PORT),
                             "--jinja", "-np", "1", "--no-webui"],
                            stdout=log, stderr=subprocess.STDOUT)
    try:
        load_s = wait_ready(proc)
        rows = []
        for i, (cid, cat, hist, pet, verif) in enumerate(CASES):
            r = run_case(hist, pet, think, sampling, seed)
            r["checks"] = {k: bool(v) for k, v in verif(r["calls"], r["final"]).items()}
            r["ok"] = all(r["checks"].values())
            rows.append({"id": cid, "cat": cat, "q": pet, "frio": i == 0, **r})
        with open(os.path.join(BASE, "results", f"{tag}.jsonl"), "w") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps({"model": tag, "load_s": round(load_s, 1),
                          "ok": sum(r["ok"] for r in rows), "n": len(rows)}))
    finally:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    main()
