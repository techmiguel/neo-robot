#!/usr/bin/env python3
"""
jlc_bom.py — BOM de fabricación para JLCPCB y comprobación de disponibilidad (fase 6).

  python3.12 jlc_bom.py <netlist> <dir_salida> [--offline]

1. Agrupa las piezas montables de la netlist: excluye las marcadas "no montar", los puntos de
   prueba (son solo pads) y los símbolos sin huella.
2. Busca cada grupo en el buscador de JLCPCB:
   * piezas nuevas (campo LCSC): por su código;
   * piezas heredadas (sin LCSC, con MPN de Seeed/Nabu Casa): por MPN, aceptando solo
     coincidencia exacta de modelo (sin mayúsculas ni caracteres invisibles).
   Si hay varias coincidencias, elige la de más stock. Las heredadas que no están (o no tienen
   stock) llevan un sustituto explícito en SUBST, y las que no tienen equivalente con la misma
   huella se consignan (CONSIGN): entran en la BOM sin código LCSC.
3. Escribe:
   * <dir>/NEO_v2_BOM_JLC.csv: formato de JLCPCB (Comment, Designator, Footprint, LCSC Part #);
   * docs/data/jlc_disponibilidad.csv: grupo por grupo, el código, el tipo (básica o
     extendida), el stock y el estado;
   * docs/data/jlc_cache.json: respuestas en crudo (instantánea con fecha) para --offline.
El stock cambia a diario: el resultado es una instantánea, no una garantía.
"""
import csv
import datetime
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from update_pcb import read_netlist  # noqa: E402

API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "docs", "data")
# Montaje a mano (no SMT en JLCPCB): THT voluminosos o conectores de usuario
HAND = {"BT201": "portapilas THT en la cara B", "J201": "tira de pines para el OLED, opcional"}

# Piezas heredadas sin la referencia original en JLCPCB (o sin stock) y sustituto elegido.
# No se tocan las hojas de Nabu Casa: la sustitución solo existe en la BOM de fabricación.
# (referencias, LCSC, modelo, verificación de huella, nota)
#   "verificada": pads y patillaje comparados con el plano del fabricante del sustituto;
#   "geometría": pads comparados con la huella EasyEDA/LCSC del sustituto (sin plano propio);
#   "sin verificar": ni lo uno ni lo otro.
SUBST = {
    ("D1",): ("C19626254", "PESD0402V05 (DOWO)", "geometría",
              "ESD 5 V bidireccional 0402; pads Δ0,11 mm. Alternativa C316059 BPESD0402-05ST"),
    ("FB12",): ("C883134", "BSMD1206-200-6V (BHFUSE)", "geometría",
                "PTC 2 A/6 V 1206 en lugar de SMD1206R200SF; pads Δ0,05 mm"),
    ("J2",): ("C177225", "Molex 53261-0271", "geometría",
              "JST 1,25 mm 2P en ángulo (PicoBlade); pines Δ0,03 mm, anclajes Δ0,28 mm (mismo tamaño). "
              "Comprobar que el conector del altavoz encaja (WY-3315 original es del mismo paso)"),
    ("J3",): ("C32713277", "HX PZ2.54-2x4P ZZ", "geometría",
              "Tira 2x4 2,54 mm THT: requiere montaje THT de JLC (coste extra) o soldar a mano"),
    ("L3",): ("C2897344", "CQ0201ARNPO8BN3R3 (Yageo)", "geometría",
              "3,3 pF NP0 0201, misma serie con otra tolerancia"),
    ("L6",): ("C98041", "LQP03TN2N2B02D (Murata)", "geometría",
              "2,2 nH 0201 de la misma familia (TN frente a TQ); ajustar en la red de la antena si hace falta"),
    ("LED1",): ("C52917434", "WS2812B-2020-V6 (Worldsemi)", "verificada",
                "Patillaje DO/GND/DI/VDD = 1/2/3/4 y pads ±0,915/±0,55 mm según la hoja V6, p. 2. "
                "VIH 0,55·VDD (2,75 V a 5 V): mejor margen que la versión original con 3,3 V"),
    ("R32",): ("C25092", "0402WGF220JTCE (Uniroyal)", "geometría", "22 Ω 1 % 0402, pieza básica"),
    ("SW3",): ("C20611677", "MK-12C02G1.5-W (HOOYA)", "geometría",
               "Pines 1–3 Δ≤0,04 mm; patas de anclaje desplazadas ~0,35 mm, solapadas con las de la huella"),
    ("U3",): ("C179173", "W25Q32JVSSIQ (Winbond)", "geometría",
              "Flash QSPI del XMOS, SOIC-8 208 mil; pads Δ0,09 mm. Revisar el bit QE (ver riesgos)"),
    ("U4",): ("C22390138", "MSM261DHP006 (MEMS)", "geometría", "Mismo micrófono con otro código LCSC; pads Δ0"),
    ("U9",): ("C7718", "TPA6211A1DGNR (TI)", "geometría", "Mismo MPN, código LCSC distinto; pads Δ0,07 mm"),
    ("U15",): ("C97521", "W25Q128JVSIQ (Winbond)", "geometría",
               "Flash del ESP32-S3, SOIC-8 208 mil; pieza básica. ESP-IDF la soporta de serie"),
    ("C97",): ("C326704", "CC0201BRNPO9BN1R2 (Yageo)", "geometría",
               "Solo por stock (8 uds. del original): misma serie, tolerancia ±0,1 pF en vez de ±0,25 pF"),
    ("R4",): ("C25177", "0402WGJ0681TCE (Uniroyal)", "geometría", "Solo por stock: 680 Ω 5 % 0402"),
    ("R209",): ("C4116370", "CRCW0402665KFKED (Vishay)", "verificada (fase 3)",
                "Solo por stock (36 uds. de C56583): 665 kΩ 1 % 0402, divisor de realimentación del elevador"),
    ("X1",): ("C5210655", "X201624MOB4SI (YXC)", "geometría",
              "24 MHz 12 pF ±10 ppm 2016; pads Δ0,11 mm"),
    ("X2",): ("C49158179", "Y201640MDBCX (JLYE)", "verificada",
              "40 MHz 9 pF ±10 ppm 2016, ESR ≤60 Ω; plano JLYE: pads ±0,64/±0,49 mm frente a ±0,6/±0,5, "
              "pines 2 y 4 a GND como en la huella"),
}
# Piezas sin equivalente en JLCPCB con la misma huella: se consignan (o se sueldan a mano).
CONSIGN = {
    "ANT2": "antena de chip MyAntenna M01-X01210U230 (Seeed 318010843); cambiarla altera la sintonía de RF",
    "J1": "jack 3,5 mm ST-PJ-930A (Seeed 320040142)",
    "SW1": "conmutador lateral DPDT JINBEILI SK-22H07 (Seeed 311010540)",
    "SW2": "encoder con pulsador ZIPPY AN-P1S-2SP-Z (Seeed 311021806)",
    "USB1": "USB-C JINBEILI USB-31C-F-16P-L7.35 (Seeed 320011358); el HRO TYPE-C-31-M-12 no casa con la huella",
}


def norm(s):
    return re.sub(r"[\s​‌‍﻿]", "", (s or "")).upper()


def search(keyword, cache, offline):
    if keyword in cache:
        return cache[keyword]
    if offline:
        return []
    body = json.dumps({"keyword": keyword, "currentPage": 1, "pageSize": 25}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.load(r)
            lst = (d.get("data") or {}).get("componentPageInfo", {}).get("list") or []
            keep = ("componentCode", "componentModelEn", "componentBrandEn", "componentLibraryType",
                    "stockCount", "componentSpecificationEn", "describe", "preferredComponentFlag")
            cache[keyword] = [{k: it.get(k) for k in keep} for it in lst]
            time.sleep(0.4)
            return cache[keyword]
        except Exception as e:  # red: reintento con espera creciente
            time.sleep(2 ** attempt)
            err = e
    raise SystemExit(f"fallo de red buscando {keyword}: {err}")


def main(net, out, *flags):
    offline = "--offline" in flags
    comps, _ = read_netlist(net)
    cache_p = os.path.join(DATA, "jlc_cache.json")
    cache = json.load(open(cache_p, encoding="utf-8"))["consultas"] if os.path.exists(cache_p) else {}
    groups = {}
    for ref, c in comps.items():
        f = c["fields"]
        if c["dnp"] or ref.startswith(("TP", "#", "H")) or not c["footprint"]:
            continue
        key = (f.get("LCSC", "") or "", norm(f.get("MPN", "")), c["value"], c["footprint"])
        groups.setdefault(key, {"refs": [], "mpn": f.get("MPN", ""), "brand": f.get("Manufacturer", "")
                                or f.get("MANUFACTURER", ""), "desc": f.get("Description", "")})["refs"].append(ref)
    nat = lambda r: (re.sub(r"\d", "", r), int(re.sub(r"\D", "", r) or 0))
    rows = []
    for (lcsc, mpn_n, value, fp), g in sorted(groups.items(), key=lambda kv: nat(sorted(kv[1]["refs"], key=nat)[0])):
        refs = sorted(g["refs"], key=nat)
        origin = "nueva" if all(re.match(r"^[A-Z]+2\d\d$", r) for r in refs) else "heredada"
        code = typ = stock = model = ""
        status = ""
        verif, note = ("verificada (fase 3)" if origin == "nueva" else "heredada de Voice PE"), ""
        sub = next((v for k, v in SUBST.items() if k[0] in refs), None)
        if "U204" in refs:
            verif = "parcial: solo concordancia con LCSC (plano Maxim 21-0168 sin consultar)"
        if "BT201" in refs:
            verif = "verificada (fase 3, plano MPD rev. G)"
        if any(r in HAND for r in refs):
            status = "montaje a mano: " + "; ".join(HAND[r] for r in refs if r in HAND)
        elif any(r in CONSIGN for r in refs):
            status = "consignar: " + "; ".join(CONSIGN[r] for r in refs if r in CONSIGN)
        if sub:
            lcsc, verif, note = sub[0], sub[2], sub[3]
        if status.startswith("consignar"):
            res = []
        elif lcsc:
            res = [x for x in search(lcsc, cache, offline) if x["componentCode"] == lcsc]
        elif mpn_n:
            res = [x for x in search(g["mpn"].replace("​", "").strip(), cache, offline)
                   if norm(x["componentModelEn"]) == mpn_n]
        else:
            res = []
        if res:
            best = max(res, key=lambda x: x["stockCount"] or 0)
            code, typ, stock, model = best["componentCode"], best["componentLibraryType"], best["stockCount"], best["componentModelEn"]
            if not status:
                need = len(refs) * 5   # 5 placas
                status = "OK" if (stock or 0) >= need else ("SIN STOCK" if not stock else f"stock bajo (<{need})")
        elif not status:
            status = "NO ENCONTRADA en JLCPCB (buscar alternativa)"
        if sub and status == "OK":
            status = "OK (sustituto)"
        rows.append({"Designator": ",".join(refs), "Cantidad": len(refs), "Valor": value, "Huella": fp,
                     "MPN": g["mpn"].replace("​", ""), "Origen": origin, "LCSC": code,
                     "Modelo JLC": model, "Tipo": {"base": "básica", "expand": "extendida"}.get(typ, typ),
                     "Stock": stock, "Estado": status, "Huella verificada": verif, "Nota": note})
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "NEO_v2_BOM_JLC.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for r in rows:
            if r["Estado"].startswith("montaje a mano"):
                continue
            # consignadas: sin código; en JLCPCB se emparejan con la pieza enviada (Parts Manager)
            w.writerow([r["Valor"], r["Designator"], r["Huella"].split(":")[-1], r["LCSC"]])
    with open(os.path.join(DATA, "jlc_disponibilidad.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    json.dump({"fecha": datetime.date.today().isoformat(), "consultas": cache},
              open(cache_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tot = len(rows)
    bad = [r for r in rows if not r["Estado"].startswith(("OK", "montaje a mano", "consignar"))]
    ext = sum(1 for r in rows if r["Tipo"] == "extendida")
    cons = [r["Designator"] for r in rows if r["Estado"].startswith("consignar")]
    print(f"{tot} grupos, {sum(r['Cantidad'] for r in rows)} piezas; extendidas: {ext}; "
          f"sustituidas: {sum(r['Estado'] == 'OK (sustituto)' for r in rows)}; consignadas: {cons}; "
          f"con problemas: {len(bad)}")
    for r in bad:
        print(f"  {r['Designator'][:40]:40s} {r['MPN'][:28]:28s} {r['LCSC']:10s} {r['Estado']}")


if __name__ == "__main__":
    main(*sys.argv[1:])
