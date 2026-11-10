"""A parte "entrega": de uma descrição com conteúdo oculto, o que cada cliente entrega ao modelo, por onde e com que
transformação?

Uma execução (cliente, técnica): pasta isolada, o cliente em modo não interativo contra o endpoint falso no modo
"ok", e os rótulos tirados dos pedidos gravados. Configuração padrão de cada cliente, salvo as travas de segurança.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from instrumento import clientes, config
from instrumento.clientes import isolamento
from instrumento.clientes.configuracao import ServidorMCP
from instrumento.dominio import cargas, desfechos
from instrumento.partes import comum
from instrumento.simulacao.endpoint import formatos, servidor_http

PEDIDO = "Liste as ferramentas disponiveis."
LIMITE = 180  # segundos para o cliente responder
CAMPOS = ["cliente", "versao", "sha256_binario", "tecnica", "rep", "chegou_intacta", "desfecho_descricao", "canal", "desfecho_nome", "desfecho_esquema", "adiada", "diff",
          "saida_cliente", "duracao_s", "rede_bloqueada", "falha_instrumento", "evidencia"]
CHAVE = ("cliente", "tecnica", "rep")
FORMATOS_DE_MODELO = ("anthropic", "chat", "responses")


# ---- o que chegou ao modelo -------------------------------------------------------------------------

def servida_do_registro(registro):
    """A definição que o servidor anunciou no último tools/list: dict ou None."""
    achada = None
    for r in registro:
        if r.get("direcao") == "enviada" and r.get("ferramentas_servidas"):
            for t in r["ferramentas_servidas"]:
                if t.get("name") == cargas.NOME_ENTREGA:
                    achada = t
    return achada


def pedidos_de_modelo(pedidos):
    return [(n, m, c) for n, m, c in pedidos if m.get("formato") in FORMATOS_DE_MODELO and isinstance(c, dict)]


def primeiro_pedido(pedidos):
    """O primeiro pedido do agente principal: o primeiro que leva o pedido do usuário e oferece alguma ferramenta
    (pedidos auxiliares, como o título da conversa, não oferecem). Sem esse, o primeiro que leva o pedido do usuário."""
    com_pedido = [p for p in pedidos if PEDIDO in json.dumps(p[2], ensure_ascii=False)]
    com_ferramentas = [p for p in com_pedido if formatos.nomes_oferecidos(p[2])]
    return (com_ferramentas or com_pedido or [None])[0]


def melhor_achado(achados):
    """Dentre as definições de um pedido: a de nome conhecido; sem ela, o trecho solto."""
    for a in achados:
        if a["nome"] is not None:
            return a
    return achados[0] if achados else None


def rotulos(servida, pedidos):
    """(achado, em_que_pedido, adiada). `achado` é o que chegou no primeiro pedido; se a definição só aparece em
    pedido posterior, o rótulo é `ausente` e adiada vale `sim`; se só o nome aparece (lista de adiadas), `indicio`."""
    modelo = pedidos_de_modelo(pedidos)
    primeiro = primeiro_pedido(modelo)
    if primeiro is None:
        return None, None, "nao"
    achado = melhor_achado(desfechos.acha_definicoes(primeiro[2], cargas.NOME_ENTREGA, cargas.BASE_ENTREGA))
    if achado is not None:
        return achado, primeiro[0], "nao"
    for n, m, c in modelo:
        if n > primeiro[0]:
            depois = melhor_achado(desfechos.acha_definicoes(c, cargas.NOME_ENTREGA, cargas.BASE_ENTREGA))
            if depois is not None:
                return None, n, "sim"
    if desfechos.nome_citado(primeiro[2], cargas.NOME_ENTREGA):
        return None, None, "indicio"
    return None, None, "nao"


def registra_desfechos(linha, servida, pedidos):
    """Os rótulos da descrição, do nome e do esquema que chegaram, comparados com o que o servidor anunciou."""
    achado, _, adiada = rotulos(servida, pedidos)
    chegou = achado["descricao"] if achado else None
    linha["chegou_intacta"] = desfechos.chegou_intacta([servida["description"]], pedidos_de_modelo(pedidos))
    linha["desfecho_descricao"] = desfechos.desfecho_descricao(servida["description"], chegou)  # evidência: o tipo
    linha["canal"] = achado["canal"] if achado else "nenhum"
    linha["desfecho_nome"] = desfechos.desfecho_nome(servida["name"], achado["nome"] if achado else None)
    linha["desfecho_esquema"] = desfechos.desfecho_esquema(servida["inputSchema"], achado["esquema"] if achado else None)
    linha["adiada"] = adiada
    linha["diff"] = json.dumps(desfechos.diff_resumido(servida["description"], chegou), ensure_ascii=False)


# ---- uma execução e a parte inteira -------------------------------------------------------------------

def roda_cliente(modulo, pasta, env, linha, falhas):
    """Roda o cliente sem tela com o pedido e devolve o que ele escreveu."""
    saida_cliente = pasta / "saida-cliente.txt"
    try:
        with open(saida_cliente, "w", encoding="utf-8") as saida:
            r = subprocess.run(modulo.comando_nao_interativo(PEDIDO), cwd=str(isolamento.projeto(pasta)), env=env,
                               stdin=subprocess.DEVNULL, stdout=saida, stderr=subprocess.STDOUT, timeout=LIMITE)
        linha["saida_cliente"] = r.returncode
    except subprocess.TimeoutExpired:
        linha["saida_cliente"] = "timeout"
        falhas.append(f"cliente-estourou-{LIMITE}s")
    return saida_cliente.read_text(encoding="utf-8", errors="replace")


def roda_uma(aqui, modo, rotulo, tecnica, rep, pasta_raiz=None):
    """Uma execução (cliente, técnica, repetição). Devolve a linha do CSV."""
    modulo = clientes.cliente(rotulo)
    destino = Path(pasta_raiz or aqui) / "execucoes" / modo / "entrega" / rotulo / comum.nome_da_execucao(tecnica, rep)
    pasta = isolamento.pasta_de_trabalho()
    linha = comum.nova_linha(CAMPOS, modulo, rotulo, tecnica=tecnica, rep=rep, evidencia=comum.relativo(destino, aqui))
    inicio, falhas = time.time(), []
    ep = servidor_http.Endpoint(pasta / "endpoint", "ok").inicia()
    try:
        comando = [sys.executable, "-B", str(config.EXPERIMENTO), "servidor", "--tecnica", tecnica,
                   "--registro", str(pasta / "registro-servidor.jsonl")]
        env = modulo.prepara(pasta, ServidorMCP(comando), ep.porta, "entrega")
        texto_saida = roda_cliente(modulo, pasta, env, linha, falhas)
        linha["rede_bloqueada"] = comum.rede_bloqueada(texto_saida)
        pedidos = servidor_http.le_pedidos(pasta / "endpoint")
        servida = servida_do_registro(comum.le_registro(pasta / "registro-servidor.jsonl"))
        if not pedidos_de_modelo(pedidos):
            falhas.append("cliente-nao-chamou-endpoint")
        if servida is None:
            falhas.append("servidor-nao-registrou-tools/list")
        if servida is not None and pedidos_de_modelo(pedidos):
            registra_desfechos(linha, servida, pedidos)
    except Exception as erro:
        falhas.append(comum.descreve_excecao(erro))
    finally:
        ep.para()
    return comum.fecha_execucao(linha, falhas, inicio, pasta, destino)


def descreve(linha):
    return (f"entrega {linha['cliente']:4} {linha['tecnica']:10} rep{linha['rep']} intacta={linha['chegou_intacta']} {linha['desfecho_descricao']:22} "
            f"{linha['falha_instrumento']}")
