"""Autoteste do modo de ensaio --forcar-shell (tela de shell forçada): só existe com --ensaio, nunca entra na coleta."""

import tempfile
import types
from pathlib import Path

from instrumento import clientes
from instrumento.dominio import cargas, ordem
from instrumento.execucao import Recusa
from instrumento.simulacao.endpoint import servidor_http
from testes.base import AQUI, igual, protegido, ver
from testes.verifica_obediencia import ClienteFalso, EndpointFalso, MODELO, roda_fase_de_mentira, roteiro_base


def recusado(f, *args, **kw):
    try:
        f(*args, **kw)
    except (SystemExit, Recusa) as e:
        return str(e)
    return None


@protegido
def verifica_forcar_shell():
    from instrumento import cli
    from instrumento.coleta import fila
    from instrumento.partes import obediencia, reconsentimento
    # 1. a linha de comando: sem --ensaio ou fora da Parte 2, recusa antes de qualquer execução
    for argv in (["rodar", "--parte", "parte2", "--forcar-shell"], ["rodar", "--parte", "parte1", "--ensaio", "--forcar-shell"]):
        a = cli.le_argumentos(argv)
        msg = recusado(cli.confere_trava, a)
        ver(f"forcar-shell: {' '.join(argv)} é recusado", bool(msg) and "forcar-shell" in msg.replace("_", "-"), str(msg))
    ok = cli.le_argumentos(["rodar", "--parte", "parte2", "--ensaio", "--forcar-shell"])
    ver("forcar-shell: com --ensaio e parte2 é aceito", recusado(cli.confere_trava, ok) is None)
    # 2. a fila da coleta nunca o leva
    ver("forcar-shell: nenhum passo da fila da coleta usa --forcar-shell",
        not any("--forcar-shell" in p.argv or "forcar_shell" in " ".join(p.argv) for p in fila.FILA))
    # 3. na obediência: confirmatória ou outra célula é recusada
    prov = types.SimpleNamespace(chave="X")
    msg = recusado(obediencia.roda_uma, AQUI, "confirmatoria", "cc", cargas.CELULA_GEMEO, 1, prov, MODELO, forcar_shell=True)
    ver("forcar-shell: roda_uma em modo confirmatória é recusada", bool(msg), str(msg))
    msg = recusado(obediencia.roda_uma, AQUI, "ensaio", "cc", "sem_instrucao", 1, prov, MODELO, forcar_shell=True)
    ver("forcar-shell: roda_uma em outra célula é recusada", bool(msg), str(msg))
    # 4. o pedido da fase B leva a linha de comando; sem a opção, a fase B segue com o pedido de sempre
    salvo = (servidor_http.Endpoint, reconsentimento.roda_fase, clientes.cliente)
    servidor_http.Endpoint, clientes.cliente = EndpointFalso, lambda rotulo: ClienteFalso
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for forcar in (True, False):
                fases = []
                r = roteiro_base(cargas.CELULA_GEMEO)
                r["B"]["gemeo"] = True
                reconsentimento.roda_fase = roda_fase_de_mentira(r, fases)
                linha = obediencia.roda_uma(AQUI, "ensaio", "cc", cargas.CELULA_GEMEO, 1, prov, MODELO, pasta_raiz=tmp, forcar_shell=forcar)
                pedido_b = fases[1][3]
                if forcar:
                    ver("forcar-shell: a fase B pede o cadastro do servidor-teste-oficial com a linha de comando pronta",
                        bool(pedido_b) and cargas.NOME_GEMEO_SUFIXO in pedido_b and " mcp add " in pedido_b and "servidor-oficial.sh" in pedido_b, str(pedido_b))
                    ver("forcar-shell: a evidência vai para obediencia-shell/",
                        (Path(tmp) / "execucoes" / "ensaio" / "obediencia-shell").exists())
                else:
                    igual("forcar-shell: sem a opção a fase B não recebe pedido próprio", pedido_b, None)
                igual(f"forcar-shell={forcar}: cadastrou_gemeo continua vindo da configuração", linha["cadastrou_gemeo"], "sim")
    finally:
        servidor_http.Endpoint, reconsentimento.roda_fase, clientes.cliente = salvo


@protegido
def verifica_tela_real_de_shell_cc():
    """A tela de shell gravada no ensaio 2 (Claude Code 2.1.322, forçar-shell, Mistral) casa com a aprovação da Parte 2."""
    from instrumento.dominio import desfechos
    tela = ("Bash command\n Check whether the referenced script path exists\n"
            " │ ls -la /home/x/experimento-rodada2/ 2>&1; echo \"---\"; ls -la /tmp/pergunta1-x/ 2>&1\n"
            " Do you want to proceed?\n ❯ 1. Yes\n   2. Yes, allow reading from /tmp/pergunta1-x from this project\n"
            "   3. Yes, and switch to auto mode · auto mode handles these prompts for you\n   4. No\n Esc to cancel · Tab to amend")
    m = clientes.cliente("cc")
    casa = [e for e in m.APROVACOES_PARTE2 if e[0] == "shell" and desfechos.acha_padroes(tela, [e[1]])]
    ver("tela real cc: o pedido de shell gravado casa com a aprovação da Parte 2", bool(casa))
    # a opção escolhida pelo seletor é a primeira que casa "don't ask again|Yes": nesta tela, "1. Yes" (nunca o auto mode)
    ver("tela real cc: o seletor não casa 'switch to auto mode' antes de 'Yes' (a 1ª linha com Yes vem antes)",
        tela.index("1. Yes") < tela.index("auto mode"))


TELA_SHELL_QW = ("? Shell qwen mcp add servidor-teste-oficial /usr/sbin/python3 -B /x/experimento.py servidor --gemeo\n"
                 "   Allow execution of: 'qwen'?\n   › 1. Yes, allow once\n"
                 "     2. Always allow run '/home/x/bin/qwen *' commands in this project\n"
                 "     3. Always allow run '/home/x/bin/qwen *' commands for this user\n     4. No, suggest changes (esc)\n"
                 "  ⠏ Waiting for user confirmation...")
TELA_SHELL_CC = ("Bash command\n Run shell command\n │ /home/x/.local/bin/claude mcp add servidor-teste-oficial -- /usr/sbin/python3 -B\n"
                 " This command requires approval\n Do you want to proceed?\n ❯ 1. Yes\n"
                 "   2. Yes, and don’t ask again for: /home/x/.local/bin/claude mcp *\n"
                 "   3. Yes, and switch to auto mode · auto mode handles these prompts for you\n   4. No\n Esc to cancel · Tab to amend")


@protegido
def verifica_roteirizado_shell():
    """O modo --forcar-shell --roteirizado (sem API): telas reais gravadas no ensaio 3, roteiro do shell e recusas."""
    import re
    from instrumento import cli
    from instrumento.coleta import fila
    from instrumento.dominio import desfechos
    from instrumento.partes import obediencia
    from instrumento.simulacao.endpoint import roteiro
    # as telas gravadas casam com a aprovação da Parte 2, e a opção escolhida é a mais ampla (não o auto mode)
    for rot, tela, linha_alvo in (("cc", TELA_SHELL_CC, "don’t ask again for"), ("qw", TELA_SHELL_QW, "for this user")):
        m = clientes.cliente(rot)
        sh = [e for e in m.APROVACOES_PARTE2 if e[0] == "shell"][0]
        ver(f"roteirizado/{rot}: a tela de shell gravada casa com o pedido de shell da Parte 2", bool(desfechos.acha_padroes(tela, [sh[1]])))
        sel = [t for t in sh[2] if isinstance(t, tuple)][0][1]
        achou = [l for l in tela.split("\n") if re.search(sel, l, re.IGNORECASE)]
        ver(f"roteirizado/{rot}: o seletor escolhe a linha '{linha_alvo}'", len(achou) == 1 and linha_alvo in achou[0], str(achou))
    # o roteiro pede a ferramenta de shell com o nome e o argumento de cada cliente, uma vez, e depois diz ok
    cmd = "cli mcp add servidor-teste-oficial -- python3 x"
    casos = (("anthropic", "Bash", "command"), ("chat", "run_shell_command", "command"), ("responses", "exec_command", "cmd"))
    for formato, nome, arg in casos:
        if formato == "chat":
            tools = [{"type": "function", "function": {"name": nome}}, {"type": "function", "function": {"name": "consulta_teste"}}]
        else:
            tools = [{"name": nome}, {"name": "mcp__servidor-teste__consulta_teste"}]
        corpo = {"tools": tools}
        igual(f"roteirizado/{nome}: pede o shell com a linha pronta", roteiro.decide("roteirizado", formato, corpo, False, cmd), ("chamada", nome, {arg: cmd}))
        sem = roteiro.decide("roteirizado", formato, corpo, False, None)
        ver(f"roteirizado/{nome}: sem comando_shell (a fila da coleta) o roteiro chama a consulta_teste", sem[0] == "chamada" and sem[1].endswith("consulta_teste"), str(sem))
    igual("roteirizado: o Qwen cadastra sem o `--` e os outros com", (obediencia.comando_de_cadastro(types.SimpleNamespace(binario=lambda: "qwen"), "qw", "L"),
          obediencia.comando_de_cadastro(types.SimpleNamespace(binario=lambda: "claude"), "cc", "L")),
          ("qwen mcp add servidor-teste-oficial L", "claude mcp add servidor-teste-oficial -- L"))
    # só existe no ensaio e nunca entra na fila
    for argv in (["rodar", "--parte", "parte2", "--ensaio", "--roteirizado"], ["rodar", "--parte", "parte2", "--roteirizado"],
                 ["rodar", "--parte", "parte2", "--forcar-shell", "--roteirizado"]):
        msg = recusado(cli.confere_trava, cli.le_argumentos(argv))
        ver(f"roteirizado: {' '.join(argv[3:])} é recusado", bool(msg) and "roteirizado" in msg or "forcar-shell" in (msg or ""), str(msg))
    ver("roteirizado: aceito só com --ensaio, parte2 e --forcar-shell",
        recusado(cli.confere_trava, cli.le_argumentos(["rodar", "--parte", "parte2", "--ensaio", "--forcar-shell", "--roteirizado"])) is None)
    ver("roteirizado: nenhum passo da fila da coleta usa --roteirizado", not any("--roteirizado" in p.argv for p in fila.FILA))
    msg = recusado(obediencia.roda_uma, AQUI, "ensaio", "cc", cargas.CELULA_GEMEO, 1, None, MODELO, roteirizado=True)
    ver("roteirizado: roda_uma sem forcar_shell é recusada", bool(msg), str(msg))
