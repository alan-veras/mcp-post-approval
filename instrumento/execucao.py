"""O laço comum das partes: cada execução pendente roda uma vez e grava a sua linha; dá para pausar entre duas. Na Parte 1, o erro de conexão local do cliente refaz até 2 vezes."""
import re
from pathlib import Path
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


# Parte 1: o único erro de infraestrutura visto no ensaio (1 em cerca de 270): o Qwen Code sem conseguir abrir conexão com o
# endereço local. Lista fechada; "a tela não ficou pronta", "o servidor não recebeu a chamada" e "o modelo não pediu a
# chamada" NÃO entram, porque podem ser comportamento do cliente (resultado).
CONEXAO_LOCAL = re.compile(r"API Error: Connection error\. \(cause: fetch failed\)")
REFACOES_INFRA_PARTE1 = 2


def conexao_local_falhou(linha, aqui):
    """A linha tem falha de instrumento E o histórico da tela traz o erro de conexão local do cliente (lista fechada)."""
    pasta = Path(aqui) / (linha.get("evidencia") or "_")
    if not linha.get("falha_instrumento") or not pasta.is_dir():
        return False
    return any(CONEXAO_LOCAL.search(h.read_text(encoding="utf-8", errors="replace")) for h in pasta.glob("historico-*.txt"))


def arquiva_tentativa(linha, aqui, n):
    """Guarda a evidência da tentativa que vai ser refeita (nada é apagado): `<pasta>-t<n>`; a linha aponta para ela."""
    origem = Path(aqui) / linha["evidencia"]
    destino = origem.with_name(f"{origem.name}-t{n}")
    origem.rename(destino)
    linha["evidencia"] = str(Path(linha["evidencia"]).with_name(destino.name))


def percorre(tarefas, motivo_de_parada=None, refaz_se=None, aqui=None):
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
        for n in range(1, REFACOES_INFRA_PARTE1 + 1):  # só infraestrutura (lista fechada), no máximo 2 vezes, tudo registrado
            if not (refaz_se and refaz_se(linha, aqui)):
                break
            arquiva_tentativa(linha, aqui, n)
            csvs.grava_linha(t.csv, t.campos, linha)
            print(t.descreve(linha) + f"  [refeita: erro de conexão local ({n}/{REFACOES_INFRA_PARTE1})]", flush=True)
            linha = t.roda()
        csvs.grava_linha(t.csv, t.campos, linha)
        print(t.descreve(linha), flush=True)
        falhas += bool(linha["falha_instrumento"])
        motivo = motivo_de_parada(linha, t.componente) if motivo_de_parada else ""
        if motivo:
            raise Parada(motivo)
    return falhas
