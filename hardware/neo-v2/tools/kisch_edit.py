#!/usr/bin/env python3
"""
kisch_edit.py — Edición quirúrgica de hojas .kicad_sch heredadas.

Trabaja sobre el texto original: localiza los elementos de primer nivel por su intervalo de
caracteres y solo reescribe los que cambian, de modo que el resto del archivo de Nabu Casa
queda byte a byte igual (el diff de git muestra exactamente lo modificado).
"""
import re

import sexpdata
from sexpdata import Symbol


def _n(x):
    return x.value() if isinstance(x, Symbol) else x


def _f(node, k):
    return [c for c in node if isinstance(c, list) and c and _n(c[0]) == k]


def top_level_spans(text):
    """Intervalos (inicio, fin) de los hijos directos de (kicad_sch ...)."""
    spans = []
    depth = 0
    i = 0
    start = None
    in_str = False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
            if depth == 2:
                start = i
        elif c == ")":
            if depth == 2:
                spans.append((start, i + 1))
            depth -= 1
        i += 1
    return spans


class Sheet:
    def __init__(self, path):
        self.path = path
        self.text = open(path, encoding="utf-8").read()

    def items(self):
        out = []
        for s, e in top_level_spans(self.text):
            chunk = self.text[s:e]
            kind = re.match(r"\((\w+)", chunk).group(1)
            out.append((s, e, kind, chunk))
        return out

    @staticmethod
    def parse(chunk):
        return sexpdata.loads(chunk)

    def symbol_ref(self, chunk):
        d = self.parse(chunk)
        for p in _f(d, "property"):
            if p[1] == "Reference":
                return p[2]
        return None

    def _rewrite(self, edits):
        """edits: lista de (inicio, fin, texto_nuevo); se aplican de atrás hacia delante."""
        for s, e, new in sorted(edits, key=lambda x: -x[0]):
            # al borrar, absorbe el salto de línea y la sangría precedentes
            if new == "":
                while s > 0 and self.text[s - 1] in "\t ":
                    s -= 1
                if s > 0 and self.text[s - 1] == "\n":
                    s -= 1
            self.text = self.text[:s] + new + self.text[e:]

    def delete_symbols(self, refs):
        refs = set(refs)
        edits, found = [], set()
        for s, e, kind, chunk in self.items():
            if kind == "symbol":
                r = self.symbol_ref(chunk)
                if r in refs:
                    edits.append((s, e, ""))
                    found.add(r)
        self._rewrite(edits)
        return found

    def delete_uuids(self, uuids):
        uuids = set(uuids)
        edits = []
        for s, e, kind, chunk in self.items():
            m = re.search(r'\(uuid "([0-9a-f-]+)"\)', chunk)
            # el uuid propio del elemento es el último de primer nivel; en hilos y etiquetas es único
            ids = set(re.findall(r'\(uuid "([0-9a-f-]+)"\)', chunk))
            if kind in ("wire", "junction", "label", "global_label", "no_connect", "symbol", "text") and ids & uuids:
                edits.append((s, e, ""))
        self._rewrite(edits)
        return len(edits)

    def set_dnp(self, refs, value=True):
        refs = set(refs)
        edits, found = [], set()
        for s, e, kind, chunk in self.items():
            if kind == "symbol" and self.symbol_ref(chunk) in refs:
                new = re.sub(r"\(dnp (yes|no)\)", f"(dnp {'yes' if value else 'no'})", chunk, count=1)
                edits.append((s, e, new))
                found.add(self.symbol_ref(chunk))
        self._rewrite(edits)
        return found

    def rename_global_labels(self, mapping, where=None):
        """mapping {viejo: nuevo}; where: función opcional (x, y) -> bool para filtrar."""
        edits, n = [], 0
        for s, e, kind, chunk in self.items():
            if kind != "global_label":
                continue
            d = self.parse(chunk)
            name = d[1]
            at = _f(d, "at")[0]
            if name in mapping and (where is None or where(float(at[1]), float(at[2]))):
                new = chunk.replace(f'(global_label "{name}"', f'(global_label "{mapping[name]}"', 1)
                edits.append((s, e, new))
                n += 1
        self._rewrite(edits)
        return n

    def labels(self, kinds=("global_label", "label")):
        out = []
        for s, e, kind, chunk in self.items():
            if kind in kinds:
                d = self.parse(chunk)
                at = _f(d, "at")[0]
                uid = _f(d, "uuid")[0][1]
                out.append((kind, d[1], float(at[1]), float(at[2]), uid))
        return out

    def symbols(self):
        out = []
        for s, e, kind, chunk in self.items():
            if kind == "symbol":
                d = self.parse(chunk)
                props = {p[1]: p[2] for p in _f(d, "property")}
                at = _f(d, "at")[0]
                uid = _f(d, "uuid")[0][1]
                out.append((props.get("Reference"), props.get("Value"), float(at[1]), float(at[2]), uid))
        return out

    def insert_before_end(self, block):
        """Inserta elementos nuevos antes de (sheet_instances ...) o (embedded_fonts ...)."""
        # solo elementos de primer nivel: línea que empieza con un único tabulador (en hojas sin
        # embedded_fonts de primer nivel, la subcadena aparece dentro de los símbolos de biblioteca)
        for key in ("\n\t(sheet_instances", "\n\t(embedded_fonts"):
            i = self.text.rfind(key)
            if i >= 0:
                i += 1
                self.text = self.text[:i] + block + self.text[i:]
                return
        i = self.text.rstrip().rfind(")")
        self.text = self.text[:i] + block + self.text[i:]

    def save(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(self.text)
