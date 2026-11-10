"""Os 3 clientes medidos (aprovação persistente): um módulo por cliente, todos com o contrato de `contrato.Cliente`.

`isolamento` monta o ambiente de cada execução e `configuracao` escreve os arquivos que o cliente lê.
"""
import importlib

# rótulo curto (usado em --clientes) -> módulo do cliente
CLIENTES = {"cc": "claude_code", "qw": "qwen", "cx": "codex"}
ORDEM_RECONSENTIMENTO = ["cc", "qw", "cx"]


def cliente(rotulo):
    """O módulo do cliente de rótulo `rotulo` (um `contrato.Cliente`)."""
    return importlib.import_module(f"instrumento.clientes.{CLIENTES[rotulo]}")
