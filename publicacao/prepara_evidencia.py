#!/usr/bin/env python3
"""Prepara a evidência para o git público: tira o cache e o lixo das pastas `home/` e troca o caminho do computador do autor por `~` nos arquivos de texto, CSVs inclusive. Nos CSVs (e em todo arquivo) a troca é feita em bytes e é a única alteração: fins de linha, aspas e o resto ficam como estavam.

Dentro de cada `home/` ficam só os arquivos de configuração e de sessão (.json, .jsonl, .toml, .yaml, .yml, .npmrc, até
300 KB) fora de skills, caches e plugins: é onde o cadastro do gêmeo e as aprovações do cliente deixam rastro. O resto
(sqlite, imagens, skills, caches) sai.

Uso: python3 publicacao/prepara_evidencia.py PASTA [--aplicar --copia-bruta DESTINO.tar.gz]
Sem --aplicar, só lista o que faria. Com --aplicar, exige a cópia bruta (tar.gz fora do repo) e a faz ANTES de alterar.
"""
import argparse
import getpass
import os
import re
import socket
import subprocess
import sys
import tarfile
from pathlib import Path

USUARIO, MAQUINA = getpass.getuser(), socket.gethostname()
# trocas, em bytes: o caminho da casa do autor (o usuário desta máquina e o de sempre) e o nome da máquina, que os clientes
# gravam em alguns arquivos de sessão (ex.: "hostname" dos .runtime.json do Qwen Code)
SUBSTITUI = [("/home/alanv", "~"), ("/home/" + USUARIO, "~")] + ([(MAQUINA, "maquina-do-autor")] if len(MAQUINA) >= 3 else [])
SEGREDOS = re.compile(rb"nvapi-[A-Za-z0-9_-]{10,}|Bearer [A-Za-z0-9._-]{20,}|sk-[A-Za-z0-9]{20,}")
MANTEM_SUFIXOS = {".json", ".jsonl", ".toml", ".yaml", ".yml", ".npmrc"}
DESCARTA_PARTES = {"skills", ".cache", "node_modules", ".npm", "plugins", "cache"}
LIMITE_HOME = 300 * 1024


def descartavel(p, home):
    rel = p.relative_to(home)
    return (any(x in DESCARTA_PARTES for x in rel.parts) or p.suffix not in MANTEM_SUFIXOS and p.name != ".npmrc"
            or p.stat().st_size > LIMITE_HOME or "sqlite" in p.name)
LIMITE = 20 * 1024 * 1024


def texto(p):
    """O arquivo como bytes, se for texto UTF-8 (a troca é feita em bytes: nada mais muda, nem os fins de linha)."""
    try:
        dados = p.read_bytes()
        dados.decode("utf-8")
        return dados
    except (UnicodeDecodeError, OSError):
        return None


def principal():
    a = argparse.ArgumentParser()
    a.add_argument("pasta")
    a.add_argument("--aplicar", action="store_true")
    a.add_argument("--copia-bruta")
    ns = a.parse_args()
    pasta = Path(ns.pasta).resolve()
    homes = [d for d in pasta.rglob("home") if d.is_dir() and d.parent != pasta]
    lixo = [p for h in homes for p in h.rglob("*") if p.is_symlink() or (p.is_file() and descartavel(p, h))]
    arquivos = [p for p in pasta.rglob("*") if p.is_file() and not p.is_symlink() and p not in set(lixo) and p.stat().st_size < LIMITE]
    trocar = [p for p in arquivos if (t := texto(p)) is not None and any(o.encode() in t for o, _ in SUBSTITUI)]
    print(f"{len(homes)} pastas home/, {len(lixo)} arquivos de cache e lixo a remover; {len(trocar)} arquivos com o caminho do autor a trocar por ~")
    if not ns.aplicar:
        print("(nada foi alterado: use --aplicar --copia-bruta DESTINO.tar.gz)")
        return 0
    raiz = subprocess.run(["git", "-C", str(pasta), "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    cb = Path(ns.copia_bruta).resolve() if ns.copia_bruta else None
    if cb is None or pasta in cb.parents or (raiz and Path(raiz) in cb.parents):
        sys.exit("--aplicar exige --copia-bruta fora da pasta e fora do repositório git")
    if Path(ns.copia_bruta).exists():
        sys.exit(f"{ns.copia_bruta} já existe: não sobrescrevo a cópia bruta (escolha outro nome)")
    with tarfile.open(ns.copia_bruta, "w:gz") as t:
        t.add(pasta, arcname=pasta.name)
    print(f"cópia bruta: {ns.copia_bruta}")
    for p in lixo:
        p.unlink(missing_ok=True)
    for h in homes:  # pastas que ficaram vazias
        for raiz, _, _ in os.walk(h, topdown=False):
            try:
                os.rmdir(raiz)
            except OSError:
                pass
    for p in trocar:
        t = texto(p)
        for o, n in SUBSTITUI:
            t = t.replace(o.encode(), n.encode())
        p.write_bytes(t)
    sobras = []
    for p in pasta.rglob("*"):
        if p.is_file() and not p.is_symlink() and p.stat().st_size < LIMITE and (t := texto(p)) is not None:
            if SEGREDOS.search(t) or any(re.search(rb"\b" + re.escape(o.encode()) + rb"\b", t) for o in (USUARIO, MAQUINA) if len(o) >= 3):
                sobras.append(p)
    if sobras:
        print(f"ATENÇÃO: {len(sobras)} arquivo(s) ainda trazem usuário, nome da máquina ou algo com cara de chave; revise antes de commitar:")
        for p in sobras[:20]:
            print("  ", p.relative_to(pasta))
        return 3
    print("pronto: cache e lixo removidos dos home/, caminhos e nome da máquina trocados; varredura final limpa")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
