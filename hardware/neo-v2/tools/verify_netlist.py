#!/usr/bin/env python3
"""
verify_netlist.py — Verificación formal del esquemático de NEO v2 contra:
  1) la netlist del diseño original (Nabu Casa): todo pin heredado conservado debe seguir en
     la misma neta, salvo los renombres declarados en RENAMES;
  2) la conectividad pretendida de las hojas nuevas (docs/data/intent_new_sheets.json):
     cada pin nuevo debe estar en la neta prevista y cada neta prevista debe ser una sola neta
     de KiCad, sin pines ajenos.
Uso: python3 verify_netlist.py <netlist_original.net> <netlist_neo.net> <intent.json>
"""
import collections
import json
import os
import sys

from netlist import pin_to_net, read

RENAMES = {"GROVE_SDA": "CHG_PG", "GROVE_SCL": "ESP_IO2", "GROVE_PWR": "ESP_IO46"}
REMOVED = {"C100", "C118", "C32", "C79", "C84", "C85", "C98", "C99", "D15", "D17", "D21", "FB11", "J4", "Q5",
           "Q7", "R117", "R118", "R137", "R140", "R141", "R144", "R145", "R40", "R64", "R65", "R67", "TP34",
           "TP5", "U13", "U20"}


def main(base_p, neo_p, intent_p):
    nb, cb = read(base_p)
    nn, cn = read(neo_p)
    intent = json.load(open(intent_p))
    pb, pn = pin_to_net(nb), pin_to_net(nn)
    errors = []

    # --- 1. heredado
    removed = set(cb) - set(cn)
    if removed != REMOVED:
        errors.append(f"componentes eliminados distintos de lo previsto: sobran {sorted(removed - REMOVED)}, "
                      f"faltan {sorted(REMOVED - removed)}")
    dup = [r for r in cn if r in cb and cn[r]["value"] != cb[r]["value"]]
    if dup:
        errors.append(f"referencias heredadas con otro valor (¿colisión de referencias?): {dup}")
    for net, pins in nb.items():
        keep = [p for p in pins if p.split(".")[0] in cn]
        groups = collections.defaultdict(list)
        for p in keep:
            groups[pn.get(p)].append(p)
        if len(groups) > 1:
            errors.append(f"neta heredada partida {net}: {dict(groups)}")
        for newnet, ps in groups.items():
            exp = RENAMES.get(net, net)
            if newnet != exp and not (net.startswith("Net-(") or net.startswith("unconnected")):
                errors.append(f"neta heredada {net} ahora se llama {newnet} (esperado {exp})")
    # --- 2. hojas nuevas
    by_net = collections.defaultdict(set)
    for pin, net in intent.items():
        if net == "NC":
            if pin in pn and not pn[pin].startswith("unconnected"):
                errors.append(f"{pin} debía quedar sin conectar y está en {pn[pin]}")
            continue
        by_net[net].add(pin)
        if pin not in pn:
            errors.append(f"pin nuevo {pin} ausente de la netlist")
    for net, pins in by_net.items():
        got = {pn.get(p) for p in pins}
        if len(got) != 1:
            errors.append(f"neta pretendida {net} repartida en {got}")
            continue
        real = got.pop()
        if real != net:
            errors.append(f"neta pretendida {net} se llama {real} en KiCad")
        foreign = {p for p in nn.get(real, set()) if p.split(".")[0] not in cb and p not in pins}
        if foreign:
            errors.append(f"neta {net}: pines nuevos no previstos {sorted(foreign)}")
    new_refs = {p.split(".")[0] for p in intent}
    # --- 3. huellas de las piezas nuevas: asignadas y existentes en una biblioteca
    here = os.path.dirname(os.path.abspath(__file__))
    for ref in sorted(new_refs):
        fp = cn.get(ref, {}).get("footprint", "")
        if not fp:
            errors.append(f"{ref} sin huella asignada")
            continue
        lib, name = fp.split(":", 1)
        cands = [os.path.join(here, "..", "kicad", "lib", f"{lib}.pretty", f"{name}.kicad_mod"),
                 f"/usr/share/kicad/footprints/{lib}.pretty/{name}.kicad_mod"]
        if not any(os.path.exists(c) for c in cands):
            errors.append(f"{ref}: huella {fp} no encontrada en ninguna biblioteca")
    extra = set(cn) - set(cb) - new_refs
    if extra:
        errors.append(f"componentes en la netlist que no están ni en el original ni en las hojas nuevas: {sorted(extra)}")
    print(f"original: {len(cb)} componentes, {len(nb)} netas | NEO v2: {len(cn)} componentes, {len(nn)} netas")
    print(f"eliminados {len(removed)}, nuevos {len(set(cn) - set(cb))}, pines nuevos comprobados {len(intent)}")
    if errors:
        print("ERRORES:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print("OK: heredado intacto salvo cambios declarados; hojas nuevas conectadas según lo previsto")


if __name__ == "__main__":
    main(*sys.argv[1:4])
