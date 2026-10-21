#!/usr/bin/env python3
"""
capture_dataset_hablantes.py — Captura del dataset del wake word "Hola NEO"

El modelo local SOLO detecta el wake word (clases hola_neo / desconocido /
silencio de tools/vocabulario.json). El script graba de dos formas:

  · hola_neo → MUESTRAS: una tecla = un clip de 1.5 s ("Hola NEO" una vez).
  · desconocido y silencio → LARGO: una tecla arranca una grabación continua
    de varios minutos; se habla (o se deja el ruido) sin tocar nada y al parar
    se trocea sola en clips de 1.5 s.

  Carpeta            Clase         Modo     Cuota (clips)   Qué grabar
  hola_neo           hola_neo      muestra  200/hablante    "Hola NEO" (h3, h4… sobre todo)
  neg_similares      desconocido   largo    120/hablante    leer en voz alta las palabras
                                                            parecidas que salen en pantalla
  neg_libre          desconocido   largo    120/hablante    hablar normal, leer, TV, charla
  neg_ambiente       silencio      largo    120 en total    ruido sin voz (ventilador…)

Cada grabación larga dura lo justo para completar la posición actual (20 clips
≈ 50 s); al terminar, el menú pide cambiar de distancia/orientación. --minutos
fuerza otra duración; cualquier tecla la detiene antes.

Las carpetas neg_* se asocian a su clase en vocabulario.json ("carpetas_extra")
y train_model.py las carga con esa etiqueta.

── Por qué el troceado va alineado a bloques ─────────────────────────────────
En modo continuo el firmware graba 1.5 s, los envía por la UART y vuelve a
grabar. Enviar 48 000 bytes a 921 600 baud tarda ~0.52 s y el buffer DMA del
micrófono solo guarda 128 ms (8 × 256 muestras): lo que se dice mientras se
envía se pierde. El WAV largo es, por tanto, una sucesión de bloques de 1.5 s
con huecos de ~0.5 s ENTRE ellos (inaudibles en el archivo: están pegados).
Una ventana que cruzara dos bloques mezclaría dos instantes distintos con un
"clic" en medio. Por eso cada clip = exactamente un bloque, que sí es audio
continuo de verdad, y del mismo tamaño que la ventana del modelo.

Archivos:
    dataset/largos/<carpeta>/h3_d100_frente_L002.wav (+ .json)   grabación larga
    dataset/<carpeta>/h3_d100_frente_L002_b017.wav                clip (bloque 17)
    dataset/hola_neo/h3_d100_lat90_0007.wav                        muestra suelta
    dataset/neg_ambiente/amb_ventilador_L001_b004.wav              (sin hablante)
dataset/largos/ no lo lee train_model.py; los clips sí.

Comandos:
    python tools/capture_dataset_hablantes.py --port COM3              # menú interactivo
    python tools/capture_dataset_hablantes.py --port COM3 largo neg_libre --hablante h3 --minutos 2
    python tools/capture_dataset_hablantes.py --port COM3 largo neg_ambiente --fuente ventilador
    python tools/capture_dataset_hablantes.py plan                     # qué falta
    python tools/capture_dataset_hablantes.py trocear                  # re-trocea todos los largos
    python tools/capture_dataset_hablantes.py --simular                # ensayo sin ESP32

Teclas del menú:
    [Enter]  Grabar (muestra en hola_neo · grabación larga en neg_*)
    [c] Carpeta   [h] Hablante   [d] Condición   [f] Fuente de ruido
    [u] Deshacer la última   [p] Plan   [q] Salir
    Durante una grabación larga: cualquier tecla la detiene.

Requiere el firmware de captura con START_CONT: pio run -e dataset_capture --target upload
"""

import argparse
import json
import random
import re
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Reutiliza utilidades y vocabulario del script de captura base.
from capture_dataset import (
    BAUD_RATE, CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH,
    FRASES, _vocab,
    getch, limpiar_pantalla, esperar_linea, leer_audio,
)

# ── Configuración de la sesión ────────────────────────────────────────────────
DISTANCIAS     = [("d050", "0.5 m"), ("d100", "1 m"), ("d200", "2 m")]
ORIENTACIONES  = [("frente", "de frente al micrófono"),
                  ("lat90",  "a 90° (lateral) del micrófono")]
CONDICIONES    = [(d, o) for d, _ in DISTANCIAS for o, _ in ORIENTACIONES]
_DIST_TXT      = dict(DISTANCIAS)
_ORI_TXT       = dict(ORIENTACIONES)

BLOQUE_MUESTRAS = SAMPLE_RATE * 3 // 2       # 1.5 s = ventana del modelo
SEG_POR_MUESTRA = 5.0     # modo muestra: cuenta atrás + 1.5 s + envío (estimado)
SEG_POR_BLOQUE  = 2.0     # modo largo: 1.5 s grabando + ~0.5 s enviando
MARGEN_FILTRO   = 1.25    # graba un 25 % más: parte de los bloques no tendrá voz
SEG_MINIMO_LARGO = 20     # duración mínima de una grabación larga (s)

# Filtro de voz al trocear (solo carpetas de habla): un bloque se descarta si
# ningún tramo de 256 muestras supera noise_floor × FACTOR, igual que el VAD
# del firmware (WAKE_FACTOR_INICIO). Así no se etiqueta silencio como "habla".
VAD_BLOQUE = 256
VAD_FACTOR = 4.0

# Palabras parecidas a "Hola NEO" (o a una mitad). Durante la grabación larga se
# muestran una a una, una por bloque. Incluye /l/ + vocal + nasal tipo "clima",
# la palabra que más dispara el modelo hoy.
FRASES_SIMILARES = (
    "Hola", "Hola, ¿qué tal?", "Hola a todos", "Hola, mamá", "Neo",
    "Hola Leo", "Hola Teo", "Hola Mateo", "Hola nene", "Hola Elena",
    "Hola Noemí", "Hola, ¿y eso?", "Ola", "Leonel", "Neón",
    "Museo", "Paseo", "Deseo", "Correo", "Video",
    "Trofeo", "Romeo", "Lo veo", "Creo que no", "Feo",
    "Clima", "Lima", "Limón", "Alarma", "Llama",
    "Elena", "Ahora no", "Hora", "Olé", "Bueno",
    "Colegio", "Lunes", "Hielo", "Ya llegó", "Oye",
)
# Habla normal. Se cambia de tema cada ~6 bloques (~12 s).
TEMAS_LIBRES = (
    "Cuenta qué hiciste hoy",
    "Lee en voz alta un texto o una noticia",
    "Describe la habitación en la que estás",
    "Pide cosas a NEO SIN decir 'Hola NEO': el clima, las noticias, el dólar…",
    "Cuenta del 1 al 40 y di los días de la semana",
    "Habla como si estuvieras al teléfono",
    "Conversa con otra persona (las dos voces cuentan)",
    "Pon la TV o la radio con gente hablando cerca del micro",
    "Di nombres de personas, calles y ciudades",
    "Ríete, tose, carraspea, silba",
)
BLOQUES_POR_TEMA = 6
# Ruido SIN voz cercana (la voz va en neg_libre). Una fuente por grabación.
FUENTES_AMBIENTE = (
    "silencio", "ventilador", "musica_instrumental", "platos_cocina",
    "teclado", "pasos_puerta", "calle_trafico", "agua_grifo", "palmas", "objetos_mesa",
)


@dataclass
class Carpeta:
    nombre: str          # subcarpeta de dataset/
    clase: str           # clase del vocabulario (etiqueta en train_model)
    largo: bool          # True → grabación continua troceada; False → muestra suelta
    cuota: int           # clips por hablante (o total si por_hablante=False)
    por_hablante: bool = True
    voz: bool = True     # filtrar bloques sin voz al trocear
    ayuda: str = ""


def _carpetas() -> list:
    extra = {n: c["nombre"] for c in _vocab["clases"] for n in c.get("carpetas_extra", [])}
    for n in ("neg_similares", "neg_libre", "neg_ambiente"):
        if n not in extra:
            sys.exit(f"ERROR: '{n}' no está en carpetas_extra de vocabulario.json")
    positivo = next(c["nombre"] for c in _vocab["clases"] if c.get("comando"))
    return [
        Carpeta(positivo, positivo, False, 200,
                ayuda="Di «Hola NEO» una vez, natural. Varía volumen y entonación."),
        Carpeta("neg_similares", extra["neg_similares"], True, 120,
                ayuda="Lee en voz alta cada palabra que aparezca, sin prisa."),
        Carpeta("neg_libre", extra["neg_libre"], True, 120,
                ayuda="Habla con naturalidad sobre el tema; puedes cambiar de tema."),
        Carpeta("neg_ambiente", extra["neg_ambiente"], True, 120, por_hablante=False, voz=False,
                ayuda="Que NADIE hable cerca. Mantén el ruido indicado todo el rato."),
    ]


CARPETAS = _carpetas()
POR_NOMBRE = {c.nombre: c for c in CARPETAS}


def cuota_condicion(carpeta: Carpeta, idx_cond: int) -> int:
    """Reparte la cuota del hablante entre las condiciones; el resto, a las primeras."""
    base, resto = divmod(carpeta.cuota, len(CONDICIONES))
    return base + (1 if idx_cond < resto else 0)


# ── Archivos y conteos ────────────────────────────────────────────────────────

def pref_cond(hablante: str, cond: tuple) -> str:
    return f"{hablante}_{cond[0]}_{cond[1]}"


def contar(dataset: Path, carpeta: Carpeta, patron: str) -> int:
    return len(list((dataset / carpeta.nombre).glob(patron)))


def contar_cond(dataset: Path, carpeta: Carpeta, hablante: str, cond: tuple) -> int:
    return contar(dataset, carpeta, f"{pref_cond(hablante, cond)}_*.wav")


def contar_hablante(dataset: Path, carpeta: Carpeta, hablante: str) -> int:
    if not carpeta.por_hablante:
        return contar(dataset, carpeta, "amb_*.wav")
    return contar(dataset, carpeta, f"{hablante}_*.wav")


def guardar_wav(ruta: Path, pcm: bytes):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ruta), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)


def siguiente_indice(directorio: Path, pref: str, patron_idx: str) -> int:
    """Máximo índice existente + 1 (evita colisiones tras borrar)."""
    rx = re.compile(rf"^{re.escape(pref)}_{patron_idx}$")
    idx = [int(m.group(1)) for f in directorio.glob(f"{pref}_*") if (m := rx.match(f.name))]
    return max(idx, default=0) + 1


def dir_largos(dataset: Path, carpeta: Carpeta) -> Path:
    return dataset / "largos" / carpeta.nombre


# ── Troceado ──────────────────────────────────────────────────────────────────

def bloques_con_voz(bloques: np.ndarray) -> np.ndarray:
    """Máscara de bloques que contienen voz. El noise floor se estima con toda la
    grabación (percentil 20 del RMS por tramo), así un bloque entero de voz no
    se compara consigo mismo."""
    x = bloques.astype(np.float64) / 32768.0
    tramos = x[:, : (x.shape[1] // VAD_BLOQUE) * VAD_BLOQUE].reshape(len(x), -1, VAD_BLOQUE)
    rms = np.sqrt((tramos ** 2).mean(axis=2))              # (bloques, tramos)
    ruido = max(float(np.percentile(rms, 20)), 1e-6)
    return (rms > ruido * VAD_FACTOR).any(axis=1)


def trocear(dataset: Path, carpeta: Carpeta, ruta_largo: Path) -> tuple:
    """Corta un WAV largo en clips de un bloque. Idempotente: borra antes los
    clips previos de esa grabación. Devuelve (guardados, descartados_sin_voz)."""
    meta_ruta = ruta_largo.with_suffix(".json")
    meta = json.loads(meta_ruta.read_text(encoding="utf-8")) if meta_ruta.exists() else {}
    n_bloque = int(meta.get("muestras_bloque", BLOQUE_MUESTRAS))
    with wave.open(str(ruta_largo), "rb") as wf:
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    n = len(pcm) // n_bloque
    for viejo in (dataset / carpeta.nombre).glob(f"{ruta_largo.stem}_b*.wav"):
        viejo.unlink()
    if n == 0:
        return 0, 0
    bloques = pcm[: n * n_bloque].reshape(n, n_bloque)
    con_voz = bloques_con_voz(bloques) if carpeta.voz else np.ones(n, bool)
    for i in np.where(con_voz)[0]:
        guardar_wav(dataset / carpeta.nombre / f"{ruta_largo.stem}_b{i + 1:03d}.wav",
                    bloques[i].tobytes())
    return int(con_voz.sum()), int(n - con_voz.sum())


def trocear_todo(dataset: Path):
    print("\n  Troceando grabaciones largas (un clip por bloque de 1.5 s):")
    for c in [c for c in CARPETAS if c.largo]:
        largos = sorted(dir_largos(dataset, c).glob("*.wav"))
        g = d = 0
        for r in largos:
            gi, di = trocear(dataset, c, r)
            g, d = g + gi, d + di
        print(f"    {c.nombre:<14} {len(largos):>3} grabaciones → {g:>4} clips"
              + (f"  ({d} bloques sin voz descartados)" if d else ""))


# ── Comunicación con ESP32 ────────────────────────────────────────────────────

def kbhit() -> bool:
    """¿Hay una tecla pulsada? (sin bloquear)."""
    try:
        import msvcrt
        return msvcrt.kbhit()
    except ImportError:
        import select
        return bool(select.select([sys.stdin], [], [], 0)[0])


def vaciar_teclado():
    try:
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getch()
    except ImportError:
        pass


def leer_exacto(ser, n: int, timeout: float) -> bytes:
    """Lee exactamente n bytes del serial (sin barra de progreso)."""
    limite = time.time() + timeout
    buf = bytearray()
    while len(buf) < n:
        if time.time() > limite:
            raise TimeoutError(f"Timeout leyendo audio ({len(buf)}/{n} bytes)")
        buf.extend(ser.read(min(n - len(buf), max(1, ser.in_waiting))))
    return bytes(buf)


def capturar_muestra(ser, clase: str) -> bytes:
    """RECORD:{clase} → 1.5 s de PCM. Con ser=None (--simular) devuelve ruido."""
    if ser is None:
        time.sleep(1.5)
        return (np.random.randn(BLOQUE_MUESTRAS) * 300).astype(np.int16).tobytes()
    ser.reset_input_buffer()
    ser.write(f"RECORD:{clase}\n".encode())
    ser.flush()
    esperar_linea(ser, "RECORDING:", timeout=4.0)
    n_bytes = int(esperar_linea(ser, "START_AUDIO:", timeout=4.0).split(":")[1])
    pcm = leer_audio(ser, n_bytes, timeout=15.0)
    esperar_linea(ser, "END_AUDIO", timeout=4.0)
    return pcm


def _bloque_simulado(i: int) -> bytes:
    """Ruido de fondo y, en 2 de cada 3 bloques, una "palabra" (tono modulado)."""
    x = np.random.randn(BLOQUE_MUESTRAS) * 60
    if i % 3:
        t = np.arange(8000) / SAMPLE_RATE
        ini = random.randint(0, BLOQUE_MUESTRAS - 8000)
        x[ini:ini + 8000] += 4000 * np.sin(2 * np.pi * 220 * t) * np.hanning(8000)
    return x.astype(np.int16).tobytes()


def grabar_largo(ser, minutos: float, al_recibir) -> list:
    """
    Grabación continua: START_CONT → bloques crudos de BLOCK_SIZE bytes → ESC.
    `al_recibir(n_bloques, segundos)` se llama tras cada bloque (refresca la
    pantalla). Para con cualquier tecla o al llegar a `minutos`.

    Tras el ESC el firmware termina el bloque que está grabando, lo envía y
    escribe END_CONT. Por eso, tras parar, se lee "bloque o END_CONT" hasta ver
    el marcador: así no se pierde el último bloque ni se cuela texto en el audio.
    """
    bloques, t0 = [], time.time()
    if ser is None:                                           # --simular
        while True:
            time.sleep(0.15)
            bloques.append(_bloque_simulado(len(bloques)))
            al_recibir(len(bloques), time.time() - t0)
            if kbhit() or len(bloques) * SEG_POR_BLOQUE >= minutos * 60:
                vaciar_teclado()
                return bloques

    ser.reset_input_buffer()
    ser.write(b"START_CONT\n")
    ser.flush()
    try:
        esperar_linea(ser, "START_AUDIO:", timeout=4.0)
        n_bytes = int(esperar_linea(ser, "BLOCK_SIZE:", timeout=4.0).split(":")[1])
    except TimeoutError:
        raise RuntimeError("el firmware no responde a START_CONT. Flashea la versión "
                           "actual: pio run -e dataset_capture --target upload")
    try:
        while True:
            bloques.append(leer_exacto(ser, n_bytes, timeout=10.0))
            al_recibir(len(bloques), time.time() - t0)
            if kbhit() or time.time() - t0 >= minutos * 60:
                vaciar_teclado()
                break
    finally:
        ser.write(b"\x1b")                                    # ESC: parar
        ser.flush()
    marca = b"END_CONT"
    try:
        while True:
            cab = leer_exacto(ser, len(marca), timeout=6.0)
            if cab == marca:
                break
            bloques.append(cab + leer_exacto(ser, n_bytes - len(marca), timeout=6.0))
    except TimeoutError:
        print("\n  (no llegó END_CONT; se guarda lo recibido)")
    return bloques


# ── Interfaz ──────────────────────────────────────────────────────────────────

def primera_incompleta(dataset: Path, carpeta: Carpeta, hablante: str, desde: int = 0) -> int:
    """Primera condición con cuota sin cubrir (desde `desde`, circular)."""
    if not carpeta.por_hablante:
        return 0
    n = len(CONDICIONES)
    for k in range(n):
        i = (desde + k) % n
        if contar_cond(dataset, carpeta, hablante, CONDICIONES[i]) < cuota_condicion(carpeta, i):
            return i
    return desde % n


def fuente_menos_grabada(dataset: Path) -> str:
    c = POR_NOMBRE["neg_ambiente"]
    return min(FUENTES_AMBIENTE, key=lambda f: contar(dataset, c, f"amb_{f}_*.wav"))


def minutos_auto(dataset: Path, carpeta: Carpeta, hablante: str, cond: tuple,
                 fuente: str) -> float:
    """Lo justo para completar la posición (o la fuente de ruido) actual, con
    margen para los bloques sin voz que se descartan al trocear."""
    if carpeta.por_hablante:
        i = CONDICIONES.index(cond)
        falta = cuota_condicion(carpeta, i) - contar_cond(dataset, carpeta, hablante, cond)
    else:
        por_fuente = -(-carpeta.cuota // len(FUENTES_AMBIENTE))       # techo
        falta = por_fuente - contar(dataset, carpeta, f"amb_{fuente}_*.wav")
    seg = max(falta, 0) * SEG_POR_BLOQUE * (MARGEN_FILTRO if carpeta.voz else 1.0)
    return max(seg, SEG_MINIMO_LARGO) / 60


def faltan(dataset: Path, carpeta: Carpeta, hablantes: list) -> dict:
    if not carpeta.por_hablante:
        return {"total": max(0, carpeta.cuota - contar_hablante(dataset, carpeta, ""))}
    return {h: max(0, carpeta.cuota - contar_hablante(dataset, carpeta, h)) for h in hablantes}


def mostrar_plan(dataset: Path, hablantes: list):
    print("\n  Plan (en este orden):")
    total_min = 0.0
    for i, c in enumerate(CARPETAS, 1):
        f = faltan(dataset, c, hablantes)
        resto = sum(f.values())
        mins = resto * (SEG_POR_BLOQUE if c.largo else SEG_POR_MUESTRA) / 60
        total_min += mins
        detalle = "  ".join(f"{h}:{n}" for h, n in f.items() if n) or "completo ✓"
        modo = "largo  " if c.largo else "muestra"
        cuota = f"{c.cuota}/hablante" if c.por_hablante else f"{c.cuota} total"
        print(f"   {i}. {c.nombre:<14}[{c.clase:<11}] {modo} {cuota:<12} faltan {resto:>4}"
              f" ≈ {mins:4.0f} min  ({detalle})")
    print(f"   Total ≈ {total_min:.0f} min de grabación"
          " (en neg_* los bloques sin voz se descartan: graba algo más).")
    print("   Consejo: cada hablante nuevo (h3, h4…) vale más que muchas muestras de h1/h2.")


def mostrar_menu(dataset: Path, hablantes: list, hablante: str, carpeta: Carpeta,
                 idx_cond: int, fuente: str, minutos: float):
    cond = CONDICIONES[idx_cond]
    limpiar_pantalla()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║          NEO — Captura del dataset del wake word             ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print("\n  Carpetas:  ", end="")
    for c in CARPETAS:
        marca = "►" if c is carpeta else " "
        print(f"{marca}{c.nombre}", end="   ")
    if carpeta.largo:
        seg = 60 * (minutos or minutos_auto(dataset, carpeta, hablante, cond, fuente))
        modo = f"GRABACIÓN LARGA de {seg:.0f} s, se trocea en clips de 1.5 s"
    else:
        modo = "una muestra de 1.5 s por tecla"
    print(f"\n\n  dataset/{carpeta.nombre}/ → clase {carpeta.clase} · {modo}")

    if carpeta.por_hablante:
        print("  Hablantes:  ", end="")
        for h in hablantes:
            marca = "►" if h == hablante else " "
            print(f"{marca}{h}: {contar_hablante(dataset, carpeta, h)}/{carpeta.cuota}  ", end="")
        print(f"\n\n  Clips de {hablante} por posición:")
        print(f"    {'':>8}" + "".join(f"{o:>14}" for o, _ in ORIENTACIONES))
        for d, d_txt in DISTANCIAS:
            fila = f"    {d_txt:>8}"
            for o, _ in ORIENTACIONES:
                i = CONDICIONES.index((d, o))
                n = contar_cond(dataset, carpeta, hablante, (d, o))
                q = cuota_condicion(carpeta, i)
                fila += f"{f'{n}/{q}':>11} {'✓' if n >= q else ' '}{'◄' if i == idx_cond else ' '}"
            print(fila)
        print(f"\n  ▶ {hablante} · {_DIST_TXT[cond[0]]} · {_ORI_TXT[cond[1]]}")
    else:
        print(f"  Clips: {contar_hablante(dataset, carpeta, '')}/{carpeta.cuota}   "
              f"(micrófono en su sitio habitual)")
        print(f"\n  ▶ Fuente de ruido: «{fuente}»  ([f] para cambiarla)")
    print(f"    {carpeta.ayuda}")
    print("\n  [Enter] Grabar · [c] Carpeta · [h] Hablante · [d] Condición · [f] Fuente\n"
          "  [u] Deshacer · [p] Plan · [q] Salir")


def pantalla_largo(carpeta: Carpeta, rotulo: str, minutos: float, guia: list):
    """Devuelve el callback que refresca la pantalla en cada bloque recibido."""
    def refrescar(n: int, seg: float):
        limpiar_pantalla()
        print(f"\n  ● GRABANDO  {rotulo}")
        print(f"    {int(seg) // 60}:{int(seg) % 60:02d} / {int(minutos * 60) // 60}:"
              f"{int(minutos * 60) % 60:02d}   bloques: {n}   (≈{n} clips antes del filtro)")
        print("\n    CUALQUIER TECLA = PARAR\n")
        if carpeta.nombre == "neg_similares":
            print(f"    Di:  «{guia[n % len(guia)]}»")
            print(f"    luego: {guia[(n + 1) % len(guia)]}")
        elif carpeta.nombre == "neg_libre":
            print(f"    Tema: {guia[(n // BLOQUES_POR_TEMA) % len(guia)]}")
        else:
            print(f"    Ruido: {rotulo.split('·')[-1].strip()} — que nadie hable cerca")
    return refrescar


def sesion_larga(ser, dataset: Path, carpeta: Carpeta, hablante: str, cond: tuple,
                 fuente: str, minutos=None) -> Path:
    """Graba y guarda el WAV largo + .json en dataset/largos/ (luego: trocear).
    minutos=None → la duración que falta para completar la posición actual."""
    minutos = minutos or minutos_auto(dataset, carpeta, hablante, cond, fuente)
    if carpeta.por_hablante:
        pref, rotulo = pref_cond(hablante, cond), f"{carpeta.nombre} · {hablante} · " \
                       f"{_DIST_TXT[cond[0]]} · {_ORI_TXT[cond[1]]}"
    else:
        pref, rotulo = f"amb_{fuente}", f"{carpeta.nombre} · {fuente}"
    guia = list(FRASES_SIMILARES if carpeta.nombre == "neg_similares" else TEMAS_LIBRES)
    random.shuffle(guia)

    print(f"\n  → {rotulo}\n    {carpeta.ayuda}")
    for rest in (3, 2, 1):
        print(f"    Empieza en {rest}...", end="\r", flush=True)
        time.sleep(0.6)
    bloques = grabar_largo(ser, minutos, pantalla_largo(carpeta, rotulo, minutos, guia))
    if not bloques:
        raise RuntimeError("no se recibió ningún bloque")

    d = dir_largos(dataset, carpeta)
    d.mkdir(parents=True, exist_ok=True)
    idx = siguiente_indice(d, pref, r"L(\d+)\.wav")
    ruta = d / f"{pref}_L{idx:03d}.wav"
    guardar_wav(ruta, b"".join(bloques))
    meta = {"carpeta": carpeta.nombre, "clase": carpeta.clase,
            "hablante": hablante if carpeta.por_hablante else None,
            "condicion": "_".join(cond) if carpeta.por_hablante else None,
            "fuente": None if carpeta.por_hablante else fuente,
            "muestras_bloque": len(bloques[0]) // SAMPLE_WIDTH, "bloques": len(bloques),
            "fecha": time.strftime("%Y-%m-%d %H:%M"),
            "nota": "bloques contiguos con huecos de ~0.5 s ENTRE ellos (envío UART); "
                    "trocear alineado a bloques"}
    ruta.with_suffix(".json").write_text(json.dumps(meta, indent=1, ensure_ascii=False),
                                         encoding="utf-8")
    return ruta


def borrar_largo(dataset: Path, carpeta: Carpeta, ruta: Path):
    for clip in (dataset / carpeta.nombre).glob(f"{ruta.stem}_b*.wav"):
        clip.unlink()
    ruta.unlink(missing_ok=True)
    ruta.with_suffix(".json").unlink(missing_ok=True)


def elegir(titulo: str, opciones: list) -> int:
    """Menú numérico de una tecla. Devuelve el índice elegido o -1 si se cancela."""
    teclas = "123456789abcdefghij"[:len(opciones)]
    print(f"\n  {titulo}")
    for t, o in zip(teclas, opciones):
        print(f"    [{t}] {o}")
    print("    [Esc] cancelar")
    while True:
        k = getch()
        if k == "\x1b":
            return -1
        if k and k in teclas:
            return teclas.index(k)


def abrir_serial(port: str, baud: int):
    import serial
    print(f"Conectando a {port} @ {baud} baud...")
    try:
        # dsrdtr/rtscts desactivados: evita resets involuntarios del ESP32.
        ser = serial.Serial(port, baud, timeout=1, dsrdtr=False, rtscts=False)
    except serial.SerialException as e:
        sys.exit(f"Error al abrir puerto: {e}")
    print("Esperando boot del ESP32 (3s)...")
    time.sleep(3)
    ser.reset_input_buffer()
    ser.write(b"STATUS\n")
    ser.flush()
    try:
        print(f"  Firmware OK: {esperar_linea(ser, 'STATUS:', timeout=3.0)}")
    except TimeoutError:
        # Sin STATUS no funcionará ni RECORD ni START_CONT: mejor parar aquí.
        ser.close()
        sys.exit("  ERROR: la placa no responde a STATUS en este puerto.\n"
                 "    1) Desconecta y reconecta el USB y vuelve a intentarlo.\n"
                 "    2) Si sigue igual, flashea y comprueba que termine en 'Hash of data verified':\n"
                 f"       pio run -e dataset_capture --target upload --upload-port {port}\n"
                 "       Si dice 'Failed to connect': mantén BOOT, pulsa RST, suelta BOOT y repite.")
    return ser


def menu(ser, dataset: Path, hablantes: list, minutos: float, simular: bool):
    carpeta  = CARPETAS[0]
    hablante = hablantes[0]
    idx_cond = primera_incompleta(dataset, carpeta, hablante)
    fuente   = fuente_menos_grabada(dataset)
    ultimas  = []                     # (carpeta, ruta, es_largo) para [u]
    aviso    = "MODO SIMULADO: no hay ESP32, se guarda audio sintético." if simular else ""

    while True:
        mostrar_menu(dataset, hablantes, hablante, carpeta, idx_cond, fuente, minutos)
        if aviso:
            print(f"\n  {aviso}")
            aviso = ""
        key = getch()

        if key in ("q", "\x03"):
            return

        elif key in ("\r", "\n", " "):
            cond = CONDICIONES[idx_cond]
            try:
                if carpeta.largo:
                    ruta = sesion_larga(ser, dataset, carpeta, hablante, cond, fuente, minutos)
                    g, d = trocear(dataset, carpeta, ruta)
                    ultimas.append((carpeta, ruta, True))
                    aviso = (f"✓ {ruta.name}: {g} clips en {carpeta.nombre}/"
                             + (f" ({d} bloques sin voz descartados)" if d else ""))
                    if not carpeta.por_hablante:
                        fuente = fuente_menos_grabada(dataset)
                else:
                    print(f"\n  → Prepara: «{FRASES[carpeta.clase]}»")
                    for rest in (3, 2, 1):
                        print(f"    {rest}...", end="\r", flush=True)
                        time.sleep(0.4)
                    print("    ¡Ahora!         ")
                    pcm = capturar_muestra(ser, carpeta.clase)
                    pref = pref_cond(hablante, cond)
                    d = dataset / carpeta.nombre
                    idx = siguiente_indice(d, pref, r"(\d+)\.wav")
                    ruta = d / f"{pref}_{idx:04d}.wav"
                    guardar_wav(ruta, pcm)
                    ultimas.append((carpeta, ruta, False))
                    aviso = f"✓ Guardado: {carpeta.nombre}/{ruta.name}"
                if carpeta.por_hablante and \
                        contar_cond(dataset, carpeta, hablante, cond) >= cuota_condicion(carpeta, idx_cond):
                    nuevo = primera_incompleta(dataset, carpeta, hablante, idx_cond + 1)
                    if nuevo != idx_cond:
                        idx_cond = nuevo
                        c = CONDICIONES[idx_cond]
                        aviso += (f"\n  ✓ Posición completa. CAMBIA A → "
                                  f"{_DIST_TXT[c[0]]}, {_ORI_TXT[c[1]]}")
                    else:
                        aviso += f"\n  ✓ {hablante} completó {carpeta.nombre}."
            except Exception as e:      # TimeoutError, SerialException, RuntimeError…
                aviso = f"✗ Error: {e}"
                if ser is not None:
                    ser.reset_input_buffer()

        elif key == "u":
            if ultimas:
                c, ruta, es_largo = ultimas.pop()
                if es_largo:
                    borrar_largo(dataset, c, ruta)
                else:
                    ruta.unlink(missing_ok=True)
                aviso = f"Borrada: {ruta.name}" + (" y sus clips" if es_largo else "")
            else:
                aviso = "Nada que deshacer en esta sesión."

        elif key == "p":
            limpiar_pantalla()
            mostrar_plan(dataset, hablantes)
            print("\n  Pulsa una tecla para volver...")
            getch()

        elif key == "c":
            i = elegir("Carpeta:", [f"{c.nombre:<14} → {c.clase:<11} "
                                    f"({'grabación larga' if c.largo else 'muestras sueltas'})"
                                    for c in CARPETAS])
            if i >= 0:
                carpeta  = CARPETAS[i]
                idx_cond = primera_incompleta(dataset, carpeta, hablante)

        elif key == "h":
            i = elegir("Hablante:", hablantes)
            if i >= 0:
                hablante = hablantes[i]
                idx_cond = primera_incompleta(dataset, carpeta, hablante)

        elif key == "d":
            if carpeta.por_hablante:
                i = elegir("Posición:", [f"{_DIST_TXT[d]} · {_ORI_TXT[o]}" for d, o in CONDICIONES])
                if i >= 0:
                    idx_cond = i
            else:
                aviso = "neg_ambiente no usa distancia/orientación."

        elif key == "f":
            i = elegir("Fuente de ruido (neg_ambiente):", list(FUENTES_AMBIENTE))
            if i >= 0:
                fuente = FUENTES_AMBIENTE[i]


def main():
    parser = argparse.ArgumentParser(
        description="NEO — captura del dataset del wake word",
        epilog="Ejemplos:  --port COM3   ·   --port COM3 largo neg_libre --hablante h3   ·   plan")
    parser.add_argument("accion", nargs="?", default="menu",
                        choices=("menu", "largo", "plan", "trocear"),
                        help="menu (defecto) · largo: una grabación larga y sale · "
                             "plan: qué falta · trocear: re-trocea dataset/largos/")
    parser.add_argument("carpeta", nargs="?", choices=[c.nombre for c in CARPETAS if c.largo],
                        help="Para 'largo': neg_similares | neg_libre | neg_ambiente")
    parser.add_argument("--port", help="Puerto serial (ej: COM3  o  /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=BAUD_RATE,
                        help=f"Baud rate (default: {BAUD_RATE})")
    parser.add_argument("--dir", default=None,
                        help="Directorio del dataset (default: dataset, o dataset_simulado con --simular)")
    parser.add_argument("--hablantes", type=int, default=4,
                        help="Número de hablantes h1..hN (default: 4, máx. 9)")
    parser.add_argument("--hablante", default="h1", help="Para 'largo' (default: h1)")
    parser.add_argument("--cond", default=None,
                        help="Para 'largo': d050_frente, d100_lat90… (default: la primera incompleta)")
    parser.add_argument("--fuente", default=None, choices=FUENTES_AMBIENTE,
                        help="Para 'largo neg_ambiente' (default: la menos grabada)")
    parser.add_argument("--minutos", type=float, default=None,
                        help="Duración de cada grabación larga (default: lo que falta para "
                             "completar la posición actual, mín. 20 s)")
    parser.add_argument("--simular", action="store_true",
                        help="Sin ESP32: audio sintético para ensayar la sesión")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(errors="replace")   # consola cp1252 en Windows
    except AttributeError:
        pass
    if not 1 <= args.hablantes <= 9:
        parser.error("--hablantes debe estar entre 1 y 9")
    hablantes = [f"h{i}" for i in range(1, args.hablantes + 1)]
    dataset = Path(args.dir or ("dataset_simulado" if args.simular else "dataset"))
    for c in CARPETAS:
        (dataset / c.nombre).mkdir(parents=True, exist_ok=True)

    if args.accion == "plan":
        mostrar_plan(dataset, hablantes)
        return
    if args.accion == "trocear":
        trocear_todo(dataset)
        mostrar_plan(dataset, hablantes)
        return
    if args.accion == "largo":
        if not args.carpeta:
            parser.error("largo necesita la carpeta: neg_similares | neg_libre | neg_ambiente")
        if not re.fullmatch(r"h\d", args.hablante):
            parser.error("--hablante debe ser h1..h9")
        if args.cond and args.cond not in ["_".join(c) for c in CONDICIONES]:
            parser.error("--cond: " + ", ".join("_".join(c) for c in CONDICIONES))
    if not args.simular and not args.port:
        parser.error("--port es obligatorio (o usa --simular)")

    ser = None if args.simular else abrir_serial(args.port, args.baud)
    try:
        if args.accion == "largo":
            carpeta = POR_NOMBRE[args.carpeta]
            cond = (tuple(args.cond.split("_")) if args.cond else
                    CONDICIONES[primera_incompleta(dataset, carpeta, args.hablante)])
            ruta = sesion_larga(ser, dataset, carpeta, args.hablante, cond,
                                args.fuente or fuente_menos_grabada(dataset), args.minutos)
            g, d = trocear(dataset, carpeta, ruta)
            print(f"\n  ✓ {ruta}\n    {g} clips en dataset/{carpeta.nombre}/"
                  + (f" ({d} bloques sin voz descartados)" if d else ""))
        else:
            menu(ser, dataset, hablantes, args.minutos, args.simular)
    except KeyboardInterrupt:
        print("\n\nInterrumpido por el usuario.")
    finally:
        if ser is not None:
            ser.close()
    mostrar_plan(dataset, hablantes)
    print(f"\n  Dataset: {dataset.resolve()}")


if __name__ == "__main__":
    main()
