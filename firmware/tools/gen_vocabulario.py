#!/usr/bin/env python3
"""
gen_vocabulario.py — Genera src/models/vocabulario.h desde tools/vocabulario.json

Fuente única de verdad del vocabulario: firmware de captura, entrenamiento e
inferencia leen las mismas clases.

Uso:
    python tools/gen_vocabulario.py
    python tools/gen_vocabulario.py --umbrales models/umbrales.json

--umbrales: JSON {clase: umbral} escrito por train_model.py tras calcular el
umbral óptimo por clase (criterio de Youden sobre el set de validación).
Sin este argumento se usa "umbral_defecto" del vocabulario.
"""
import argparse
import json
import sys
from pathlib import Path

# Ordinales exactos del enum Comando en src/commands/dispatcher.h
# (mantener sincronizado si se reordena el enum)
COMANDO_ORDINALES = {
    "DESCONOCIDO": 0, "HOLA_NEO": 1, "CLIMA": 2, "NOTICIAS": 3,
    "ELTOQUE": 4, "CRIPTO": 5, "TEMPORIZADOR": 6, "BUSCAR": 7,
    "TRADUCIR": 8, "RECORDATORIO": 9, "CALCULAR": 10, "TRIVIA": 11, "DADO": 12,
}


def main():
    raiz = Path(__file__).resolve().parent.parent   # firmware/

    parser = argparse.ArgumentParser()
    parser.add_argument("--vocab", default=str(raiz / "tools" / "vocabulario.json"))
    parser.add_argument("--out",   default=str(raiz / "src" / "models" / "vocabulario.h"))
    parser.add_argument("--umbrales", default=None,
                        help="models/umbrales.json generado por train_model.py (opcional)")
    args = parser.parse_args()

    vocab = json.loads(Path(args.vocab).read_text(encoding="utf-8"))
    clases = vocab["clases"]
    defecto = float(vocab.get("umbral_defecto", 0.85))

    umbrales = {}
    if args.umbrales and Path(args.umbrales).exists():
        umbrales = json.loads(Path(args.umbrales).read_text(encoding="utf-8"))
        print(f"  Umbrales desde: {args.umbrales}")
    else:
        print(f"  Umbrales: defecto {defecto} (ejecuta train_model.py y pasa --umbrales)")

    nombres  = [c["nombre"] for c in clases]
    n = len(nombres)

    comandos, es_comando, umb = [], [], []
    for c in clases:
        cmd = c.get("comando")
        if cmd is None:
            comandos.append(COMANDO_ORDINALES["DESCONOCIDO"])
            es_comando.append("false")
        else:
            if cmd not in COMANDO_ORDINALES:
                sys.exit(f"ERROR: comando desconocido en vocabulario.json: {cmd}")
            comandos.append(COMANDO_ORDINALES[cmd])
            es_comando.append("true")
        umb.append(f"{float(umbrales.get(c['nombre'], defecto)):.4f}f")

    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    def c_str(vals):
        return ", ".join('"' + str(v) + '"' for v in vals)

    with dst.open("w", encoding="utf-8") as f:
        f.write("// GENERADO por gen_vocabulario.py desde tools/vocabulario.json\n")
        f.write("// NO editar manualmente — regenerar tras cambiar el vocabulario\n")
        f.write("#pragma once\n")
        f.write("#include <stdint.h>\n\n")
        f.write(f"#define VOCAB_N_CLASES {n}\n\n")
        f.write("static const char* const VOCAB_CLASES[VOCAB_N_CLASES]    = {" + c_str(nombres) + "};\n")
        f.write("static const char* const VOCAB_FRASES[VOCAB_N_CLASES]    = {" + c_str([c['frase'] for c in clases]) + "};\n")
        f.write(f"static const uint16_t    VOCAB_OBJETIVOS[VOCAB_N_CLASES] = {{{', '.join(str(c['objetivo']) for c in clases)}}};\n")
        f.write(f"static const bool        VOCAB_ES_COMANDO[VOCAB_N_CLASES] = {{{', '.join(es_comando)}}};\n")
        f.write(f"static const float       VOCAB_UMBRALES[VOCAB_N_CLASES]  = {{{', '.join(umb)}}};\n")
        # Valor del enum Comando (dispatcher.h) por índice de clase
        f.write(f"static const int         VOCAB_COMANDO[VOCAB_N_CLASES]   = {{{', '.join(str(x) for x in comandos)}}};\n")

    print(f"  Generado: {dst}  ({n} clases)")
    for i, c in enumerate(clases):
        marca = "cmd" if c.get("comando") else "   "
        print(f"    [{i}] {marca} {c['nombre']:<12} objetivo={c['objetivo']:>4}  umbral={umb[i][:-1]}")


if __name__ == "__main__":
    main()
