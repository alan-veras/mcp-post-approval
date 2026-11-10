"""O que é conferido antes de cada passo: trava, manifesto, versões e SHA-256 dos clientes e chave."""

import os
import subprocess

from instrumento import config
from instrumento.clientes import isolamento
from instrumento.coleta.fila import CLAUDE_FIXO, FIXADAS


MANIFESTO = config.RAIZ / "selo" / "MANIFEST.sha256"


def ambiente_da_coleta():
    """O ambiente do rodar e dos clientes: sem variável de chave (a chave da Parte 2 é lida de TCC/.env só pelo provedor),
    com o binário fixo do Claude Code."""
    return {**isolamento.sem_chaves(os.environ), "CLAUDE_CODE_BINARIO": str(CLAUDE_FIXO), "PYTHONDONTWRITEBYTECODE": "1"}


def versoes_atuais():
    from instrumento import clientes
    from instrumento.partes import comum
    os.environ["CLAUDE_CODE_BINARIO"] = str(CLAUDE_FIXO)
    return {r: (clientes.cliente(r).versao(), comum.sha256_binario(clientes.cliente(r)))
            for r in clientes.ORDEM_RECONSENTIMENTO}


def problemas(precisa_chave):
    """Lista do que impede a coleta (vazia: pode rodar)."""
    erros = []
    if not config.TRAVA.exists():
        erros.append("falta TRAVA-COLETA na raiz do experimento (quem cria é o Alan, depois do selo)")
    if not MANIFESTO.exists():
        erros.append(f"falta {MANIFESTO.name} (o selo do plano)")
    else:
        r = subprocess.run(["sha256sum", "--quiet", "-c", str(MANIFESTO)], cwd=config.RAIZ, capture_output=True, text=True)
        if r.returncode:
            erros.append("o instrumento mudou depois do selo:\n" + (r.stdout + r.stderr).strip())
    if not CLAUDE_FIXO.exists():
        erros.append(f"falta a cópia fixa do Claude Code em {CLAUDE_FIXO}")
    atuais = versoes_atuais()
    for rot, (versao, sha) in FIXADAS.items():
        v, s = atuais.get(rot, ("?", "?"))
        if (v, s) != (versao, sha):
            erros.append(f"cliente {rot}: fixado {versao} {sha[:12]}, achado {v} {s[:12]}")
    if precisa_chave and not (config.RAIZ.parent / ".env").exists():
        # o rodar da coleta não herda variável de chave: a Parte 2 lê a chave só de TCC/.env (o conteúdo não é lido aqui)
        erros.append("falta o arquivo TCC/.env com a chave da NVIDIA (a Parte 2 ainda tem passos)")
    return erros
