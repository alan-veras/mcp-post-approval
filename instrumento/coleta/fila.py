"""A fila da rodada 2: as versões fixadas dos clientes e um passo por parte (a Parte 1 mistura os componentes na ordem
sorteada com a semente 20261109; a Parte 2 mistura clientes, células e modelos)."""

from pathlib import Path
from typing import NamedTuple

from instrumento.dominio import ordem

# a cópia fixa do Claude Code (o `claude` do PATH se atualiza sozinho)
CLAUDE_FIXO = Path.home() / ".local/share/tcc-clientes-fixos/claude-2.1.321"

# rótulo -> (versão, SHA-256 do binário que o cliente executa, seguindo links). Conferidos em 9/nov/2026 nas versões
# instaladas: claude 2.1.321 (a que validou o alwaysLoad; cópia fixa em CLAUDE_FIXO), qwen 0.26.0 e codex 0.155.1
# (estes dois com o mesmo SHA-256 da rodada 1). O que valer no selo fica no manifesto.
FIXADAS = {
    "cc": ("2.1.321", "426c33815ca6645a772f722fbff10dbf2cbdb124a8aeab733c1365dbf8bbf61f"),
    "qw": ("0.26.0", "3c53a220bdf124e8ef9fd28cd3465c761a2a466deb6dc6a97272d0a6d1121f59"),
    "cx": ("0.155.1", "61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70"),
}

MODELOS = list(ordem.MODELOS)
CODIGO_PARADA_INSTRUMENTO = 5
CODIGO_PARADA_PROVEDOR = 6


class Saida(NamedTuple):
    """Um CSV que o passo grava: o arquivo, a chave que identifica uma execução e quantas são esperadas."""
    csv: str
    chave: tuple
    esperadas: int


class Passo(NamedTuple):
    nome: str
    argv: list
    saidas: tuple
    gasta_api: bool = False


n1, n2 = len(ordem.CLIENTES), len(ordem.CLIENTES)
FILA = [
    Passo("parte1", ["rodar", "--parte", "parte1"], (
        Saida("reconsentimento-confirmatoria.csv", ("cliente", "celula", "rep"), 7 * n1),
        Saida("entrega-confirmatoria.csv", ("cliente", "tecnica", "rep"), 4 * n1),
        Saida("instalacao-confirmatoria.csv", ("cliente", "canal", "cabecalhos", "celula", "rep"), 2 * n1),
        Saida("gemeo-confirmatoria.csv", ("cliente", "rep"), n1 * ordem.REPS_GEMEO))),
    Passo("sonda", ["rodar", "--parte", "sonda"],
          (Saida("instalacao-sonda-confirmatoria.csv", ("canal", "cabecalhos", "passo"), 2 * 5),)),
    Passo("parte2", ["rodar", "--parte", "parte2"],
          (Saida("obediencia-confirmatoria.csv", ("cliente", "celula", "rep", "modelo"),
                 n1 * 6 * ordem.REPS_PARTE2 * len(MODELOS)),), gasta_api=True),
]
