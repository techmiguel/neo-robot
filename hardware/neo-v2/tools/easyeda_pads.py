#!/usr/bin/env python3
"""
easyeda_pads.py — Descarga la huella que LCSC/JLCPCB asocian a un número LCSC (API de
EasyEDA) y lista sus pads en mm, relativos al origen de la huella. Sirve como segunda
referencia independiente para verificar huellas de KiCad.
Uso: python3 easyeda_pads.py C2682616
"""
import json
import subprocess
import sys

MIL10 = 0.254  # 1 unidad EasyEDA = 10 mil


def fetch(code):
    url = f"https://easyeda.com/api/products/{code}/components?version=6.4.19.5"
    out = subprocess.run(["curl", "-sS", "-m", "40", url], capture_output=True, text=True).stdout
    return json.loads(out)["result"]


def pads(code):
    r = fetch(code)
    pkg = r["packageDetail"]
    ds = pkg["dataStr"]
    ox, oy = float(ds["head"]["x"]), float(ds["head"]["y"])
    res = []
    for s in ds["shape"]:
        f = s.split("~")
        if f[0] == "PAD":
            shape, x, y, w, h, layer, _net, num = f[1], float(f[2]), float(f[3]), float(f[4]), float(f[5]), f[6], f[7], f[8]
            hole = float(f[9]) * 2 * MIL10 if f[9] not in ("", "0") else None
            rot = float(f[11]) if len(f) > 11 and f[11] not in ("",) else 0.0
            if rot in (90.0, 270.0):
                w, h = h, w
            res.append({"num": num, "shape": shape, "x": round((x - ox) * MIL10, 3),
                        "y": round((y - oy) * MIL10, 3), "w": round(w * MIL10, 3),
                        "h": round(h * MIL10, 3), "drill": round(hole, 3) if hole else None})
    return pkg["title"], res


if __name__ == "__main__":
    title, ps = pads(sys.argv[1])
    print(title)
    for p in ps:
        print(p)
