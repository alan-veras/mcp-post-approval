"""O registro local de pacotes da parte "instalação" (METODO.md).

Um servidor HTTP em 127.0.0.1, numa thread do orquestrador, que fala os dois
formatos que o npx e o uvx usam: o registro npm (packument e tarball) e o índice
PyPI "simple" (PEP 503 e PEP 691, com PEP 658 para os metadados). Os pacotes
`servidor-teste-mcp` são construídos na hora com tarfile e zipfile, sem rede nem
ferramenta de build, e existem só aqui: nada é publicado em registro real.

A 1.0.0 anuncia a definição A da célula e a 1.0.1 anuncia a B; a versão vem
gravada dentro do pacote. Antes da fase A só a 1.0.0 é visível; entre as fases o
orquestrador chama `publica("1.0.1")` e nada mais muda. Toda requisição vai para
`registro-pacotes.jsonl` (hora, fase, método, caminho, versão servida, status).
Os cabeçalhos das requisições nunca são gravados.
"""
import base64
import gzip
import hashlib
import io
import json
import tarfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from instrumento.dominio import cargas

PACOTE = "servidor-teste-mcp"
MODULO = "servidor_teste_mcp"
VERSOES = ["1.0.0", "1.0.1"]
DEFINICAO_DA_VERSAO = {"1.0.0": "A", "1.0.1": "B"}
MTIME = 499162500  # data fixa nos arquivos dos pacotes: os mesmos bytes a cada construção
# os cabeçalhos de cache dos registros de verdade (npm: 5 minutos; PyPI: 10 minutos) e um
# perfil que manda revalidar sempre, para separar o que o cache HTTP faz do que a ferramenta faz
CACHE = {"real": {"npm": "public, max-age=300", "pypi": "max-age=600, public"},
         "sem-cache": {"npm": "no-cache", "pypi": "no-cache"}}
NOME_WHEEL = "{m}-{v}-py3-none-any.whl"
NOME_TGZ = "{p}-{v}.tgz"


# ---- o servidor embutido (autônomo: não importa cargas.py) ----------------------

FONTE_SERVIDOR = '''#!/usr/bin/env python3
"""Servidor MCP de teste embutido no pacote servidor-teste-mcp (so biblioteca padrao).
Local e inofensivo: tools/call devolve texto fixo e so escreve no registro."""
import json
import sys
import time

PACOTE_VERSAO = "@@VERSAO@@"
DEFINICAO = "@@DEFINICAO@@"
CELULAS = json.loads(@@CELULAS@@)


def argumentos(argv):
    celula, registro, perfil = None, None, "a"
    i = 0
    while i < len(argv):
        if argv[i] == "--celula" and i + 1 < len(argv):
            celula, i = argv[i + 1], i + 2
        elif argv[i] == "--registro" and i + 1 < len(argv):
            registro, i = argv[i + 1], i + 2
        elif argv[i] == "--perfil" and i + 1 < len(argv):
            perfil, i = argv[i + 1], i + 2
        else:
            i += 1
    return celula, registro, perfil


def main(argv=None):
    celula, caminho, perfil = argumentos(sys.argv[1:] if argv is None else argv)
    if celula not in CELULAS:
        sys.exit("servidor-teste-mcp: informe --celula " + ",".join(CELULAS))
    dados = CELULAS[celula]
    arquivo = open(caminho, "a", encoding="utf-8") if caminho else None

    def grava(direcao, mensagem, **extra):
        if arquivo:
            linha = {"t": round(time.time(), 3), "direcao": direcao, "celula": celula, "versao": DEFINICAO,
                     "versao_pacote": PACOTE_VERSAO, "perfil": perfil,
                     "codigo": DEFINICAO if celula == "codigo_novo" else None, **extra, "mensagem": mensagem}
            arquivo.write(json.dumps(linha, ensure_ascii=False) + "\\n")
            arquivo.flush()

    def responde(req):
        metodo, mid = req.get("method"), req.get("id")
        if mid is None:
            return None
        if metodo == "initialize":
            pedida = (req.get("params") or {}).get("protocolVersion") or "2025-06-18"
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": pedida, "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "servidor-teste", "version": PACOTE_VERSAO}}}
        if metodo == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if metodo == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [dados["definicao"]]}}
        if metodo == "tools/call":
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": dados["texto"]}]}}
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "metodo nao suportado"}}

    grava("partida", {"argv": argv if argv is not None else sys.argv[1:]})
    for linha in sys.stdin:
        linha = linha.strip()
        if not linha:
            continue
        try:
            req = json.loads(linha)
        except ValueError:
            continue
        grava("recebida", req, **({"chamada": True} if req.get("method") == "tools/call" else {}))
        resp = responde(req)
        if resp is None:
            continue
        extra = {"ferramentas_servidas": [dados["definicao"]]} if req.get("method") == "tools/list" else {}
        grava("enviada", resp, **extra)
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
'''


def fonte_servidor(versao):
    """O texto do servidor embutido na versão do pacote: só a definição daquela versão
    (A na 1.0.0, B na 1.0.1) de cada célula, copiada de cargas.py. ASCII puro: os
    caracteres do bloco TAG viajam como escapes \\u do JSON, lidos por json.loads (um literal
    de texto do Python deixaria os pares substitutos soltos)."""
    definicao = DEFINICAO_DA_VERSAO[versao]
    celulas = {c: {"definicao": cargas.ferramenta_teste(c, definicao), "texto": cargas.texto_chamada(c, definicao)}
               for c in cargas.CELULAS_CLIENTE}
    return (FONTE_SERVIDOR.replace("@@VERSAO@@", versao).replace("@@DEFINICAO@@", definicao)
            .replace("@@CELULAS@@", repr(json.dumps(celulas, ensure_ascii=True, sort_keys=True))))


# ---- os pacotes -----------------------------------------------------------------

def monta_tgz(versao):
    """O tarball npm: package/package.json e package/servidor.py (executável)."""
    manifesto = {"name": PACOTE, "version": versao, "description": "Servidor MCP de teste (local, inofensivo)",
                 "bin": {PACOTE: "servidor.py"}, "license": "UNLICENSED", "private": False}
    arquivos = [("package/package.json", json.dumps(manifesto, indent=2).encode(), 0o644),
                ("package/servidor.py", fonte_servidor(versao).encode(), 0o755)]
    bruto = io.BytesIO()
    with gzip.GzipFile(fileobj=bruto, mode="wb", filename="", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            for nome, dados, modo in arquivos:
                info = tarfile.TarInfo(nome)
                info.size, info.mode, info.mtime = len(dados), modo, MTIME
                tar.addfile(info, io.BytesIO(dados))
    return bruto.getvalue()


def _hash_record(dados):
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(dados).digest()).rstrip(b"=").decode()


def metadata_wheel(versao):
    return (f"Metadata-Version: 2.1\nName: {PACOTE}\nVersion: {versao}\n"
            "Summary: Servidor MCP de teste (local, inofensivo)\nRequires-Python: >=3.8\n").encode()


def monta_wheel(versao):
    """O wheel: o módulo, METADATA, WHEEL, entry_points.txt e o RECORD com os hashes."""
    dist = f"{MODULO}-{versao}.dist-info"
    arquivos = [(f"{MODULO}.py", fonte_servidor(versao).encode()),
                (f"{dist}/METADATA", metadata_wheel(versao)),
                (f"{dist}/WHEEL", b"Wheel-Version: 1.0\nGenerator: pergunta-1-reconsentimento\n"
                                  b"Root-Is-Purelib: true\nTag: py3-none-any\n"),
                (f"{dist}/entry_points.txt", f"[console_scripts]\n{PACOTE} = {MODULO}:main\n".encode())]
    record = "".join(f"{n},{_hash_record(d)},{len(d)}\n" for n, d in arquivos) + f"{dist}/RECORD,,\n"
    arquivos.append((f"{dist}/RECORD", record.encode()))
    bruto = io.BytesIO()
    with zipfile.ZipFile(bruto, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, dados in arquivos:
            info = zipfile.ZipInfo(nome, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            z.writestr(info, dados)
    return bruto.getvalue()


def agora_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---- o registro -------------------------------------------------------------------

class Registro:
    """O registro local. Sobe numa thread; uma instância serve as duas fases (a mesma
    porta), e `publica` torna visível a 1.0.1 entre elas."""

    def __init__(self, pasta, cabecalhos="real"):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.log = self.pasta / "registro-pacotes.jsonl"
        self.cache = CACHE[cabecalhos]
        self.cabecalhos = cabecalhos
        self.trava = threading.Lock()
        self.fase_atual = "A"
        self.publicadas = [VERSOES[0]]
        self.horas = {VERSOES[0]: agora_iso()}
        self.tgz = {v: monta_tgz(v) for v in VERSOES}
        self.wheel = {v: monta_wheel(v) for v in VERSOES}
        dono = self

        class Tratador(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _trata(self):
                status, tipo, corpo, extra, meta = dono.responde(self.command, self.path.split("?")[0],
                                                                 self.headers.get("Accept") or "")
                if status == 200 and extra.get("ETag") and self.headers.get("If-None-Match") == extra["ETag"]:
                    status, corpo = 304, b""
                dono.grava(self.command, self.path, status, meta)
                self.send_response(status)
                if status != 304:
                    self.send_header("Content-Type", tipo)
                for k, v in extra.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(corpo)

            do_GET = do_HEAD = _trata

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        self.http.daemon_threads = True
        self.porta = self.http.server_address[1]
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)

    # -- endereços para o ambiente do gerenciador --
    @property
    def url_npm(self):
        return f"http://127.0.0.1:{self.porta}/"

    @property
    def url_simple(self):
        return f"http://127.0.0.1:{self.porta}/simple"

    def inicia(self):
        self.thread.start()
        return self

    def para(self):
        self.http.shutdown()
        self.http.server_close()

    # -- o que o orquestrador controla --
    def fase(self, nome):
        with self.trava:
            self.fase_atual = nome

    def publica(self, versao):
        """Torna a versão visível: `latest` passa a apontar para ela e ela entra no `time`."""
        if versao not in VERSOES:
            raise ValueError(f"versão desconhecida: {versao}")
        with self.trava:
            if versao not in self.publicadas:
                self.publicadas.append(versao)
                self.horas[versao] = agora_iso()

    def ultima(self):
        with self.trava:
            return self.publicadas[-1]

    # -- os documentos --
    def packument(self):
        with self.trava:
            publicadas, horas = list(self.publicadas), dict(self.horas)
        versoes = {}
        for v in publicadas:
            dados = self.tgz[v]
            versoes[v] = {"name": PACOTE, "version": v, "description": "Servidor MCP de teste (local, inofensivo)",
                          "bin": {PACOTE: "servidor.py"}, "_id": f"{PACOTE}@{v}",
                          "dist": {"tarball": f"http://127.0.0.1:{self.porta}/{PACOTE}/-/{NOME_TGZ.format(p=PACOTE, v=v)}",
                                   "shasum": hashlib.sha1(dados).hexdigest(),
                                   "integrity": "sha512-" + base64.b64encode(hashlib.sha512(dados).digest()).decode(),
                                   "fileCount": 2, "unpackedSize": len(fonte_servidor(v)) + 120}}
        return {"_id": PACOTE, "name": PACOTE, "description": "Servidor MCP de teste (local, inofensivo)",
                "dist-tags": {"latest": publicadas[-1]}, "versions": versoes,
                "time": {"created": horas[VERSOES[0]], "modified": horas[publicadas[-1]], **horas},
                "readme": "", "modified": horas[publicadas[-1]]}

    def indice(self):
        """Os dados do índice simple: [(versão, nome do wheel, sha256, sha256 dos metadados)]."""
        with self.trava:
            publicadas, horas = list(self.publicadas), dict(self.horas)
        return [(v, NOME_WHEEL.format(m=MODULO, v=v), hashlib.sha256(self.wheel[v]).hexdigest(),
                 hashlib.sha256(metadata_wheel(v)).hexdigest(), horas[v]) for v in publicadas]

    def indice_json(self):
        return {"meta": {"api-version": "1.1"}, "name": PACOTE, "versions": [i[0] for i in self.indice()],
                "files": [{"filename": nome, "url": f"http://127.0.0.1:{self.porta}/files/{nome}",
                           "hashes": {"sha256": sha}, "requires-python": ">=3.8",
                           "core-metadata": {"sha256": meta}, "upload-time": hora.replace(".000Z", ".000000Z")}
                          for v, nome, sha, meta, hora in self.indice()]}

    def indice_html(self):
        links = "".join(f'<a href="http://127.0.0.1:{self.porta}/files/{nome}#sha256={sha}" data-requires-python="&gt;=3.8" '
                        f'data-core-metadata="sha256={meta}">{nome}</a><br/>\n'
                        for v, nome, sha, meta, hora in self.indice())
        return (f'<!DOCTYPE html>\n<html><head><meta name="pypi:repository-version" content="1.1">'
                f"<title>Links for {PACOTE}</title></head><body>\n<h1>Links for {PACOTE}</h1>\n{links}</body></html>\n")

    def responde(self, metodo, caminho, accept):
        """(status, tipo, corpo, cabeçalhos extras, meta do registro) de um GET."""
        meta = {"tipo": "outro", "versao_servida": None}
        nao_achou = (404, "application/json", b'{"error":"Not found"}', {}, meta)
        partes = [p for p in caminho.split("/") if p]
        publicadas = list(self.publicadas)
        if partes == [PACOTE]:
            ultima = self.ultima()
            corpo = json.dumps(self.packument()).encode()
            abreviado = "application/vnd.npm.install-v1+json" in accept
            meta.update(tipo="packument", versao_servida=ultima, formato="abreviado" if abreviado else "completo")
            return (200, "application/vnd.npm.install-v1+json" if abreviado else "application/json", corpo,
                    {"Cache-Control": self.cache["npm"], "ETag": '"' + hashlib.sha1(corpo).hexdigest() + '"'}, meta)
        if len(partes) == 3 and partes[0] == PACOTE and partes[1] == "-":
            for v in publicadas:
                if partes[2] == NOME_TGZ.format(p=PACOTE, v=v):
                    meta.update(tipo="tarball", versao_servida=v)
                    return 200, "application/octet-stream", self.tgz[v], {"Cache-Control": self.cache["npm"]}, meta
            return nao_achou
        if partes == ["-", "ping"]:
            return 200, "application/json", b"{}", {}, meta
        if partes[:1] == ["simple"] and len(partes) == 2 and partes[1] == PACOTE:
            json_pedido = "application/vnd.pypi.simple.v1+json" in accept
            corpo = json.dumps(self.indice_json()).encode() if json_pedido else self.indice_html().encode()
            meta.update(tipo="indice", versao_servida=self.ultima(), formato="json" if json_pedido else "html")
            tipo = "application/vnd.pypi.simple.v1+json" if json_pedido else "text/html; charset=utf-8"
            return (200, tipo, corpo, {"Cache-Control": self.cache["pypi"],
                                       "ETag": '"' + hashlib.sha1(corpo).hexdigest() + '"'}, meta)
        if len(partes) == 2 and partes[0] == "files":
            for v in publicadas:
                nome = NOME_WHEEL.format(m=MODULO, v=v)
                if partes[1] == nome:
                    meta.update(tipo="wheel", versao_servida=v)
                    return 200, "application/octet-stream", self.wheel[v], {"Cache-Control": self.cache["pypi"]}, meta
                if partes[1] == nome + ".metadata":
                    meta.update(tipo="metadados", versao_servida=v)
                    return 200, "text/plain; charset=utf-8", metadata_wheel(v), {"Cache-Control": self.cache["pypi"]}, meta
        return nao_achou

    def grava(self, metodo, caminho, status, meta):
        with self.trava:
            linha = {"t": round(time.time(), 3), "fase": self.fase_atual, "metodo": metodo, "caminho": caminho,
                     "status": status, **meta}
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(linha) + "\n")


def le_requisicoes(caminho):
    """As requisições gravadas, em ordem."""
    try:
        return [json.loads(l) for l in Path(caminho).read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


# ---- as observações da instalação (ver instalacao.py) -------------------------------------------

def buscou_registro(requisicoes, fase):
    """buscou: na fase dada, o gerenciador consultou o registro (packument ou índice simple)?"""
    return "sim" if any(r["fase"] == fase and r.get("tipo") in ("packument", "indice") for r in requisicoes) else "nao"


def baixou_versao(requisicoes, fase, versao="1.0.1"):
    """baixou: o tarball ou o wheel da versão foi baixado na fase dada?"""
    return "sim" if any(r["fase"] == fase and r.get("tipo") in ("tarball", "wheel") and r.get("versao_servida") == versao
                        and r.get("status") == 200 for r in requisicoes) else "nao"


def versao_rodou(registro_servidor):
    """versao instalada: a versão que respondeu `initialize` (pelo registro-servidor.jsonl): 1.0.0, 1.0.1 ou nenhuma."""
    achadas = [r.get("versao_pacote") for r in registro_servidor if r.get("direcao") == "enviada"
               and ((r.get("mensagem") or {}).get("result") or {}).get("serverInfo")]
    return achadas[-1] if achadas else "nenhuma"
