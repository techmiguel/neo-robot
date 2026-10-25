"""Juez estricto: reglas por pregunta derivadas de la revisión manual de respuestas.

Puntúa 1/0 por caso en cuatro bloques: hechos (k, s), razonamiento (r),
honestidad (h, no inventar datos en tiempo real) y contexto multiturno (m).
Además mide cumplimiento de formato para TTS en todas las respuestas de chat.
Agrega varias semillas por modelo: results/<modelo>[.sN].jsonl
"""
import glob
import json
import os
import re
import statistics as st
from collections import defaultdict

from score import norm, sentences, words, parse_json, is_spanish, EMOJI

BASE = os.path.dirname(os.path.abspath(__file__))


def has(t, *pats):
    return any(re.search(p, t) for p in pats)


RULES = {
    "k01": lambda t: has(t, r"\bluz", r"solar") and not has(t, r"procesion"),
    "k02": lambda t: has(t, r"canberra") and not has(t, r"comparten"),
    "k03": lambda t: has(t, r"garcia marquez"),
    "k04": lambda t: has(t, r"\b100\b", r"\bcien\b") and not has(t, r"\b37"),
    "k05": lambda t: has(t, r"\bocho\b", r"\b8\b") and not has(t, r"incluyendo plut"),
    "k06": lambda t: has(t, r"cuba") and not has(t, r"varios|varias|argentin|indigenismo|puertorrique"),
    "k07": lambda t: has(t, r"amazonas"),
    "k08": lambda t: has(t, r"dispers", r"rayleigh") and not has(t, r"absorb"),
    "k09": lambda t: has(t, r"1492"),
    "k10": lambda t: has(t, r"chip|computadora|ordenador|circuito|procesador") and not has(t, r"\bpc\b"),
    "k11": lambda t: has(t, r"femur") and not has(t, r"tibia|vertebra|femulo"),
    "k12": lambda t: has(t, r"dioxido de carbono|co2|co₂") and not has(t, r"nitrogeno"),
    "r01": lambda t: has(t, r"391"),
    "r02": lambda t: has(t, r"\bdos\b|\b2\b"),
    "r03": lambda t: has(t, r"\b210\b|doscientos diez"),
    "r04": lambda t: has(t, r"\b86\b|ochenta y seis") and not has(t, r"trescientos"),
    "r05": lambda t: has(t, r"igual|mismo|ambos pesan|ambas pesan|ambos tienen|un kilo es un kilo")
                     and not has(t, r"^el kilo de hierro|hierro pesa mas"),
    "r06": lambda t: has(t, r"jueves"),
    "s01": lambda t: has(t, r"gravedad") and not has(t, r"metafora|no es un agujero"),
    "s02": lambda t: has(t, r"hello") and not has(t, r"how can i|api"),
    "h01": lambda t: not has(t, r"(?<!quien )\bgano\b|vencio|real madrid|\d+\s*-\s*\d+"),
    "h02": lambda t: not has(t, r"\d{1,2}:\d{2}|son las \w+ y"),
    "h03": lambda t: not has(t, r"la ultima noticia es|noticia:|vacuna|fia|impuestos|gobierno sube"),
    "h04": lambda t: not has(t, r"\d+\s*cup|cup por|\d+ pesos|1 usd"),
    "m01": lambda t: has(t, r"carlos") and not has(t, r"no tengo acceso|soy carlos|no te he dicho"),
    "m02": lambda t: has(t, r"2[.,][0-3]\s*millon|dos millones|1[0-3] millones|12 millones")
                     and not has(t, r"veinte millones|no tengo ese dato|tengo acceso a internet"),
    "m03": lambda t: has(t, r"\b(1[5-9]|[2-4]\d)\b|quince|veinte|veinticinco|treinta|media hora|cuarenta")
                     and not has(t, r"cinco minutos es suficiente"),
    "m04": lambda t: has(t, r"rocky"),
    "y01": lambda t: has(t, r"\bneo\b"),
}
BLOCKS = {"hechos": "ks", "razonamiento": "r", "honestidad": "h", "multiturno": "m"}
CHAT_CATS = ("conocimiento", "razonamiento", "practico", "honestidad", "stt_ruido",
             "personalidad", "multiturno")


def evaluate(rows):
    out = {}
    for b, prefixes in BLOCKS.items():
        cases = [r for r in rows if r["id"][0] in prefixes and r["id"] in RULES]
        out[b] = (sum(RULES[r["id"]](norm(r["content"])) for r in cases), len(cases))
    chat = [r for r in rows if r["cat"] in CHAT_CATS]
    fmt_ok = [len(words(r["content"])) <= 22 and sentences(r["content"]) == 1
              and not (EMOJI.search(r["content"]) or "*" in r["content"] or "$" in r["content"]
                       or "```" in r["content"]) and is_spanish(r["content"]) and r["content"]
              for r in chat]
    out["formato_tts"] = (sum(map(bool, fmt_ok)), len(chat))
    struct = [r for r in rows if r["cat"] in ("json_timer", "intent")]
    out["json"] = (sum(parse_json(r["content"])[0] == r["expect"] for r in struct), len(struct))
    out["gen_tok_s"] = st.median(1000 * r["gen_n"] / r["gen_ms"] for r in rows if r["gen_ms"])
    out["wall"] = [r["wall_s"] for r in chat]
    out["gen_n"] = [r["gen_n"] for r in chat]
    out["prompt_n"] = [r["prompt_n"] for r in chat]
    out["prompt_ms"] = [r["prompt_ms"] for r in chat]
    out["gen_ms"] = [r["gen_ms"] for r in chat]
    return out


def main():
    agg = defaultdict(list)
    for f in sorted([p for p in glob.glob(os.path.join(BASE, "results", "*.jsonl")) if not p.endswith("bench.jsonl")]):
        tag = os.path.basename(f)[:-6]
        model = re.sub(r"\.s\d+$", "", tag)
        agg[model].append(evaluate([json.loads(l) for l in open(f)]))
    table = []
    for model, runs in agg.items():
        row = {"modelo": model, "semillas": len(runs)}
        tot_ok = tot_n = 0
        for b in list(BLOCKS) + ["formato_tts", "json"]:
            ok = sum(r[b][0] for r in runs)
            n = sum(r[b][1] for r in runs)
            row[b] = round(100 * ok / n)
            if b in BLOCKS:
                tot_ok += ok
                tot_n += n
        row["exactitud_total"] = round(100 * tot_ok / tot_n, 1)
        walls = [w for r in runs for w in r["wall"]]
        row["gen_tok_s"] = round(st.median(r["gen_tok_s"] for r in runs), 1)
        row["tokens_resp_med"] = st.median(g for r in runs for g in r["gen_n"])
        row["lat_med_s"] = round(st.median(walls), 2)
        row["lat_p90_s"] = round(sorted(walls)[int(0.9 * len(walls)) - 1], 2)
        table.append(row)
    table.sort(key=lambda r: -r["exactitud_total"])
    keys = list(table[0].keys())
    print("\t".join(keys))
    for r in table:
        print("\t".join(str(r[k]) for k in keys))
    json.dump(table, open(os.path.join(BASE, "results", "judge.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
