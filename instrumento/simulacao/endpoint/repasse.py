"""O modo repasse: o pedido do cliente vira um pedido OpenAI Chat para o provedor, e a resposta volta."""

import json
import re
import zlib


class Nomes:
    """Os nomes de ferramenta do cliente <-> nomes planos válidos no OpenAI Chat (`[A-Za-z0-9_-]{1,64}`).
    Os grupos (`namespace`) do Codex viram `<grupo>__<nome>` e se desfazem na volta."""

    def __init__(self):
        self.por_chave, self.por_plano, self.custom = {}, {}, set()

    def plano(self, nome, grupo=None):
        chave = (grupo, nome)
        if chave in self.por_chave:
            return self.por_chave[chave]
        base = nome if not grupo else f"{grupo}__{nome}"
        plano = re.sub(r"[^A-Za-z0-9_-]", "_", base) or "_"
        if len(plano) > 64:
            plano = plano[:55] + "_" + format(zlib.crc32(base.encode()), "08x")
        candidato, i = plano, 1
        while candidato in self.por_plano:
            i += 1
            candidato = plano[:64 - len(str(i)) - 1] + f"_{i}"
        self.por_chave[chave], self.por_plano[candidato] = candidato, chave
        return candidato

    def original(self, plano):
        """(grupo, nome) do cliente; um nome que o cliente não ofereceu volta como veio."""
        return self.por_plano.get(plano, (None, plano))


def _texto_de(conteudo):
    """O texto de um conteúdo: string, ou lista de partes com `text` (as outras partes caem)."""
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        return "\n".join(p if isinstance(p, str) else p["text"] for p in conteudo
                         if isinstance(p, str) or (isinstance(p, dict) and isinstance(p.get("text"), str)))
    return "" if conteudo is None else json.dumps(conteudo, ensure_ascii=False)


def _funcao(nome, descricao, esquema):
    return {"type": "function", "function": {"name": nome, "description": descricao or "",
                                             "parameters": esquema if isinstance(esquema, dict) else {"type": "object", "properties": {}}}}


def _chamada_chat(id_, nome, args):
    if not isinstance(args, str):
        args = json.dumps(args if args is not None else {})
    return {"id": id_, "type": "function", "function": {"name": nome, "arguments": args}}


def _normaliza_sistema(msgs):
    """Mensagens de sistema do começo viram uma só; as do meio da conversa viram `user` (alguns
    modelos do provedor só aceitam sistema no começo)."""
    i = 0
    while i < len(msgs) and msgs[i]["role"] == "system":
        i += 1
    sistema = "\n\n".join(m["content"] for m in msgs[:i] if m.get("content"))
    saida = [{"role": "system", "content": sistema}] if sistema else []
    return saida + [dict(m, role="user") if m["role"] == "system" else m for m in msgs[i:]]


def _ida_anthropic(corpo, nomes):
    tools = [_funcao(nomes.plano(t["name"]), t.get("description"), t["input_schema"])
             for t in corpo.get("tools") or []
             if isinstance(t, dict) and isinstance(t.get("name"), str) and isinstance(t.get("input_schema"), dict)]
    msgs = []
    if corpo.get("system"):
        msgs.append({"role": "system", "content": _texto_de(corpo["system"])})
    for m in corpo.get("messages") or []:
        papel, conteudo = m.get("role"), m.get("content")
        if isinstance(conteudo, str):
            msgs.append({"role": papel, "content": conteudo})
            continue
        textos, resultados, chamadas = [], [], []
        for b in conteudo or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                textos.append(b.get("text", ""))
            elif b.get("type") == "tool_result":
                resultados.append({"role": "tool", "tool_call_id": b.get("tool_use_id"), "content": _texto_de(b.get("content"))})
            elif b.get("type") == "tool_use":
                chamadas.append(_chamada_chat(b.get("id"), nomes.plano(b.get("name", "")), b.get("input")))
            # thinking, redacted_thinking, imagens e documentos não vão ao provedor
        if papel == "assistant":
            if textos or chamadas:
                msg = {"role": "assistant", "content": "\n".join(textos) if textos else None}
                if chamadas:
                    msg["tool_calls"] = chamadas
                msgs.append(msg)
        else:
            msgs += resultados
            if textos:
                msgs.append({"role": papel, "content": "\n".join(textos)})
    return msgs, tools


def _ida_chat(corpo, nomes):
    tools = [_funcao(nomes.plano(t["function"]["name"]), t["function"].get("description"), t["function"].get("parameters"))
             for t in corpo.get("tools") or []
             if isinstance(t, dict) and isinstance(t.get("function"), dict) and isinstance(t["function"].get("name"), str)]
    msgs = []
    for m in corpo.get("messages") or []:
        papel = "system" if m.get("role") == "developer" else m.get("role")
        conteudo = m.get("content")
        if isinstance(conteudo, list) and (papel == "tool" or all(
                isinstance(p, dict) and isinstance(p.get("text"), str) for p in conteudo)):
            conteudo = _texto_de(conteudo)
        msg = {"role": papel, "content": conteudo}
        if papel == "tool":
            msg["tool_call_id"] = m.get("tool_call_id")
        for c in (m.get("tool_calls") or []) if papel == "assistant" else []:
            fn = c.get("function") or {}
            msg.setdefault("tool_calls", []).append(
                _chamada_chat(c.get("id"), nomes.plano(fn.get("name", "")), fn.get("arguments")))
        msgs.append(msg)
    return msgs, tools


def _ferramentas_responses(lista, nomes, grupo=None):
    saida = []
    for t in lista or []:
        if not isinstance(t, dict):
            continue
        if t.get("type") == "namespace":
            saida += _ferramentas_responses(t.get("tools"), nomes, t.get("name"))
        elif not isinstance(t.get("name"), str):
            continue  # web_search e afins não têm nome nem vão ao provedor
        elif t.get("type") == "function":
            saida.append(_funcao(nomes.plano(t["name"], grupo), t.get("description"), t.get("parameters")))
        elif t.get("type") == "custom":
            plano = nomes.plano(t["name"], grupo)
            nomes.custom.add(plano)
            saida.append(_funcao(plano, t.get("description"), {
                "type": "object", "properties": {"input": {"type": "string", "description": "Texto de entrada da ferramenta."}},
                "required": ["input"]}))
    return saida


def _ida_responses(corpo, nomes):
    tools = _ferramentas_responses(corpo.get("tools"), nomes)
    msgs = []
    if corpo.get("instructions"):
        msgs.append({"role": "system", "content": _texto_de(corpo["instructions"])})
    itens = corpo.get("input")
    if isinstance(itens, str):
        itens = [{"type": "message", "role": "user", "content": itens}]
    for it in itens or []:
        if not isinstance(it, dict):
            continue
        tipo = it.get("type") or ("message" if "role" in it else None)
        if tipo == "message":
            papel = "system" if it.get("role") == "developer" else it.get("role")
            msgs.append({"role": papel, "content": _texto_de(it.get("content"))})
        elif tipo in ("function_call", "custom_tool_call"):
            plano = nomes.plano(it.get("name", ""), it.get("namespace"))
            args = it.get("arguments") if tipo == "function_call" else {"input": it.get("input", "")}
            chamada = _chamada_chat(it.get("call_id") or it.get("id"), plano, args)
            if not msgs or msgs[-1]["role"] != "assistant":
                msgs.append({"role": "assistant", "content": None})
            msgs[-1].setdefault("tool_calls", []).append(chamada)
        elif tipo in ("function_call_output", "custom_tool_call_output"):
            msgs.append({"role": "tool", "tool_call_id": it.get("call_id"), "content": _texto_de(it.get("output"))})
        # reasoning, web_search_call etc. não vão ao provedor
    return msgs, tools


def traduz_ida(formato, corpo):
    """(corpo_chat, nomes): o pedido do cliente como pedido OpenAI Chat (mensagens e ferramentas;
    `model`, `temperature` e `max_tokens` são do `Provedor`)."""
    nomes = Nomes()
    msgs, tools = {"anthropic": _ida_anthropic, "chat": _ida_chat,
                   "responses": _ida_responses}[formato](corpo, nomes)
    chat = {"messages": _normaliza_sistema(msgs)}
    if tools:
        chat["tools"] = tools
    return chat, nomes


def traduz_volta(resp, nomes):
    """(texto, chamadas, tokens) de uma resposta Chat do provedor. O raciocínio (`reasoning_content`,
    `<think>`) não volta ao cliente; fica em `prov-NNN-volta.json`."""
    msg = (resp["choices"][0].get("message") or {})
    texto = _texto_de(msg.get("content")) if msg.get("content") else ""
    if "</think>" in texto:
        texto = texto.rsplit("</think>", 1)[1].lstrip("\n")
    chamadas, usados = [], set()
    for i, c in enumerate(msg.get("tool_calls") or []):
        fn = c.get("function") or {}
        grupo, nome = nomes.original(fn.get("name") or "")
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        id_ = re.sub(r"[^A-Za-z0-9_-]", "_", str(c.get("id") or "")) or f"call_{i + 1}"
        while id_ in usados:
            id_ += "_"
        usados.add(id_)
        chamada = {"id": id_, "name": nome, "args": args}
        if grupo:
            chamada["namespace"] = grupo
        if fn.get("name") in nomes.custom:
            chamada["custom"] = True
        chamadas.append(chamada)
    uso = resp.get("usage") or {}
    tokens = tuple(v if isinstance(v, int) else 0 for v in (uso.get("prompt_tokens"), uso.get("completion_tokens")))
    return texto, chamadas, tokens


def nome_efetivo(chamada):
    """O nome que o modelo de fato chamou. Pela ponte do Qwen (`tool_call` com `name` nos
    argumentos) vira `tool_call:<nome>`, para o `obedeceu` enxergar a ferramenta de destino."""
    nome, args = chamada.get("name"), chamada.get("args") or {}
    if nome == "tool_call" and isinstance(args.get("name"), str):
        return f"tool_call:{args['name']}"
    return nome
