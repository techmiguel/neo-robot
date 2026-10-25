"""Ejecuta el banco de NEO contra un GGUF vía llama-server y guarda JSONL.

Uso: python3 run_eval.py <nombre> <ruta.gguf> [--think] [--seed N]
Requiere llama-server (llama.cpp); ruta en LLAMA_SERVER.
Los parámetros de muestreo salen de SAMPLING (recomendados por cada fabricante
para modo sin razonamiento).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prompts import CHAT, MULTITURN, NEO_SYSTEM, TASKS  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.getenv("LLAMA_SERVER", os.path.join(BASE, "llama.cpp/build/bin/llama-server"))
PORT = 8091

# Muestreo recomendado por fabricante (model card / Modelfile oficial de Ollama).
SAMPLING = {
    # Variante probada y descartada: Gemma 4 con temperatura baja (no mejora; ver README).
    "lowt-gemma4": {"temperature": 0.3, "top_p": 0.95, "top_k": 64},
    "qwen2.5": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "repeat_penalty": 1.05},
    "qwen3.5": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.5},
    "gemma4": {"temperature": 1.0, "top_p": 0.95, "top_k": 64},
    "granite4.2": {"temperature": 1.0, "top_p": 0.95},
    "ministral3": {"temperature": 0.15},
    "lfm2.5-1.2b": {"temperature": 0.1, "top_k": 50, "repeat_penalty": 1.05},
    "lfm2.5-8b": {"temperature": 0.2, "top_k": 80, "repeat_penalty": 1.05},
    "llama3.2": {"temperature": 0.6, "top_p": 0.9},
}


def sampling_for(name):
    for k, v in SAMPLING.items():
        if name.startswith(k):
            return v
    raise KeyError(name)


def post(path, body, timeout=600):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def wait_ready(proc, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError("llama-server terminó")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                if r.status == 200:
                    return time.time() - t0
        except Exception:
            time.sleep(0.5)
    raise TimeoutError


def chat(messages, think, max_tokens, sampling, seed):
    body = {
        "messages": messages,
        "max_tokens": max_tokens,
        **sampling, "seed": seed,
        "cache_prompt": True,
        "chat_template_kwargs": {"enable_thinking": think},
    }
    t0 = time.time()
    r = post("/v1/chat/completions", body)
    wall = time.time() - t0
    msg = r["choices"][0]["message"]
    tm = r.get("timings", {})
    return {
        "content": (msg.get("content") or "").strip(),
        "reasoning": (msg.get("reasoning_content") or "").strip(),
        "wall_s": round(wall, 3),
        "prompt_n": tm.get("prompt_n"), "prompt_ms": tm.get("prompt_ms"),
        "gen_n": tm.get("predicted_n"), "gen_ms": tm.get("predicted_ms"),
        "finish": r["choices"][0].get("finish_reason"),
    }


def main():
    name, gguf = sys.argv[1], sys.argv[2]
    think = "--think" in sys.argv
    max_tokens = 2048 if think else 256
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 42
    sampling = sampling_for(name)
    tag = name if seed == 42 else f"{name}.s{seed}"
    out = os.path.join(BASE, "results", f"{tag}.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    log = open(os.path.join(BASE, "results", f"{tag}.server.log"), "w")
    proc = subprocess.Popen(
        [SERVER, "-m", gguf, "-t", "4", "-c", "4096", "--port", str(PORT),
         "--jinja", "-np", "1", "--no-webui"],
        stdout=log, stderr=subprocess.STDOUT)
    try:
        load_s = wait_ready(proc)
        rows = []
        # calentamiento (como _precalentar en ws_server.py)
        chat([{"role": "system", "content": NEO_SYSTEM},
              {"role": "user", "content": "Hola"}], think, max_tokens, sampling, seed)
        for cid, cat, q, expect in CHAT:
            r = chat([{"role": "system", "content": NEO_SYSTEM},
                      {"role": "user", "content": q}], think, max_tokens, sampling, seed)
            rows.append({"id": cid, "cat": cat, "q": q, "expect": expect, **r})
        for cid, cat, turns, expect in MULTITURN:
            msgs = [{"role": "system", "content": NEO_SYSTEM}]
            msgs += [{"role": ro, "content": c} for ro, c in turns]
            r = chat(msgs, think, max_tokens, sampling, seed)
            rows.append({"id": cid, "cat": cat, "q": turns[-1][1], "expect": expect, **r})
        for cid, cat, sysmsg, q, expect in TASKS:
            r = chat([{"role": "system", "content": sysmsg},
                      {"role": "user", "content": q}], think, max_tokens, sampling, seed)
            rows.append({"id": cid, "cat": cat, "q": q, "expect": expect, **r})
        with open(out, "w") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        mem = {}
        try:
            with open(f"/proc/{proc.pid}/status") as s:
                for line in s:
                    k = line.split(":")[0]
                    if k in ("VmHWM", "RssAnon", "RssFile"):
                        mem[k] = int(line.split()[1]) // 1024
        except Exception:
            pass
        print(json.dumps({"model": tag, "load_s": round(load_s, 1),
                          "peak_rss_mb": mem.get("VmHWM"), "anon_mb": mem.get("RssAnon"),
                          "file_mb": mem.get("RssFile"), "n": len(rows)}))
    finally:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    main()
