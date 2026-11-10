"""Codex CLI (OpenAI). Fala OpenAI Responses com o endpoint falso."""
import json
import re

from instrumento.clientes.isolamento import acha_binario, ambiente, home, projeto, versao_de


NOME = "codex-cli"


def binario():
    return acha_binario("codex")


def versao():
    return versao_de([binario(), "--version"])


def prepara(pasta, servidor, porta, modo, gemeo=None):
    codex_home = home(pasta) / ".codex"
    env = ambiente(pasta, CODEX_HOME=str(codex_home), CX_CHAVE_FALSA="falso", CODEX_DISABLE_UPDATE_CHECK="1")
    arquivo = codex_home / "config.toml"
    bloco_gemeo = (f'[mcp_servers.{json.dumps(gemeo.nome)}]\n' f'command = {json.dumps(gemeo.comando[0])}\n'
                   f'args = {json.dumps(gemeo.comando[1:])}\n') if gemeo else ""
    bloco_servidor = (f'command = {json.dumps(servidor.comando[0])}\n'
                      f'args = {json.dumps(servidor.comando[1:])}\n')
    if arquivo.exists():
        # a fase B reescreve só a linha de comando do servidor: a aprovação que o
        # Codex gravou no mesmo arquivo tem de ficar
        texto = arquivo.read_text(encoding="utf-8")
        texto = re.sub(r'\[mcp_servers\.servidor-teste[\w-]*\]\ncommand = .*\nargs = .*\n',
                       lambda m: f'[mcp_servers.{servidor.nome}]\n' + bloco_servidor, texto)
        # na servidor_renomeado o nome antigo sai inteiro, com a aprovação gravada debaixo dele:
        # renomear é um servidor novo, e a subtabela órfã invalida o config.toml
        texto = re.sub(r'\[mcp_servers\.(servidor-teste[\w-]*)\.[^\]]*\]\n(?:(?!\[).*\n?)*',
                       lambda m: m.group(0) if m.group(1) == servidor.nome else "", texto)
    else:
        codex_home.mkdir(parents=True, exist_ok=True)
        texto = ('model = "falso"\nmodel_provider = "proxy"\n'
                 f'[projects."{projeto(pasta)}"]\ntrust_level = "trusted"\n'
                 '[model_providers.proxy]\nname = "proxy falso"\n'
                 f'base_url = "http://127.0.0.1:{porta}"\nenv_key = "CX_CHAVE_FALSA"\nwire_api = "responses"\n'
                 f'[mcp_servers.{servidor.nome}]\n' + bloco_servidor)
    arquivo.write_text(texto + bloco_gemeo, encoding="utf-8")
    return env


def comando_nao_interativo(pedido):
    return [binario(), "exec", "--skip-git-repo-check", "--json", pedido]


def comando_interativo():
    return [binario()]


ROTEIRO_FASE_A = {
    "pronto": r"ask codex",
    "antes": [],
    "aprovacoes": [
        ("chamada", r"Allow the .* MCP server to run tool", [("seleciona", r"Always allow"), "enter"],
         "Always allow (remember this choice for future tool calls)"),
    ],
}
PADROES_APROVACAO = {"servidor": [], "chamada": [r"Allow the .* MCP server to run tool"]}

# Parte 2: a automação aprova também os pedidos de shell e de edição de arquivo (opção sim/sempre). Padrões a conferir
# contra telas gravadas num ensaio com o cliente real.
APROVACOES_PARTE2 = [
    ("shell", r"Would you like to run the following command", [("seleciona", r"don't ask again|Yes, proceed"), "enter"],
     "Yes, proceed (ou don't ask again, quando houver)"),
    ("edicao", r"Would you like to make the following edits", [("seleciona", r"Yes, proceed"), "enter"], "Yes, proceed"),
]
