"""Autoteste da robustez a falhas de infraestrutura (provedor, rede, suspensão, processo morto): sem API, sem rede."""

import contextlib
import http.client
import io
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from instrumento import config
from instrumento.analise import csvs
from instrumento.coleta import progresso
from instrumento.dominio import ordem
from instrumento.parada import ProvedorIndisponivel
from instrumento.simulacao import provedor as pv
from testes.base import AQUI, igual, protegido, ver

MODELO = ordem.MODELOS[0]


def servidor_falso(respostas):
    """Provedor local com roteiro: cada item é (status, corpo bytes) ou 'corta' (fecha no meio do Content-Length)."""
    fila = list(respostas)

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            item = fila.pop(0) if len(fila) > 1 else fila[0]
            if item == "corta":
                self.send_response(200)
                self.send_header("Content-Length", "500")
                self.end_headers()
                self.wfile.write(b'{"choices": [')
                self.wfile.flush()
                self.close_connection = True
                return
            status, corpo = item
            self.send_response(status)
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def resp(msg, fim="stop"):
    return 200, json.dumps({"choices": [{"message": msg, "finish_reason": fim}]}).encode()


@protegido
def verifica_provedor_resposta_inutilizavel():
    ok = resp({"role": "assistant", "content": "oi"})
    casos = {
        "vazio total (nem texto, nem ferramenta)": (resp({"role": "assistant", "content": ""}), True),
        "content nulo sem ferramenta": (resp({"role": "assistant", "content": None}), True),
        "cortada por tamanho com argumentos truncados": (resp({"content": "", "tool_calls": [
            {"function": {"name": "x", "arguments": '{"a": '}}]}, "length"), True),
        "texto sem ferramenta é do modelo": (ok, False),
        "ferramenta sem texto é resposta válida": (resp({"content": None, "tool_calls": [
            {"function": {"name": "x", "arguments": "{}"}}]}, "tool_calls"), False),
    }
    for nome, (primeira, deve_repetir) in casos.items():
        srv = servidor_falso([primeira, ok])
        dorme = []
        p = pv.Provedor(MODELO, "chave-falsa", base_url=f"http://127.0.0.1:{srv.server_port}", dorme=dorme.append)
        try:
            r = p.chat({"messages": []})
            igual(f"robustez P3: {nome}: {'repete' if deve_repetir else 'não repete'}", len(dorme), 1 if deve_repetir else 0)
            ver(f"robustez P3: {nome}: devolve algo utilizável", bool(r["choices"]))
        finally:
            srv.shutdown()
    srv = servidor_falso(["corta", resp({"content": "oi"})])
    dorme = []
    p = pv.Provedor(MODELO, "chave-falsa", base_url=f"http://127.0.0.1:{srv.server_port}", dorme=dorme.append)
    try:
        p.chat({"messages": []})
        igual("robustez P3: corpo cortado no meio (IncompleteRead) é repetido", len(dorme), 1)
    finally:
        srv.shutdown()
    ver("robustez P3: IncompleteRead é HTTPException", issubclass(http.client.IncompleteRead, http.client.HTTPException))
    for codigo in (401, 402, 403, 404):
        srv = servidor_falso([(codigo, b"{}")])
        dorme = []
        p = pv.Provedor(MODELO, "chave-falsa", base_url=f"http://127.0.0.1:{srv.server_port}", dorme=dorme.append)
        try:
            try:
                p.chat({"messages": []})
                lancou = False
            except pv.ErroProvedor as e:
                lancou = not isinstance(e, pv.PressaoPersistente) and f"HTTP {codigo}" in str(e)
            ver(f"robustez G2: HTTP {codigo} levanta erro permanente sem repetir", lancou and not dorme)
        finally:
            srv.shutdown()


@protegido
def verifica_robustez_roda_com_tentativas():
    from instrumento.partes import obediencia
    item = ordem.Item("obediencia", "cc", "instrucao_na_descricao", 1, MODELO)
    chave = ("cc", "instrucao_na_descricao", "1", MODELO)
    fila, esperas, sondas = [], [], []

    def falsa(aqui, modo, rotulo, celula, rep, prov, modelo, pasta_raiz=None, tentativa=1):
        l = {c: "" for c in obediencia.CAMPOS}
        l.update(cliente=rotulo, celula=celula, rep=rep, modelo=modelo, tentativa=tentativa, **fila.pop(0))
        return l
    pausa = {"falha_instrumento": "provedor: HTTP 503 do provedor"}
    perm = {"falha_instrumento": "provedor: HTTP 401 do provedor: chave"}
    com = {"nao_usou_ferramenta": "nao", "obedeceu": "nao"}
    texto_sem_ferr = {"nao_usou_ferramenta": "sim"}
    salvo = (obediencia.roda_uma, obediencia.dorme, obediencia.sonda)
    obediencia.roda_uma, obediencia.dorme = falsa, esperas.append
    obediencia.sonda = lambda base: sondas.append(base) or classe_da_sonda[0]
    classe_da_sonda = ["provedor"]
    prov = pv.Provedor(MODELO, "chave-falsa", base_url="http://127.0.0.1:9")
    try:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            csv = Path(tmp) / "o.csv"

            def tenta(linhas, p=prov):
                fila[:] = linhas
                esperas.clear()
                return obediencia.roda_com_tentativas(tmp, "ensaio", item, p, csv)
            # 4: queda longa de rede: 14 falhas `rede:` e a execução volta a funcionar na mesma vaga, sem tecto antes de 6 h
            classe_da_sonda[0] = "rede"
            ultima = tenta([pausa] * 14 + [com])
            linhas = csvs.le_csv(csv)
            igual("robustez 4: queda de rede longa: nenhuma linha final de falha, tentativa continua, a execução conclui",
                  (ultima["tentativa"], obediencia.ja_feita(csv, chave), {l["falha_instrumento"].split(":")[0] for l in linhas[:-1]}),
                  (15, True, {"rede"}))
            seq = [obediencia.espera_n(i) for i in range(7)]
            igual("robustez 4: a espera cresce 2, 5, 10, 20, 30 min e fica em 30 min", seq, [120, 300, 600, 1200, 1800, 1800, 1800])
            ver("robustez 4: a espera é em fatias de 5 s (PAUSAR é conferido a cada fatia)", max(esperas) <= obediencia.FATIA_PAUSA)
            csv.unlink()
            # 5: tecto de provedor: 8 falhas com a sonda dizendo "provedor": para (código 6), a execução continua pendente
            classe_da_sonda[0] = "provedor"
            try:
                tenta([pausa] * 8)
                parou = False
            except ProvedorIndisponivel:
                parou = True
            ver("robustez 5: 8 falhas de provedor param a coleta (ProvedorIndisponivel), sem pular a vaga",
                parou and not obediencia.ja_feita(csv, chave) and len(csvs.le_csv(csv)) == 8)
            # retomada: continua a contagem do CSV; uma nova falha para de novo, um sucesso conclui a mesma vaga
            ultima = tenta([com])
            igual("robustez 5: a retomada refaz a mesma execução (tentativa 9) e conclui", (ultima["tentativa"], obediencia.ja_feita(csv, chave)), (9, True))
            csv.unlink()
            # 6: erro permanente: para na primeira tentativa, sem esperar
            try:
                tenta([perm])
                parou = False
            except ProvedorIndisponivel as e:
                parou = "permanente" in str(e)
            ver("robustez 6: 401 para na primeira tentativa, sem espera, sem consumir a vaga",
                parou and not esperas and len(csvs.le_csv(csv)) == 1 and not obediencia.ja_feita(csv, chave))
            csv.unlink()
            # tecto de 6 h só de rede
            classe_da_sonda[0] = "rede"
            try:
                tenta([pausa] * 40)
                parou = False
            except ProvedorIndisponivel as e:
                parou = "h de espera" in str(e)
            ver("robustez: 6 h de rede fora também param a coleta", parou and 12 <= len(csvs.le_csv(csv)) <= 17, str(len(csvs.le_csv(csv))))
            csv.unlink()
            # a sonda não grava nada nem recebe a chave
            ver("robustez 17: a sonda só recebe o endereço do provedor (nunca a chave)", all("chave-falsa" not in str(b) for b in sondas))
            # 8: texto sem ferramenta na fase A continua sendo `nao_usou_ferramenta` (refaz até 2 vezes), não infraestrutura
            ultima = tenta([texto_sem_ferr] * 3)
            igual("robustez 8: modelo que não usa a ferramenta não vira falha de infraestrutura",
                  (ultima["nao_usou_ferramenta"], ultima["tentativa"], obediencia.pausou(ultima)), ("sim", 3, False))
            csv.unlink()
            # 9: falha só na B depois da A: refaz a execução inteira; só a última linha entra na análise
            ultima = tenta([pausa, com])
            ver("robustez 9: a linha antiga fica no CSV e a execução fica concluída pela última",
                len(csvs.le_csv(csv)) == 2 and obediencia.ja_feita(csv, chave))
            csv.unlink()
            # 15: a ordem não muda com as chaves já feitas (a fila vem da semente, sem ler o CSV)
            a = [(i.cliente, i.valor, i.rep, i.modelo) for i in ordem.ordem_parte2(ordem.REPS_PARTE2)]
            fila[:] = [com]
            obediencia.roda_com_tentativas(tmp, "ensaio", item, prov, csv)
            b = [(i.cliente, i.valor, i.rep, i.modelo) for i in ordem.ordem_parte2(ordem.REPS_PARTE2)]
            igual("robustez 15: a ordem sorteada é a mesma depois de execuções gravadas", (a, len(a)), (b, 180))
            csv.unlink()
            # 13: PAUSAR durante a espera longa interrompe sem perder nada
            pausa_arq = config.PAUSA
            existia = pausa_arq.exists()
            pausa_arq.write_text("teste")
            try:
                try:
                    obediencia.espera(1800)
                    interrompeu = False
                except config.PausaPedida:
                    interrompeu = True
            finally:
                if not existia:
                    pausa_arq.unlink()
            ver("robustez 13: PAUSAR interrompe a espera longa na primeira fatia", interrompeu)
            # progresso: falha de infraestrutura não conclui a execução
            linhas = [{"cliente": "cc", "falha_instrumento": "rede: x"}] * 5
            igual("robustez: o progresso não conta falha de infraestrutura como concluída", progresso.unicas(linhas, ["cliente"], ignora_pausa=True), 0)
    finally:
        obediencia.roda_uma, obediencia.dorme, obediencia.sonda = salvo


@protegido
def verifica_robustez_suspensao_e_csv():
    from instrumento.partes import obediencia
    import time as tempo
    # 10: o relógio de parede salta 1 h no meio da execução: vira `rede: suspensao-do-sistema`
    relogio = {"w": 1_000_000.0, "m": 500.0}
    real = (tempo.time, tempo.monotonic)
    tempo.time, tempo.monotonic = lambda: relogio["w"], lambda: relogio["m"]
    try:
        inicio_w, inicio_m = tempo.time(), tempo.monotonic()
        relogio["w"] += 3600
        relogio["m"] += 2
        ver("robustez 10: um salto de 1 h no relógio de parede, com monotônico quase parado, passa do limite de suspensão",
            (tempo.time() - inicio_w) - (tempo.monotonic() - inicio_m) > obediencia.SALTO_RELOGIO_S)
    finally:
        tempo.time, tempo.monotonic = real
    # 12: linha parcial no CSV: a próxima gravação não cola, a cauda vai para .parcial
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "x.csv"
        campos = ["a", "b"]
        csvs.grava_linha(f, campos, {"a": "1", "b": "2"})
        with open(f, "ab") as h:
            h.write(b"9,incompleta")  # processo morto no meio da escrita
        csvs.grava_linha(f, campos, {"a": "3", "b": "4"})
        linhas = csvs.le_csv(f)
        igual("robustez 12: a linha parcial não cola na seguinte", [(l["a"], l["b"]) for l in linhas], [("1", "2"), ("3", "4")])
        ver("robustez 12: a cauda incompleta fica guardada em .parcial (nunca apagada)",
            (Path(tmp) / "x.csv.parcial").read_text() == "9,incompleta\n")
        csvs.grava_linha(f, campos, {"a": "5", "b": "6"})
        ver("robustez 12: sem cauda incompleta nada é movido", len(csvs.le_csv(f)) == 3 and (Path(tmp) / "x.csv.parcial").read_text() == "9,incompleta\n")


@protegido
def verifica_robustez_parte1_conexao_local():
    from instrumento import execucao
    erro = "  ✕ [API Error: Connection error. (cause: fetch failed)] (Press Ctrl+Y to retry)\n"

    def roda_cenario(textos, falha):
        """`textos`: o historico-A de cada tentativa, na ordem. Devolve (chamadas, linhas do CSV)."""
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            aqui, chamadas = Path(tmp), []
            csv = aqui / "x.csv"

            def roda():
                pasta = aqui / "evid"
                pasta.mkdir(exist_ok=True)
                (pasta / "historico-A.txt").write_text(textos[min(len(chamadas), len(textos) - 1)], encoding="utf-8")
                chamadas.append(1)
                return {"cliente": "qw", "celula": "c", "rep": "1", "falha_instrumento": falha[min(len(chamadas) - 1, len(falha) - 1)],
                        "evidencia": "evid"}
            t = execucao.Tarefa(csv, ["cliente", "celula", "rep", "falha_instrumento", "evidencia"], ("cliente", "celula", "rep"),
                                ("qw", "c", "1"), roda, lambda l: "linha")
            execucao.percorre([t], refaz_se=execucao.conexao_local_falhou, aqui=aqui)
            return len(chamadas), csvs.le_csv(csv), sorted(p.name for p in aqui.iterdir() if p.is_dir())
    n, linhas, pastas = roda_cenario([erro, "tudo certo\n"], ["A:servidor-nao-recebeu-tools/call", ""])
    igual("robustez 16: erro de conexão local do cliente refaz uma vez e a segunda vale", (n, len(linhas)), (2, 2))
    ver("robustez 16: a evidência da tentativa refeita fica guardada (nada apagado)", pastas == ["evid", "evid-t1"] and linhas[0]["evidencia"] == "evid-t1", str(pastas))
    n, linhas, _ = roda_cenario([erro], ["A:servidor-nao-recebeu-tools/call"])
    igual("robustez 16: o erro persistente refaz no máximo 2 vezes (3 execuções, 3 linhas)", (n, len(linhas)), (3, 3))
    n, linhas, _ = roda_cenario(["nada de erro de conexão\n"], ["B:modelo-nao-pediu-a-chamada"])
    igual("robustez 16: 'modelo não pediu a chamada' (comportamento do cliente) não refaz", (n, len(linhas)), (1, 1))
    n, linhas, _ = roda_cenario([erro], [""])
    igual("robustez 16: histórico com o erro mas sem falha de instrumento não refaz", (n, len(linhas)), (1, 1))


@protegido
def verifica_robustez_verificador():
    """`coleta verificar` só lê: acusa cauda sem quebra, mostra faltas e o último motivo, e não altera arquivo."""
    from instrumento.partes import obediencia
    with tempfile.TemporaryDirectory() as tmp:
        salvo = progresso.AQUI
        progresso.AQUI = Path(tmp)
        try:
            f = Path(tmp) / "obediencia-confirmatoria.csv"
            csvs.grava_linha(f, obediencia.CAMPOS, {"cliente": "cc", "celula": "sem_instrucao", "rep": "1", "modelo": MODELO,
                                                    "falha_instrumento": "rede: x"})
            csvs.grava_linha(f, obediencia.CAMPOS, {"cliente": "qw", "celula": "sem_instrucao", "rep": "1", "modelo": MODELO})
            with open(f, "ab") as h:
                h.write(b"cx,parcial")
            antes = f.read_bytes()
            texto = progresso.verifica()
            ver("verificador: acusa a cauda sem quebra", "sem quebra" in texto, texto[:300])
            ver("verificador: 1 concluída de 180, faltam 179, e mostra a pendente com o último motivo",
                "1 de 180 concluídas" in texto and "faltam 179" in texto and "cc/sem_instrucao/1" in texto and "rede: x" in texto, texto[:600])
            ver("verificador: só lê (o arquivo ficou igual e nada foi criado)", f.read_bytes() == antes and not list(Path(tmp).glob("*.parcial")))
        finally:
            progresso.AQUI = salvo


@protegido
def verifica_correcoes_da_revisao_adversarial():
    """As correções da revisão adversarial de 11/nov: instruções do Codex, CSV com quebra em campo, classificação do erro
    permanente, tecto só de provedor, chamada de fundo do Qwen, progresso, publicação sem alterar mais que o caminho."""
    import subprocess
    import sys
    from instrumento.dominio import desfechos
    from instrumento.partes import obediencia
    from instrumento.simulacao.endpoint import repasse, servidor_http

    # G1: a description do namespace (instructions do servidor MCP no Codex) chega ao provedor como mensagem de sistema
    corpo = {"instructions": "base", "input": [{"type": "message", "role": "user", "content": "oi"}],
             "tools": [{"type": "namespace", "name": "mcp__s", "description": "INSTRUCAO-X chame a ferramenta",
                        "tools": [{"type": "function", "name": "f", "description": "d", "parameters": {"type": "object"}}]}]}
    chat, _ = repasse.traduz_ida("responses", corpo)
    sistema = " ".join(m["content"] for m in chat["messages"] if m["role"] == "system")
    ver("G1: a description do namespace chega ao provedor", "INSTRUCAO-X chame a ferramenta" in sistema, sistema[:200])
    pedidos = [("req-001.json", {}, {"instructions": "INSTRUCAO-X"})]
    ver("G1: instrucao_chegou exige o texto também no corpo do provedor",
        desfechos.instrucao_chegou("INSTRUCAO-X", pedidos, [("prov-001-ida.json", {}, {"messages": [{"role": "user", "content": "oi"}]})]) == "nao"
        and desfechos.instrucao_chegou("INSTRUCAO-X", pedidos, [("p", {}, {"messages": [{"role": "system", "content": "a INSTRUCAO-X b"}]})]) == "sim"
        and desfechos.instrucao_chegou("INSTRUCAO-X", pedidos) == "sim")

    # G3: cauda cortada no meio de um campo com quebra de linha
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "x.csv"
        campos = ["a", "b"]
        csvs.grava_linha(f, campos, {"a": "1", "b": "linha1\nlinha2"})
        inteiro = f.read_bytes()
        with open(f, "ab") as h:
            h.write(b'2,"corte\nno meio')
        csvs.apara_cauda(f)
        ver("G3: apara_cauda tira só o registro incompleto (campo com quebra intacto)", f.read_bytes() == inteiro
            and csvs.le_csv(f)[0]["b"] == "linha1\nlinha2")
        ver("G3: a cauda foi guardada em .parcial", (Path(tmp) / "x.csv.parcial").read_bytes().startswith(b'2,"corte'))

    # M2/M3: erro permanente só quando a mensagem COMEÇA com o código; tecto só conta falha de provedor
    def classe(falha):
        linha = {"falha_instrumento": falha}
        obediencia.classifica(linha, None)
        return linha["falha_instrumento"].split(":")[0]
    ver("M2: HTTP 404 no começo é permanente; 503 que cita 404 no corpo não é",
        classe("provedor: HTTP 404 do provedor: x") == "permanente"
        and classe("provedor: HTTP 503 do provedor: upstream HTTP 404 (depois de 4 tentativas)") == "provedor"
        and classe("provedor: HTTP 400 do provedor: x") == "permanente"
        and classe("provedor: traducao do repasse: KeyError: 'x'") == "permanente")
    ver("M3: contadores contam só a classe provedor",
        obediencia.contadores([{"falha_instrumento": "rede: x"}, {"falha_instrumento": "rede: suspensao-do-sistema"},
                               {"falha_instrumento": "provedor: y"}])[1] == 1)

    # M1: a chamada de fundo do Qwen é reconhecida
    fundo = {"messages": [{"role": "user", "content": [{"type": "text", "text": "[SUGGESTION MODE: Suggest ...]"}]}]}
    ver("M1: pedido de fundo reconhecido e pedido normal não",
        servidor_http.eh_pedido_de_fundo(fundo) and not servidor_http.eh_pedido_de_fundo({"messages": [{"role": "user", "content": "oi"}]}))

    # M7: o progresso não conta como feita a execução com refação pendente
    linhas = [{"cliente": "cc", "falha_instrumento": "", "nao_usou_ferramenta": "sim"}]
    ver("M7: sem a ferramenta na 1ª tentativa ainda é pendente; na 3ª, conta",
        progresso.unicas(linhas, ["cliente"], True) == 0 and progresso.unicas(linhas * 3, ["cliente"], True) == 1)

    # G2: a preparação da evidência troca só o caminho (CRLF preservado) e não sobrescreve a cópia bruta
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp) / "res"
        (raiz / "x").mkdir(parents=True)
        (raiz / "a.csv").write_bytes(b'c,d\r\n/home/alanv/x,"q\r\nr"\r\n')
        bruta = Path(tmp) / "bruto.tar.gz"
        script = str(AQUI / "publicacao" / "prepara_evidencia.py")
        r1 = subprocess.run([sys.executable, script, str(raiz), "--aplicar", "--copia-bruta", str(bruta)], capture_output=True, text=True)
        ver("G2: troca o caminho em bytes e mantém o resto do CSV", (raiz / "a.csv").read_bytes() == b'c,d\r\n~/x,"q\r\nr"\r\n', r1.stdout + r1.stderr)
        r2 = subprocess.run([sys.executable, script, str(raiz), "--aplicar", "--copia-bruta", str(bruta)], capture_output=True, text=True)
        ver("G2: recusa sobrescrever a cópia bruta", r2.returncode != 0 and "já existe" in (r2.stdout + r2.stderr))


@protegido
def verifica_aprovacao_persistida_e_portao():
    """A aprovação persistente é conferida no disco do cliente (a regra, não o texto do menu); o portão espera o tools/list."""
    from instrumento.partes import comum
    comum.VERIFICA_APROVACAO = True
    try:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            ver("aprovação: sem arquivo de configuração não persistiu (três clientes)",
                not any(comum.aprovacao_persistiu(r, raiz) for r in ("cc", "qw", "cx")))
            (raiz / "projeto/.claude").mkdir(parents=True)
            (raiz / "projeto/.claude/settings.local.json").write_text(json.dumps({"permissions": {"allow": ["mcp__servidor-teste__consulta_teste"]}}))
            (raiz / "home/.qwen").mkdir(parents=True)
            (raiz / "home/.qwen/settings.json").write_text(json.dumps({"permissions": {"allow": ["x"]}}))
            (raiz / "home/.codex").mkdir(parents=True)
            (raiz / "home/.codex/config.toml").write_text('[mcp_servers.servidor-teste.tools.consulta_teste]\napproval_mode = "approve"\n')
            igual("aprovação: cc e cx persistiram, qw (regra errada) não",
                  [comum.aprovacao_persistiu(r, raiz) for r in ("cc", "qw", "cx")], [True, False, True])
            reg = raiz / "registro.jsonl"
            reg.write_text(json.dumps({"direcao": "recebida", "t": 5.0, "mensagem": {"method": "tools/list"}}) + "\n")
            ver("portão: vê o tools/list depois do instante dado e não vê o anterior",
                comum.esperou_tools_list(reg, 1.0, limite=0) and not comum.esperou_tools_list(reg, 9.0, limite=0))
    finally:
        comum.VERIFICA_APROVACAO = False
