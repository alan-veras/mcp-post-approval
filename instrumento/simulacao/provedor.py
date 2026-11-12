"""O provedor do modo repasse: um cliente mínimo de OpenAI Chat Completions (API da NVIDIA).

Só o endpoint (a thread do orquestrador) usa este módulo; os clientes de linha de
comando nunca o veem nem recebem a chave. A chave nunca é impressa, gravada em
arquivo, posta em mensagem de erro nem passada a processo filho: todo texto de
falha passa por `_limpa`, que a troca por `***`.
"""
import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


BASE_NVIDIA = "https://integrate.api.nvidia.com/v1"
ESPERAS = (15, 30)  # segundos de espera antes da 2ª e da 3ª tentativa
TEMPO_LIMITE = 90  # segundos por pedido: 3 tentativas cabem na fase A (420 s)
TETO_TOKENS = 8192  # o max_tokens do cliente passa, limitado a este teto
VARIAVEL = "NVIDIA_API_KEY"


class ErroProvedor(Exception):
    """O provedor recusou o pedido de um jeito que repetir não resolve (400 a 404, 422...)."""


class PressaoPersistente(ErroProvedor):
    """429, 5xx ou erro de rede que continuaram depois de todas as esperas."""


def chave_nvidia(arquivo_env=None):
    """A chave: `NVIDIA_API_KEY` do ambiente, ou a linha `NVIDIA_API_KEY=` de um arquivo, só se ele for passado.

    Levanta erro sem a chave e sem mostrar conteúdo do arquivo. `arquivo_env` existe para o selftest.
    """
    valor = os.environ.get(VARIAVEL, "").strip()
    if valor:
        return valor
    try:
        linhas = Path(arquivo_env).read_text(encoding="utf-8").splitlines() if arquivo_env else []
    except OSError:
        linhas = []
    for linha in linhas:
        linha = linha.strip()
        if linha.startswith("export "):
            linha = linha[len("export "):].lstrip()
        if linha.startswith(VARIAVEL + "="):
            valor = linha[len(VARIAVEL) + 1:].strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
                valor = valor[1:-1]
            if valor:
                return valor
    raise ErroProvedor(f"{VARIAVEL} ausente: defina a variável de ambiente")


def resposta_inutilizavel(resp):
    """Falha de infraestrutura, não resposta do modelo (regra mecânica da seção 7): 200 sem texto e sem chamada de
    ferramenta, ou cortada por tamanho com argumentos de ferramenta que não decodificam. Texto sem ferramenta é do
    modelo e passa. Devolve o motivo (vale repetir) ou ''."""
    try:
        escolha = resp["choices"][0]
        msg = escolha.get("message") or {}
        chamadas = msg.get("tool_calls") or []
        conteudo = msg.get("content")
        texto = conteudo if isinstance(conteudo, str) else "".join(
            str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in (conteudo or []))
        if not chamadas and not texto.strip():
            return "o provedor devolveu resposta vazia (sem texto e sem chamada de ferramenta)"
        if escolha.get("finish_reason") == "length":
            # cortada pelo NOSSO limite de tokens: não é resposta do modelo (o raciocínio também conta no limite)
            return "o provedor cortou a resposta por tamanho (finish_reason=length)"
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        return "o provedor devolveu resposta cortada (argumentos de ferramenta truncados)"
    return ""


def sonda(base_url=BASE_NVIDIA, tempo=5):
    """Sem API e sem chave: só abre conexões TCP. 'provedor' se o endereço do provedor ou um segundo destino estável
    (1.1.1.1:443) responde; 'rede' se nenhum responde (internet fora ou DNS fora)."""
    partes = urlsplit(base_url)

    def abre(host, porta):
        try:
            socket.create_connection((host, porta), timeout=tempo).close()
            return True
        except OSError:
            return False
    return "provedor" if abre(partes.hostname, partes.port or 443) or abre("1.1.1.1", 443) else "rede"


class Provedor:
    """`chat(corpo)` faz um POST em `<base_url>/chat/completions` e devolve o JSON da resposta."""

    def __init__(self, modelo, chave, base_url=BASE_NVIDIA, temperatura=None, max_tokens=4096,
                 esperas=ESPERAS, tempo_limite=TEMPO_LIMITE, dorme=time.sleep):
        if not chave:
            raise ErroProvedor("chave do provedor vazia")
        self.modelo, self.temperatura, self.max_tokens = modelo, temperatura, max_tokens
        self.base_url = base_url.rstrip("/")
        self.esperas, self.tempo_limite, self.dorme = tuple(esperas), tempo_limite, dorme
        self._chave = chave
        # um provedor local (o do selftest) nunca passa por proxy do ambiente
        local = urlsplit(self.base_url).hostname in ("127.0.0.1", "localhost")
        self._abre = (urllib.request.build_opener(urllib.request.ProxyHandler({})).open if local
                      else urllib.request.urlopen)

    def __repr__(self):
        return f"Provedor(modelo={self.modelo!r}, base_url={self.base_url!r})"

    def _limpa(self, texto):
        return str(texto).replace(self._chave, "***")

    def corpo_enviado(self, corpo_chat):
        """O corpo que vai de fato ao provedor, sem streaming. É o que o endpoint grava em `prov-NNN-ida.json`.

        Parâmetros: o tradutor de pedidos (repasse.traduz_ida) não copia `temperature` nem `max_tokens` do cliente, então
        valem sempre os do Provedor, iguais para os três clientes (temperatura: o padrão do provedor; max_tokens 4096;
        sem streaming). O ramo abaixo, que aceitaria os do cliente limitados a TETO_TOKENS, só vale se um tradutor os
        copiar; hoje não copia (decisão de 11/nov, registrada em EMENDAS.md)."""
        corpo = {k: v for k, v in corpo_chat.items()
                 if k not in ("model", "temperature", "max_tokens", "max_completion_tokens", "stream", "stream_options")}
        temperatura = corpo_chat.get("temperature", self.temperatura)
        pedido = corpo_chat.get("max_tokens") or corpo_chat.get("max_completion_tokens")
        tokens = min(pedido, TETO_TOKENS) if isinstance(pedido, int) and pedido > 0 else self.max_tokens
        corpo.update(model=self.modelo, max_tokens=tokens, stream=False)
        if temperatura is not None:
            corpo["temperature"] = temperatura
        return corpo

    def _uma_vez(self, dados):
        """(resposta, motivo): resposta é o dict do provedor; motivo é o texto de uma falha que vale repetir."""
        req = urllib.request.Request(self.base_url + "/chat/completions", data=dados, method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "Authorization": "Bearer " + self._chave})
        try:
            with self._abre(req, timeout=self.tempo_limite) as r:
                bruto = r.read()
        except urllib.error.HTTPError as e:
            try:
                detalhe = e.read(500).decode("utf-8", "replace")
            except Exception:
                detalhe = ""
            texto = self._limpa(f"HTTP {e.code} do provedor: {detalhe}".strip())
            if e.code == 429 or e.code >= 500:
                return None, texto
            raise ErroProvedor(texto) from None
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as e:  # inclui IncompleteRead
            return None, self._limpa(f"erro de rede com o provedor: {type(e).__name__}: {e}")
        try:
            resp = json.loads(bruto)
        except ValueError:
            return None, "o provedor devolveu um corpo que não é JSON"
        if not isinstance(resp, dict):
            return None, "o provedor devolveu JSON que não é um objeto"
        if not resp.get("choices"):
            if resp.get("error"):
                erro = resp["error"]
                codigo = erro.get("code") if isinstance(erro, dict) else None
                texto = self._limpa("o provedor devolveu erro: " + json.dumps(erro)[:500])
                # só é permanente o erro de pedido, chave, cota ou modelo; o resto (429, 5xx, "retry later") vale repetir
                if str(codigo) in ("400", "401", "402", "403", "404", "422"):
                    raise ErroProvedor(texto)
                return None, texto.replace("o provedor devolveu erro:", "o provedor devolveu erro transitorio:", 1)
            return None, "o provedor devolveu resposta sem choices"
        vazio = resposta_inutilizavel(resp)
        if vazio:
            return None, vazio
        return resp, ""

    def chat(self, corpo_chat):
        dados = json.dumps(self.corpo_enviado(corpo_chat)).encode()
        motivo, motivos = "", []
        for espera in (0,) + self.esperas:
            if espera:
                self.dorme(espera)
            resp, motivo = self._uma_vez(dados)
            if resp is not None:
                if motivos:  # as repetições internas ficam registradas: nada é refeito sem aparecer na evidência
                    resp["_tentativas_anteriores"] = motivos
                return resp
            motivos.append(motivo[:200])
        raise PressaoPersistente(f"{motivo} (depois de {len(self.esperas) + 1} tentativas)")
