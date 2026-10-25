"""Puntúa los JSONL de results/ y produce una tabla comparativa."""
import glob
import json
import os
import re
import statistics as st
import sys
import unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


ES = {"el", "la", "de", "que", "y", "en", "es", "un", "una", "los", "las", "por",
      "con", "para", "no", "se", "lo", "su", "al", "del", "mas", "como", "pero"}
EN = {"the", "is", "and", "of", "to", "in", "it", "you", "that", "for", "are",
      "with", "this", "your", "on"}
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def words(s):
    return re.findall(r"[\wáéíóúñü]+", s, flags=re.I)


def sentences(s):
    # cuenta terminadores de oración seguidos de más texto (ignora decimales)
    body = re.sub(r"\d[.,]\d", "0", s.strip())
    parts = [p for p in re.split(r"[.!?…]+(?:\s+|$)", body) if p.strip()]
    return max(1, len(parts))


def is_spanish(s):
    w = [norm(x) for x in words(s)]
    es = sum(x in ES for x in w)
    en = sum(x in EN for x in w)
    return es >= en


def parse_json(s):
    strict = None
    try:
        strict = json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{.*?\}", s, flags=re.S)
    lenient = None
    if m:
        try:
            lenient = json.loads(m.group(0))
        except Exception:
            pass
    return strict, lenient


def score_file(path):
    rows = [json.loads(l) for l in open(path)]
    chat = [r for r in rows if r["cat"] not in ("json_timer", "intent", "traducir", "resumir")]
    tasks = [r for r in rows if r not in chat]
    res = {"model": os.path.basename(path)[:-6]}
    ok_fact = [r for r in chat if r["expect"]]
    hits = 0
    fails = []
    for r in ok_fact:
        t = norm(r["content"])
        hit = any(all(norm(x) in t for x in alt) for alt in r["expect"])
        hits += hit
        if not hit:
            fails.append(r["id"])
    res["acierto"] = f"{hits}/{len(ok_fact)}"
    wc = [len(words(r["content"])) for r in chat]
    res["palabras_med"] = st.median(wc)
    res["<=20pal"] = round(100 * sum(w <= 20 for w in wc) / len(wc))
    res["1_oracion"] = round(100 * sum(sentences(r["content"]) == 1 for r in chat) / len(chat))
    res["espanol"] = round(100 * sum(is_spanish(r["content"]) for r in chat) / len(chat))
    res["md/emoji"] = sum(bool(EMOJI.search(r["content"]) or "**" in r["content"]
                              or r["content"].lstrip().startswith(("-", "*", "#")))
                          for r in chat)
    res["vacias"] = sum(not r["content"] for r in rows)
    js_s = js_l = js_n = 0
    for r in tasks:
        if r["cat"] in ("json_timer", "intent"):
            js_n += 1
            s, l = parse_json(r["content"])
            js_s += s == r["expect"]
            js_l += l == r["expect"]
        else:
            js_n += 1
            t = norm(r["content"])
            ok = all(norm(x) in t for x in r["expect"]) and is_spanish(r["content"])
            js_s += ok
            js_l += ok
    res["tareas_estricto"] = f"{js_s}/{js_n}"
    res["tareas_tolerante"] = f"{js_l}/{js_n}"
    gen_tps = [1000 * r["gen_n"] / r["gen_ms"] for r in rows if r["gen_ms"]]
    pp = [(r["prompt_n"], r["prompt_ms"]) for r in rows if r["prompt_ms"] and r["prompt_n"] > 20]
    res["gen_tok_s"] = round(st.median(gen_tps), 1)
    res["pp_tok_s"] = round(sum(n for n, _ in pp) / sum(ms for _, ms in pp) * 1000, 1) if pp else None
    res["gen_tokens_med"] = st.median(r["gen_n"] for r in chat)
    res["wall_med_s"] = round(st.median(r["wall_s"] for r in chat), 2)
    res["wall_p95_s"] = round(sorted(r["wall_s"] for r in chat)[int(0.95 * len(chat)) - 1], 2)
    res["fallos_hechos"] = ",".join(fails)
    return res


def main():
    files = sorted(glob.glob(os.path.join(BASE, "results", "*.jsonl")))
    out = [score_file(f) for f in files]
    keys = list(out[0].keys())
    print("\t".join(keys))
    for r in out:
        print("\t".join(str(r[k]) for k in keys))
    json.dump(out, open(os.path.join(BASE, "results", "scores.json"), "w"), indent=1,
              ensure_ascii=False)
    if "-v" in sys.argv:
        for f in files:
            print("\n=====", os.path.basename(f))
            for l in open(f):
                r = json.loads(l)
                print(f"[{r['id']}] {r['q'][:50]} -> {r['content'][:220]!r}")


if __name__ == "__main__":
    main()
