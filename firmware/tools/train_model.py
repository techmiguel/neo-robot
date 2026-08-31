#!/usr/bin/env python3
"""
train_model.py — Entrena el modelo de wake word "hola_neo" para NEO

Pipeline:
  1. Carga WAVs del dataset (hola_neo / desconocido / silencio)
  2. Extrae características MFCC con tensorflow.signal
  3. Aplica data augmentation (ruido, shift temporal, volumen)
  4. Entrena una CNN pequeña (<40 KB en int8)
  5. Muestra accuracy, matriz de confusión y curvas de entrenamiento
  6. Exporta models/modelo_float.tflite y models/modelo_int8.tflite

Uso:
    cd firmware/
    python tools/train_model.py
    python tools/train_model.py --dataset ruta/dataset --epocas 50
"""

import argparse
import wave
import numpy as np
import tensorflow as tf
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import (confusion_matrix, classification_report,
                             roc_curve, auc)
from sklearn.utils.class_weight import compute_class_weight
import matplotlib
matplotlib.use("Agg")   # sin ventana gráfica; guarda PNG
import matplotlib.pyplot as plt

# ── Configuración ─────────────────────────────────────────────────────────────
CLASES = ["hola_neo", "desconocido", "silencio"]
SR     = 16000   # Hz — debe coincidir con el firmware de captura

# Parámetros MFCC — deben ser idénticos a la implementación C++ en el ESP32
FRAME_LENGTH = 400    # 25 ms a 16 kHz
FRAME_STEP   = 160    # 10 ms a 16 kHz  → stride de inferencia en el ESP32
FFT_LENGTH   = 512    # potencia de 2 >= FRAME_LENGTH; tf.signal.stft usa esta por defecto
NUM_SPEC_BINS = FFT_LENGTH // 2 + 1  # 257 bins de frecuencia
NUM_MEL_BINS = 40
NUM_MFCC     = 40
FREQ_MIN     = 20.0   # Hz
FREQ_MAX     = 8000.0 # Hz


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
    mfcc = tf.signal.mfccs_from_log_mel_spectrograms(log_mel)
    return mfcc.numpy()[:, :NUM_MFCC]              # (frames, NUM_MFCC)


# ── Data augmentation ─────────────────────────────────────────────────────────

def aumentar(audio: np.ndarray) -> list:
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

    # Desplazamiento temporal ±150 ms
    shift = int(0.15 * SR)
    variantes.append(np.roll(audio,  shift).astype(np.float32))
    variantes.append(np.roll(audio, -shift).astype(np.float32))

    # Cambio de volumen ±20 %
    for factor in (0.8, 1.2):
        variantes.append(np.clip(audio * factor, -1, 1).astype(np.float32))

    return variantes   # 7 variantes por muestra original


def aumentar_desconocido(audio: np.ndarray) -> list:
    """
    15 variantes para la clase desconocido (vs 7 de hola_neo).
    Más diversidad para compensar el menor tamaño de la clase.
    """
    n = len(audio)
    variantes = aumentar(audio)   # 7 base

    # Ruido muy suave (SNR=30) y muy fuerte (SNR=6)
    for snr_db in (30, 6):
        p_s = np.mean(audio ** 2) + 1e-9
        p_r = p_s / (10 ** (snr_db / 10))
        variantes.append(np.clip(audio + np.random.randn(n).astype(np.float32) * np.sqrt(p_r), -1, 1))

    # Desplazamiento temporal ±300 ms
    shift300 = int(0.30 * SR)
    variantes.append(np.roll(audio,  shift300).astype(np.float32))
    variantes.append(np.roll(audio, -shift300).astype(np.float32))

    # Volumen más extremo
    for factor in (0.5, 1.5):
        variantes.append(np.clip(audio * factor, -1, 1).astype(np.float32))

    # Combinadas: ruido SNR=15 + shift
    p_s = np.mean(audio ** 2) + 1e-9
    r15 = np.random.randn(n).astype(np.float32) * np.sqrt(p_s / (10 ** (15 / 10)))
    variantes.append(np.clip(np.roll(audio + r15, int(0.10 * SR)), -1, 1).astype(np.float32))

    # Combinada: ruido SNR=10 + volumen reducido
    r10 = np.random.randn(n).astype(np.float32) * np.sqrt(p_s / (10 ** (10 / 10)))
    variantes.append(np.clip((audio + r10) * 0.9, -1, 1).astype(np.float32))

    return variantes   # 15 variantes


def aumentar_silencio(audio: np.ndarray) -> list:
    """
    10 variantes para la clase silencio.
    """
    n = len(audio)
    variantes = aumentar(audio)   # 7 base

    # Ruido muy suave (SNR=30)
    p_s = np.mean(audio ** 2) + 1e-9
    r30 = np.random.randn(n).astype(np.float32) * np.sqrt(p_s / (10 ** (30 / 10)))
    variantes.append(np.clip(audio + r30, -1, 1))

    # Volumen reducido
    variantes.append(np.clip(audio * 0.6, -1, 1).astype(np.float32))

    # Desplazamiento +200 ms
    variantes.append(np.roll(audio, int(0.20 * SR)).astype(np.float32))

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

    for filtros in (16, 32, 64):
        x = tf.keras.layers.Conv2D(filtros, (3, 3), padding="same")(x)
        x = tf.keras.layers.BatchNormalization()(x)
        x = tf.keras.layers.ReLU()(x)
        x = tf.keras.layers.MaxPooling2D((2, 2))(x)

    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dense(64, activation="relu", kernel_regularizer=reg)(x)
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
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
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    output_dir  = Path(args.output)

    # ── 1. Cargar audios crudos ──────────────────────────────────────────────
    print("=" * 55)
    print("  NEO — Entrenamiento wake word")
    print("=" * 55)
    print(f"\n[1/5] Cargando dataset desde '{dataset_dir}'...")

    audios_por_clase: dict[str, list] = {c: [] for c in CLASES}
    for clase in CLASES:
        wavs = sorted((dataset_dir / clase).glob("*.wav"))
        for ruta in wavs:
            audios_por_clase[clase].append(cargar_wav(ruta))
        print(f"  {clase:<20}: {len(wavs):>4} archivos")

    total_original = sum(len(v) for v in audios_por_clase.values())
    if total_original == 0:
        print("\nERROR: no se encontraron archivos WAV en el dataset.")
        return

    # Longitud fija = mediana de todas las muestras
    todas = [len(a) for audios in audios_por_clase.values() for a in audios]
    longitud = int(np.median(todas))
    print(f"\n  Longitud fija   : {longitud} muestras  ({longitud/SR:.2f} s)")
    print(f"  Augmentation    : {'sí (hola×14, desc×30, sil×20 + SpecAugment)' if args.augment else 'no'}")

    # ── 2. Split sobre originales (ANTES de augmentación) ───────────────────
    # Crítico: si se augmenta primero y se splitea después, versiones del mismo
    # audio original quedan en train Y test → el modelo memoriza en lugar de
    # generalizar (data leakage → accuracy artificialmente alto).
    print(f"\n[2/5] Dividiendo originales en train / val / test ...")

    audios_flat, labels_flat = [], []
    for idx_clase, clase in enumerate(CLASES):
        for audio in audios_por_clase[clase]:
            audios_flat.append(ajustar_longitud(audio, longitud))
            labels_flat.append(idx_clase)

    a_tv, a_test, l_tv, l_test = train_test_split(
        audios_flat, labels_flat, test_size=0.20, stratify=labels_flat, random_state=42)
    a_train, a_val, l_train, l_val = train_test_split(
        a_tv, l_tv, test_size=0.20, stratify=l_tv, random_state=42)

    print(f"  Originales  ->  Train: {len(a_train)}  Val: {len(a_val)}  Test: {len(a_test)}")

    # ── 3. Extraer MFCC (augmentación solo en train) ─────────────────────────
    print(f"\n[3/5] Extrayendo MFCC (frame={FRAME_LENGTH}, fft={FFT_LENGTH}, mel={NUM_MEL_BINS})...")

    def preparar(audios, labels, aumentar_datos: bool) -> tuple:
        """
        Extrae MFCC con augmentación por clase:
          hola_neo (0)    →  7 variantes de audio
          desconocido (1) → 15 variantes de audio
          silencio (2)    → 10 variantes de audio
        Cada variante también genera una copia con SpecAugment,
        duplicando el conjunto sin añadir más audio grabado.
        """
        _aug_fn = [aumentar, aumentar_desconocido, aumentar_silencio]
        X, y = [], []
        for audio, label in zip(audios, labels):
            fn = _aug_fn[label] if aumentar_datos else (lambda a: [a])
            for v in fn(audio):
                mfcc = extraer_mfcc(ajustar_longitud(v, longitud))
                X.append(mfcc)
                y.append(label)
                if aumentar_datos:
                    X.append(spec_augment(mfcc))
                    y.append(label)
        return (np.array(X, dtype=np.float32)[..., np.newaxis],
                np.array(y, dtype=np.int32))

    X_train, y_train = preparar(a_train, l_train, aumentar_datos=args.augment)
    X_val,   y_val   = preparar(a_val,   l_val,   aumentar_datos=False)
    X_test,  y_test  = preparar(a_test,  l_test,  aumentar_datos=False)

    print(f"  Tras augmentation ->  Train: {len(X_train)}  Val: {len(X_val)}  Test: {len(X_test)}")
    for i, clase in enumerate(CLASES):
        print(f"  {clase:<20}: {(y_train == i).sum():>4} en train  "
              f"{(y_test == i).sum():>4} en test")

    # ── 4. Construir y entrenar ──────────────────────────────────────────────
    print(f"\n[4/5] Construyendo y entrenando modelo...")

    modelo = construir_modelo(X_train.shape[1:], len(CLASES))
    modelo.summary(print_fn=lambda s: print("  " + s))

    modelo.compile(
        optimizer=tf.keras.optimizers.Adam(1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )

    # Pesos inversamente proporcionales a la frecuencia de cada clase.
    # Evita que la clase mayoritaria (hola_neo) domine el gradiente.
    pesos = compute_class_weight("balanced", classes=np.unique(y_train), y=y_train)
    class_weight = dict(enumerate(pesos))
    print(f"  Class weights: { {CLASES[k]: f'{v:.2f}' for k, v in class_weight.items()} }")

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",          # más estable que val_accuracy con val pequeño
            patience=15,                 # era 10; da margen para escapar de mínimos locales
            min_delta=0.005,
            restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.3, patience=7, min_lr=1e-5, verbose=1),
    ]

    historial = modelo.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=args.epocas,
        batch_size=32,
        callbacks=callbacks,
        class_weight=class_weight,
    )

    # ── 5. Evaluar y exportar ────────────────────────────────────────────────
    print(f"\n[5/5] Evaluando y exportando...")

    _, acc = modelo.evaluate(X_test, y_test, verbose=0)
    print(f"\n  Accuracy en test : {acc * 100:.1f}%")

    y_pred = np.argmax(modelo.predict(X_test, verbose=0), axis=1)

    print("\n  Matriz de confusión (filas=real, columnas=predicho):")
    cm = confusion_matrix(y_test, y_pred)
    ancho = max(len(c) for c in CLASES) + 2
    header = " " * ancho + "".join(f"{c:>{ancho}}" for c in CLASES)
    print("  " + header)
    for i, clase in enumerate(CLASES):
        fila = f"{clase:>{ancho}}" + "".join(f"{cm[i,j]:>{ancho}}" for j in range(len(CLASES)))
        print("  " + fila)

    print("\n" + classification_report(y_test, y_pred, target_names=CLASES,
                                       digits=3, zero_division=0))

    # ── Umbral óptimo para hola_neo (criterio de Youden sobre el val set) ───────
    y_val_bin  = (np.array(l_val) == 0).astype(int)
    scores_val = modelo.predict(X_val, verbose=0)[:, 0]
    fpr, tpr, thresholds_roc = roc_curve(y_val_bin, scores_val)
    J       = tpr - fpr
    idx_opt = int(np.argmax(J))
    thr_opt = float(thresholds_roc[idx_opt])
    roc_auc = auc(fpr, tpr)
    print(f"\n  AUC hola_neo (val)     : {roc_auc:.3f}")
    print(f"  Umbral óptimo sugerido : {thr_opt:.3f}  "
          f"(FPR={fpr[idx_opt]*100:.1f}%  TPR={tpr[idx_opt]*100:.1f}%)")
    print(f"  -> inference.h : static constexpr float UMBRAL = {thr_opt:.3f}f;")

    # Gráficas
    output_dir.mkdir(parents=True, exist_ok=True)
    ep = range(1, len(historial.history["loss"]) + 1)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    ax1.plot(ep, historial.history["loss"],          label="train")
    ax1.plot(ep, historial.history["val_loss"],      label="val")
    ax1.set_xlabel("Época"); ax1.set_title("Loss"); ax1.legend()
    ax2.plot(ep, historial.history["accuracy"],      label="train")
    ax2.plot(ep, historial.history["val_accuracy"],  label="val")
    ax2.set_xlabel("Época"); ax2.set_title("Accuracy"); ax2.legend()
    ruta_plot = output_dir / "entrenamiento.png"
    fig.savefig(ruta_plot, dpi=100, bbox_inches="tight")
    plt.close()
    print(f"  Gráfica guardada : {ruta_plot}")

    # Exportar TFLite
    print("\n  Exportando TFLite:")
    idx_rep = np.random.choice(len(X_train), min(200, len(X_train)), replace=False)
    exportar_tflite(modelo, X_train[idx_rep], output_dir)

    print(f"\n  Modelos en : {output_dir.resolve()}")
    print("=" * 55)


if __name__ == "__main__":
    main()
