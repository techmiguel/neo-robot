# Pre-script de PlatformIO: compila esp-tflite-micro sin excepciones ni RTTI.
#
# Con -fexceptions (el valor por defecto de Arduino-ESP32), decode_state.cc no compila
# ("operator delete ... is private"). El flag solo puede aplicarse a esta librería desde
# su library.json, que PlatformIO descarga en .pio/libdeps/ (fuera de git): este script
# lo deja así en cada entorno antes de compilar, también en un clon nuevo.
Import("env")  # noqa: F821  (lo inyecta PlatformIO)

import json
from pathlib import Path

FLAGS = ["-fno-rtti", "-fno-exceptions", "-fno-threadsafe-statics"]

ruta = Path(env.subst("$PROJECT_LIBDEPS_DIR")) / env.subst("$PIOENV") / "esp-tflite-micro" / "library.json"  # noqa: F821
if ruta.exists():
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if datos.get("build", {}).get("flags") != FLAGS:
        datos.setdefault("build", {})["flags"] = FLAGS
        ruta.write_text(json.dumps(datos, indent=2) + "\n", encoding="utf-8")
        print(f"parche_tflite: flags {FLAGS} en {ruta}")
