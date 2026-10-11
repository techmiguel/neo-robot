#!/usr/bin/env python3
"""
autoroute.py — Completa con Freerouting las conexiones que route_power.py no traza a mano
(señales, puntos de prueba, retornos a los planos), sin tocar el cobre existente.

  export <pcb> <dir> [drc.json]  copia el PCB (y su .kicad_pro) a <dir>, bloquea todo el cobre,
                          marca In3.GND como plano y exporta <dir>/neo.dsn. Las netas de
                          corriente media (VBUS hacia el cargador, PACK_P) pasan a una clase
                          de 0,4 mm.
  merge <pcb> <dir>       importa <dir>/neo.ses sobre la copia y añade al PCB real solo las
                          pistas y vías nuevas (las que no existían, comparando geometría,
                          capa y neta). Comprueba que el ruteo no haya movido cobre existente.

Freerouting (v2.1.0, GPL-3) se ejecuta aparte:
  java -jar freerouting.jar -de <dir>/neo.dsn -do <dir>/neo.ses -mp 40 --gui.enabled=false
Ejecutar con el python3.12 de KiCad 9.
"""
import json
import os
import re
import shutil
import sys

import pcbnew

WIDE = {"VBUS": 0.4, "/Alimentacion/PACK_P": 0.4}   # mm


def key(t):
    if t.Type() == pcbnew.PCB_VIA_T:
        p = t.GetPosition()
        return ("V", p.x, p.y, t.GetNetname())
    s, e = t.GetStart(), t.GetEnd()
    a, b = sorted([(s.x, s.y), (e.x, e.y)])
    return ("T", a, b, t.GetLayer(), t.GetNetname())


def export(pcb, d, drc_json=None):
    os.makedirs(d, exist_ok=True)
    base = os.path.splitext(pcb)[0]
    shutil.copy(pcb, os.path.join(d, "neo.kicad_pcb"))
    shutil.copy(base + ".kicad_pro", os.path.join(d, "neo.kicad_pro"))
    board = pcbnew.LoadBoard(os.path.join(d, "neo.kicad_pcb"))
    for t in board.GetTracks():
        t.SetLocked(True)
    board.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_POWER)
    dsn = os.path.join(d, "neo.dsn")
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        raise SystemExit("falló la exportación DSN")
    txt = open(dsn, encoding="utf-8").read()
    # clase de corriente media: se quitan las netas de la lista de su clase (bloque que va de
    # "(class <nombre>" hasta "(circuit") y se declara una clase nueva
    def strip_names(m):
        head, body = m.group(1), m.group(2)
        toks = re.findall(r'"[^"]*"|\S+', body)
        toks = [t for t in toks if t.strip('"') not in WIDE]
        return head + " " + " ".join(toks) + "\n      (circuit"
    txt = re.sub(r'(\(class \S+)((?:\s+(?:"[^"]*"|[^\s()]+))*)\s*\(circuit', strip_names, txt)
    names = " ".join(f'"{n}"' if re.search(r'[\s/()]', n) else n for n in WIDE)
    w = int(max(WIDE.values()) * 1000)
    cls = (f'    (class media_corriente {names}\n      (circuit\n        (use_via "Via[0-3]_600:300_um")\n'
           f'      )\n      (rule\n        (width {w})\n        (clearance 150)\n      )\n    )\n')
    txt = txt.replace("  (wiring", cls + "  (wiring", 1) if "(class media" not in txt else txt
    # Netas a rutear: solo las que la DRC de KiCad da por incompletas (sin GND ni +5V, que se
    # resuelven con zonas y vías a los planos). El resto pasa a la clase "completa", que
    # Freerouting ignora (-inc completa): sus pads y su cobre siguen siendo obstáculos.
    if drc_json:
        pending = set()
        for v in json.load(open(drc_json))["unconnected_items"]:
            for it in v["items"]:
                m = re.search(r"\[([^\]]+)\]", it["description"])
                if m:
                    pending.add(m.group(1))
        pending -= {"GND", "+5V"}
        allnets = set(re.findall(r'\(net ("[^"]*"|\S+)\s*\n?\s*\(pins', txt))
        done = [n for n in allnets if n.strip('"') not in pending]
        def strip_done(m):
            toks = re.findall(r'"[^"]*"|\S+', m.group(2))
            toks = [t for t in toks if t in WIDE or t.strip('"') in pending]
            return m.group(1) + " " + " ".join(toks) + "\n      (circuit"
        txt = re.sub(r'(\(class (?!media_corriente)\S+)((?:\s+(?:"[^"]*"|[^\s()]+))*)\s*\(circuit',
                     strip_done, txt)
        cls = ("    (class completa " + " ".join(sorted(done)) +
               "\n      (circuit\n        (use_via \"Via[0-3]_406.4:203.2_um\")\n      )\n"
               "      (rule\n        (width 156.464)\n        (clearance 125)\n      )\n    )\n")
        txt = txt.replace("  (wiring", cls + "  (wiring", 1)
        print(f"netas a rutear: {len(pending)}; ignoradas: {len(done)}")
    open(dsn, "w", encoding="utf-8").write(txt)
    print("DSN:", dsn)


def merge(pcb, d):
    ref = pcbnew.LoadBoard(pcb)
    before = {key(t) for t in ref.GetTracks()}
    work = pcbnew.LoadBoard(os.path.join(d, "neo.kicad_pcb"))
    if not pcbnew.ImportSpecctraSES(work, os.path.join(d, "neo.ses")):
        raise SystemExit("falló la importación SES")
    after = {key(t): t for t in work.GetTracks()}
    lost = before - set(after)
    if lost:
        print(f"aviso: {len(lost)} elementos existentes no aparecen en la sesión (no se tocan en el PCB real)")
    added = 0
    for k, t in after.items():
        if k in before:
            continue
        n = ref.FindNet(t.GetNetname())
        if t.Type() == pcbnew.PCB_VIA_T:
            v = pcbnew.PCB_VIA(ref)
            v.SetPosition(t.GetPosition())
            v.SetWidth(t.GetWidth(pcbnew.F_Cu))
            v.SetDrill(t.GetDrill())
            v.SetNet(n)
            ref.Add(v)
            v.thisown = 0
        else:
            c = pcbnew.PCB_TRACK(ref)
            c.SetStart(t.GetStart())
            c.SetEnd(t.GetEnd())
            c.SetWidth(t.GetWidth())
            c.SetLayer(t.GetLayer())
            c.SetNet(n)
            ref.Add(c)
            c.thisown = 0
        added += 1
    pcbnew.SaveBoard(pcb, ref)
    b2 = pcbnew.LoadBoard(pcb)
    pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
    pcbnew.SaveBoard(pcb, b2)
    print(f"añadidos {added} elementos del autorruteo")


if __name__ == "__main__":
    {"export": export, "merge": merge}[sys.argv[1]](*sys.argv[2:])
