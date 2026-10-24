# Pre-script de PlatformIO: ajusta el library.json de esp-tflite-micro y de esp-nn.
#
# esp-tflite-micro:
#   - Sin excepciones ni RTTI. Con -fexceptions (el valor por defecto de Arduino-ESP32),
#     decode_state.cc no compila ("operator delete ... is private").
#   - Sin los kernels de referencia que ESP-NN reemplaza (kernels/esp_nn/*.cc define los
#     mismos símbolos con las rutinas SIMD del S3); es lo que hace su CMakeLists.txt.
# esp-nn: no trae library.json. Se compilan las fuentes C genéricas y las del S3 (.S),
#   no las del P4, con los flags de su CMakeLists.txt.
#
# Los library.json viven en .pio/libdeps/ (fuera de git): este script los deja así en cada
# entorno antes de compilar, también en un clon nuevo.
Import("env")  # noqa: F821  (lo inyecta PlatformIO)

import json
from pathlib import Path

LIBDEPS = Path(env.subst("$PROJECT_LIBDEPS_DIR")) / env.subst("$PIOENV")  # noqa: F821

KERNELS_ESP_NN = ["add", "conv", "depthwise_conv", "fully_connected", "mul", "pooling", "softmax"]
TFLITE = {
    "flags": ["-fno-rtti", "-fno-exceptions", "-fno-threadsafe-statics"],
    "srcFilter": ["+<*>", "-<.git/>", "-<examples/>", "-<test/>", "-<tests/>"]
                 + [f"-<tensorflow/lite/micro/kernels/{k}.cc>" for k in KERNELS_ESP_NN],
}
ESP_NN = {
    "flags": ["-I" + (LIBDEPS / "esp-nn" / "src" / "common").as_posix(),
              "-mlongcalls", "-fno-unroll-loops", "-O2", "-Wno-unused-function"],
    "srcFilter": ["+<*>", "-<convolution/esp_nn_conv_esp32p4.c>"],
}


def parchear(lib, build, nombre):
    ruta = LIBDEPS / lib / "library.json"
    if not ruta.parent.exists():
        return
    datos = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {"name": nombre}
    if datos.get("build") != build:
        datos["build"] = build
        ruta.write_text(json.dumps(datos, indent=2) + "\n", encoding="utf-8")
        print(f"parche_tflite: build {build} en {ruta}")


parchear("esp-tflite-micro", TFLITE, "esp-tflite-micro")
parchear("esp-nn", ESP_NN, "esp-nn")
