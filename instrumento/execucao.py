"""O laço comum das partes: cada execução pendente roda uma vez e grava a sua linha; dá para pausar entre duas."""
from typing import Callable, NamedTuple

from instrumento import config
from instrumento.analise import csvs
from instrumento.parada import Parada


class Recusa(Exception):
    """O rodar recusa antes de abrir qualquer cliente; a mensagem vai para o usuário."""


class Tarefa(NamedTuple):
    """Uma execução da fila: onde grava, a chave que a identifica, como roda e como se descreve."""
    csv: object
    campos: list
    campos_chave: tuple
    chave: tuple
    roda: Callable
    descreve: Callable
    componente: str = ""


def percorre(tarefas, motivo_de_parada=None):
    """Roda as tarefas NA ORDEM dada (a ordem sorteada). Pula a chave que já tem linha no CSV (parar e retomar nunca
    refaz nem perde execução), confere o arquivo PAUSAR antes de cada uma, grava a linha e a imprime. Se
    `motivo_de_parada(linha, componente)` devolver texto, levanta Parada depois de gravar a linha. Devolve quantas
    tiveram falha de instrumento."""
    falhas = 0
    for t in tarefas:
        if csvs.ja_feito(t.csv, t.campos_chave, t.chave):
            continue
        config.checa_pausa()
        linha = t.roda()
        csvs.grava_linha(t.csv, t.campos, linha)
        print(t.descreve(linha), flush=True)
        falhas += bool(linha["falha_instrumento"])
        motivo = motivo_de_parada(linha, t.componente) if motivo_de_parada else ""
        if motivo:
            raise Parada(motivo)
    return falhas
