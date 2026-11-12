"""Qwen Code (Alibaba). Fala OpenAI Chat Completions com o endpoint falso."""

from instrumento.clientes.configuracao import mescla_json, so_o_servidor_atual
from instrumento.clientes.isolamento import acha_binario, ambiente, home, versao_de


NOME = "qwen-code"


def binario():
    return acha_binario("qwen")


def versao():
    return versao_de([binario(), "--version"])


def prepara(pasta, servidor, porta, modo, gemeo=None):
    env = ambiente(pasta, OPENAI_API_KEY="falso", OPENAI_BASE_URL=f"http://127.0.0.1:{porta}/v1",
                   OPENAI_MODEL="falso", QWEN_CODE_DISABLE_AUTOUPDATE="1", DISABLE_AUTOUPDATER="1",
                   QWEN_TELEMETRY_ENABLED="false", DEBUG="")
    so_o_servidor_atual(home(pasta) / ".qwen" / "settings.json", servidor.nome, "mcpServers")
    mescla_json(home(pasta) / ".qwen" / "settings.json", {
        "security": {"auth": {"selectedType": "openai"}},
        "model": {"name": "falso"},
        "general": {"disableAutoUpdate": True, "disableUpdateNag": True},
        "privacy": {"usageStatisticsEnabled": False},
        "telemetry": {"enabled": False},
        "mcpServers": {s.nome: {"command": s.comando[0], "args": s.comando[1:], "alwaysLoadTools": True}
                       for s in (servidor, gemeo) if s}})
    return env


def comando_nao_interativo(pedido):
    return [binario(), pedido]


def comando_interativo():
    return [binario(), "--approval-mode", "default"]


ROTEIRO_FASE_A = {
    "pronto": r"type your message",
    "antes": [],
    "aprovacoes": [
        ("chamada", r"Allow execution of MCP tool", [("seleciona", r"Always allow .* for this user"), "enter"],
         "Always allow mcp__servidor-teste__consulta_teste for this user"),
    ],
}
PADROES_APROVACAO = {"servidor": [], "chamada": [r"Allow execution of MCP tool"]}

# Parte 2: a automação aprova também os pedidos de shell e de edição de arquivo (opção sim/sempre). Padrões a conferir
# contra telas gravadas num ensaio com o cliente real.
APROVACOES_PARTE2 = [
    ("shell", r"Allow execution of: ", [("seleciona", r"Always allow run .* for this user"), "enter"],
     "Always allow run '<comando> *' commands for this user (se a linha não existir, fica o 1. Yes, allow once)"),
    ("edicao", r"Apply this change", [("seleciona", r"allow always|Yes"), "enter"], "Yes, allow always"),
]
