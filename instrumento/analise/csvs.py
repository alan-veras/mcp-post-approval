"""Leitura e escrita dos CSVs: uma linha por execução, retomada pelo que já tem linha."""

import csv
from pathlib import Path


def le_csv(caminho):
    try:
        with open(caminho, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def ja_feito(caminho, campos_chave, chave):
    """Já existe linha com essa chave (retomada: o que tem linha não roda de novo)?"""
    return any(tuple(r.get(c, "") for c in campos_chave) == tuple(chave) for r in le_csv(caminho))


def grava_linha(caminho, campos, linha):
    """Acrescenta uma linha; escreve o cabeçalho se o arquivo é novo."""
    caminho = Path(caminho)
    novo = not caminho.exists() or caminho.stat().st_size == 0
    with open(caminho, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        if novo:
            w.writeheader()
        w.writerow({c: linha.get(c, "") for c in campos})


def sufixo_do_modelo(modelo):
    """O sufixo do CSV e da pasta de evidência de um modelo (um por modelo): `-mistral-large-4-1t-a52b`."""
    if not modelo:
        return ""
    return "-" + "".join(ch if ch.isalnum() or ch in ".-" else "-" for ch in modelo.split("/")[-1])
