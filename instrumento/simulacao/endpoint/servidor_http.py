"""O servidor HTTP do endpoint falso, só em 127.0.0.1, e a leitura dos pedidos gravados.

Grava o corpo de cada requisição (nunca os cabeçalhos, para as chaves jamais entrarem na evidência).
"""
import json
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from instrumento.simulacao.endpoint.formatos import (DIALETOS, MODELO, formato_do_caminho, modelo_do_pedido,
                                                     oferece_ferramenta, tem_resultado)
from instrumento.simulacao.endpoint.repasse import nome_efetivo, traduz_ida, traduz_volta
from instrumento.simulacao.endpoint.respostas import erro_503, monta_resposta, monta_resposta_multi
from instrumento.simulacao.endpoint.roteiro import decide
from instrumento.simulacao.provedor import ErroProvedor

LIMITE_TEXTO_MODELO = 4000  # caracteres do texto do modelo guardados em cada repasse
LISTA_DE_MODELOS = {"object": "list", "has_more": False, "first_id": MODELO, "last_id": MODELO,
                    "data": [{"id": MODELO, "object": "model", "type": "model", "display_name": MODELO}],
                    "models": []}  # a resposta a GET /models e a caminhos que não são pedido de modelo


def le_corpo(cabecalhos, entrada):
    """O corpo da requisição, desfeito o `chunked` e descomprimido (gzip ou zstd) quando dá."""
    if "chunked" in (cabecalhos.get("Transfer-Encoding") or ""):
        dados = b""
        while True:
            tam = int(entrada.readline().strip() or b"0", 16)
            if tam == 0:
                entrada.readline()
                break
            dados += entrada.read(tam)
            entrada.readline()
    else:
        dados = entrada.read(int(cabecalhos.get("Content-Length") or 0))
    cod = (cabecalhos.get("Content-Encoding") or "").lower()
    try:
        if cod == "gzip":
            dados = zlib.decompress(dados, 31)
        elif cod == "zstd":
            from compression import zstd
            dados = zstd.decompress(dados)
    except Exception:
        pass
    return dados


class Tratador(BaseHTTPRequestHandler):
    """Uma requisição. O `Endpoint` dono fica em `self.server.dono`."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    @property
    def dono(self):
        return self.server.dono

    def _envia(self, codigo, tipo, saida):
        try:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(saida)))
            self.end_headers()
            self.wfile.write(saida)
        except (BrokenPipeError, ConnectionResetError):
            pass  # o cliente desistiu (por exemplo, tempo-limite durante o repasse)

    def _meta(self, bruto, formato, acao):
        return {"metodo": self.command, "caminho": self.path, "formato": formato, "tamanho": len(bruto), "acao": acao}

    def _trata(self):
        bruto = le_corpo(self.headers, self.rfile)
        formato = formato_do_caminho(self.path)
        try:
            corpo = json.loads(bruto) if bruto else {}
        except ValueError:
            corpo = {}
        if (self.dono.modo == "repasse" and self.command == "POST" and formato in DIALETOS
                and isinstance(corpo, dict) and oferece_ferramenta(corpo)):
            return self._repassa(bruto, formato, corpo)
        self._responde_local(bruto, formato, corpo)

    do_GET = do_POST = do_PUT = do_DELETE = _trata

    def _responde_local(self, bruto, formato, corpo):
        """Os modos ok e roteirizado, e o que o repasse não manda ao provedor (título, contagem, GET /models)."""
        acao, nome, args = decide(self.dono.modo, formato, corpo if isinstance(corpo, dict) else {}, self.dono.alvo_gemeo,
                                  self.dono.comando_shell)
        meta = self._meta(bruto, formato, acao if formato not in (None, "contagem") else None)
        if self.command == "GET" or formato is None:
            tipo, saida = "application/json", json.dumps(LISTA_DE_MODELOS).encode()
        else:
            tipo, saida = monta_resposta(formato, acao, nome, args, corpo, self.path, self.dono.alvo_gemeo)
        self.dono.grava(bruto, meta)
        if self.dono.modo == "roteirizado" and acao == "ok" and isinstance(corpo, dict) and tem_resultado(formato, corpo):
            self.dono.terminou = True
        self._envia(200, tipo, saida)

    def _repassa(self, bruto, formato, corpo):
        """Repassa o pedido ao provedor e devolve a resposta no dialeto do cliente."""
        with self.dono.trava:
            self.dono.em_voo += 1
        try:
            return self._repassa_um(bruto, formato, corpo)
        finally:
            with self.dono.trava:
                self.dono.em_voo -= 1

    def _pede_ao_provedor(self, pasta, n, formato, corpo):
        """(volta, falha). `volta`: {"resp", "texto", "chamadas", "saida" (tipo, bytes para o cliente)}. A ida e a
        volta ficam em prov-NNN-ida.json e prov-NNN-volta.json. Se a execução já acabou e a pasta temporária foi
        movida, a resposta atrasada não tem onde ficar nem quem a leia: (None, "")."""
        try:
            chat, nomes = traduz_ida(formato, corpo)
            (pasta / f"prov-{n:03d}-ida.json").write_text(
                json.dumps(self.dono.provedor.corpo_enviado(chat), ensure_ascii=False), encoding="utf-8")
            resp = self.dono.provedor.chat(chat)
            if not pasta.exists():
                return None, ""
            (pasta / f"prov-{n:03d}-volta.json").write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
            texto, chamadas, tokens = traduz_volta(resp, nomes)
            saida = monta_resposta_multi(formato, texto, chamadas, corpo, self.path,
                                         modelo_do_pedido(formato, corpo, self.path), tokens)
            return {"resp": resp, "texto": texto, "chamadas": chamadas, "saida": saida}, ""
        except ErroProvedor as e:
            return None, str(e)
        except Exception as e:  # um defeito de tradução também para o repasse, e fica registrado
            return None, f"traducao do repasse: {type(e).__name__}: {e}"

    def _responde_falha(self, pasta, n, bruto, formato, meta, falha, latencia):
        meta["repasse"] = {"n": n, "formato": formato, "chamadas": [], "texto": False, "latencia_s": latencia, "falha": falha}
        if meta["acao"] == "repasse":
            (pasta / f"prov-{n:03d}-volta.json").write_text(json.dumps({"falha": falha}, ensure_ascii=False), encoding="utf-8")
            with self.dono.trava:
                self.dono.falha_provedor = self.dono.falha_provedor or falha
        self.dono.escreve(pasta, n, bruto, meta)
        self._envia(503, "application/json", json.dumps(erro_503(formato)).encode())

    def _repassa_um(self, bruto, formato, corpo):
        n, pasta = self.dono.reserva()
        if eh_pedido_de_fundo(corpo):
            # Chamada de fundo do Qwen Code (sugestão do que o usuário digitaria): não é da tarefa, o modelo não a vê como
            # parte da sessão e ela corre com o fim da fase. Fica gravada, não vai ao provedor e não conta como repasse.
            meta = self._meta(bruto, formato, "fundo-sem-repasse")
            self.dono.escreve(pasta, n, bruto, meta)
            return self._envia(200, *monta_resposta_multi(formato, "", [], corpo, self.path,
                                                           modelo_do_pedido(formato, corpo, self.path), (10, 1)))
        meta = self._meta(bruto, formato, "repasse")
        self.dono.escreve(pasta, n, bruto, meta)  # o pedido fica gravado mesmo se a espera pelo provedor travar
        inicio = time.monotonic()
        if self.dono.falha_provedor:
            meta["acao"], volta, falha = "falha-provedor", None, "recusado: o provedor já falhou nesta execução"
        else:
            volta, falha = self._pede_ao_provedor(pasta, n, formato, corpo)
            if volta is None and not falha:
                return
        latencia = round(time.monotonic() - inicio, 3)
        if falha:
            return self._responde_falha(pasta, n, bruto, formato, meta, falha, latencia)
        texto, chamadas = volta["texto"], volta["chamadas"]
        rep = {"n": n, "formato": formato, "chamadas": [nome_efetivo(c) for c in chamadas],
               "texto": bool(texto), "texto_modelo": (texto or "")[:LIMITE_TEXTO_MODELO], "latencia_s": latencia,
               "modelo_servido": str(volta["resp"].get("model") or "")}  # o nome que o provedor diz ter servido
        rep["finish_reason"] = str(((volta["resp"].get("choices") or [{}])[0] or {}).get("finish_reason") or "")
        if volta["resp"].get("_tentativas_anteriores"):
            rep["tentativas_anteriores"] = volta["resp"]["_tentativas_anteriores"]  # falhas repetidas dentro do Provedor
        self.dono.registra_repasse(pasta, rep, chamadas)
        meta["repasse"] = rep
        self.dono.escreve(pasta, n, bruto, meta)
        self._envia(200, *volta["saida"])


class Endpoint:
    """O endpoint falso. Sobe numa thread; uma instância por execução, com uma pasta por fase (`fase`).

    Modos: `ok`, `roteirizado` e `repasse` (ver o pacote). No modo `repasse`, `provedor` é um `provedor.Provedor`;
    `repasses` lista, em ordem, o que foi repassado nesta fase ({"n", "formato", "chamadas", "texto", "latencia_s"}),
    `terminou` fica verdadeiro quando o provedor responde sem chamada de ferramenta a um pedido repassado (no
    roteirizado: quando responde o texto final a um pedido que já trazia o resultado da ferramenta) e
    `falha_provedor` guarda o texto da primeira falha do provedor (sem a chave). Depois da falha nenhum pedido é
    repassado. `em_voo` conta os repasses à espera do provedor."""

    def __init__(self, pasta, modo="ok", provedor=None, alvo_gemeo=False):
        if modo == "repasse" and provedor is None:
            raise ValueError("o modo repasse precisa de um provedor")
        self.pasta, self.modo, self.provedor, self.alvo_gemeo = Path(pasta), modo, provedor, alvo_gemeo
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.n, self.trava = 0, threading.Lock()
        self.terminou = False
        self.comando_shell = None   # só no ensaio --forcar-shell --roteirizado: a linha que o "modelo" pede ao shell do cliente
        self.repasses, self.falha_provedor = [], ""
        self.em_voo = 0
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        self.http.dono = self
        self.http.daemon_threads = True
        self.porta = self.http.server_address[1]
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)

    def reserva(self):
        """O próximo número de pedido e a pasta em que ele grava."""
        with self.trava:
            self.n += 1
            return self.n, self.pasta

    @staticmethod
    def escreve(pasta, n, bruto, meta):
        if not Path(pasta).exists():
            return  # resposta atrasada de uma execução já encerrada
        (pasta / f"req-{n:03d}.json").write_bytes(bruto)
        (pasta / f"req-{n:03d}.meta").write_text(json.dumps(meta), encoding="utf-8")

    def grava(self, bruto, meta):
        n, pasta = self.reserva()
        self.escreve(pasta, n, bruto, meta)

    def registra_repasse(self, pasta, rep, chamadas):
        """Um repasse que voltou. O que chegou numa fase e só voltou depois da troca fica na evidência da fase dele e
        não conta para a fase seguinte."""
        with self.trava:
            if pasta != self.pasta:
                rep["fora_da_fase"] = True
            else:
                self.repasses.append(rep)
                if not chamadas:
                    self.terminou = True

    def fase(self, pasta):
        """Passa a gravar em outra pasta, com a contagem zerada (a mesma porta vale nas duas fases).
        Zera também `terminou` e `repasses`; `falha_provedor` não zera: uma falha vale para a execução toda."""
        with self.trava:
            self.pasta = Path(pasta)
            self.pasta.mkdir(parents=True, exist_ok=True)
            self.n, self.terminou, self.repasses = 0, False, []

    def inicia(self):
        self.thread.start()
        return self

    def para(self):
        self.http.shutdown()
        self.http.server_close()


def eh_pedido_de_fundo(corpo):
    """A última mensagem do pedido (formato Chat do Qwen Code) começa com `[SUGGESTION MODE`: chamada de fundo da interface."""
    mensagens = corpo.get("messages") if isinstance(corpo, dict) else None
    if not isinstance(mensagens, list) or not mensagens or not isinstance(mensagens[-1], dict):
        return False
    c = mensagens[-1].get("content")
    if isinstance(c, list):
        c = "".join(str(p.get("text") or "") for p in c if isinstance(p, dict))
    return isinstance(c, str) and c.lstrip().startswith("[SUGGESTION MODE")


def le_pedidos(pasta):
    """Os pedidos gravados, em ordem: lista de (nome, meta, corpo ou None)."""
    saida = []
    for f in sorted(Path(pasta).glob("req-*.json")):
        try:
            corpo = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            corpo = None
        try:
            meta = json.loads(f.with_suffix(".meta").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        saida.append((f.name, meta, corpo))
    return saida


def le_pedidos_provedor(pasta):
    """Os corpos que foram de fato ao provedor (prov-NNN-ida.json), no mesmo formato de `le_pedidos`. Vazio nas partes
    sem provedor."""
    saida = []
    for f in sorted(Path(pasta).glob("prov-*-ida.json")):
        try:
            corpo = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            corpo = None
        saida.append((f.name, {}, corpo))
    return saida
