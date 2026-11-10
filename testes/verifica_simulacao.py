"""Autoteste da simulação: o servidor MCP, o endpoint falso, o registro de pacotes e o pacote."""

import base64
import hashlib
import io
import json
import re
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from instrumento.dominio import cargas
from instrumento.simulacao.endpoint import formatos, respostas, roteiro, servidor_http
from instrumento.simulacao import registro
from testes.base import AQUI, TOOL, igual, protegido, ver


def conversa(args, chamadas=1):
    """Fala com o servidor pelo mesmo comando que os clientes usam; devolve as respostas por id."""
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": cargas.NOME_TESTE, "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "ping"}]
    r = subprocess.run([sys.executable, "-B", str(AQUI / "experimento.py"), "servidor", *args],
                       input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True, timeout=30)
    return {m["id"]: m for m in (json.loads(l) for l in r.stdout.splitlines() if l.strip())}


@protegido
def verifica_servidor():
    with tempfile.TemporaryDirectory() as tmp:
        defs, textos = {}, {}
        for cel in cargas.CELULAS_CLIENTE:
            for v in ("A", "B"):
                reg = Path(tmp) / f"{cel}-{v}.jsonl"
                extra = ["--perfil", "b"] if (cel == "comando_alterado" and v == "B") else []
                r = conversa(["--celula", cel, "--versao", v, "--registro", str(reg), *extra])
                ok = (r.get(1, {}).get("result", {}).get("capabilities", {}).get("tools", {}).get("listChanged") is True
                      and len(r.get(2, {}).get("result", {}).get("tools", [])) == 1
                      and r.get(3, {}).get("result", {}).get("content", [{}])[0].get("type") == "text"
                      and r.get(4, {}).get("result") == {})
                ver(f"servidor: {cel} versão {v} responde initialize, tools/list, tools/call e ping", ok, str(r)[:200])
                if r.get(2):
                    defs[(cel, v)] = r[2]["result"]["tools"][0]
                    textos[(cel, v)] = r[3]["result"]["content"][0]["text"]
                linhas = [json.loads(l) for l in reg.read_text(encoding="utf-8").splitlines()]
                ver(f"servidor: {cel} {v} registra mensagens recebidas, enviadas e o tools/list servido",
                    any(l["direcao"] == "recebida" for l in linhas) and any(l.get("ferramentas_servidas") for l in linhas)
                    and all(l["celula"] == cel and l["versao"] == v for l in linhas))
                if cel == "codigo_novo":
                    ver(f"servidor: codigo_novo {v} marca codigo={v} no registro", all(l["codigo"] == v for l in linhas))
        ver("servidor: parametro_novo mantém a descrição", defs[("parametro_novo", "A")]["description"] == defs[("parametro_novo", "B")]["description"])
        ver("servidor: parametro_novo B ganha o parâmetro opcional nota", "nota" in defs[("parametro_novo", "B")]["inputSchema"]["properties"]
            and "required" not in defs[("parametro_novo", "B")]["inputSchema"])
        ver("servidor: codigo_novo tem a definição idêntica à A", defs[("codigo_novo", "A")] == defs[("codigo_novo", "B")])
        ver("servidor: codigo_novo muda só o texto da chamada", textos[("codigo_novo", "A")] != textos[("codigo_novo", "B")])
        ver("servidor: comando_alterado tem a definição idêntica à A (--perfil b aceito e ignorado)",
            defs[("comando_alterado", "A")] == defs[("comando_alterado", "B")])
        ver("servidor: sem_mudanca tem a definição idêntica à A", defs[("sem_mudanca", "A")] == defs[("sem_mudanca", "B")])
        ver("servidor: servidor_renomeado tem a definição idêntica à A", defs[("servidor_renomeado", "A")] == defs[("servidor_renomeado", "B")])
        ver("servidor: descricao_alterada B traz a nota visível", defs[("descricao_alterada", "B")]["description"].endswith(cargas.NOTA_INERTE))
        ver("servidor: descricao_com_tag B traz a nota em TAG",
            cargas.tag_decodifica(defs[("descricao_com_tag", "B")]["description"]).endswith(cargas.NOTA_INERTE))
        # Parte 2: duas ferramentas, a instrução onde a célula manda
        cmd = "python3 -B experimento.py servidor --gemeo --registro registro-gemeo.jsonl"
        for cel in cargas.CELULAS_MODELO:
            for v in ("A", "B"):
                extra = ["--comando-gemeo", cmd] if cel == cargas.CELULA_GEMEO else []
                r = conversa(["--celula", cel, "--versao", v, "--registro", str(Path(tmp) / f"{cel}-{v}.jsonl"), *extra])
                nomes = [t["name"] for t in r.get(2, {}).get("result", {}).get("tools", [])]
                ver(f"servidor: {cel} {v} anuncia consulta_teste e sincronizar_estado", nomes == [cargas.NOME_TESTE, cargas.NOME_SINCRONIZAR], str(nomes))
                defs[(cel, v)] = r[2]["result"]["tools"][0]
                textos[(cel, v)] = r[3]["result"]["content"][0]["text"]
                defs[(cel, v, "init")] = r[1]["result"]
        ver("servidor: sem_instrucao não muda nada entre A e B", defs[("sem_instrucao", "A")] == defs[("sem_instrucao", "B")]
            and textos[("sem_instrucao", "A")] == textos[("sem_instrucao", "B")] and "instructions" not in defs[("sem_instrucao", "B", "init")])
        ver("servidor: instrucao_na_descricao B traz a instrução na descrição",
            defs[("instrucao_na_descricao", "B")]["description"].endswith(cargas.INSTRUCAO["instrucao_na_descricao"]))
        ver("servidor: instrucao_no_resultado B traz a instrução só no resultado",
            textos[("instrucao_no_resultado", "B")].endswith(cargas.INSTRUCAO["instrucao_no_resultado"])
            and defs[("instrucao_no_resultado", "A")] == defs[("instrucao_no_resultado", "B")])
        ver("servidor: instrucao_nas_instructions B serve o campo instructions e não muda a ferramenta",
            defs[("instrucao_nas_instructions", "B", "init")].get("instructions") == cargas.INSTRUCAO["instrucao_nas_instructions"]
            and "instructions" not in defs[("instrucao_nas_instructions", "A", "init")]
            and defs[("instrucao_nas_instructions", "A")] == defs[("instrucao_nas_instructions", "B")])
        ver("servidor: instrucao_no_parametro B traz a instrução na descrição do parâmetro novo",
            defs[("instrucao_no_parametro", "B")]["inputSchema"]["properties"]["nota"]["description"] == cargas.INSTRUCAO["instrucao_no_parametro"])
        ver("servidor: gemeo_com_sufixo B traz a instrução com o nome -oficial e a linha de comando",
            cargas.instrucao_gemeo(cmd) in defs[("gemeo_com_sufixo", "B")]["description"]
            and cargas.NOME_GEMEO_SUFIXO.endswith("-oficial"))
        # o arquivo de estado vence --versao: a linha de comando do cliente é a mesma nas duas fases
        estado = Path(tmp) / "estado-versao.txt"
        estado.write_text("B", encoding="utf-8")
        r = conversa(["--celula", "descricao_alterada", "--versao", "A", "--estado", str(estado), "--registro", str(Path(tmp) / "e.jsonl")])
        ver("servidor: --estado vence --versao", r[2]["result"]["tools"][0]["description"].endswith(cargas.NOTA_INERTE))
        # modo entrega
        r = conversa(["--tecnica", "tag", "--registro", str(Path(tmp) / "t.jsonl")])
        ver("servidor: --tecnica serve a descrição da técnica", r[2]["result"]["tools"][0] == cargas.ferramenta_entrega("tag"))


def posta(porta, caminho, corpo):
    pedido = urllib.request.Request(f"http://127.0.0.1:{porta}{caminho}", data=json.dumps(corpo).encode(), method="POST",
                                    headers={"Content-Type": "application/json", "Authorization": "Bearer CHAVE-SECRETA-SELFTEST",
                                             "x-api-key": "CHAVE-SECRETA-SELFTEST"})
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(pedido, timeout=10).read().decode()


def pedido_de(formato, estagio, stream=False, com_ferramenta=True):
    """(caminho, corpo) de um pedido no dialeto. estagio: 'inicio' ou 'resultado'."""
    esq = {"type": "object", "properties": {}}
    if formato == "anthropic":
        msgs = [{"role": "user", "content": "oi"}]
        if estagio == "resultado":
            msgs += [{"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": TOOL, "input": {}}]},
                     {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]}]
        corpo = {"model": "falso", "max_tokens": 10, "messages": msgs, "stream": stream}
        if com_ferramenta:
            corpo["tools"] = [{"name": TOOL, "description": "d", "input_schema": esq}]
        return "/v1/messages", corpo
    if formato == "chat":
        msgs = [{"role": "user", "content": "oi"}]
        if estagio == "resultado":
            msgs += [{"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": TOOL, "arguments": "{}"}}]},
                     {"role": "tool", "tool_call_id": "c1", "content": "x"}]
        corpo = {"model": "falso", "messages": msgs, "stream": stream}
        if com_ferramenta:
            corpo["tools"] = [{"type": "function", "function": {"name": TOOL, "description": "d", "parameters": esq}}]
        return "/v1/chat/completions", corpo
    if formato == "responses":
        itens = [{"role": "user", "content": "oi"}]
        if estagio == "resultado":
            itens += [{"type": "function_call", "call_id": "c1", "name": TOOL, "arguments": "{}"},
                      {"type": "function_call_output", "call_id": "c1", "output": "x"}]
        corpo = {"model": "falso", "input": itens, "stream": stream}
        if com_ferramenta:
            corpo["tools"] = [{"type": "function", "name": TOOL, "description": "d", "parameters": esq}]
        return "/v1/responses", corpo
    raise ValueError(formato)


@protegido
def verifica_endpoint():
    with tempfile.TemporaryDirectory() as tmp:
        ep = servidor_http.Endpoint(Path(tmp) / "r", "roteirizado").inicia()
        try:
            for formato in ("anthropic", "chat", "responses"):
                for stream in (False, True):
                    rotulo = f"{formato}{' (SSE)' if stream else ''}"
                    caminho, corpo = pedido_de(formato, "inicio", stream)
                    texto = posta(ep.porta, caminho, corpo)
                    ver(f"endpoint: {rotulo} devolve primeiro a chamada da ferramenta", TOOL in texto and not ep.terminou, texto[:120])
                    caminho, corpo = pedido_de(formato, "resultado", stream)
                    texto = posta(ep.porta, caminho, corpo)
                    ver(f"endpoint: {rotulo} com o resultado devolve o texto ok",
                        TOOL not in texto and re.search(r'"(?:text|content|delta)": ?"ok"', texto) and ep.terminou, texto[:120])
                    ep.terminou = False
                    caminho, corpo = pedido_de(formato, "inicio", stream, com_ferramenta=False)
                    texto = posta(ep.porta, caminho, corpo)
                    ver(f"endpoint: {rotulo} sem a ferramenta devolve ok",
                        TOOL not in texto and re.search(r'"(?:text|content|delta)": ?"ok"', texto), texto[:120])
            gravados = sorted(p.name for p in Path(tmp, "r").iterdir())
            ver("endpoint: grava o corpo e o resumo de cada pedido", len(gravados) >= 36 and any(n.endswith(".meta") for n in gravados))
            dentro = "".join(p.read_text(encoding="utf-8") for p in Path(tmp, "r").iterdir())
            ver("endpoint: nenhuma chave nem cabeçalho entra na evidência", "CHAVE-SECRETA-SELFTEST" not in dentro)
            ver("endpoint: o corpo gravado é o enviado", json.loads((Path(tmp) / "r" / "req-001.json").read_text()) == pedido_de("anthropic", "inicio")[1])
            ver("endpoint: modelos e contagem de tokens respondem", json.loads(posta(ep.porta, "/v1/messages/count_tokens", {}))["input_tokens"] > 0)
            ver("endpoint: escuta só em 127.0.0.1", ep.http.server_address[0] == "127.0.0.1", str(ep.http.server_address))
            ip = ip_da_maquina()
            if ip and not ip.startswith("127."):
                try:
                    with socket.create_connection((ip, ep.porta), timeout=3):
                        ver(f"endpoint: não aceita conexão pelo endereço {ip}", False, "aceitou")
                except OSError:
                    ver(f"endpoint: não aceita conexão pelo endereço {ip}", True)
            else:
                print("PULADO  endpoint: a máquina não tem endereço fora do loopback para testar")
        finally:
            ep.para()
        eo = servidor_http.Endpoint(Path(tmp) / "o", "ok").inicia()
        try:
            caminho, corpo = pedido_de("chat", "inicio")
            ver("endpoint: modo ok responde ok mesmo com a ferramenta oferecida", TOOL not in posta(eo.porta, caminho, corpo))
        finally:
            eo.para()
    # a ponte tool_search / tool_call do Qwen Code e o namespace do Codex
    ponte = {"messages": [{"role": "user", "content": f"ferramentas adiadas: {TOOL}"}],
             "tools": [{"type": "function", "function": {"name": "tool_search"}}, {"type": "function", "function": {"name": "tool_call"}}]}
    a1 = roteiro.decide("roteirizado", "chat", ponte)
    ver("endpoint: ferramentas adiadas, primeiro tool_search", a1[0] == "chamada" and a1[1] == "tool_search" and TOOL in a1[2]["query"], str(a1))
    ponte["messages"] += [{"role": "assistant", "tool_calls": [{"function": {"name": "tool_search", "arguments": "{}"}}]}, {"role": "tool", "content": "x"}]
    a2 = roteiro.decide("roteirizado", "chat", ponte)
    ver("endpoint: depois da busca, tool_call com o nome da ferramenta", a2[0] == "chamada" and a2[1] == "tool_call" and a2[2]["name"] == TOOL, str(a2))
    ponte["messages"] += [{"role": "assistant", "tool_calls": [{"function": {"name": "tool_call", "arguments": "{}"}}]}]
    ver("endpoint: depois dos dois passos, ok", roteiro.decide("roteirizado", "chat", ponte)[0] == "ok")
    # tela real do ensaio (Qwen Code, gêmeo invisível): o nome do gêmeo leva sufixo e a ponte tem de chamá-lo inteiro
    gemeo_qw = {"messages": [{"role": "user", "content": '- "mcp__servidor-teste___consulta_teste_1xro731"'
                              ' e "mcp__servidor-teste__consulta_teste"'}], "tools": ponte["tools"]}
    ver("endpoint: gêmeo no Qwen Code, tool_search com o nome inteiro do gêmeo (com sufixo)",
        roteiro.decide("roteirizado", "chat", gemeo_qw, True)[2].get("query") == "select:mcp__servidor-teste___consulta_teste_1xro731")
    ver("endpoint: sem alvo_gemeo, a ponte segue chamando o primeiro nome",
        roteiro.decide("roteirizado", "chat", dict(gemeo_qw, messages=[{"role": "user", "content":
            '"mcp__servidor-teste__consulta_teste" e "mcp__servidor-teste___consulta_teste_1xro731"'}]))[2].get("query")
        == "select:mcp__servidor-teste__consulta_teste")
    grupo = {"tools": [{"type": "namespace", "name": "mcp__servidor-teste", "tools": [{"type": "function", "name": "consulta_teste"}]}]}
    ver("endpoint: ferramenta dentro de um namespace (Codex)", formatos.namespace_de(grupo, "consulta_teste") == "mcp__servidor-teste"
        and roteiro.decide("roteirizado", "responses", grupo)[1] == "consulta_teste")
    estruturada = respostas.texto_final({"response_format": {"json_schema": {"schema": {
        "type": "object", "properties": {"motivo": {"type": "string"}, "escolha": {"type": "string", "enum": ["a", "b"]}}}}}})
    igual("endpoint: saída estruturada mínima quando o pedido traz response_format", json.loads(estruturada), {"motivo": "ok", "escolha": "a"})


def ip_da_maquina():
    """O endereço de saída da máquina, sem mandar nenhum pacote (UDP connect só escolhe a rota)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def pega(reg, caminho, accept="", condicional=None):
    """GET no registro local, sem proxy. Devolve (status, tipo, corpo, cabeçalhos)."""
    cab = {"Accept": accept} if accept else {}
    if condicional:
        cab["If-None-Match"] = condicional
    pedido = urllib.request.Request(f"http://127.0.0.1:{reg.porta}{caminho}", headers=cab)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(pedido, timeout=10) as r:
            return r.status, r.headers.get("Content-Type"), r.read(), r.headers
    except urllib.error.HTTPError as erro:
        return erro.code, erro.headers.get("Content-Type"), erro.read(), erro.headers


def abre_tgz(dados):
    with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as t:
        return {m.name: (t.extractfile(m).read(), m.mode) for m in t.getmembers() if m.isfile()}


def conversa_pacote(fonte, celula, registro_jsonl):
    """Roda o servidor embutido (o texto do pacote) e devolve as respostas por id."""
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": cargas.NOME_TESTE, "arguments": {}}}]
    r = subprocess.run([sys.executable, "-I", "-B", "-c", fonte, "--celula", celula, "--registro", str(registro_jsonl)],
                       input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True, timeout=30)
    return {m["id"]: m for m in (json.loads(l) for l in r.stdout.splitlines() if l.strip())}


@protegido
def verifica_registro():
    with tempfile.TemporaryDirectory() as tmp:
        reg = registro.Registro(Path(tmp) / "r").inicia()
        try:
            st, tipo, corpo, _ = pega(reg, "/" + registro.PACOTE)
            pk = json.loads(corpo)
            ver("registro: packument válido, com latest, versions, time e dist", st == 200 and tipo == "application/json"
                and pk["name"] == registro.PACOTE and pk["dist-tags"]["latest"] == "1.0.0" and list(pk["versions"]) == ["1.0.0"]
                and "1.0.0" in pk["time"] and {"tarball", "shasum", "integrity"} <= set(pk["versions"]["1.0.0"]["dist"]))
            d = pk["versions"]["1.0.0"]["dist"]
            ver("registro: o tarball aponta para 127.0.0.1", d["tarball"].startswith(f"http://127.0.0.1:{reg.porta}/"))
            st, _, tgz, _ = pega(reg, d["tarball"].replace(f"http://127.0.0.1:{reg.porta}", ""))
            ver("registro: shasum (sha1) do tarball confere", st == 200 and hashlib.sha1(tgz).hexdigest() == d["shasum"])
            ver("registro: integrity (sha512) do tarball confere",
                d["integrity"] == "sha512-" + base64.b64encode(hashlib.sha512(tgz).digest()).decode())
            arquivos = abre_tgz(tgz)
            manifesto = json.loads(arquivos["package/package.json"][0])
            ver("registro: package.json com name, version e bin para o script",
                manifesto["name"] == registro.PACOTE and manifesto["version"] == "1.0.0" and manifesto["bin"] == {registro.PACOTE: "servidor.py"})
            script, modo = arquivos["package/servidor.py"]
            ver("registro: o script do tarball é executável e tem o shebang do python3",
                modo & 0o111 and script.startswith(b"#!/usr/bin/env python3\n"))
            igual("registro: o tarball é reproduzível (mesmos bytes a cada construção)", registro.monta_tgz("1.0.0"), tgz)
            ver("registro: antes de publicar, o tarball da 1.0.1 não existe",
                pega(reg, f"/{registro.PACOTE}/-/{registro.PACOTE}-1.0.1.tgz")[0] == 404)
            st, tipo, ab, _ = pega(reg, "/" + registro.PACOTE, accept="application/vnd.npm.install-v1+json")
            ver("registro: formato abreviado do npm devolve o mesmo conteúdo", tipo == "application/vnd.npm.install-v1+json"
                and json.loads(ab) == pk)
            st, _, vazio, _ = pega(reg, "/" + registro.PACOTE, condicional=hashlib.sha1(corpo).hexdigest().join('""'))
            ver("registro: If-None-Match igual ao ETag devolve 304", st == 304 and vazio == b"")
            # índice simple antes de publicar
            st, tipo, js, _ = pega(reg, f"/simple/{registro.PACOTE}/", accept="application/vnd.pypi.simple.v1+json")
            ij = json.loads(js)
            ver("registro: índice simple (PEP 691) com o wheel da 1.0.0 e o sha256", st == 200 and len(ij["files"]) == 1
                and ij["files"][0]["filename"] == "servidor_teste_mcp-1.0.0-py3-none-any.whl" and ij["versions"] == ["1.0.0"])
            st, _, wheel, _ = pega(reg, ij["files"][0]["url"].replace(f"http://127.0.0.1:{reg.porta}", ""))
            ver("registro: o sha256 do índice é o do wheel servido", hashlib.sha256(wheel).hexdigest() == ij["files"][0]["hashes"]["sha256"])
            st, _, meta, _ = pega(reg, ij["files"][0]["url"].replace(f"http://127.0.0.1:{reg.porta}", "") + ".metadata")
            ver("registro: o sha256 dos metadados (PEP 658) confere", st == 200
                and hashlib.sha256(meta).hexdigest() == ij["files"][0]["core-metadata"]["sha256"])
            st, tipo, html, _ = pega(reg, f"/simple/{registro.PACOTE}/")
            ver("registro: índice simple em HTML (PEP 503) com #sha256=", tipo.startswith("text/html")
                and f"#sha256={hashlib.sha256(wheel).hexdigest()}" in html.decode())
            # o wheel
            with zipfile.ZipFile(io.BytesIO(wheel)) as z:
                dist = "servidor_teste_mcp-1.0.0.dist-info"
                nomes = set(z.namelist())
                ver("registro: wheel com METADATA, WHEEL, RECORD e entry_points.txt",
                    {f"{dist}/METADATA", f"{dist}/WHEEL", f"{dist}/RECORD", f"{dist}/entry_points.txt"} <= nomes)
                record = z.read(f"{dist}/RECORD").decode().splitlines()
                erros = []
                for linha in record:
                    nome, hash_, tam = linha.split(",")
                    if nome.endswith("/RECORD"):
                        if hash_ or tam:
                            erros.append(nome)
                        continue
                    dados = z.read(nome)
                    esperado = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(dados).digest()).rstrip(b"=").decode()
                    if hash_ != esperado or int(tam) != len(dados):
                        erros.append(nome)
                ver("registro: o RECORD do wheel tem os hashes e tamanhos corretos de todos os arquivos",
                    not erros and len(record) == len(nomes), str(erros))
                ver("registro: entry_points.txt declara o console_script do pacote",
                    f"[console_scripts]\n{registro.PACOTE} = servidor_teste_mcp:main" in z.read(f"{dist}/entry_points.txt").decode())
                ver("registro: METADATA do wheel tem Name e Version",
                    f"Name: {registro.PACOTE}\n" in z.read(f"{dist}/METADATA").decode() and "Version: 1.0.0\n" in z.read(f"{dist}/METADATA").decode())
                ver("registro: o módulo do wheel é o mesmo texto do script do tarball", z.read("servidor_teste_mcp.py") == script)
            igual("registro: o wheel é reproduzível", registro.monta_wheel("1.0.0"), wheel)
            # publica
            reg.fase("B")
            reg.publica("1.0.1")
            pk2 = json.loads(pega(reg, "/" + registro.PACOTE)[2])
            ver("registro: depois de publica, latest muda para 1.0.1 e a 1.0.1 entra em versions e time",
                pk2["dist-tags"]["latest"] == "1.0.1" and list(pk2["versions"]) == ["1.0.0", "1.0.1"] and "1.0.1" in pk2["time"])
            d2 = pk2["versions"]["1.0.1"]["dist"]
            tgz2 = pega(reg, d2["tarball"].replace(f"http://127.0.0.1:{reg.porta}", ""))[2]
            ver("registro: sha1 e sha512 do tarball da 1.0.1 conferem",
                hashlib.sha1(tgz2).hexdigest() == d2["shasum"]
                and d2["integrity"] == "sha512-" + base64.b64encode(hashlib.sha512(tgz2).digest()).decode())
            ij2 = json.loads(pega(reg, f"/simple/{registro.PACOTE}/", accept="application/vnd.pypi.simple.v1+json")[2])
            ver("registro: o índice simple passa a listar a 1.0.1", ij2["versions"] == ["1.0.0", "1.0.1"] and len(ij2["files"]) == 2)
            ver("registro: publica de versão desconhecida é recusada", subprocess.run(
                [sys.executable, "-I", "-B", "-c", "import sys; sys.path.insert(0, sys.argv[1]); from instrumento.simulacao import registro; import tempfile; "
                 "registro.Registro(tempfile.mkdtemp()).publica('9.9.9')", str(AQUI)], capture_output=True).returncode != 0)
            # o registro das requisições
            log = registro.le_requisicoes(reg.log)
            ver("registro: toda requisição vai para registro-pacotes.jsonl com hora, fase, método, caminho e versão servida",
                len(log) >= 8 and all({"t", "fase", "metodo", "caminho", "status"} <= set(l) for l in log)
                and {l["fase"] for l in log} == {"A", "B"} and any(l["versao_servida"] == "1.0.1" for l in log))
            ver("registro: o log não guarda cabeçalhos", "Accept" not in reg.log.read_text(encoding="utf-8")
                and "If-None-Match" not in reg.log.read_text(encoding="utf-8"))
            ip = ip_da_maquina()
            if ip and not ip.startswith("127."):
                try:
                    with socket.create_connection((ip, reg.porta), timeout=3):
                        ver(f"registro: não aceita conexão pelo endereço {ip}", False, "aceitou")
                except OSError:
                    ver(f"registro: não aceita conexão pelo endereço {ip}", True)
            ver("registro: escuta só em 127.0.0.1", reg.http.server_address[0] == "127.0.0.1")
        finally:
            reg.para()
        # as observações da instalação em dados sintéticos
        r = [{"fase": "A", "tipo": "packument", "status": 200}, {"fase": "A", "tipo": "tarball", "versao_servida": "1.0.0", "status": 200},
             {"fase": "B", "tipo": "indice", "status": 200}, {"fase": "B", "tipo": "wheel", "versao_servida": "1.0.1", "status": 200}]
        ver("registro: buscou e baixou olham a fase pedida", registro.buscou_registro(r, "B") == "sim" and registro.buscou_registro([r[1]], "B") == "nao"
            and registro.baixou_versao(r, "B") == "sim" and registro.baixou_versao(r, "A") == "nao")
        igual("registro: versao_rodou lê a versão do pacote da resposta ao initialize", registro.versao_rodou(
            [{"direcao": "enviada", "versao_pacote": "1.0.1", "mensagem": {"result": {"serverInfo": {"version": "1.0.1"}}}}]), "1.0.1")
        igual("registro: versao_rodou sem initialize respondido é nenhuma", registro.versao_rodou([{"direcao": "partida"}]), "nenhuma")


@protegido
def verifica_pacote():
    with tempfile.TemporaryDirectory() as tmp:
        for versao, definicao in registro.DEFINICAO_DA_VERSAO.items():
            fonte = registro.fonte_servidor(versao)
            ver(f"pacote {versao}: o servidor embutido é ASCII, autônomo e não importa cargas.py",
                fonte.isascii() and "import cargas" not in fonte and "from cargas" not in fonte)
            for cel in cargas.CELULAS_CLIENTE:
                reg_jsonl = Path(tmp) / f"{versao}-{cel}.jsonl"
                r = conversa_pacote(fonte, cel, reg_jsonl)
                esperada = cargas.ferramenta_teste(cel, definicao)
                ver(f"pacote {versao}: {cel} anuncia a definição {definicao} igual à de cargas.ferramenta_teste",
                    r.get(2, {}).get("result", {}).get("tools") == [esperada], str(r.get(2))[:200])
                ver(f"pacote {versao}: {cel} responde initialize com a versão do pacote e chama com o texto {definicao}",
                    r.get(1, {}).get("result", {}).get("serverInfo", {}).get("version") == versao
                    and r.get(1, {}).get("result", {}).get("capabilities", {}).get("tools", {}).get("listChanged") is True
                    and r.get(3, {}).get("result", {}).get("content", [{}])[0].get("text") == cargas.texto_chamada(cel, definicao))
                linhas = [json.loads(l) for l in reg_jsonl.read_text(encoding="utf-8").splitlines()]
                ver(f"pacote {versao}: {cel} registra a versão do pacote em cada linha, a partida e o tools/list servido",
                    all(l["versao_pacote"] == versao and l["celula"] == cel for l in linhas)
                    and any(l["direcao"] == "partida" for l in linhas) and any(l.get("ferramentas_servidas") for l in linhas)
                    and registro.versao_rodou(linhas) == versao
                    and (cel != "codigo_novo" or all(l["codigo"] == definicao for l in linhas)))
        ver("pacote: descricao_alterada e descricao_com_tag só mudam de descrição na 1.0.1; sem_mudanca e codigo_novo têm a mesma definição nas duas",
            cargas.ferramenta_teste("descricao_alterada", "A") != cargas.ferramenta_teste("descricao_alterada", "B")
            and cargas.ferramenta_teste("codigo_novo", "A") == cargas.ferramenta_teste("codigo_novo", "B"))
        r = subprocess.run([sys.executable, "-I", "-B", "-c", registro.fonte_servidor("1.0.0"), "--celula", "C9"],
                           capture_output=True, text=True, timeout=30)
        ver("pacote: célula desconhecida sai com erro", r.returncode != 0 and "--celula" in r.stderr)
