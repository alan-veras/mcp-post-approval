"""A ordem das execuções: intercalada, sorteada com a semente 20261109 (seção 2 do pré-registro).

Cada parte tem a sua lista, embaralhada por uma ordenação por números sorteados (só `random()`, que é estável entre
versões do Python). Assim cliente, célula e modelo se alternam, e uma mudança do provedor no meio da coleta não cai
toda numa célula. Parte 1 mistura os componentes (reconsentimento, entrega, instalação, gêmeo); Parte 2 mistura
clientes, células e modelos. Nada aqui lê o resultado de nada.
"""
import random
from typing import NamedTuple

from instrumento.dominio import cargas

SEMENTE = 20261109
CLIENTES = ["cc", "qw", "cx"]            # Claude Code, Qwen Code, Codex CLI
MODELOS = ["mistralai/mistral-large-4-1t-a52b", "nvidia/nemotron-3-ultra-550b-a55b"]
CANAIS = ["npx", "uvx"]
REPS_PARTE1, REPS_PARTE2 = 1, 5
REPS_GEMEO = 5  # o gêmeo invisível tem 5 por cliente na confirmatória (o Claude Code variou entre execuções iguais no ensaio)
COMPONENTES = ["reconsentimento", "entrega", "instalacao", "gemeo"]


class Item(NamedTuple):
    """Uma execução da fila. `valor` é a célula, a técnica ou o canal; `modelo` só existe na Parte 2."""
    componente: str
    cliente: str
    valor: str
    rep: int
    modelo: str = ""


def itens_parte1(reps=REPS_PARTE1):
    """Com as repetições do pré-registro (reps=1), o gêmeo leva REPS_GEMEO; com --reps do ensaio, todos levam o mesmo N."""
    reps_gemeo = REPS_GEMEO if reps == REPS_PARTE1 else reps
    itens = []
    for c in CLIENTES:
        for r in range(1, reps + 1):
            itens += [Item("reconsentimento", c, cel, r) for cel in cargas.CELULAS_CLIENTE]
            itens += [Item("entrega", c, t, r) for t in cargas.TECNICAS]
            itens += [Item("instalacao", c, canal, r) for canal in CANAIS]
        itens += [Item("gemeo", c, "gemeo_invisivel", r) for r in range(1, reps_gemeo + 1)]
    return itens


def itens_parte2(reps=REPS_PARTE2):
    return [Item("obediencia", c, cel, r, m) for m in MODELOS for c in CLIENTES for cel in cargas.CELULAS_MODELO
            for r in range(1, reps + 1)]


def sorteia(itens, semente=SEMENTE):
    """A mesma lista, na ordem sorteada com a semente (a ordem de entrada é a canônica: nunca depende de conjunto)."""
    rng = random.Random(semente)
    pesos = [rng.random() for _ in itens]
    return [itens[i] for i in sorted(range(len(itens)), key=lambda i: pesos[i])]


def ordem_parte1(reps=REPS_PARTE1):
    return sorteia(itens_parte1(reps))


def ordem_parte2(reps=REPS_PARTE2):
    return sorteia(itens_parte2(reps))
