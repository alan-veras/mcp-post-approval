"""O que as quatro partes repartem: hashes e instantâneos dos arquivos, o registro do servidor e a linha do CSV.

Uma execução sempre: abre uma pasta isolada, cria a linha com os campos da parte, roda, preenche os desfechos,
junta as falhas e guarda a pasta como evidência (`fecha_execucao`).
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

from instrumento.clientes import isolamento
from instrumento.dominio import desfechos

IGNORADOS = (".cache", "node_modules", ".npm", ".git")  # caches que não são configuração do cliente
TRAVA_NO_HISTORICO = re.compile(r"127\.0\.0\.1:9\b")  # o cliente tentou sair pela trava de proxy
TRAVESSAO = chr(0x2014)  # o travessão longo, que não vai para o CSV


# ---- arquivos -----------------------------------------------------------------------------------

def sha256_arquivo(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def sha256_binario(modulo):
    """O SHA-256 do binário do cliente (seguindo links), ou vazio se ele não está instalado."""
    b = modulo.binario()
    return sha256_arquivo(os.path.realpath(b)) if b else ""


def instantaneo(pasta):
    """{caminho relativo: sha256} de tudo em home/ e projeto/ (menos caches)."""
    pasta = Path(pasta)
    saida = {}
    for raiz in ("home", "projeto"):
        for f in sorted((pasta / raiz).rglob("*")):
            rel = f.relative_to(pasta)
            if f.is_file() and not f.is_symlink() and not any(p in IGNORADOS for p in rel.parts):
                try:
                    saida[str(rel)] = sha256_arquivo(f)
                except OSError:
                    pass
    return saida


def diff_instantaneos(antes, depois):
    return {"novos": sorted(set(depois) - set(antes)),
            "alterados": sorted(k for k in antes if k in depois and antes[k] != depois[k]),
            "removidos": sorted(set(antes) - set(depois)),
            "sha256": {k: depois[k] for k in depois if k not in antes or antes[k] != depois[k]}}


def le_registro(caminho):
    """As linhas JSON do registro do servidor MCP (vazio se ainda não existe)."""
    try:
        return [json.loads(l) for l in Path(caminho).read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


def recebeu_tools_call(registro):
    """O servidor recebeu ao menos um `tools/call` (a ferramenta rodou)?"""
    return any(r["direcao"] == "recebida" and r["mensagem"].get("method") == "tools/call" for r in registro)


# ---- a linha do CSV -----------------------------------------------------------------------------

def nome_da_execucao(base, rep):
    """A pasta de uma repetição: `entrega` na primeira, `entrega-rep2` nas outras."""
    return base if rep == 1 else f"{base}-rep{rep}"


def relativo(destino, aqui):
    """O caminho da evidência como vai no CSV: relativo à pasta do modo, quando está dentro dela."""
    return str(destino.relative_to(aqui)) if destino.is_relative_to(aqui) else str(destino)


def nova_linha(campos, modulo, rotulo, **valores):
    """A linha de uma execução com todos os campos vazios, mais o cliente, a versão e o hash do binário."""
    linha = {c: "" for c in campos}
    linha.update(cliente=rotulo, versao=modulo.versao(), sha256_binario=sha256_binario(modulo), **valores)
    return linha


def rede_bloqueada(*historicos):
    return "sim" if TRAVA_NO_HISTORICO.search("".join(historicos)) else "nao"


def registra_fase_a(linha, a, falhas):
    """O que a fase A pediu e aprovou, e a falha dela, se houve."""
    linha["pediu_fase_a"] = "+".join(dict.fromkeys(a["pediu"])) or "nada"
    linha["opcao_aprovada"] = " | ".join(dict.fromkeys(a["opcoes"])) or "nenhuma"
    if a["falha"]:
        falhas.append("A:" + a["falha"])


def registra_desfechos_cliente(linha, b):
    """Os desfechos da fase B na Parte 1: rodou_sem_aviso, pediu_aprovacao e bloqueado_sem_explicacao.
    O modelo roteirizado sempre pede a chamada; se o endpoint não registrou o pedido E a tela também não mostra a frase de
    pedido do cliente, a linha vira falha de instrumento (devolve o texto da falha, ou vazio). Pedido na partida (a frase
    aparece antes do prompt): a automação não aprova, o modelo nem chega a pedir, e o desfecho é pediu_aprovacao."""
    pediu = desfechos.modelo_pediu_chamada(b["pedidos"])
    recebeu = desfechos.rodou_sem_aviso(b["registro"]) == "sim"
    frase = bool(b["achados"]["servidor"] or b["achados"]["chamada"])
    linha.update(desfechos.classifica_cliente(pediu, recebeu, frase))
    linha["modelo_pediu"] = "sim" if pediu else "nao"
    return "" if (pediu or frase) else "B:modelo-nao-pediu-a-chamada"


def descreve_excecao(erro):
    return f"excecao:{type(erro).__name__}:{erro}"


def fecha_execucao(linha, falhas, inicio, pasta, destino):
    """Grava a duração e as falhas na linha, deixa a linha.json na pasta e a move para a evidência."""
    linha["duracao_s"] = round(time.time() - inicio, 1)
    linha["falha_instrumento"] = "; ".join(falhas)
    (Path(pasta) / "linha.json").write_text(json.dumps(linha, ensure_ascii=False, indent=1), encoding="utf-8")
    isolamento.guarda_evidencia(pasta, destino)
    return linha
