"""A leitura de um pedido de modelo, em qualquer dos quatro dialetos: qual é, o que oferece, o que já chamou."""

import json
import re
from urllib.parse import urlsplit


SUFIXO_FERRAMENTA = "consulta_teste"


MODELO = "falso"


def formato_do_caminho(caminho):
    """Qual dialeto o caminho indica; None quando não é pedido de modelo."""
    p = urlsplit(caminho).path
    if p.endswith("/count_tokens"):
        return "contagem"
    if p.endswith("/messages"):
        return "anthropic"
    if p.endswith("/chat/completions"):
        return "chat"
    if p.endswith("/responses"):
        return "responses"
    return None


def nomes_oferecidos(corpo, ferramentas=None):
    """Nomes de ferramenta que o pedido oferece, em qualquer dialeto (inclui os
    grupos aninhados do Codex, `namespace`)."""
    nomes = []
    for t in (corpo.get("tools") or []) if ferramentas is None else ferramentas:
        if not isinstance(t, dict):
            continue
        if isinstance(t.get("name"), str):
            nomes.append(t["name"])
        if isinstance(t.get("function"), dict) and isinstance(t["function"].get("name"), str):
            nomes.append(t["function"]["name"])
        if isinstance(t.get("tools"), list):
            nomes += nomes_oferecidos(corpo, t["tools"])
    return nomes


def namespace_de(corpo, nome):
    """O grupo (namespace) em que o pedido oferece a ferramenta, ou None."""
    for t in corpo.get("tools") or []:
        if isinstance(t, dict) and t.get("type") == "namespace" and nome in nomes_oferecidos(corpo, t.get("tools") or []):
            return t.get("name")
    return None


def tem_resultado(formato, corpo):
    """O pedido já traz o resultado de uma chamada de ferramenta?"""
    if formato == "anthropic":
        return any(isinstance(b, dict) and b.get("type") == "tool_result"
                   for m in corpo.get("messages") or []
                   if isinstance(m.get("content"), list) for b in m["content"])
    if formato == "chat":
        return any(m.get("role") == "tool" for m in corpo.get("messages") or [])
    if formato == "responses":
        itens = corpo.get("input")
        return isinstance(itens, list) and any(
            isinstance(i, dict) and i.get("type") == "function_call_output" for i in itens)
    return False


def chamadas_anteriores(formato, corpo):
    """Os nomes das ferramentas que o modelo já chamou nesta conversa, em ordem."""
    nomes = []
    if formato == "chat":
        for m in corpo.get("messages") or []:
            for c in m.get("tool_calls") or []:
                nomes.append((c.get("function") or {}).get("name"))
    elif formato == "anthropic":
        for m in corpo.get("messages") or []:
            if isinstance(m.get("content"), list):
                nomes += [b.get("name") for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"]
    elif formato == "responses":
        itens = corpo.get("input")
        nomes = [i.get("name") for i in itens if isinstance(i, dict) and i.get("type") == "function_call"] if isinstance(itens, list) else []
    return nomes


DIALETOS = ("anthropic", "chat", "responses")


def oferece_ferramenta(corpo):
    """O pedido oferece a ferramenta de teste? Como no `decide`: pelo nome, ou pela ponte
    tool_search / tool_call do Qwen quando o nome aparece no corpo."""
    oferecidos = nomes_oferecidos(corpo)
    if any(n.endswith(SUFIXO_FERRAMENTA) for n in oferecidos):
        return True
    return bool(re.search(r"mcp__[\w-]+__" + SUFIXO_FERRAMENTA, json.dumps(corpo))
                and "tool_search" in oferecidos and "tool_call" in oferecidos)


def modelo_do_pedido(formato, corpo, caminho):
    """O modelo que o cliente pediu (a resposta o repete, para o cliente não estranhar)."""
    if isinstance(corpo.get("model"), str):
        return corpo["model"]
    achou = re.search(r"models/([^:/?]+)", urlsplit(caminho).path)
    return achou.group(1) if achou else MODELO
