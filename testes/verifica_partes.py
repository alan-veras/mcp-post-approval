"""Autoteste das partes e dos clientes: instalação, uma execução de ponta a ponta e o contrato dos clientes."""

import json
import os
import re
import subprocess
import shutil
import sys
import tempfile
from pathlib import Path

import types
from instrumento.dominio import cargas, ordem
from instrumento.simulacao.endpoint import servidor_http
from instrumento import clientes
from instrumento.clientes import isolamento
from instrumento.clientes.configuracao import ServidorMCP
from instrumento.partes import instalacao
from instrumento.simulacao import registro
from testes.base import AQUI, igual, protegido, ver


@protegido
def verifica_instalacao():
    with tempfile.TemporaryDirectory() as tmp:
        reg = registro.Registro(Path(tmp) / "r").inicia()
        try:
            extras = instalacao.prepara_gerenciador(Path(tmp), reg)
            env = isolamento.ambiente(Path(tmp), **extras)
            ver("instalação: o npm aponta para o registro local, sem aviso de atualização, fund nem audit",
                env["npm_config_registry"] == reg.url_npm and env["npm_config_update_notifier"] == "false"
                and env["npm_config_fund"] == "false" and env["npm_config_audit"] == "false")
            ver("instalação: o uv aponta para o índice local e não baixa python",
                env["UV_DEFAULT_INDEX"] == reg.url_simple and env["UV_PYTHON_DOWNLOADS"] == "never" and env["UV_PYTHON"])
            ver("instalação: o cache fica no HOME isolado ($HOME/.npm e $XDG_CACHE_HOME/uv)",
                env["HOME"].startswith(str(tmp)) and env["XDG_CACHE_HOME"].startswith(env["HOME"]))
            ver("instalação: a trava de proxy continua, com 127.0.0.1 em NO_PROXY",
                all(env[v] == isolamento.TRAVA for v in ("HTTP_PROXY", "HTTPS_PROXY")) and "127.0.0.1" in env["NO_PROXY"])
            npmrc = (Path(tmp) / "home" / ".npmrc").read_text(encoding="utf-8")
            uvtoml = (Path(tmp) / "home" / ".config" / "uv" / "uv.toml").read_text(encoding="utf-8")
            ver("instalação: ~/.npmrc e uv.toml do HOME isolado apontam para o registro local",
                f"registry={reg.url_npm}" in npmrc and reg.url_simple in uvtoml and "registry.npmjs.org" not in npmrc + uvtoml)
        finally:
            reg.para()
        igual("instalação: os dois gerenciadores, sem versão fixa", sorted(instalacao.CANAIS), ["npx", "uvx"])
        igual("instalação: a confirmação usa a célula codigo_novo", instalacao.CELULA, "codigo_novo")
        for canal, base in (("npx", ["npx", "-y", "servidor-teste-mcp"]), ("uvx", ["uvx", "servidor-teste-mcp"])):
            c = instalacao.comando_canal(canal, "codigo_novo", Path(tmp))
            ver(f"instalação: comando do canal {canal} guardado no cliente, sem versão fixa e igual nas duas fases",
                c[:len(base)] == base and c[len(base):] == ["--celula", "codigo_novo", "--registro", str(Path(tmp) / "registro-servidor.jsonl")]
                and c == instalacao.comando_canal(canal, "codigo_novo", Path(tmp)), str(c))
        igual("instalação: hosts externos em URLs são detectados, 127.0.0.1 não", instalacao.hosts_externos(
            "GET http://127.0.0.1:1234/x e GET https://registry.npmjs.org/pacote e http://pypi.org/simple/"),
            ["pypi.org", "registry.npmjs.org"])
        # o roteiro de fase: o registro do servidor se separa por horário quando há comando
        ver("instalação: roda_fase aceita comando e extras (a linha do gerenciador e o ambiente)",
            {"comando", "extras"} <= set(__import__("inspect").signature(__import__("instrumento.partes.reconsentimento", fromlist=["x"]).roda_fase).parameters))


@protegido
def verifica_ponta_a_ponta():
    """npx e uvx reais contra o registro local, sem cliente: a versão servida é a que o registro tinha."""
    for canal, binario in (("npx", "npx"), ("uvx", "uvx")):
        if not shutil.which(binario):
            print(f"PULADO  instalação ponta a ponta: {binario} não existe nesta máquina")
            continue
        servido = {}
        for publicada, esperada in (("1.0.0", "A"), ("1.0.1", "B")):
            trabalho = isolamento.pasta_de_trabalho()
            reg = registro.Registro(trabalho / "registro").inicia()
            try:
                if publicada == "1.0.1":
                    reg.publica("1.0.1")
                env = isolamento.ambiente(trabalho, **instalacao.prepara_gerenciador(trabalho, reg, depuracao=True))
                linha = instalacao.roda_gerenciador(canal, "descricao_alterada", trabalho, env, reg, "e2e")
                lista = [l for l in reconsentimento_le(trabalho / "registro-servidor.jsonl") if l.get("ferramentas_servidas")]
                servido[publicada] = lista[-1]["ferramentas_servidas"][0] if lista else None
                ver(f"ponta a ponta {canal}: com a {publicada} publicada rodou {publicada}, baixou {publicada} e consultou o registro",
                    linha["versao_rodou"] == publicada and linha["baixou"] == publicada and linha["buscou"] == "sim" and linha["saida_codigo"] == 0,
                    str(linha)[:300])
                ver(f"ponta a ponta {canal}: a definição servida é a {esperada} da descricao_alterada e nenhuma requisição saiu da máquina",
                    servido[publicada] == cargas.ferramenta_teste("descricao_alterada", esperada) and not linha["rede_externa"], linha["rede_externa"])
            finally:
                reg.para()
                shutil.rmtree(trabalho, ignore_errors=True)


def reconsentimento_le(caminho):
    from instrumento.partes import comum
    return comum.le_registro(caminho)


@protegido
def verifica_clientes():
    trabalho = isolamento.pasta_de_trabalho()
    ver("clientes: a pasta de trabalho fica fora da árvore do usuário (nenhum CLAUDE.md ancestral)",
        not str(trabalho).startswith(str(Path.home())) and not any((a / "CLAUDE.md").exists() or (a / ".claude").exists()
                                                                    for a in [trabalho, *trabalho.parents]), str(trabalho))
    trabalho.rmdir()
    igual("clientes: só os 3 persistentes", sorted(clientes.CLIENTES), ["cc", "cx", "qw"])
    ver("clientes: gemini, kimi, opencode e goose saíram do código",
        not [n for n in ("gemini", "kimi", "opencode", "goose") if (AQUI / "instrumento" / "clientes" / f"{n}.py").exists()])
    segredos = {p: "REAL-SECRET-" + p for p in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_HOME", "QWEN_API_KEY")}
    salvo = {k: os.environ.get(k) for k in segredos}
    os.environ.update(segredos)
    try:
        for rotulo in clientes.CLIENTES:
            m = clientes.cliente(rotulo)
            faltam = [n for n in ("NOME", "binario", "versao", "prepara", "comando_nao_interativo", "comando_interativo",
                                  "ROTEIRO_FASE_A", "PADROES_APROVACAO") if not hasattr(m, n)]
            ver(f"clientes/{rotulo}: tem a forma comum", not faltam, f"faltam {faltam}")
            rf = getattr(m, "ROTEIRO_FASE_A", {})
            ver(f"clientes/{rotulo}: roteiro com pronto, antes e aprovacoes",
                isinstance(rf.get("pronto"), str) and isinstance(rf.get("antes"), list) and isinstance(rf.get("aprovacoes"), list))
            ver(f"clientes/{rotulo}: a aprovação da fase A é a opção persistente (sempre permitir ou equivalente)",
                rf["aprovacoes"] and all(re.search(r"always|all future|don't ask again|Use this MCP server", a[3], re.I) for a in rf["aprovacoes"]), str(rf["aprovacoes"]))
            ver(f"clientes/{rotulo}: padrões de aprovação do servidor e da chamada",
                set(getattr(m, "PADROES_APROVACAO", {})) == {"servidor", "chamada"})
            for modo in ("entrega", "reconsentimento"):
                with tempfile.TemporaryDirectory() as tmp:
                    srv = [sys.executable, "-B", "/x/experimento.py", "servidor", "--celula", "sem_mudanca", "--estado", "/x/e", "--registro", "/x/r"]
                    env = m.prepara(Path(tmp), ServidorMCP(srv), 4321, modo)
                    arquivos = [p for p in Path(tmp).rglob("*") if p.is_file()]
                    tudo = "".join(p.read_text(encoding="utf-8", errors="replace") for p in arquivos) + "".join(env.values())
                    ver(f"clientes/{rotulo}/{modo}: HOME dentro da pasta isolada", env["HOME"].startswith(tmp))
                    ver(f"clientes/{rotulo}/{modo}: trava de proxy em 127.0.0.1:9",
                        all(env[v] == isolamento.TRAVA for v in ("HTTP_PROXY", "HTTPS_PROXY")) and "127.0.0.1" in env["NO_PROXY"])
                    ver(f"clientes/{rotulo}/{modo}: nenhuma chave real no ambiente", "REAL-SECRET" not in tudo)
                    ver(f"clientes/{rotulo}/{modo}: aponta para o endpoint (porta) e para o servidor de teste",
                        "4321" in tudo and "servidor-teste" in tudo)
                    ver(f"clientes/{rotulo}/{modo}: comandos são listas de texto",
                        all(isinstance(a, str) for a in m.comando_interativo() + m.comando_nao_interativo("x")))
                    if rotulo == "cc":
                        mcp = json.loads((Path(tmp) / "projeto/.mcp.json").read_text(encoding="utf-8"))
                        ver(f"clientes/cc/{modo}: o servidor entra no .mcp.json com alwaysLoad = true (sem ele a ferramenta não chega ao modelo em -p)",
                            mcp["mcpServers"]["servidor-teste"].get("alwaysLoad") is True, str(mcp))
                        ver(f"clientes/cc/{modo}: a busca de ferramentas fica desligada", env.get("ENABLE_TOOL_SEARCH") == "false")
                    if rotulo == "cx" and modo == "reconsentimento":
                        cfg = Path(tmp) / "home/.codex/config.toml"
                        cfg.write_text(cfg.read_text(encoding="utf-8") + 'approval_mode = "approve"\n', encoding="utf-8")
                        srv2 = srv[:-1] + ["/x/outro"]
                        m.prepara(Path(tmp), ServidorMCP(srv2), 4321, modo)
                        novo = cfg.read_text(encoding="utf-8")
                        ver("clientes/cx: a fase B preserva a aprovação gravada e troca só o comando",
                            'approval_mode = "approve"' in novo and "/x/outro" in novo)
            # o gêmeo invisível: o segundo servidor entra na configuração, com U+200B no nome
            with tempfile.TemporaryDirectory() as tmp:
                gem = ServidorMCP([sys.executable, "-B", "/x/experimento.py", "servidor", "--gemeo", "--registro", "/x/g"], cargas.NOME_GEMEO_INVISIVEL)
                m.prepara(Path(tmp), ServidorMCP(["true"]), 4321, "reconsentimento", gemeo=gem)
                tudo = "".join(p.read_text(encoding="utf-8", errors="replace") for p in Path(tmp).rglob("*") if p.is_file())
                ver(f"clientes/{rotulo}: o gêmeo invisível entra na configuração junto do servidor aprovado",
                    "/x/g" in tudo and ("servidor-teste" + cargas.ZWSP in tudo or "servidor-teste\\u200b" in tudo) and "servidor-teste" in tudo)
    finally:
        for k, v in salvo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class ClienteFalso:
    NOME = "falso"
    versao = staticmethod(lambda: "0.0")
    binario = staticmethod(lambda: None)


class EndpointFalso:
    def __init__(self, pasta, modo="ok", provedor=None, alvo_gemeo=False):
        self.modo, self.alvo_gemeo, self.parou = modo, alvo_gemeo, False
        self.porta, self.terminou, self.repasses, self.falha_provedor, self.em_voo = 0, False, [], "", 0

    def inicia(self):
        return self

    def fase(self, pasta):
        pass

    def para(self):
        self.parou = True


def fase_falsa(a, b, chamadas):
    """Uma roda_fase que devolve a e b (dicts parciais) e anota o que recebeu."""
    base = {"snap_antes": {}, "snap_depois": {}, "tela": "", "historico": "", "pediu": [], "opcoes": [],
            "achados": {"servidor": [], "chamada": []}, "falha": "", "registro": [], "pedidos": []}

    def roda(modulo, ep, pasta, celula, fase, limite, comando=None, extras=None, aprova_na_b=False, pedido=None, gemeo=None):
        chamadas.append((celula, fase, aprova_na_b, gemeo.nome if gemeo else None))
        if fase == "B" and gemeo:
            Path(pasta, cargas.ARQUIVO_REGISTRO_GEMEO).write_text(json.dumps(
                {"t": 1.0, "direcao": "recebida", "mensagem": {"method": "tools/call"}}) + "\n" if b.get("gemeo_recebeu") else "", encoding="utf-8")
        return {**base, **(a if fase == "A" else b)}
    return roda


CHAMADA = [{"t": 1.0, "direcao": "recebida", "mensagem": {"method": "tools/call", "params": {"name": cargas.NOME_TESTE}}}]
PEDIU = {"n": 1, "acao": "chamada"}


@protegido
def verifica_parte1_fluxo():
    from instrumento.partes import entrega, gemeo, reconsentimento
    salvo = (servidor_http.Endpoint, reconsentimento.roda_fase, clientes.cliente)
    servidor_http.Endpoint, clientes.cliente = EndpointFalso, lambda rotulo: ClienteFalso
    try:
        with tempfile.TemporaryDirectory() as tmp:
            definicao = cargas.ferramenta_teste("descricao_com_tag", "B")["description"]
            pedidos_ok = [("req-001.json", PEDIU, {"tools": [{"function": {"name": "t", "description": definicao}}]})]
            pedidos_sem_tag = [("req-001.json", PEDIU, {"tools": [{"function": {"name": "t", "description": cargas.BASE_TESTE}}]})]
            A = {"registro": CHAMADA, "pediu": ["chamada"], "opcoes": ["sempre"]}
            chamadas = []
            casos = [
                ("rodou_sem_aviso", dict(registro=CHAMADA, pedidos=pedidos_ok), ("sim", "nao", "nao", "sim")),
                ("pediu_aprovacao", dict(registro=[], pedidos=pedidos_ok, achados={"servidor": [], "chamada": ["Allow"]}), ("nao", "sim", "nao", "sim")),
                ("bloqueado_sem_explicacao", dict(registro=[], pedidos=pedidos_sem_tag), ("nao", "nao", "sim", "nao")),
            ]
            for nome, b, esperado in casos:
                reconsentimento.roda_fase = fase_falsa(A, b, chamadas)
                linha = reconsentimento.roda_uma(AQUI, "ensaio", "cc", "descricao_com_tag", 1, pasta_raiz=tmp)
                igual(f"parte1: {nome}", (linha["rodou_sem_aviso"], linha["pediu_aprovacao"], linha["bloqueado_sem_explicacao"], linha["chegou_intacta"]), esperado)
                igual(f"parte1: {nome}: sem falha de instrumento", linha["falha_instrumento"], "")
            igual("parte1: a fase B não aprova (a Parte 1 não aperta tecla depois do pedido)", {c[2] for c in chamadas if c[1] == "B"}, {False})
            reconsentimento.roda_fase = fase_falsa(A, dict(registro=[], pedidos=[("r", {"acao": "ok"}, {})]), [])
            linha = reconsentimento.roda_uma(AQUI, "ensaio", "cc", "sem_mudanca", 1, pasta_raiz=tmp)
            ver("parte1: o modelo roteirizado que não pediu a chamada vira falha de instrumento", "modelo-nao-pediu" in linha["falha_instrumento"])
            reconsentimento.roda_fase = fase_falsa(A, dict(registro=[], pedidos=pedidos_ok, achados={"servidor": ["x"], "chamada": []}), [])
            linha = reconsentimento.roda_uma(AQUI, "ensaio", "cc", "sem_mudanca", 2, pasta_raiz=tmp)
            igual("parte1: sem_mudanca que pede aprovação é controle inesperado (só registra, sem falha)", (bool(linha["controle_inesperado"]), linha["falha_instrumento"]), (True, ""))
            ver("parte1: a linha não tem d1, d5 nem classe_p0", not {"d1", "d2", "d3", "d4", "d5", "classe_p0"} & set(reconsentimento.CAMPOS))
            # o gêmeo invisível
            chamadas.clear()
            reconsentimento.roda_fase = fase_falsa(A, dict(registro=[], pedidos=pedidos_ok, achados={"servidor": [], "chamada": ["Allow"]}), chamadas)
            linha = gemeo.roda_uma(AQUI, "ensaio", "qw", 1, pasta_raiz=tmp)
            igual("gêmeo: a fase B leva o gêmeo com U+200B no nome; pediu_aprovacao lido do registro do gêmeo",
                  (chamadas[1][3], linha["pediu_aprovacao"], linha["rodou_sem_aviso"]), (cargas.NOME_GEMEO_INVISIVEL, "sim", "nao"))
            reconsentimento.roda_fase = fase_falsa(A, dict(registro=CHAMADA, pedidos=pedidos_ok, gemeo_recebeu=True), [])
            linha = gemeo.roda_uma(AQUI, "ensaio", "qw", 2, pasta_raiz=tmp)
            igual("gêmeo: o gêmeo recebeu a chamada sem pedido; o original também recebeu e fica à parte",
                  (linha["rodou_sem_aviso"], linha["pediu_aprovacao"], linha["original_recebeu"]), ("sim", "nao", "sim"))
            dois = [("r", PEDIU, {"tools": [{"function": {"name": "mcp__a__consulta_teste"}}, {"function": {"name": "mcp__b__consulta_teste"}}]})]
            ver("gêmeo: nomes_distintos vê dois nomes de ferramenta", gemeo.nomes_distintos(dois) and not gemeo.nomes_distintos(pedidos_ok))
            # caso qw: ferramentas adiadas, os dois nomes só chegam no resultado do tool_search (sem lista tools com eles)
            adiado = [("r", PEDIU, {"tools": [{"function": {"name": "tool_search"}}], "messages": [{"role": "tool", "content":
                       '"mcp__servidor-teste__consulta_teste" "mcp__servidor-teste___consulta_teste_1xro731"'}]})]
            ver("gêmeo: nomes_distintos vê os dois nomes no resultado do tool_search (qw)", gemeo.nomes_distintos(adiado))
            um_so = [("r", PEDIU, {"messages": [{"role": "tool", "content": '"mcp__servidor-teste__consulta_teste"'}]})]
            ver("gêmeo: um nome só, nem na tela, não é distinto", not gemeo.nomes_distintos(um_so, "servidor-teste MCP Server"))
            ver("gêmeo: nomes_distintos pela tela (nome + U+200B ou U+FFFD)",
                gemeo.nomes_distintos(um_so, "Allow " + cargas.NOME_GEMEO_INVISIVEL + " x") and gemeo.nomes_distintos(um_so, "servidor-teste\ufffd x"))
    finally:
        servidor_http.Endpoint, reconsentimento.roda_fase, clientes.cliente = salvo
    # entrega: chegou_intacta com a descrição, o tipo de alteração fica de evidência
    serv = cargas.ferramenta_entrega("tag")
    def pedidos_com(desc):
        return [("r", {"formato": "chat"}, {"messages": [{"role": "user", "content": entrega.PEDIDO}],
                                            "tools": [{"type": "function", "function": {"name": "mcp__s__read_config", "description": desc, "parameters": serv["inputSchema"]}}]})]
    for desc, esperado, tipo in ((serv["description"], "sim", "intacta"), (cargas.BASE_ENTREGA, "nao", "removeu-tag")):
        linha = {c: "" for c in entrega.CAMPOS}
        entrega.registra_desfechos(linha, serv, pedidos_com(desc))
        igual(f"entrega: tag {tipo}", (linha["chegou_intacta"], linha["desfecho_descricao"]), (esperado, tipo))


@protegido
def verifica_comandos():
    rodar = lambda *a: subprocess.run([sys.executable, "-B", str(AQUI / "experimento.py"), *a], capture_output=True, text=True, timeout=30)
    r = rodar("rodar", "--ensaio", "--parte", "parte2", "--modelos", "x", "--clientes", "zz")
    ver("experimento: cliente desconhecido é recusado", r.returncode != 0 and "cliente desconhecido" in r.stderr, r.stderr[-200:])
    r = rodar("rodar", "--parte", "parte1", "--clientes", "cc")
    ver("experimento: na confirmatória os filtros e --reps são recusados (ou falta a trava)", r.returncode != 0 and
        ("TRAVA-COLETA" in r.stderr or "filtros" in r.stderr), r.stderr[-200:])
    r = rodar("rodar", "--ensaio", "--parte", "tudo")
    ver("experimento: não há mais a parte 'tudo' nem as partes soltas", r.returncode != 0 and "invalid choice" in r.stderr, r.stderr[-200:])
    from instrumento import cli
    a = cli.le_argumentos(["rodar", "--parte", "parte1", "--ensaio"])
    ver("experimento: sem --ensaio o modo é a confirmatória", (cli.le_argumentos(["analise"]).modo, a.modo) == ("confirmatoria", "ensaio"))
    itens = cli.filtra(ordem.ordem_parte1(), types.SimpleNamespace(componentes="entrega", clientes="cc", celulas=None, tecnicas="tag,u200b", canais=None, modelos=None))
    ver("experimento: o filtro do ensaio mantém a ordem sorteada e só tira itens",
        [i for i in ordem.ordem_parte1() if i in itens] == itens and {i.componente for i in itens} == {"entrega"}, str(itens))
