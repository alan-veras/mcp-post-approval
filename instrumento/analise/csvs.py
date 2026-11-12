"""Leitura e escrita dos CSVs: uma linha por execução, retomada pelo que já tem linha."""

import csv
import io
import os
from pathlib import Path


def le_csv(caminho):
    """Só os registros COMPLETOS: uma cauda cortada (processo morto ou disco cheio no meio da escrita) nunca vira linha."""
    try:
        dados = Path(caminho).read_bytes()
    except OSError:
        return []
    completo = dados[:fim_do_ultimo_registro(dados)]
    linhas = list(csv.DictReader(io.StringIO(completo.decode("utf-8", "replace"), newline="")))
    return [r for r in linhas if None not in r.values() and None not in r]  # registro curto = escrita incompleta


def ja_feito(caminho, campos_chave, chave):
    """Já existe linha com essa chave (retomada: o que tem linha não roda de novo)?"""
    return any(tuple(r.get(c, "") for c in campos_chave) == tuple(chave) for r in le_csv(caminho))


def fim_do_ultimo_registro(dados):
    """Posição (em bytes) logo depois da última quebra de linha que fecha um registro CSV, isto é, fora de aspas: campos
    com quebra dentro de aspas (texto do modelo) não contam como fim de registro. 0 se nenhum registro está completo."""
    dentro, fim = False, 0
    for i, b in enumerate(dados):
        if b == 0x22:  # aspas; "" dentro de campo alterna duas vezes e volta ao mesmo estado
            dentro = not dentro
        elif b == 0x0A and not dentro:
            fim = i + 1
    return fim


def apara_cauda(caminho):
    """Se a última linha ficou incompleta (processo morto no meio da escrita, sem quebra final ou no meio de um campo
    entre aspas), tira a cauda para `<arquivo>.parcial` (nunca apaga) e deixa o CSV terminando em quebra, para a
    próxima linha não se colar nela."""
    caminho = Path(caminho)
    if not caminho.exists() or caminho.stat().st_size == 0:
        return
    dados = caminho.read_bytes()
    corte = fim_do_ultimo_registro(dados)
    if corte == len(dados):
        return
    with open(caminho.with_suffix(caminho.suffix + ".parcial"), "ab") as f:
        f.write(dados[corte:] + b"\n")
    with open(caminho, "r+b") as f:
        f.truncate(corte)


def grava_linha(caminho, campos, linha):
    """Acrescenta uma linha (uma só escrita, com flush e fsync); escreve o cabeçalho se o arquivo é novo."""
    caminho = Path(caminho)
    apara_cauda(caminho)
    novo = not caminho.exists() or caminho.stat().st_size == 0
    with open(caminho, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        if novo:
            w.writeheader()
        w.writerow({c: linha.get(c, "") for c in campos})
        f.flush()
        os.fsync(f.fileno())


def sufixo_do_modelo(modelo):
    """O sufixo do CSV e da pasta de evidência de um modelo (um por modelo): `-mistral-large-4-1t-a52b`."""
    if not modelo:
        return ""
    return "-" + "".join(ch if ch.isalnum() or ch in ".-" else "-" for ch in modelo.split("/")[-1])
