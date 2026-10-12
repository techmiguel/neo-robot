#!/usr/bin/env python3
"""
jlc_search.py — consulta de candidatos en el buscador de piezas de JLCPCB (fase 1).

  python3 jlc_search.py <palabra> [<palabra> ...]        # muestra los resultados
  python3 jlc_search.py --code C2913202 [...]            # solo coincidencia exacta de código

Guarda las respuestas en docs/data/jlc_cache.json (instantánea con fecha). Adaptado de
hardware/neo-v2/tools/jlc_bom.py (misma API), añadiendo precio y paquete mínimo.
El stock y el precio cambian a diario: el resultado es una instantánea, no una garantía.
"""
import datetime
import json
import os
import sys
import time
import urllib.request

API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", "docs", "data", "jlc_cache.json")
KEEP = ("componentCode", "componentModelEn", "componentBrandEn", "componentLibraryType",
        "stockCount", "componentSpecificationEn", "describe", "preferredComponentFlag",
        "componentPrices", "dataManualUrl", "leastPatchNumber")


def load_cache():
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding="utf-8"))["consultas"]
    return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump({"fecha": datetime.date.today().isoformat(), "consultas": cache},
              open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def search(keyword, cache, offline=False, size=25):
    if keyword in cache:
        return cache[keyword]
    if offline:
        return []
    body = json.dumps({"keyword": keyword, "currentPage": 1, "pageSize": size}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.load(r)
            lst = (d.get("data") or {}).get("componentPageInfo", {}).get("list") or []
            cache[keyword] = [{k: it.get(k) for k in KEEP} for it in lst]
            time.sleep(0.4)
            return cache[keyword]
        except Exception as e:  # red: reintento con espera creciente
            err = e
            time.sleep(2 ** attempt)
    raise SystemExit(f"fallo de red buscando {keyword}: {err}")


def price(item, qty):
    """Precio unitario (USD) para qty unidades según la tabla escalonada de JLCPCB."""
    for p in item.get("componentPrices") or []:
        if p["startNumber"] <= qty and (p["endNumber"] == -1 or qty <= p["endNumber"]):
            return p["productPrice"]
    ps = item.get("componentPrices") or []
    return ps[0]["productPrice"] if ps else None


def kind(item):
    t = item["componentLibraryType"]
    if t == "base":
        return "básica"
    return "preferida" if item.get("preferredComponentFlag") else "extendida"


def main(args):
    exact = "--code" in args
    words = [a for a in args if a != "--code"]
    cache = load_cache()
    for w in words:
        res = search(w, cache)
        if exact:
            res = [x for x in res if x["componentCode"] == w]
        print(f"== {w}")
        for x in sorted(res, key=lambda x: -(x["stockCount"] or 0))[:8]:
            p = price(x, 10)
            print(f"  {x['componentCode']:11s} {kind(x):9s} stock {x['stockCount'] or 0:>9} "
                  f"${p if p is not None else '?':<8} {x['componentModelEn'][:32]:32s} "
                  f"{(x['describe'] or '')[:70]}")
    save_cache(cache)


if __name__ == "__main__":
    main(sys.argv[1:])
