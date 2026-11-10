"""O modo roteirizado: chama a ferramenta de teste uma vez e depois responde "ok"."""

import json
import re

from instrumento.simulacao.endpoint.formatos import (SUFIXO_FERRAMENTA, chamadas_anteriores, nomes_oferecidos,
                                                     tem_resultado)


# A ferramenta de shell de cada cliente, com o nome que ele anuncia na lista de ferramentas e o argumento da linha de comando
# (Claude Code: Bash/command; Qwen Code: run_shell_command/command; Codex: exec_command/cmd). Nomes lidos de pedidos reais.
FERRAMENTAS_DE_SHELL = {"Bash": "command", "run_shell_command": "command", "exec_command": "cmd"}


def decide(modo, formato, corpo, alvo_gemeo=False, comando_shell=None):
    """(acao, nome, argumentos): acao é "ok" ou "chamada"; nome é o nome a chamar.

    Com `alvo_gemeo` (gêmeo invisível da Parte 1), o servidor aprovado e o gêmeo oferecem a mesma ferramenta; a
    chamada vai à de nome mais longo, que é a do gêmeo (o nome dele tem um caractere a mais, ou um `_` no lugar dele).

    Quando o cliente adia as ferramentas MCP e só oferece a ponte (Qwen Code:
    tool_search, depois tool_call), a chamada vai pela ponte, nesses dois passos.
    """
    if modo != "roteirizado":
        return "ok", None, {}
    oferecidos, feitas = nomes_oferecidos(corpo), chamadas_anteriores(formato, corpo)
    if comando_shell:  # ensaio --forcar-shell --roteirizado: o "modelo" pede o shell do cliente, uma vez, e depois diz ok
        shell = [n for n in oferecidos if n in FERRAMENTAS_DE_SHELL]
        if shell:
            return ("ok", None, {}) if shell[0] in feitas else ("chamada", shell[0], {FERRAMENTAS_DE_SHELL[shell[0]]: comando_shell})
    alvo = [n for n in oferecidos if n.endswith(SUFIXO_FERRAMENTA)]
    if alvo:
        escolhido = max(alvo, key=len) if alvo_gemeo else alvo[0]
        return ("ok", None, {}) if tem_resultado(formato, corpo) else ("chamada", escolhido, {})
    # `\w*` no fim: o Qwen Code acrescenta um sufixo ao nome do gêmeo (`..._consulta_teste_1xro731`, visto na tela do ensaio)
    achados = re.findall(r"mcp__[\w-]+__" + SUFIXO_FERRAMENTA + r"\w*", json.dumps(corpo))
    achou = (max(achados, key=len) if alvo_gemeo else achados[0]) if achados else None
    if achou and "tool_search" in oferecidos and "tool_call" in oferecidos:
        if "tool_search" not in feitas:
            return "chamada", "tool_search", {"query": "select:" + achou}
        if "tool_call" not in feitas:
            return "chamada", "tool_call", {"name": achou, "arguments": {}}
    return "ok", None, {}
