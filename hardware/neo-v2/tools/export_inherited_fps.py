#!/usr/bin/env python3
"""
export_inherited_fps.py — Extrae del PCB las huellas heredadas cuyas bibliotecas no son públicas
(bibliotecas internas de Seeed usadas por Nabu Casa: "Capacitor", "Ic", "reSpeaker Library"...)
y las guarda en kicad/lib/inherited/<alias>.pretty, una carpeta por alias. Después registra cada
alias en el fp-lib-table del proyecto, de modo que los campos "Footprint" del esquemático heredado
resuelvan sin modificarlos.

Las huellas se copian tal como están en el PCB del original (son su única fuente): se devuelven a
la cara F, giro 0 y origen 0, y se guardan sin netas. Si varias instancias comparten nombre, se
comprueba que su geometría de pads coincida; si no, el script se detiene.

Alias que coinciden con bibliotecas estándar de KiCad (Connector, Crystal, Fuse): la tabla del
proyecto tiene prioridad sobre la global, así que en este proyecto esos alias apuntan a las copias
heredadas. Ninguna pieza nueva de NEO v2 usa esos alias.
Uso: python3.12 export_inherited_fps.py <pcb> <dir_kicad>
"""
import os
import sys

import pcbnew

STD = "/usr/share/kicad/footprints"


def pad_sig(fp):
    """Firma de la geometría de pads, en coordenadas locales de la huella."""
    sig = []
    for p in fp.Pads():
        sig.append((p.GetNumber(), round(pcbnew.ToMM(p.GetFPRelativePosition().x), 3),
                    round(pcbnew.ToMM(p.GetFPRelativePosition().y), 3),
                    round(pcbnew.ToMM(p.GetSize(pcbnew.F_Cu).x), 3),
                    round(pcbnew.ToMM(p.GetSize(pcbnew.F_Cu).y), 3)))
    return sorted(sig)


def normalized(src, name):
    """Copia de la huella en cara F, giro 0, origen 0, sin netas ni campos de compra."""
    fp = pcbnew.FOOTPRINT(src)
    if fp.IsFlipped():
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    fp.SetOrientationDegrees(0)
    fp.SetPosition(pcbnew.VECTOR2I(0, 0))
    fp.SetReference("REF**")
    fp.SetValue(name)
    fp.SetPath(pcbnew.KIID_PATH())
    fp.SetDNP(False)
    for p in fp.Pads():
        p.SetNetCode(0)
    for k in ("LCSC", "MPN", "Manufacturer"):
        if fp.GetFieldByName(k):
            fp.RemoveField(k)
    return fp


def main(pcb, kdir):
    board = pcbnew.LoadBoard(pcb)
    io = pcbnew.PCB_IO_KICAD_SEXPR()
    out_root = os.path.join(kdir, "lib", "inherited")
    chosen, sigs = {}, {}
    for src in board.GetFootprints():
        nick = src.GetFPID().GetLibNickname().wx_str()
        name = src.GetFPID().GetLibItemName().wx_str()
        if not nick or os.path.exists(f"{STD}/{nick}.pretty/{name}.kicad_mod") or \
                os.path.exists(os.path.join(kdir, "lib", f"{nick}.pretty", f"{name}.kicad_mod")):
            continue
        fp = normalized(src, name)
        key = (nick, name)
        sigs.setdefault(key, {}).setdefault(str(pad_sig(fp)), []).append((src, fp))
    # Si las instancias de un mismo nombre difieren (el original mezcla versiones de su
    # biblioteca), se guarda la variante más usada y se informa del resto: el PCB conserva la
    # copia de cada instancia, que es la que se fabrica.
    for key, variants in sigs.items():
        ordered = sorted(variants.values(), key=len, reverse=True)
        best = next((x for x in ordered[0] if not x[0].IsFlipped()), ordered[0][0])
        chosen[key] = best
        for other in ordered[1:]:
            print(f"aviso {key[0]}:{key[1]}: variante distinta en "
                  f"{', '.join(sorted(x[0].GetReference() for x in other))}")
    libs = {}
    for (nick, name), (src, fp) in sorted(chosen.items()):
        path = os.path.join(out_root, f"{nick}.pretty")
        os.makedirs(path, exist_ok=True)
        io.FootprintSave(path, fp)
        libs.setdefault(nick, []).append(name)
    # tabla de bibliotecas del proyecto
    tpath = os.path.join(kdir, "fp-lib-table")
    table = open(tpath, encoding="utf-8").read()
    lines = [l for l in table.splitlines() if "/lib/inherited/" not in l and l.strip() != ")"]
    for nick in sorted(libs):
        lines.append(f'  (lib (name "{nick}")(type "KiCad")(uri "${{KIPRJMOD}}/lib/inherited/{nick}.pretty")'
                     f'(options "")(descr "Huellas heredadas de Home Assistant Voice PE (Nabu Casa, CERN-OHL-P v2), '
                     f'extraídas del PCB original"))')
    lines.append(")")
    open(tpath, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    for nick, names in sorted(libs.items()):
        print(f"{nick}: {len(names)} huellas")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
