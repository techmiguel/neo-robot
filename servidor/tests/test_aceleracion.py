"""
Pruebas de src/benchmark/aceleracion.py (asistente de las pruebas de aceleración)
con mediciones sintéticas: sin Ollama, sin e2e real y sin placa.
"""

import json
import subprocess

import pytest

from src.benchmark import aceleracion as ac

FRASES = [f"f{i:02d}" for i in range(1, 25)]


def _consultas(base: float, delta=lambda i: 0.0, reps: int = 3, variante: str = "b0",
               errores_palabra: int = 0, respuesta: str = "Tokio. Muy humano.", load_s: float = 0.01) -> list[dict]:
    """Filas como las de consultas.jsonl de e2e: 24 preguntas libres y un comando."""
    filas = []
    for rep in range(reps):
        for i, id_ in enumerate(FRASES):
            t = base + 0.1 * i + delta(i) + 0.01 * rep
            filas.append({"id": id_, "repeticion": rep, "ok": True, "tipo": "llm_libre", "perfil_medido": variante,
                          "inicio_audio": t, "stt": 2.4, "llm_primer_token": 3.0 + delta(i),
                          "prompt_tokens": 160, "prompt_s": 3.0, "eval_tok_s": 7.0, "load_s": load_s,
                          "respuesta": respuesta, "palabras": 6, "errores_palabra": errores_palabra,
                          "errores_caracter": 0, "caracteres": 30, "exacta": not errores_palabra,
                          "intencion_ok": True})
        filas.append({"id": "c01", "repeticion": rep, "ok": True, "tipo": "keyword", "perfil_medido": variante,
                      "inicio_audio": 6.0, "palabras": 5, "errores_palabra": 0, "errores_caracter": 0,
                      "caracteres": 25, "exacta": True, "intencion_ok": True})
    return filas


def _guardar(carpeta, filas):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "consultas.jsonl").write_text("\n".join(json.dumps(f) for f in filas), encoding="utf-8")
    return carpeta


def test_mejora_clara_se_mantiene():
    r = ac.comparar(_consultas(9.0), _consultas(8.2), ruido=0.1)
    assert r["frases"] == 24 and r["n_ref"] == 72
    assert r["delta_mediana"] == pytest.approx(-0.8)
    assert r["fraccion_mejoran"] == 1.0 and r["delta_p90"] == pytest.approx(-0.8)
    assert r["etapas"]["stt"]["delta"] == 0
    assert r["decision"] == "mantener" and r["motivos"] == []


def test_ganancia_dentro_del_ruido_se_repite():
    r = ac.comparar(_consultas(9.0), _consultas(8.85), ruido=0.15)   # umbral 0,30 s
    assert r["umbral"] == pytest.approx(0.3)
    assert r["decision"] == "repetir"


def test_calidad_rota_descarta_aunque_sea_mas_rapido():
    r = ac.comparar(_consultas(9.0), _consultas(7.0, errores_palabra=1), ruido=0.1)
    assert r["decision"] == "descartar" and any("WER" in m for m in r["motivos"])
    r = ac.comparar(_consultas(9.0), _consultas(7.0, respuesta="东京"), ruido=0.1)
    assert r["decision"] == "descartar" and any("latino" in m for m in r["motivos"])


def test_pocas_frases_mejoran_descarta():
    # La mediana mejora, pero solo en la mitad de las frases (la otra mitad empeora)
    r = ac.comparar(_consultas(9.0), _consultas(9.0, delta=lambda i: -1.0 if i % 2 else 0.1), ruido=0.0)
    assert r["fraccion_mejoran"] == 0.5 and r["decision"] == "descartar"


def test_aa_y_avisos():
    r = ac.comparar(_consultas(9.0), _consultas(9.1))
    aa = ac.ruido_aa(r)
    assert aa["delta_aa"] == pytest.approx(0.1) and aa["umbral_resultante"] == pytest.approx(0.2)
    assert aa["avisos"] == []
    texto = ac.bloque("p0_a1 (b0)", "p0_a2 (b0)", r, aa)
    assert "**Δ_AA = 0.10 s.**" in texto and "Medición válida" in texto

    r = ac.comparar(_consultas(9.0), _consultas(9.8, load_s=2.0))
    avisos = ac.ruido_aa(r)["avisos"]
    assert len(avisos) == 2 and "recargaba" in avisos[1]


def test_bloque_de_decision():
    r = ac.comparar(_consultas(9.0), _consultas(8.2), ruido=0.1)
    texto = ac.bloque("p0_a1 (b0)", "p3 (tts)", r)
    assert "| Mediana | " in texto and "-0.80 (pareada)" in texto
    assert "| Tokens de prompt procesados | 160 | 160 | +0 |" in texto
    assert "**Decisión según la regla: mantener**" in texto


def test_cli_comparar_variantes_de_una_ejecucion(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ac, "DOCS", tmp_path / "docs")
    _guardar(tmp_path / "docs" / "p2", _consultas(9.0, variante="m") + _consultas(8.0, variante="m_cache"))
    with pytest.raises(SystemExit, match="varias variantes"):
        ac.cargar("p2")
    ac.main(["comparar", "p2", "p2", "--variante-ref", "m", "--variante-nueva", "m_cache",
             "--ruido", "0.1", "--json", str(tmp_path / "r.json")])
    salida = capsys.readouterr().out
    assert "p2 (m) → p2 (m_cache)" in salida and "mantener" in salida
    assert json.loads((tmp_path / "r.json").read_text())["decision"] == "mantener"


def test_fijar_corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(ac, "CORPUS_FIJADO", tmp_path / "logs" / "corpus.txt")
    sesion = tmp_path / "panel"
    (sesion / "grabaciones").mkdir(parents=True)
    (sesion / "corpus.csv").write_text("archivo,id,referencia,intencion\n"
                                       "grabaciones/f01_1.wav,f01,¿Hola?,\n"
                                       "grabaciones/c01_1.wav,c01,¿Clima?,clima\n", encoding="utf-8")
    (sesion / "grabaciones" / "f01_1.wav").write_bytes(b"RIFF")
    with pytest.raises(SystemExit, match="faltan 1 WAV"):
        ac.fijar_corpus(sesion)
    assert ac.corpus_fijado() is None
    (sesion / "grabaciones" / "c01_1.wav").write_bytes(b"RIFF")
    assert ac.fijar_corpus(sesion) == (sesion / "corpus.csv").resolve()
    assert ac.corpus_fijado() == (sesion / "corpus.csv").resolve()


def test_condiciones_sin_ollama(monkeypatch):
    c = ac.condiciones({"OLLAMA_HOST": "http://127.0.0.1:9", "OLLAMA_MODEL": "lfm3:1.7b-qad-q4_0",
                        "GROQ_API_KEY": "secreto", "PATH": "/bin"})
    assert "error" in c["ollama"]
    assert c["variables"] == {"OLLAMA_HOST": "http://127.0.0.1:9", "OLLAMA_MODEL": "lfm3:1.7b-qad-q4_0"}
    assert c["cpu"]["nucleos_logicos"] and set(c) >= {"so", "ram_libre_gb", "commit", "fecha"}


def test_medir_lanza_e2e_y_publica(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "DOCS", tmp_path / "docs")
    monkeypatch.setattr(ac, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(ac, "comprobar", lambda modelos, exigir_corpus, env: ([], []))
    monkeypatch.setattr(ac, "condiciones", lambda env=None: {"commit": "abc1234"})
    corpus_csv = tmp_path / "corpus.csv"
    corpus_csv.write_text("archivo,id,referencia,intencion\n", encoding="utf-8")
    llamadas = []

    def run(cmd, cwd=None):
        llamadas.append(cmd)
        salida = tmp_path / "logs" / "p0_a1"
        for nombre in ("informe.md", "resultados.json", "consultas.jsonl"):
            (salida / nombre).write_text("{}", encoding="utf-8")
        (salida / "b0").mkdir()
        (salida / "b0" / "servidor.log").write_text("no se publica")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(ac.subprocess, "run", run)
    destino = ac.medir("p0_a1", ["b0=local,OLLAMA_MODEL=gemma4:e2b"], corpus_csv=corpus_csv)
    cmd = llamadas[0]
    assert cmd[1:3] == ["-m", "src.benchmark.e2e"]
    assert cmd[cmd.index("--repeticiones") + 1] == "3" and cmd[cmd.index("--calentamiento") + 1] == "2"
    assert "--sin-red" in cmd and cmd[cmd.index("--whisper-model") + 1] == "small"
    assert cmd[cmd.index("--variante") + 1] == "b0=local,OLLAMA_MODEL=gemma4:e2b"
    assert sorted(p.name for p in destino.iterdir()) == sorted(ac.PUBLICABLES)
    cond = json.loads((destino / "condiciones.json").read_text(encoding="utf-8"))
    assert cond["prueba"] == "p0_a1" and cond["corpus"] == str(corpus_csv)

    with pytest.raises(SystemExit, match="ya tiene datos publicados"):
        ac.medir("p0_a1", ["b0=local"], corpus_csv=corpus_csv)
    with pytest.raises(SystemExit, match="solo minúsculas"):
        ac.medir("P0 A1", ["b0=local"], corpus_csv=corpus_csv)


def test_modelos_de_las_variantes():
    env = {"OLLAMA_MODEL": "gemma4:e2b"}
    assert ac._modelos(["b0=local", "lfm3=local,OLLAMA_MODEL=lfm3:1.7b-qad-q4_0", "nube"], env) == \
        ["gemma4:e2b", "lfm3:1.7b-qad-q4_0"]
