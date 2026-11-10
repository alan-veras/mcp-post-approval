"""O contrato que todo arquivo de cliente cumpre (um módulo por cliente, sem herança)."""
from typing import Protocol

from instrumento.clientes.configuracao import ServidorMCP


class Cliente(Protocol):
    """O que as partes usam de um cliente.

    NOME: o nome do cliente; binario() e versao(): onde está e qual é;
    prepara(pasta, servidor, porta, modo, gemeo=None): escreve (gemeo: um segundo ServidorMCP, só no gêmeo da Parte 1) a configuração na pasta isolada e devolve o ambiente;
    comando_nao_interativo(pedido) e comando_interativo(): as linhas de comando;
    ROTEIRO_FASE_A: pronto (a tela aceita o pedido), antes (diálogos de partida), aprovacoes
    ((tipo, texto do pedido, teclas, texto da opção mais ampla)) e, se preciso, folga (segundos);
    PADROES_APROVACAO: {"servidor": [...], "chamada": [...]}, os padrões de tela de um novo pedido.
    """

    NOME: str
    ROTEIRO_FASE_A: dict
    PADROES_APROVACAO: dict

    def binario(self) -> str | None: ...

    def versao(self) -> str: ...

    def prepara(self, pasta, servidor: ServidorMCP, porta: int, modo: str, gemeo: ServidorMCP | None = None) -> dict: ...

    def comando_nao_interativo(self, pedido: str) -> list: ...

    def comando_interativo(self) -> list: ...
