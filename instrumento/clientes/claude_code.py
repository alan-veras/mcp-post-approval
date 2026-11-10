"""Claude Code (Anthropic). Fala Anthropic Messages com o endpoint falso."""
import json
import os

from instrumento.clientes.configuracao import escreve, mescla_json
from instrumento.clientes.isolamento import acha_binario, ambiente, home, projeto, versao_de


NOME = "claude-code"


def binario():
    # na confirmatória o coleta.py aponta para uma cópia fixa: o `claude` do PATH se atualiza sozinho
    return os.environ.get("CLAUDE_CODE_BINARIO") or acha_binario("claude")


def versao():
    return versao_de([binario(), "--version"])


def prepara(pasta, servidor, porta, modo, gemeo=None):
    proj = projeto(pasta)
    env = ambiente(pasta, ANTHROPIC_BASE_URL=f"http://127.0.0.1:{porta}", ANTHROPIC_API_KEY="falso-sem-valor",
                   DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1",
                   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
    # busca de ferramentas desligada nas duas partes. No padrão o Claude Code adia as ferramentas MCP: a definição só
    # entra no prompt quando o modelo a pede, e o endpoint roteirizado nunca pede. Sem isso a entrega daria `ausente` nas
    # 12 técnicas, e o reconsentimento não veria a ferramenta na lista para chamá-la.
    env["ENABLE_TOOL_SEARCH"] = "false"
    mescla_json(home(pasta) / ".claude.json", {
        "hasCompletedOnboarding": True, "theme": "dark", "numStartups": 5,
        "customApiKeyResponses": {"approved": ["falso-sem-valor"], "rejected": []},
        "projects": {str(proj): {"hasTrustDialogAccepted": True, "hasCompletedProjectOnboarding": True}}})
    # alwaysLoad: sem ele, em -p, a ferramenta não chega ao modelo no turno 1 (validado com claude 2.1.321)
    entrada = lambda s: {"type": "stdio", "command": s.comando[0], "args": s.comando[1:], "alwaysLoad": True}
    servidores = {servidor.nome: entrada(servidor)}
    if gemeo:
        servidores[gemeo.nome] = entrada(gemeo)
    escreve(proj / ".mcp.json", json.dumps({"mcpServers": servidores}))
    if modo == "entrega":
        mescla_json(proj / ".claude" / "settings.json", {"enableAllProjectMcpServers": True})
    return env


def comando_nao_interativo(pedido):
    return [binario(), "-p", pedido]


def comando_interativo():
    return [binario(), "--permission-mode", "default"]


# pronto: a tela aceita o pedido. antes: diálogos de partida que não são a aprovação medida.
# aprovacoes: (tipo, texto do pedido, teclas, texto da opção mais ampla)
ROTEIRO_FASE_A = {
    "pronto": r"mode on",
    "antes": [],
    "aprovacoes": [
        ("servidor", r"New MCP server found", [("seleciona", r"all future MCP servers"), "enter"],
         "Use this and all future MCP servers in this project"),
        ("chamada", r"Do you want to proceed", [("seleciona", r"don't ask again"), "enter"],
         "Yes, and don't ask again for servidor-teste"),
    ],
}
PADROES_APROVACAO = {"servidor": [r"New MCP server found"], "chamada": [r"Do you want to proceed"]}

# Parte 2: a automação aprova também os pedidos de shell e de edição de arquivo (opção sim/sempre). Os padrões são os da
# interface do cliente na versão fixada e precisam ser conferidos contra telas gravadas num ensaio com o cliente real.
# (O pedido de shell do Claude Code usa a mesma frase do pedido de ferramenta, já coberto por "chamada".)
APROVACOES_PARTE2 = [
    ("shell", r"Do you want to proceed", [("seleciona", r"don.t ask again for"), "enter"],
     "Yes, and don't ask again for: <comando> (se a linha não existir, fica o 1. Yes)"),
    ("edicao", r"Do you want to (make this edit|create)", [("seleciona", r"allow all edits|Yes"), "enter"], "Yes, allow all edits during this session"),
]
