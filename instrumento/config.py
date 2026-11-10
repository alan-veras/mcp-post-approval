"""Onde cada coisa mora: a raiz do experimento, o `experimento.py` e as pastas de dados.

`resultados/` recebe a coleta confirmatória (só com TRAVA-COLETA na raiz); a coluna `evidencia` dos CSVs é relativa a ela.
`saida-local/`, fora do git, recebe o ensaio (`--ensaio`), que testa o instrumento sem trava e nunca toca em `resultados/`.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
EXPERIMENTO = RAIZ / "experimento.py"
RESULTADOS = RAIZ / "resultados"
SAIDA_LOCAL = RAIZ / "saida-local"
MODOS = ("confirmatoria", "ensaio")  # o rótulo vai em cada linha de CSV e no nome dos arquivos
TRAVA = RAIZ / "TRAVA-COLETA"
PAUSA = RAIZ / "PAUSAR"  # se existe, o rodar para antes da próxima execução (coleta.py pausar)
CODIGO_PAUSA_PEDIDA = 4


class PausaPedida(Exception):
    """O arquivo PAUSAR apareceu: o rodar sai entre duas execuções, sem perder nenhuma."""


def checa_pausa():
    if PAUSA.exists():
        raise PausaPedida()


def pasta_do_modo(modo):
    """Onde o modo grava e o analise lê: resultados/ na confirmatória, saida-local/ no ensaio."""
    if modo not in MODOS:
        raise ValueError(f"modo desconhecido: {modo}")
    return RESULTADOS if modo == "confirmatoria" else SAIDA_LOCAL
