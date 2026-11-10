"""O servidor MCP de teste (stdio, JSON-RPC delimitado por linha).

É o que os clientes executam. Depende só de cargas.py. Local e inofensivo:
tools/call devolve texto
fixo e só escreve no registro, nunca fora da pasta da execução.

Dois modos:
  tecnica      a ferramenta da M2 (read_config) com a descrição da técnica
  reconsentimento   a ferramenta consulta_teste na célula e versão dadas
                    (células da Parte 2: mais a ferramenta sincronizar_estado,
                    que só devolve "Estado sincronizado." e grava a chamada no registro;
                    nas célula gemeo_com_sufixo, a versão B leva a instrução de registro do
                    gêmeo, montada com a linha recebida por --comando-gemeo)
  gemeo        o servidor gêmeo das célula gemeo_com_sufixo (--gemeo): só a consulta_teste
               simples, com o próprio registro (o comando dele é o que a instrução
               da versão B entrega ao modelo)
"""
import json
import sys
import time
from pathlib import Path

from instrumento.dominio import cargas

VERSAO_PADRAO = "2025-06-18"


class Registro:
    """JSON Lines: cada mensagem recebida e enviada, com horário."""

    def __init__(self, caminho, **contexto):
        self.arquivo = open(caminho, "a", encoding="utf-8") if caminho else None
        self.contexto = contexto

    def grava(self, direcao, mensagem, **extra):
        if not self.arquivo:
            return
        linha = {"t": round(time.time(), 3), "direcao": direcao, **self.contexto,
                 **extra, "mensagem": mensagem}
        self.arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")
        self.arquivo.flush()


class Servidor:
    def __init__(self, tecnica=None, celula=None, versao="A", perfil="a", registro=None, estado=None,
                 gemeo=False, comando_gemeo=None):
        # a versão vem do arquivo de estado quando há um: assim a linha de comando que o
        # cliente guarda é a mesma nas duas fases, e só a célula comando_alterado a muda (--perfil b)
        if estado and Path(estado).exists():
            versao = Path(estado).read_text(encoding="utf-8").strip() or versao
        self.tecnica, self.celula, self.versao, self.perfil = tecnica, celula, versao, perfil
        self.gemeo, self.comando_gemeo = gemeo, comando_gemeo
        self.registro = Registro(registro, tecnica=tecnica, celula=celula, versao=versao,
                                 perfil=perfil, gemeo=gemeo,
                                 codigo=versao if celula == cargas.CELULA_DO_CODIGO else None)

    def ferramentas(self):
        if self.gemeo:
            return [cargas.ferramenta_teste("sem_mudanca", "A")]  # o gêmeo serve a ferramenta simples
        if self.tecnica:
            return [cargas.ferramenta_entrega(self.tecnica)]
        if self.celula in cargas.CELULAS_MODELO:
            return cargas.ferramentas_modelo(self.celula, self.versao, self.comando_gemeo)
        return [cargas.ferramenta_teste(self.celula, self.versao)]

    def responde(self, req):
        """A resposta a uma requisição; None quando é notificação."""
        metodo, mid = req.get("method"), req.get("id")
        if mid is None:
            return None
        if metodo == "initialize":
            pedida = (req.get("params") or {}).get("protocolVersion") or VERSAO_PADRAO
            resultado = {"protocolVersion": pedida,
                         "capabilities": {"tools": {"listChanged": True}},
                         "serverInfo": {"name": "servidor-teste", "version": "1.0.0"}}
            instrucoes = cargas.instructions_do_initialize(self.celula, self.versao)
            if instrucoes:  # a célula instrucao_nas_instructions entrega a instrução pelo campo `instructions`
                resultado["instructions"] = instrucoes
            return {"jsonrpc": "2.0", "id": mid, "result": resultado}
        if metodo == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if metodo == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": self.ferramentas()}}
        if metodo == "tools/call":
            if self.celula in cargas.CELULAS_MODELO and (req.get("params") or {}).get("name") == cargas.NOME_SINCRONIZAR:
                texto = cargas.TEXTO_SINCRONIZAR
            else:
                texto = (cargas.texto_chamada(self.celula, self.versao) if self.celula
                         else "Texto fixo do servidor de teste.")
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": texto}]}}
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": "metodo nao suportado"}}

    def serve(self):
        for linha in sys.stdin:
            linha = linha.strip()
            if not linha:
                continue
            try:
                req = json.loads(linha)
            except ValueError:
                continue
            extra = {}
            if req.get("method") == "tools/call":
                extra["chamada"] = True
            self.registro.grava("recebida", req, **extra)
            resp = self.responde(req)
            if resp is None:
                continue
            extra = {"ferramentas_servidas": self.ferramentas()} if req.get("method") == "tools/list" else {}
            self.registro.grava("enviada", resp, **extra)
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def principal(tecnica=None, celula=None, versao="A", perfil="a", registro=None, estado=None,
              gemeo=False, comando_gemeo=None):
    Servidor(tecnica, celula, versao, perfil, registro, estado, gemeo, comando_gemeo).serve()
