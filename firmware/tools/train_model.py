#!/usr/bin/env python3
"""
train_model.py — Entrena el modelo de comandos de voz locales de NEO

Las clases provienen de tools/vocabulario.json (fuente única de verdad
compartida con el firmware de captura y la inferencia en ESP32).

Pipeline:
  1. Carga WAVs del dataset (una subcarpeta por clase)
  2. Extrae características MFCC con tensorflow.signal
  3. Aplica data augmentation (ruido, shift temporal, volumen, SpecAugment)
  4. Entrena una CNN pequeña (<40 KB en int8)
  5. Evalúa float e int8 (accuracy, matriz de confusión, calibración)
  6. Calcula el umbral del wake word (FPR objetivo o Youden)
  7. Exporta modelo_float.tflite, modelo_int8.tflite, umbrales.json,
     entrenamiento.png, entrenamiento_log.txt y metricas.json

Modos:
    python tools/train_model.py --output models/experimentos/X     # split único
    python tools/train_model.py --cv 5 --output ...                 # CV estratificada
    python tools/train_model.py --leave-speaker-out --output ...    # por locutor
    python tools/train_model.py --leave-speaker-out --por-distancia --output ...  # por distancia

Modelo desplegado (2026-10-20, ver models/experimentos/2026-10-20/RESUMEN.md):
    python tools/train_model.py --neg-entrenar clima,cripto,dado --neg-peso base
    python tools/train_model.py --solo-evaluar models --output ...  # evalúa .tflite ya exportados
    python tools/train_model.py --cv 5 --neg-entrenar cripto,dado,el_toque,noticias --output ...
                                         # habla real como desconocido (leave-one-word-out)

Uso:
    cd firmware/
    python tools/train_model.py
    python tools/train_model.py --dataset ruta/dataset --epocas 50

Tras entrenar, regenerar el header del firmware:
    python tools/gen_vocabulario.py --umbrales models/umbrales.json
"""

import argparse
import json
import os
import random
import re
import sys
import wave
import numpy as np
import tensorflow as tf
from datetime import datetime
from pathlib import Path
from scipy.stats import beta
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import (confusion_matrix, classification_report,
                             roc_curve, log_loss)
from sklearn.utils.class_weight import compute_class_weight
import matplotlib
matplotlib.use("Agg")   # sin ventana gráfica; guarda PNG
import matplotlib.pyplot as plt

# ── Configuración ─────────────────────────────────────────────────────────────
VOCAB_RUTA = Path(__file__).resolve().parent / "vocabulario.json"
_vocab     = json.loads(VOCAB_RUTA.read_text(encoding="utf-8"))
CLASES     = [c["nombre"] for c in _vocab["clases"]]
# Clases que son comandos accionables (vs. desconocido/silencio, que no se despachan)
ES_COMANDO = {c["nombre"]: c.get("comando") is not None for c in _vocab["clases"]}
# Subcarpetas de dataset/ que se cargan con la etiqueta de una clase (las graba
# tools/capture_dataset_hablantes.py: neg_similares, neg_libre → desconocido,
# neg_ambiente → silencio). Forman parte de la clase: entran en train/val/test.
CARPETAS_EXTRA = {c["nombre"]: c.get("carpetas_extra", []) for c in _vocab["clases"]}
SR     = 16000   # Hz — debe coincidir con el firmware de captura

# Parámetros MFCC — deben ser idénticos a la implementación C++ en el ESP32
FRAME_LENGTH = 400    # 25 ms a 16 kHz
FRAME_STEP   = 160    # 10 ms a 16 kHz  → stride de inferencia en el ESP32
FFT_LENGTH   = 512    # potencia de 2 >= FRAME_LENGTH; tf.signal.stft usa esta por defecto
NUM_SPEC_BINS = FFT_LENGTH // 2 + 1  # 257 bins de frecuencia
NUM_MEL_BINS = 40
NUM_MFCC     = 40
C0_PISO      = -40.0  # piso de c0 relativo al frame más fuerte (ver normalizar_c0)
FREQ_MIN     = 20.0   # Hz
FREQ_MAX     = 8000.0 # Hz

# Parámetros del VAD — deben coincidir con main.cpp / microphone.h del firmware.
# Se usan para alinear el audio de entrenamiento al onset de voz igual que la
# captura en inferencia (evita el desajuste posición-en-la-ventana).
VAD_BLOCK        = 256    # Microphone::BLOCK_SIZE
VAD_FACTOR_INICIO = 4.0   # WAKE_FACTOR_INICIO en main.cpp (rms > noise × factor)

# Longitud fija = ventana del modelo en el firmware (MFCC_AUDIO_SAMPLES).
LONGITUD = SR * 3 // 2   # 24000 muestras = 1.5 s

# Modo de desplazamiento temporal en augmentation (ver desplazar()):
#   roll    → np.roll ±150 ms (±300 ms en desconocido). Comportamiento original:
#             tras recortar_a_onset() saca la palabra de la muestra 0 y envuelve
#             la cola al inicio (desajuste con el firmware).
#   pequeno → sin wraparound; hola_neo solo ±SHIFT_PEQUENO (incertidumbre real
#             del onset del VAD); negativos con sus magnitudes originales.
#   ninguno → hola_neo sin variantes de shift; negativos como en "pequeno".
SHIFT_MODOS   = ("roll", "pequeno", "ninguno")
SHIFT_PEQUENO = 2 * VAD_BLOCK   # 32 ms: el VAD del firmware descarta el bloque
                                # que dispara y su noise floor es un EMA, así
                                # que el onset real varía ±1-2 bloques.
_shift_modo   = "pequeno"
_velocidades  = ()      # factores de speed perturbation (--velocidad)
_cmn          = True    # normalización cepstral de c1.. por clip (--sin-cmn la quita)

# Negativos externos: frases de las clases antiguas del modelo multi-comando
# ("Clima", "Cripto"...). Nunca se entrena con ellas; solo sirven para calibrar
# el umbral (NEG_CAL) y para medir falsos positivos en datos no vistos (NEG_EVAL).
NEG_CAL  = ("clima", "cripto", "dado")
NEG_EVAL = ("el_toque", "noticias")
NEG_PALABRAS = NEG_CAL + NEG_EVAL

# Con --neg-entrenar, estas palabras se añaden como "desconocido" SOLO al train
# de cada split (el val/test del vocabulario no cambia, así los folds de CV son
# idénticos a los de un experimento sin la opción). Las palabras no entrenadas
# pasan a ser los negativos externos de evaluación y no se calibra con externos.
_neg_entrenar = ()

# Umbrales fijos del desglose de falsos positivos por palabra
UMBRALES_PALABRA = (0.5706, 0.70, 0.80, 0.90)

IDX_POS = next(i for i, c in enumerate(CLASES) if ES_COMANDO.get(c))   # hola_neo


# ── Log a texto ───────────────────────────────────────────────────────────────

class Log:
    """Imprime y acumula las líneas para volcarlas a un .txt al final."""
    def __init__(self):
        self.lineas = []

    def __call__(self, s: str = ""):
        print(s)
        self.lineas.append(s)

    def guardar(self, ruta: Path):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("\n".join(self.lineas) + "\n", encoding="utf-8")


def fijar_semillas(seed: int):
    """Semillas de python, numpy y TF + ops deterministas (reproducibilidad)."""
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    tf.random.set_seed(seed)
    tf.keras.utils.set_random_seed(seed)
    try:
        tf.config.experimental.enable_op_determinism()
    except Exception:
        pass


# ── Carga de audio ────────────────────────────────────────────────────────────

def cargar_wav(ruta: Path) -> np.ndarray:
    """Lee un WAV mono 16-bit y devuelve float32 en [-1, 1]."""
    with wave.open(str(ruta), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
    audio /= 32768.0
    return audio


def ajustar_longitud(audio: np.ndarray, n: int) -> np.ndarray:
    """Recorta o rellena con ceros hasta la longitud n."""
    if len(audio) >= n:
        return audio[:n]
    return np.pad(audio, (0, n - len(audio)))


def _rms_bloques(audio: np.ndarray, block: int = VAD_BLOCK) -> np.ndarray:
    """RMS por bloque de `block` muestras, replicando Microphone::rms() (C++).
    El audio llega normalizado a [-1, 1]; el RMS relativo basta para el umbral."""
    n = (len(audio) // block) * block
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    x = audio[:n].reshape(-1, block).astype(np.float64)
    return np.sqrt((x ** 2).mean(axis=1)).astype(np.float32)


def recortar_a_onset(audio: np.ndarray, n: int,
                     factor: float = VAD_FACTOR_INICIO,
                     block: int = VAD_BLOCK) -> np.ndarray:
    """
    Alinea la palabra al inicio del buffer replicando el VAD de inferencia
    (main.cpp): la captura arranca cuando el RMS de un bloque supera
    noise_floor × factor, y el resto se rellena con ceros.

    Esto elimina el desajuste train/inferencia: en el firmware la palabra
    empieza pegada a la muestra 0, así que el entrenamiento debe verla igual.

    Si no se detecta onset (clase silencio, o audio demasiado plano) se cae de
    vuelta a ajustar_longitud() sin desplazar nada.
    """
    rms = _rms_bloques(audio, block)
    if len(rms) == 0:
        return ajustar_longitud(audio, n)

    # Noise floor = percentil bajo del RMS del clip (zonas sin voz).
    noise    = max(float(np.percentile(rms, 20)), 1e-6)
    supera   = rms > noise * factor
    if not supera.any():
        return ajustar_longitud(audio, n)      # sin voz clara → sin recorte

    onset = int(np.argmax(supera)) * block     # inicio del primer bloque activo
    return ajustar_longitud(audio[onset:], n)


def grupo_locutor(nombre: str) -> str:
    """Locutor codificado en el nombre (h1_d050_frente_0001 → h1). Los clips
    antiguos (0001.wav, S1_...) no tienen metadatos → 'legacy'."""
    m = re.match(r"(h\d+)_d\d+_", nombre)
    return m.group(1) if m else "legacy"


def grupo_distancia(nombre: str) -> str:
    """Distancia codificada en el nombre (h1_d050_frente_0001 → d050)."""
    m = re.match(r"h\d+_(d\d+)_", nombre)
    return m.group(1) if m else "legacy"


def cargar_dataset(dataset_dir: Path, alinear: bool, log: Log) -> dict:
    """Carga clases del vocabulario + negativos externos, ya normalizados."""
    normalizar = recortar_a_onset if alinear else ajustar_longitud
    audios, labels, nombres = [], [], []
    for idx_clase, clase in enumerate(CLASES):
        n_clase = 0
        for carpeta in [clase] + CARPETAS_EXTRA.get(clase, []):
            wavs = sorted((dataset_dir / carpeta).glob("*.wav"))
            for ruta in wavs:
                audios.append(normalizar(cargar_wav(ruta), LONGITUD))
                labels.append(idx_clase)
                nombres.append(ruta.stem)
            n_clase += len(wavs)
            if carpeta != clase and wavs:
                log(f"    + {carpeta:<16}: {len(wavs):>4} archivos  (-> {clase})")
        log(f"  {clase:<20}: {n_clase:>4} archivos")

    externos = {}
    for clase in NEG_CAL + NEG_EVAL:
        wavs = sorted((dataset_dir / clase).glob("*.wav"))
        if wavs:
            externos[clase] = [normalizar(cargar_wav(r), LONGITUD) for r in wavs]
    if externos:
        log(f"  negativos externos  : "
            + "  ".join(f"{k}={len(v)}" for k, v in externos.items())
            + ("  (solo calibración/evaluación, nunca entrenamiento)" if not _neg_entrenar
               else f"  (entrenan como desconocido: {', '.join(_neg_entrenar)})"))
    return {"audios": audios, "labels": np.array(labels), "nombres": nombres,
            "externos": externos}


# ── Extracción de features ────────────────────────────────────────────────────

def extraer_mfcc(audio: np.ndarray) -> np.ndarray:
    """
    Devuelve un array (frames, NUM_MFCC) con los coeficientes MFCC.

    Implementación con tensorflow.signal para consistencia con el código
    que se replicará en C++ sobre el ESP32-S3.
    """
    t = tf.constant(audio, dtype=tf.float32)

    # Espectrograma de magnitud
    # fft_length=FFT_LENGTH hace explícito el tamaño del FFT (512 → 257 bins).
    # Sin este parámetro tf usa la siguiente potencia de 2, que es 512 de todas
    # formas, pero dejarlo implícito causó la incompatibilidad con la mel matrix.
    stft = tf.signal.stft(t, frame_length=FRAME_LENGTH, frame_step=FRAME_STEP,
                          fft_length=FFT_LENGTH)
    magnitud = tf.abs(stft)                         # (frames, 257)

    # Banco de filtros Mel
    mel_w = tf.signal.linear_to_mel_weight_matrix(
        num_mel_bins=NUM_MEL_BINS,
        num_spectrogram_bins=NUM_SPEC_BINS,         # 257 — debe coincidir con stft
        sample_rate=SR,
        lower_edge_hertz=FREQ_MIN,
        upper_edge_hertz=FREQ_MAX,
    )
    mel     = tf.tensordot(magnitud, mel_w, axes=1) # (frames, NUM_MEL_BINS)
    log_mel = tf.math.log(mel + 1e-6)

    # MFCC (DCT sobre log-Mel)
    mfcc = tf.signal.mfccs_from_log_mel_spectrograms(log_mel).numpy()[:, :NUM_MFCC]
    return normalizar_c0(mfcc)                     # (frames, NUM_MFCC)


def normalizar_c0(mfcc: np.ndarray) -> np.ndarray:
    """
    c0 (energía) relativo al frame más fuerte, con piso C0_PISO. Un cambio de
    volumen solo desplaza c0 en todos los frames, así que restarle su máximo
    hace al modelo invariante al volumen (sin esto aprendía "fuerte = hola_neo").
    El piso recorta el relleno de ceros (c0 ≈ −124) y mejora la cuantización
    int8 de la entrada. El firmware debe aplicar lo mismo (inference.cpp).
    """
    out = mfcc.copy()
    relleno = out[:, 0] - out[:, 0].max() <= C0_PISO
    out[:, 0] = np.maximum(out[:, 0] - out[:, 0].max(), C0_PISO)
    if _cmn and not relleno.all():
        # CMN: c1.. menos su media en los frames con audio → quita la
        # coloración fija del canal (distancia, orientación, sala).
        out[~relleno, 1:] -= out[~relleno, 1:].mean(axis=0)
        out[relleno, 1:] = 0.0
    return out


# ── Data augmentation ─────────────────────────────────────────────────────────

def desplazar(audio: np.ndarray, k: int) -> np.ndarray:
    """
    Desplaza k muestras (k>0 → a la derecha). En modo 'roll' usa np.roll
    (comportamiento original, con wraparound). En el resto rellena con ceros,
    igual que el buffer del firmware: k<0 equivale a un onset tardío del VAD
    (se pierde el inicio de la palabra), k>0 a un onset temprano.
    """
    if _shift_modo == "roll":
        return np.roll(audio, k).astype(np.float32)
    out = np.zeros_like(audio)
    if k >= 0:
        out[k:] = audio[:len(audio) - k]
    else:
        out[:k] = audio[-k:]
    return out


def _shifts_base(positivo: bool) -> tuple:
    """Desplazamientos de aumentar() según el modo y el tipo de clase."""
    s150 = int(0.15 * SR)
    if _shift_modo == "roll" or not positivo:
        return (s150, -s150)
    if _shift_modo == "ninguno":
        return ()
    return (SHIFT_PEQUENO, -SHIFT_PEQUENO)


def aumentar(audio: np.ndarray, positivo: bool = True) -> list:
    """
    Genera variantes aumentadas de un audio.
    Devuelve lista de arrays float32 de la misma longitud que el original.
    """
    n = len(audio)
    variantes = [audio]

    # Ruido gaussiano a distintos SNR
    for snr_db in (20, 12):
        p_señal = np.mean(audio ** 2) + 1e-9
        p_ruido = p_señal / (10 ** (snr_db / 10))
        ruido   = np.random.randn(n).astype(np.float32) * np.sqrt(p_ruido)
        variantes.append(np.clip(audio + ruido, -1, 1))

    # Desplazamiento temporal (±150 ms en modo roll; ver _shifts_base)
    for k in _shifts_base(positivo):
        variantes.append(desplazar(audio, k))

    # Cambio de volumen ±20 %
    for factor in (0.8, 1.2):
        variantes.append(np.clip(audio * factor, -1, 1).astype(np.float32))

    # Speed perturbation (como Kaldi): cambia tempo y tono → simula otras voces
    for factor in _velocidades:
        idx = np.arange(0, n, factor)
        variantes.append(np.interp(idx, np.arange(n), audio).astype(np.float32))

    return variantes   # 7 variantes por muestra original (5 en modo ninguno) + velocidades


def aumentar_desconocido(audio: np.ndarray) -> list:
    """
    15 variantes para la clase desconocido (vs 7 de hola_neo).
    Más diversidad para compensar el menor tamaño de la clase.
    """
    n = len(audio)
    variantes = aumentar(audio, positivo=False)   # 7 base

    # Ruido muy suave (SNR=30) y muy fuerte (SNR=6)
    for snr_db in (30, 6):
        p_s = np.mean(audio ** 2) + 1e-9
        p_r = p_s / (10 ** (snr_db / 10))
        variantes.append(np.clip(audio + np.random.randn(n).astype(np.float32) * np.sqrt(p_r), -1, 1))

    # Desplazamiento temporal ±300 ms
    shift300 = int(0.30 * SR)
    variantes.append(desplazar(audio,  shift300))
    variantes.append(desplazar(audio, -shift300))

    # Volumen más extremo
    for factor in (0.5, 1.5):
        variantes.append(np.clip(audio * factor, -1, 1).astype(np.float32))

    # Combinadas: ruido SNR=15 + shift
    p_s = np.mean(audio ** 2) + 1e-9
    r15 = np.random.randn(n).astype(np.float32) * np.sqrt(p_s / (10 ** (15 / 10)))
    variantes.append(np.clip(desplazar(audio + r15, int(0.10 * SR)), -1, 1).astype(np.float32))

    # Combinada: ruido SNR=10 + volumen reducido
    r10 = np.random.randn(n).astype(np.float32) * np.sqrt(p_s / (10 ** (10 / 10)))
    variantes.append(np.clip((audio + r10) * 0.9, -1, 1).astype(np.float32))

    return variantes   # 15 variantes


def aumentar_silencio(audio: np.ndarray) -> list:
    """
    10 variantes para la clase silencio.
    """
    n = len(audio)
    variantes = aumentar(audio, positivo=False)   # 7 base

    # Ruido muy suave (SNR=30)
    p_s = np.mean(audio ** 2) + 1e-9
    r30 = np.random.randn(n).astype(np.float32) * np.sqrt(p_s / (10 ** (30 / 10)))
    variantes.append(np.clip(audio + r30, -1, 1))

    # Volumen reducido
    variantes.append(np.clip(audio * 0.6, -1, 1).astype(np.float32))

    # Desplazamiento +200 ms
    variantes.append(desplazar(audio, int(0.20 * SR)))

    return variantes   # 10 variantes


def spec_augment(mfcc: np.ndarray,
                 T_max: int = 25,
                 F_max: int = 10,
                 n_T: int = 2,
                 n_F: int = 2) -> np.ndarray:
    """
    SpecAugment sobre una matriz MFCC (frames, coefs).
    Aplica n_T máscaras temporales y n_F máscaras de frecuencia con la media
    como valor de relleno. Solo se llama sobre muestras de entrenamiento.
    """
    out = mfcc.copy()
    media = out.mean()
    num_frames, num_coefs = out.shape

    for _ in range(n_T):
        t = np.random.randint(0, max(1, T_max))
        t0 = np.random.randint(0, max(1, num_frames - t))
        out[t0:t0 + t, :] = media

    for _ in range(n_F):
        f = np.random.randint(0, max(1, F_max))
        f0 = np.random.randint(0, max(1, num_coefs - f))
        out[:, f0:f0 + f] = media

    return out


def preparar(audios, labels, aumentar_datos: bool) -> tuple:
    """
    Extrae MFCC con augmentación según el tipo de clase:
      desconocido → 15 variantes de audio (máxima diversidad)
      silencio    → 10 variantes de audio
      comandos    →  7 variantes de audio
    Cada variante también genera una copia con SpecAugment,
    duplicando el conjunto sin añadir más audio grabado.
    """
    _aug_por_nombre = {"desconocido": aumentar_desconocido,
                       "silencio":    aumentar_silencio}
    X, y = [], []
    for audio, label in zip(audios, labels):
        if not aumentar_datos:
            fn = lambda a: [a]
        else:
            fn = _aug_por_nombre.get(CLASES[label], aumentar)
        for v in fn(audio):
            mfcc = extraer_mfcc(ajustar_longitud(v, LONGITUD))
            X.append(mfcc)
            y.append(label)
            if aumentar_datos:
                X.append(spec_augment(mfcc))
                y.append(label)
    return (np.array(X, dtype=np.float32)[..., np.newaxis],
            np.array(y, dtype=np.int32))


# ── Modelo ────────────────────────────────────────────────────────────────────

def construir_modelo(input_shape: tuple, num_clases: int) -> tf.keras.Model:
    """
    CNN pequeña (~28 K parámetros → ~28 KB en int8).
    Arquitectura: 3× [Conv2D → BN → ReLU → MaxPool] → GAP → Dense → Softmax
    L2 en Dense(64) penaliza overfitting sin aumentar el tamaño del modelo.
    """
    reg = tf.keras.regularizers.L2(1e-4)

    entradas = tf.keras.Input(shape=input_shape)
    x = entradas

    # Canales reducidos: la entrada 148×40 hace cara la 1ª conv con kernels de
    # referencia (ESP-NN no activo en este build). (8,16,32) ≈ 4.4M MACs → la
    # inferencia en el ESP32-S3 baja de varios segundos a ~1 s y no estrella IDLE0.
    for filtros in (8, 16, 32):
        x = tf.keras.layers.Conv2D(filtros, (3, 3), padding="same")(x)
        x = tf.keras.layers.BatchNormalization()(x)
        x = tf.keras.layers.ReLU()(x)
        x = tf.keras.layers.MaxPooling2D((2, 2))(x)

    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dense(32, activation="relu", kernel_regularizer=reg)(x)
    x = tf.keras.layers.Dropout(0.50)(x)
    salidas = tf.keras.layers.Dense(num_clases, activation="softmax")(x)

    return tf.keras.Model(entradas, salidas, name="neo_wake_word")


# ── Exportación TFLite ────────────────────────────────────────────────────────

def exportar_tflite(modelo: tf.keras.Model,
                    X_rep: np.ndarray,
                    directorio: Path) -> tuple:
    """
    Exporta dos versiones del modelo:
      - modelo_float.tflite : float32 (para validar en PC)
      - modelo_int8.tflite  : int8 cuantizado (para flashear en ESP32-S3)

    X_rep: subconjunto representativo de features para calibrar la cuantización.
    """
    directorio.mkdir(parents=True, exist_ok=True)

    # Float32 —————————————————————————————————————————
    conv = tf.lite.TFLiteConverter.from_keras_model(modelo)
    data_float = conv.convert()
    ruta_float = directorio / "modelo_float.tflite"
    ruta_float.write_bytes(data_float)

    # Int8 ————————————————————————————————————————————
    conv = tf.lite.TFLiteConverter.from_keras_model(modelo)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type  = tf.int8
    conv.inference_output_type = tf.int8

    def dataset_representativo():
        for muestra in X_rep:
            yield [muestra[np.newaxis].astype(np.float32)]

    conv.representative_dataset = dataset_representativo
    data_int8 = conv.convert()
    ruta_int8 = directorio / "modelo_int8.tflite"
    ruta_int8.write_bytes(data_int8)

    print(f"  modelo_float.tflite : {len(data_float)/1024:6.1f} KB")
    print(f"  modelo_int8.tflite  : {len(data_int8)/1024:6.1f} KB")
    return ruta_float, ruta_int8


def predecir_tflite(ruta: Path, X: np.ndarray) -> np.ndarray:
    """
    Probabilidades de un .tflite sobre X (float32). Si el modelo es int8,
    cuantiza la entrada con su scale/zero_point y descuantiza la salida,
    exactamente como Inference::clasificar() en el firmware.
    """
    interp = tf.lite.Interpreter(model_path=str(ruta))
    interp.allocate_tensors()
    d_in  = interp.get_input_details()[0]
    d_out = interp.get_output_details()[0]
    s_in,  zp_in  = d_in["quantization"]
    s_out, zp_out = d_out["quantization"]
    salida = []
    for x in X:
        x = x[np.newaxis].astype(np.float32)
        if d_in["dtype"] == np.int8:
            x = np.clip(np.round(x / s_in + zp_in), -128, 127).astype(np.int8)
        interp.set_tensor(d_in["index"], x)
        interp.invoke()
        y = interp.get_tensor(d_out["index"])[0]
        if d_out["dtype"] == np.int8:
            y = (y.astype(np.float32) - zp_out) * s_out
        salida.append(y)
    return np.array(salida, dtype=np.float32)


# ── Métricas ──────────────────────────────────────────────────────────────────

def ece(probs: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """Expected Calibration Error (top-label): |confianza − acierto| por bins."""
    conf = probs.max(axis=1)
    ok   = probs.argmax(axis=1) == y
    bordes = np.linspace(0, 1, bins + 1)
    e = 0.0
    for lo, hi in zip(bordes[:-1], bordes[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            e += m.mean() * abs(ok[m].mean() - conf[m].mean())
    return float(e)


def metricas(probs: np.ndarray, y: np.ndarray) -> dict:
    pred = probs.argmax(axis=1)
    p = np.clip(probs, 1e-7, 1.0)
    p = p / p.sum(axis=1, keepdims=True)
    onehot = np.eye(len(CLASES))[y]
    return {
        "accuracy": float((pred == y).mean()),
        "nll":      float(log_loss(y, p, labels=list(range(len(CLASES))))),
        "brier":    float(((probs - onehot) ** 2).sum(axis=1).mean()),
        "ece":      ece(probs, y),
        "cm":       confusion_matrix(y, pred, labels=list(range(len(CLASES)))).tolist(),
        "report":   classification_report(y, pred, labels=list(range(len(CLASES))),
                                          target_names=CLASES, digits=3,
                                          zero_division=0),
    }


def log_metricas(log: Log, nombre: str, m: dict):
    log(f"\n  ── {nombre} ──")
    log(f"  Accuracy {m['accuracy']*100:.2f}%   NLL {m['nll']:.4f}   "
        f"Brier {m['brier']:.4f}   ECE {m['ece']:.4f}")
    ancho = max(len(c) for c in CLASES) + 2
    log("  Matriz de confusión (filas=real, columnas=predicho):")
    log("  " + " " * ancho + "".join(f"{c:>{ancho}}" for c in CLASES))
    for i, clase in enumerate(CLASES):
        log("  " + f"{clase:>{ancho}}" + "".join(f"{v:>{ancho}}" for v in m["cm"][i]))
    log("")
    for linea in m["report"].rstrip().splitlines():
        log("  " + linea)


# ── Umbral del wake word ──────────────────────────────────────────────────────

def score_deteccion(probs: np.ndarray) -> np.ndarray:
    """
    Score efectivo de disparo, igual que el firmware: dispara si la clase top
    es hola_neo Y su score ≥ umbral. Si la top no es hola_neo, el score es 0.
    """
    s = probs[:, IDX_POS].copy()
    s[probs.argmax(axis=1) != IDX_POS] = 0.0
    return s


def umbral_youden(probs_val: np.ndarray, y_val: np.ndarray) -> float:
    """Criterio original: max(TPR − FPR) sobre el val set (score crudo)."""
    y_bin = (y_val == IDX_POS).astype(int)
    fpr, tpr, thr = roc_curve(y_bin, probs_val[:, IDX_POS])
    return float(thr[int(np.argmax(tpr - fpr))])


def umbral_para_fpr(s_neg: np.ndarray, objetivo: float, minimo: float) -> float:
    """
    Menor umbral (≥ minimo) tal que la fracción de negativos con score ≥ umbral
    no supere `objetivo`. Se redondea hacia arriba a 4 decimales (formato de
    umbrales.json) para no admitir un negativo extra por redondeo.
    """
    s = np.sort(s_neg)[::-1]
    k = int(np.floor(objetivo * len(s)))       # nº de FP permitidos
    if k >= len(s):
        return minimo
    thr = float(np.ceil((s[k] + 1e-6) * 1e4) / 1e4)
    return max(thr, minimo)


def cota_superior(k: int, n: int, conf: float = 0.95) -> float:
    """Cota superior Clopper-Pearson (una cola) de una proporción k/n."""
    if n == 0:
        return float("nan")
    if k >= n:
        return 1.0
    return float(beta.ppf(conf, k + 1, n - k))


def tasa(s: np.ndarray, thr: float) -> tuple:
    k = int((s >= thr).sum())
    return k, len(s)


# ── Entrenamiento + evaluación de un split ────────────────────────────────────

def entrenar(X_train, y_train, X_val, y_val, epocas: int, log: Log, verbose=1,
             y_pesos=None):
    modelo = construir_modelo(X_train.shape[1:], len(CLASES))
    modelo.compile(
        optimizer=tf.keras.optimizers.Adam(1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )

    # Pesos inversamente proporcionales a la frecuencia de cada clase.
    # Evita que la clase mayoritaria (hola_neo) domine el gradiente.
    # y_pesos permite calcularlos sobre un subconjunto (ver --neg-peso).
    y_w = y_train if y_pesos is None else y_pesos
    pesos = compute_class_weight("balanced", classes=np.unique(y_w), y=y_w)
    class_weight = dict(enumerate(pesos))
    log(f"  Class weights: { {CLASES[k]: f'{v:.2f}' for k, v in class_weight.items()} }")

    early = tf.keras.callbacks.EarlyStopping(
        monitor="val_loss",          # más estable que val_accuracy con val pequeño
        patience=15,                 # era 10; da margen para escapar de mínimos locales
        min_delta=0.005,
        restore_best_weights=True)
    callbacks = [
        early,
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.3, patience=7, min_lr=1e-5, verbose=verbose),
    ]

    historial = modelo.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=epocas,
        batch_size=32,
        callbacks=callbacks,
        class_weight=class_weight,
        verbose=verbose,
    )
    h = historial.history
    n_ep = len(h["loss"])
    mejor = int(early.best_epoch) + 1     # 1-based, la que restaura Keras
    log(f"  Épocas ejecutadas: {n_ep}   Mejor época (pesos restaurados): {mejor}   "
        f"{'early stopping' if early.stopped_epoch > 0 else 'llegó al máximo de épocas'}")
    log(f"  En la mejor época: loss {h['loss'][mejor-1]:.4f}  acc {h['accuracy'][mejor-1]:.4f}  "
        f"val_loss {h['val_loss'][mejor-1]:.4f}  val_acc {h['val_accuracy'][mejor-1]:.4f}")
    return modelo, h, mejor


def evaluar_split(datos: dict, idx_train, idx_val, idx_test, args, log: Log,
                  output_dir: Path, verbose=1, guardar_grafica=True) -> dict:
    """Entrena con idx_train/idx_val, evalúa en idx_test y negativos externos,
    exporta TFLite a output_dir y devuelve un dict de resultados."""
    A, L = datos["audios"], datos["labels"]
    sel = lambda idx: ([A[i] for i in idx], L[idx])

    a_train, l_train = sel(idx_train)
    a_val,   l_val   = sel(idx_val)
    a_test,  l_test  = sel(idx_test)
    log(f"  Originales  ->  Train: {len(a_train)}  Val: {len(a_val)}  Test: {len(a_test)}")
    for i, c in enumerate(CLASES):
        log(f"    {c:<14} train {int((l_train==i).sum()):>4}  val {int((l_val==i).sum()):>4}  "
            f"test {int((l_test==i).sum()):>4}")

    ext = datos["externos"]
    X_train, y_train = preparar(a_train, l_train, aumentar_datos=args.augment)
    y_pesos = None
    if _neg_entrenar:
        # Habla real de otras palabras como "desconocido", después de los clips
        # originales para que el azar de su augmentation no cambie.
        idx_desc = CLASES.index("desconocido")
        extra = [a for c in _neg_entrenar for a in ext.get(c, [])]
        X_e, y_e = preparar(extra, np.full(len(extra), idx_desc, dtype=l_train.dtype),
                            aumentar_datos=args.augment)
        if args.neg_peso == "base":
            y_pesos = y_train          # pesos de clase sin los extra (como el baseline)
        X_train = np.concatenate([X_train, X_e])
        y_train = np.concatenate([y_train, y_e])
        log(f"  + {len(extra)} clips de habla como desconocido en train "
            f"({', '.join(_neg_entrenar)}), pesos de clase: {args.neg_peso}")

    X_val,   y_val   = preparar(a_val,   l_val,   aumentar_datos=False)
    X_test,  y_test  = preparar(a_test,  l_test,  aumentar_datos=False)
    log(f"  Tras augmentation ->  Train: {len(X_train)}  Val: {len(X_val)}  Test: {len(X_test)}")

    neg_cal, neg_eval = palabras_cal_eval()
    X_cal_ext  = preparar([a for c in neg_cal  for a in ext.get(c, [])], [1] * sum(len(ext.get(c, [])) for c in neg_cal),  False)[0]
    X_eval_ext = preparar([a for c in neg_eval for a in ext.get(c, [])], [1] * sum(len(ext.get(c, [])) for c in neg_eval), False)[0]

    modelo, h, mejor = entrenar(X_train, y_train, X_val, y_val, args.epocas, log, verbose,
                                y_pesos=y_pesos)

    # Historial por época al log
    log("\n  Historial (época  loss  acc  val_loss  val_acc  lr):")
    for e in range(len(h["loss"])):
        lr = h.get("learning_rate", h.get("lr", [float("nan")] * len(h["loss"])))[e]
        marca = "  ← mejor" if e + 1 == mejor else ""
        log(f"    {e+1:>3}  {h['loss'][e]:.4f}  {h['accuracy'][e]:.4f}  "
            f"{h['val_loss'][e]:.4f}  {h['val_accuracy'][e]:.4f}  {lr:.1e}{marca}")

    # Exportar TFLite (siempre a output_dir, nunca a models/ salvo que se pida)
    rng = np.random.RandomState(args.seed)
    idx_rep = rng.choice(len(X_train), min(200, len(X_train)), replace=False)
    ruta_float, ruta_int8 = exportar_tflite(modelo, X_train[idx_rep], output_dir)

    res = {"mejor_epoca": mejor, "epocas": len(h["loss"]),
           "historial": {k: [float(v) for v in vs] for k, vs in h.items()}}

    # Probabilidades: keras, tflite float, tflite int8
    p_keras = modelo.predict(X_test, verbose=0)
    p_float = predecir_tflite(ruta_float, X_test)
    p_int8  = predecir_tflite(ruta_int8,  X_test)
    res["test_keras"] = metricas(p_keras, y_test)
    res["test_float"] = metricas(p_float, y_test)
    res["test_int8"]  = metricas(p_int8,  y_test)
    res["acuerdo_float_int8"] = float((p_float.argmax(1) == p_int8.argmax(1)).mean())
    res["max_abs_dif_prob"]   = float(np.abs(p_float - p_int8).max())

    log_metricas(log, "TEST — modelo Keras (float)", res["test_keras"])
    log_metricas(log, "TEST — modelo_int8.tflite (entrada cuantizada como en el firmware)",
                 res["test_int8"])
    perdida = res["test_float"]["accuracy"] - res["test_int8"]["accuracy"]
    log(f"\n  Pérdida por cuantización (acc float.tflite − int8): {perdida*100:+.2f} pp   "
        f"acuerdo de predicción {res['acuerdo_float_int8']*100:.1f}%   "
        f"|Δp| máx {res['max_abs_dif_prob']:.3f}")

    # Umbrales (calculados sobre el modelo int8, que es lo que corre el ESP32)
    p_val_f  = modelo.predict(X_val, verbose=0)
    p_val_8  = predecir_tflite(ruta_int8, X_val)
    p_cal_8  = predecir_tflite(ruta_int8, X_cal_ext)  if len(X_cal_ext)  else np.zeros((0, len(CLASES)))
    p_eval_8 = predecir_tflite(ruta_int8, X_eval_ext) if len(X_eval_ext) else np.zeros((0, len(CLASES)))
    res.update(calcular_umbrales(p_val_f, p_val_8, y_val, p_cal_8, p_test_8=p_int8,
                                 y_test=y_test, p_eval_8=p_eval_8, args=args, log=log))
    # Nombres del test para desglose por condición
    nombres_test = [datos["nombres"][i] for i in idx_test]
    desglose_condiciones(nombres_test, y_test, p_int8, res["umbral"], log)
    res["fp_por_palabra"] = fp_por_palabra(ruta_int8, ext, log)

    if guardar_grafica:
        ep = range(1, len(h["loss"]) + 1)
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
        ax1.plot(ep, h["loss"],          label="train")
        ax1.plot(ep, h["val_loss"],      label="val")
        ax2.plot(ep, h["accuracy"],      label="train")
        ax2.plot(ep, h["val_accuracy"],  label="val")
        for ax, t in ((ax1, "Loss"), (ax2, "Accuracy")):
            ax.axvline(mejor, color="gray", ls="--", lw=1, label=f"mejor ({mejor})")
            ax.set_xlabel("Época"); ax.set_title(t); ax.legend()
        fig.savefig(output_dir / "entrenamiento.png", dpi=100, bbox_inches="tight")
        plt.close()
    return res


def calcular_umbrales(p_val_f, p_val_8, y_val, p_cal_8, p_test_8, y_test,
                      p_eval_8, args, log: Log) -> dict:
    """
    Calcula el umbral de hola_neo por Youden (referencia) y por FPR objetivo.
    Negativos de calibración = negativos del val + NEG_CAL externos.
    Se evalúa en test (positivos y negativos) + NEG_EVAL externos.
    """
    y_val = np.asarray(y_val)
    s_val = score_deteccion(p_val_8)
    s_neg_cal = np.concatenate([s_val[y_val != IDX_POS], score_deteccion(p_cal_8)])
    s_neg_val = s_val[y_val != IDX_POS]

    s_test = score_deteccion(p_test_8)
    s_pos_test = s_test[y_test == IDX_POS]
    s_neg_test = np.concatenate([s_test[y_test != IDX_POS], score_deteccion(p_eval_8)])

    thr_youden  = umbral_youden(p_val_f, y_val)
    thr_fpr_val = umbral_para_fpr(s_neg_val, args.fpr_objetivo, args.umbral_minimo)
    thr_fpr     = umbral_para_fpr(s_neg_cal, args.fpr_objetivo, args.umbral_minimo)

    log(f"\n  ── Umbral de {CLASES[IDX_POS]} (scores del modelo int8) ──")
    log(f"  Negativos para calibrar: {len(s_neg_cal)} "
        f"(val {len(s_neg_val)} + externos {len(s_neg_cal)-len(s_neg_val)})   "
        f"FPR objetivo {args.fpr_objetivo*100:.1f}%")
    log(f"  Negativos para evaluar : {len(s_neg_test)} "
        f"(test {int((y_test!=IDX_POS).sum())} + externos {len(s_neg_test)-int((y_test!=IDX_POS).sum())})"
        f"   Positivos test: {len(s_pos_test)}")
    tabla = {}
    candidatos = [("youden (val, float)", thr_youden),
                  ("fpr (solo val)",       thr_fpr_val),
                  ("fpr (val+externos)",   thr_fpr),
                  ("desplegado 0.5706",    0.5706)]
    for t in (0.6, 0.7, 0.8, 0.9):
        candidatos.append((f"fijo {t:.2f}", t))
    log(f"  {'criterio':<22}{'umbral':>8}{'TPR test':>12}{'FPR test+ext':>15}{'cota95%':>9}"
        f"{'TPR²':>8}{'FPR² (indep.)':>15}")
    for nombre, thr in candidatos:
        kp, npos = tasa(s_pos_test, thr)
        kn, nneg = tasa(s_neg_test, thr)
        tpr, fpr = kp / max(npos, 1), kn / max(nneg, 1)
        cs = cota_superior(kn, nneg)
        tabla[nombre] = {"umbral": thr, "tpr": tpr, "fp": kn, "n_neg": nneg,
                         "fpr": fpr, "fpr_cota95": cs, "tp": kp, "n_pos": npos}
        log(f"  {nombre:<22}{thr:>8.4f}{tpr*100:>11.1f}%{kn:>6}/{nneg:<4}{fpr*100:>4.1f}%"
            f"{cs*100:>8.1f}%{tpr**2*100:>7.1f}%{fpr**2*100:>14.2f}%")
    log("  (cota95% = Clopper-Pearson una cola; TPR²/FPR² = CONF_MINIMAS=2 suponiendo "
        "independencia entre dos frases seguidas)")
    elegido = thr_fpr if args.umbral_criterio == "fpr" else thr_youden
    log(f"  Umbral elegido ({args.umbral_criterio}): {elegido:.4f}")

    # Score máximo y nº de disparos (umbral elegido) por origen de los negativos
    log("  Negativos por origen (score efectivo máx · disparos ≥ umbral elegido):")
    n_val_neg = int((y_val != IDX_POS).sum())
    n_test_neg = int((y_test != IDX_POS).sum())
    origenes = [("val", s_neg_cal[:n_val_neg]), ("cal_externos", s_neg_cal[n_val_neg:]),
                ("test", s_neg_test[:n_test_neg]), ("eval_externos", s_neg_test[n_test_neg:])]
    for nombre, s in origenes:
        if len(s):
            log(f"    {nombre:<14} n={len(s):>4}  máx {s.max():.3f}  "
                f"disparos {int((s >= elegido).sum())}  ≥0.5: {int((s >= 0.5).sum())}")
    return {"umbral": elegido, "umbral_youden": thr_youden,
            "umbral_fpr_val": thr_fpr_val, "umbral_fpr": thr_fpr, "tabla_umbrales": tabla}


def palabras_cal_eval() -> tuple:
    """Palabras externas para calibrar y para evaluar. Sin --neg-entrenar,
    NEG_CAL / NEG_EVAL. Con él, las no entrenadas solo evalúan (calibrar con
    ellas contaminaría la medida de la palabra excluida)."""
    if not _neg_entrenar:
        return NEG_CAL, NEG_EVAL
    return (), tuple(c for c in NEG_PALABRAS if c not in _neg_entrenar)


def fp_por_palabra(ruta_int8: Path, ext: dict, log: Log) -> dict:
    """Disparos de hola_neo (score efectivo int8) en cada palabra externa a
    umbrales fijos. Marca si la palabra se usó para entrenar."""
    out = {}
    log("\n  Falsos positivos por palabra (int8, score ≥ umbral):")
    log(f"    {'palabra':<10}{'origen':>10}{'n':>5}" + "".join(f"{t:>8.4g}" for t in UMBRALES_PALABRA)
        + f"{'máx':>8}")
    for c in NEG_PALABRAS:
        if not ext.get(c):
            continue
        X = preparar(ext[c], [1] * len(ext[c]), False)[0]
        s = score_deteccion(predecir_tflite(ruta_int8, X))
        fps = {f"{t:.4f}": int((s >= t).sum()) for t in UMBRALES_PALABRA}
        origen = "entrenada" if c in _neg_entrenar else "excluida"
        out[c] = {"origen": origen, "n": len(s), "fp": fps,
                  "scores": [round(float(v), 4) for v in s]}
        log(f"    {c:<10}{origen:>10}{len(s):>5}" + "".join(f"{v:>8}" for v in fps.values())
            + f"{s.max():>8.3f}")
    return out


def desglose_condiciones(nombres, y, probs, thr, log: Log):
    """TPR del wake word en test por locutor / distancia / orientación."""
    s = score_deteccion(probs)
    grupos = {}
    for n, yi, si in zip(nombres, y, s):
        if yi != IDX_POS:
            continue
        m = re.match(r"(h\d+)_(d\d+)_(\w+?)_\d+$", n)
        claves = [f"locutor={m.group(1)}", f"distancia={m.group(2)}",
                  f"orientación={m.group(3)}"] if m else ["locutor=legacy"]
        for k in claves:
            grupos.setdefault(k, []).append(si >= thr)
    log(f"\n  TPR en test por condición (umbral {thr:.4f}, int8):")
    for k in sorted(grupos):
        v = grupos[k]
        log(f"    {k:<22} {sum(v):>3}/{len(v):<3} {np.mean(v)*100:5.1f}%")


# ── Modos ─────────────────────────────────────────────────────────────────────

def split_unico(datos: dict, seed: int):
    """Split original 64/16/20 estratificado por clip (random_state fijo)."""
    idx = np.arange(len(datos["labels"]))
    L = datos["labels"]
    idx_tv, idx_test = train_test_split(idx, test_size=0.20, stratify=L, random_state=42)
    idx_train, idx_val = train_test_split(idx_tv, test_size=0.20, stratify=L[idx_tv],
                                          random_state=42)
    return idx_train, idx_val, idx_test


def resumen_cv(resultados: list, log: Log, titulo: str) -> dict:
    """Media ± desviación de las métricas principales a través de folds."""
    def col(f):
        return np.array([f(r) for r in resultados], dtype=float)
    filas = {
        "mejor_epoca":        col(lambda r: r["mejor_epoca"]),
        "acc_float":          col(lambda r: r["test_keras"]["accuracy"]),
        "acc_int8":           col(lambda r: r["test_int8"]["accuracy"]),
        "perdida_cuant_pp":   col(lambda r: (r["test_float"]["accuracy"] - r["test_int8"]["accuracy"]) * 100),
        "nll_float":          col(lambda r: r["test_keras"]["nll"]),
        "ece_float":          col(lambda r: r["test_keras"]["ece"]),
        "nll_int8":           col(lambda r: r["test_int8"]["nll"]),
        "umbral_youden":      col(lambda r: r["umbral_youden"]),
        "umbral_fpr":         col(lambda r: r["umbral_fpr"]),
        "tpr@umbral_fpr":     col(lambda r: r["tabla_umbrales"]["fpr (val+externos)"]["tpr"]),
        "fpr@umbral_fpr":     col(lambda r: r["tabla_umbrales"]["fpr (val+externos)"]["fpr"]),
        "tpr@youden":         col(lambda r: r["tabla_umbrales"]["youden (val, float)"]["tpr"]),
        "fpr@youden":         col(lambda r: r["tabla_umbrales"]["youden (val, float)"]["fpr"]),
    }
    log(f"\n{'=' * 60}\n  {titulo}: {len(resultados)} folds (media ± desv. estándar)\n{'=' * 60}")
    out = {}
    for k, v in filas.items():
        log(f"  {k:<18} {v.mean():8.4f} ± {v.std(ddof=1) if len(v) > 1 else 0:.4f}   "
            f"[{', '.join(f'{x:.3f}' for x in v)}]")
        out[k] = {"media": float(v.mean()), "std": float(v.std(ddof=1)) if len(v) > 1 else 0.0,
                  "valores": v.tolist()}
    return out


def _json_limpio(res):
    """Quita los classification_report (texto) para metricas.json."""
    if isinstance(res, dict):
        return {k: _json_limpio(v) for k, v in res.items() if k != "report"}
    if isinstance(res, list):
        return [_json_limpio(v) for v in res]
    return res


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global _shift_modo, _neg_entrenar, _velocidades, _cmn
    parser = argparse.ArgumentParser(description="Entrena el wake word model de NEO")
    parser.add_argument("--dataset", default="dataset",
                        help="Directorio raíz del dataset (default: dataset/)")
    parser.add_argument("--epocas",  type=int, default=80,
                        help="Épocas máximas de entrenamiento (default: 80)")
    parser.add_argument("--output",  default="models",
                        help="Directorio de salida para modelos y gráficas (default: models/)")
    parser.add_argument("--sin-augment", dest="augment",
                        action="store_false", default=True,
                        help="Desactivar data augmentation")
    parser.add_argument("--sin-alinear", dest="alinear",
                        action="store_false", default=True,
                        help="No alinear al onset de voz (usar relleno simple)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Semilla para numpy/tf/random (default: 42)")
    # "pequeno" por defecto: en CV k=5 mejora a "roll" en accuracy, NLL, ECE y
    # varianza entre folds (models/experimentos/2026-10-15/). "roll" reproduce
    # el comportamiento anterior.
    parser.add_argument("--shift", choices=SHIFT_MODOS, default="pequeno",
                        help="Modo de shift temporal en augmentation (default: pequeno)")
    parser.add_argument("--umbral-criterio", choices=("fpr", "youden"), default="fpr",
                        help="Criterio para umbrales.json (default: fpr)")
    parser.add_argument("--fpr-objetivo", type=float, default=0.01,
                        help="FPR objetivo por frase para el criterio fpr (default: 0.01)")
    parser.add_argument("--umbral-minimo", type=float, default=0.5,
                        help="Suelo del umbral fpr (default: 0.5)")
    parser.add_argument("--cv", type=int, default=0,
                        help="Validación cruzada estratificada con K folds (0 = split único)")
    parser.add_argument("--leave-speaker-out", action="store_true",
                        help="Test = todos los hola_neo de un locutor (h1, h2...)")
    parser.add_argument("--velocidad", default="",
                        help="Factores de speed perturbation en augmentation, p. ej. 0.9,1.1")
    # CMN por defecto: inference.cpp lo aplica siempre. --sin-cmn solo para
    # experimentos (un modelo así NO sirve para el firmware actual).
    parser.add_argument("--sin-cmn", dest="cmn", action="store_false", default=True,
                        help="No restar a c1.. su media por clip (incompatible con inference.cpp)")
    parser.add_argument("--por-distancia", action="store_true",
                        help="Con --leave-speaker-out, agrupar por distancia (d050/d100/d200) en vez de locutor")
    parser.add_argument("--loso-estricto", action="store_true",
                        help="Con --leave-speaker-out, los negativos del locutor también van al test")
    parser.add_argument("--solo-evaluar", default=None,
                        help="Directorio con modelo_float/int8.tflite ya entrenados: "
                             "evalúa en el test del split único sin entrenar")
    parser.add_argument("--neg-entrenar", default="",
                        help="Palabras externas (coma) que entrenan como desconocido, "
                             f"de {','.join(NEG_PALABRAS)}. El resto solo evalúa")
    # "balanceado": los clips extra entran en compute_class_weight → el peso total
    # de desconocido no crece, solo se reparte (y hola_neo pesa más que antes).
    # "base": pesos calculados solo con los clips del vocabulario (los del
    # baseline), así cada clip extra suma peso de desconocido en la pérdida.
    parser.add_argument("--neg-peso", choices=("balanceado", "base"), default="balanceado",
                        help="Pesos de clase con --neg-entrenar (default: balanceado)")
    args = parser.parse_args()

    # Consola Windows (cp1252) no admite algunos símbolos del log: reemplazarlos
    # en pantalla; el .txt se escribe siempre en UTF-8.
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    _shift_modo = args.shift
    _velocidades = tuple(float(v) for v in args.velocidad.split(",") if v.strip())
    _cmn = args.cmn
    _neg_entrenar = tuple(c.strip() for c in args.neg_entrenar.split(",") if c.strip())
    desconocidas = [c for c in _neg_entrenar if c not in NEG_PALABRAS]
    if desconocidas:
        parser.error(f"--neg-entrenar: palabras no válidas {desconocidas} (opciones: {NEG_PALABRAS})")
    fijar_semillas(args.seed)
    dataset_dir = Path(args.dataset)
    output_dir  = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    log = Log()

    log("=" * 60)
    log("  NEO — Entrenamiento wake word")
    log("=" * 60)
    log(f"  Fecha           : {datetime.now():%Y-%m-%d %H:%M}")
    log(f"  Args            : {vars(args)}")
    log(f"  TF {tf.__version__}  numpy {np.__version__}")
    log(f"\n[1/5] Cargando dataset desde '{dataset_dir}'...")
    datos = cargar_dataset(dataset_dir, args.alinear, log)
    if len(datos["labels"]) == 0:
        log("\nERROR: no se encontraron archivos WAV en el dataset.")
        return
    log(f"\n  Longitud fija   : {LONGITUD} muestras  ({LONGITUD/SR:.2f} s)")
    log(f"  Clases          : {len(CLASES)}  {CLASES}")
    log(f"  Alineación      : {'sí (onset de voz, igual que el VAD)' if args.alinear else 'no (relleno simple)'}")
    log(f"  Augmentation    : {'sí, shift=' + args.shift if args.augment else 'no'}")

    L = datos["labels"]
    resultados = []

    if args.solo_evaluar:
        # ── Evaluar .tflite existentes sobre el test del split único ──────────
        _, idx_val, idx_test = split_unico(datos, args.seed)
        X_val,  y_val  = preparar([datos["audios"][i] for i in idx_val],  L[idx_val],  False)
        X_test, y_test = preparar([datos["audios"][i] for i in idx_test], L[idx_test], False)
        ext = datos["externos"]
        X_cal  = preparar([a for c in NEG_CAL  for a in ext.get(c, [])], [1] * sum(len(ext.get(c, [])) for c in NEG_CAL),  False)[0]
        X_eval = preparar([a for c in NEG_EVAL for a in ext.get(c, [])], [1] * sum(len(ext.get(c, [])) for c in NEG_EVAL), False)[0]
        d = Path(args.solo_evaluar)
        p_f = predecir_tflite(d / "modelo_float.tflite", X_test)
        p_8 = predecir_tflite(d / "modelo_int8.tflite",  X_test)
        res = {"test_float": metricas(p_f, y_test), "test_int8": metricas(p_8, y_test)}
        log_metricas(log, f"TEST — {d/'modelo_float.tflite'}", res["test_float"])
        log_metricas(log, f"TEST — {d/'modelo_int8.tflite'}",  res["test_int8"])
        log(f"\n  Pérdida por cuantización: "
            f"{(res['test_float']['accuracy']-res['test_int8']['accuracy'])*100:+.2f} pp")
        res.update(calcular_umbrales(predecir_tflite(d / "modelo_float.tflite", X_val),
                                     predecir_tflite(d / "modelo_int8.tflite", X_val), y_val,
                                     predecir_tflite(d / "modelo_int8.tflite", X_cal),
                                     p_8, y_test, predecir_tflite(d / "modelo_int8.tflite", X_eval),
                                     args, log))
        desglose_condiciones([datos["nombres"][i] for i in idx_test], y_test, p_8, res["umbral"], log)
        resultados.append(res)

    elif args.cv:
        # ── CV estratificada: cada fold es test una vez; val = 20 % del resto ─
        skf = StratifiedKFold(n_splits=args.cv, shuffle=True, random_state=args.seed)
        for k, (idx_tv, idx_test) in enumerate(skf.split(np.zeros(len(L)), L)):
            log(f"\n{'#' * 60}\n  FOLD {k+1}/{args.cv}\n{'#' * 60}")
            fijar_semillas(args.seed + k)
            idx_train, idx_val = train_test_split(idx_tv, test_size=0.20, stratify=L[idx_tv],
                                                  random_state=args.seed + k)
            resultados.append(evaluar_split(datos, idx_train, idx_val, idx_test, args, log,
                                            output_dir / f"fold{k+1}", verbose=2))
        resumen_cv(resultados, log, f"CV estratificada k={args.cv}")

    elif args.leave_speaker_out:
        # ── Test = hola_neo de un locutor + 20 % de negativos (sin metadatos) ─
        # --loso-estricto: los negativos con locutor (h1_..., h2_...) van al test
        # con su locutor; así el FPR del test es con una voz nunca oída.
        # --por-distancia: mismo esquema pero el grupo es la distancia (d050…),
        # siempre estricto → mide sesiones/posiciones nuevas con voces conocidas.
        grupo = grupo_distancia if args.por_distancia else grupo_locutor
        estricto = args.loso_estricto or args.por_distancia
        grupos = np.array([grupo(n) if l == IDX_POS else
                           (grupo(n).replace("legacy", "neg") if estricto else "neg")
                           for n, l in zip(datos["nombres"], L)])
        idx_neg = np.where(grupos == "neg")[0]
        locutores = sorted(g for g in set(grupos) if g not in ("neg", "legacy"))
        log(f"  Grupos hola_neo: " + "  ".join(
            f"{g}={int((grupos==g).sum())}" for g in sorted(set(grupos)) if g != "neg"))
        for k, loc in enumerate(locutores):
            log(f"\n{'#' * 60}\n  TEST = locutor {loc}\n{'#' * 60}")
            fijar_semillas(args.seed + k)
            neg_tv, neg_test = train_test_split(idx_neg, test_size=0.20, stratify=L[idx_neg],
                                                random_state=args.seed + k)
            idx_test = np.concatenate([np.where(grupos == loc)[0], neg_test])
            idx_tv = np.concatenate([np.where((grupos != loc) & (grupos != "neg"))[0], neg_tv])
            idx_train, idx_val = train_test_split(idx_tv, test_size=0.20, stratify=L[idx_tv],
                                                  random_state=args.seed + k)
            r = evaluar_split(datos, idx_train, idx_val, idx_test, args, log,
                              output_dir / f"test_{loc}", verbose=2)
            r["locutor_test"] = loc
            resultados.append(r)
        resumen_cv(resultados, log, "Leave-one-speaker-out (hola_neo)")

    else:
        # ── Split único (comportamiento original) ─────────────────────────────
        log(f"\n[2/5] Dividiendo originales en train / val / test ...")
        idx_train, idx_val, idx_test = split_unico(datos, args.seed)
        log(f"\n[3-5/5] Entrenando, evaluando y exportando...")
        res = evaluar_split(datos, idx_train, idx_val, idx_test, args, log, output_dir)
        resultados.append(res)

        # Escribir umbrales.json para gen_vocabulario.py
        ruta_umbrales = output_dir / "umbrales.json"
        ruta_umbrales.write_text(json.dumps({CLASES[IDX_POS]: round(res["umbral"], 4)},
                                            indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"\n  Umbrales guardados: {ruta_umbrales}")
        log("  Regenera el header del firmware:")
        log(f"    python tools/gen_vocabulario.py --umbrales {ruta_umbrales}")

    (output_dir / "metricas.json").write_text(
        json.dumps(_json_limpio(resultados), indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"\n  Salidas en : {output_dir.resolve()}")
    log("=" * 60)
    log.guardar(output_dir / "entrenamiento_log.txt")


if __name__ == "__main__":
    main()
