"""Os corpos de resposta, um construtor por dialeto (Anthropic, OpenAI Chat, OpenAI Responses).

Cada `resp_*_multi` monta a resposta com texto e zero ou mais chamadas de ferramenta; `chamadas` é uma lista
de dicts {"id", "name", "args"}, mais "namespace" (grupo do Codex) e "custom" (ferramenta `custom` do
Codex, cujo `args` é {"input": texto}). As `resp_*` de uma chamada só delegam a elas."""

import json
import time

from instrumento.simulacao.endpoint.formatos import MODELO, namespace_de


IDS_FALSOS = {"anthropic": "toolu_falso1", "chat": "call_falso1", "responses": "call_falso1"}


def _sse(eventos):
    saida = ""
    for nome, dado in eventos:
        saida += (f"event: {nome}\n" if nome else "") + "data: " + (
            dado if isinstance(dado, str) else json.dumps(dado)) + "\n\n"
    return saida.encode()


def _com_texto(texto, chamadas):
    """O texto entra na resposta quando há texto, ou quando não há chamada nenhuma."""
    return bool(texto) or not chamadas


def resp_anthropic_multi(texto, chamadas, stream, modelo=MODELO, tokens=(10, 5)):
    uso = {"input_tokens": tokens[0], "output_tokens": tokens[1]}
    blocos = [{"type": "text", "text": texto}] if _com_texto(texto, chamadas) else []
    blocos += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in chamadas]
    parada = "tool_use" if chamadas else "end_turn"
    msg = {"id": "msg_falso", "type": "message", "role": "assistant", "model": modelo,
           "content": blocos, "stop_reason": parada, "stop_sequence": None, "usage": uso}
    if not stream:
        return "application/json", json.dumps(msg).encode()
    ev = [("message_start", {"type": "message_start", "message": dict(msg, content=[], stop_reason=None)})]
    for i, bloco in enumerate(blocos):
        chama = bloco["type"] == "tool_use"
        vazio = dict(bloco, **({"input": {}} if chama else {"text": ""}))
        delta = ({"type": "input_json_delta", "partial_json": json.dumps(bloco["input"])} if chama
                 else {"type": "text_delta", "text": bloco["text"]})
        ev += [("content_block_start", {"type": "content_block_start", "index": i, "content_block": vazio}),
               ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": delta}),
               ("content_block_stop", {"type": "content_block_stop", "index": i})]
    ev += [("message_delta", {"type": "message_delta", "delta": {"stop_reason": parada, "stop_sequence": None},
                              "usage": {"output_tokens": tokens[1]}}),
           ("message_stop", {"type": "message_stop"})]
    return "text/event-stream", _sse(ev)


def resp_anthropic(acao, nome, args, texto, stream):
    chamadas = [{"id": IDS_FALSOS["anthropic"], "name": nome, "args": args}] if acao == "chamada" else []
    return resp_anthropic_multi("" if chamadas else texto, chamadas, stream)


def resp_chat_multi(texto, chamadas, stream, modelo=MODELO, tokens=(10, 5)):
    base = {"id": "chatcmpl-falso", "created": int(time.time()), "model": modelo}
    uso = {"prompt_tokens": tokens[0], "completion_tokens": tokens[1], "total_tokens": sum(tokens)}
    if chamadas:
        feitas = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}
                  for c in chamadas]
        msg, fim = {"role": "assistant", "content": texto or None, "tool_calls": feitas}, "tool_calls"
    else:
        msg, fim = {"role": "assistant", "content": texto}, "stop"
    if not stream:
        return "application/json", json.dumps(dict(base, object="chat.completion", usage=uso, choices=[
            {"index": 0, "message": msg, "finish_reason": fim}])).encode()
    delta = dict(msg)
    if chamadas:
        delta["tool_calls"] = [dict(f, index=i) for i, f in enumerate(feitas)]
    chunk = lambda d, f: dict(base, object="chat.completion.chunk",
                              choices=[{"index": 0, "delta": d, "finish_reason": f}])
    return "text/event-stream", _sse([
        (None, chunk(delta, None)), (None, chunk({}, fim)),
        (None, dict(base, object="chat.completion.chunk", choices=[], usage=uso)),
        (None, "[DONE]")])


def resp_chat(acao, nome, args, texto, stream):
    chamadas = [{"id": IDS_FALSOS["chat"], "name": nome, "args": args}] if acao == "chamada" else []
    return resp_chat_multi("" if chamadas else texto, chamadas, stream)


def _item_chamada(c):
    """O item `function_call` (ou `custom_tool_call`) do Responses para uma chamada."""
    id_item = c.get("item_id") or "fc_" + (c["id"][5:] if c["id"].startswith("call_") else c["id"])
    if c.get("custom"):
        return {"type": "custom_tool_call", "id": id_item, "call_id": c["id"], "name": c["name"],
                "input": str(c["args"].get("input", ""))}
    item = {"type": "function_call", "id": id_item, "call_id": c["id"],
            "name": c["name"], "arguments": json.dumps(c["args"]), "status": "completed"}
    if c.get("namespace"):
        item["namespace"] = c["namespace"]
    return item


def resp_responses_multi(texto, chamadas, stream, modelo=MODELO, tokens=(10, 5)):
    uso = {"input_tokens": tokens[0], "output_tokens": tokens[1], "total_tokens": sum(tokens)}
    itens = []
    if _com_texto(texto, chamadas):
        itens.append({"type": "message", "id": "msg_falso1", "role": "assistant", "status": "completed",
                      "content": [{"type": "output_text", "text": texto, "annotations": []}]})
    itens += [_item_chamada(c) for c in chamadas]
    resp = {"id": "resp_falso", "object": "response", "created_at": int(time.time()),
            "status": "completed", "model": modelo, "output": itens, "usage": uso}
    if not stream:
        return "application/json", json.dumps(resp).encode()
    em_curso = dict(resp, status="in_progress", output=[], usage=None)
    ev = [("response.created", {"type": "response.created", "response": em_curso}),
          ("response.in_progress", {"type": "response.in_progress", "response": em_curso})]
    for i, item in enumerate(itens):
        if item["type"] == "function_call":
            ev += [("response.output_item.added", {"type": "response.output_item.added", "output_index": i,
                                                   "item": dict(item, arguments="", status="in_progress")}),
                   ("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta",
                                                               "item_id": item["id"], "output_index": i,
                                                               "delta": item["arguments"]}),
                   ("response.function_call_arguments.done", {"type": "response.function_call_arguments.done",
                                                              "item_id": item["id"], "output_index": i,
                                                              "arguments": item["arguments"]})]
        elif item["type"] == "custom_tool_call":
            ev += [("response.output_item.added", {"type": "response.output_item.added", "output_index": i,
                                                   "item": dict(item, input="")}),
                   ("response.custom_tool_call_input.delta", {"type": "response.custom_tool_call_input.delta",
                                                              "item_id": item["id"], "output_index": i,
                                                              "delta": item["input"]}),
                   ("response.custom_tool_call_input.done", {"type": "response.custom_tool_call_input.done",
                                                             "item_id": item["id"], "output_index": i,
                                                             "input": item["input"]})]
        else:
            parte = item["content"][0]
            ev += [("response.output_item.added", {"type": "response.output_item.added", "output_index": i,
                                                   "item": dict(item, content=[], status="in_progress")}),
                   ("response.content_part.added", {"type": "response.content_part.added", "item_id": item["id"],
                                                    "output_index": i, "content_index": 0,
                                                    "part": dict(parte, text="")}),
                   ("response.output_text.delta", {"type": "response.output_text.delta", "item_id": item["id"],
                                                   "output_index": i, "content_index": 0, "delta": texto}),
                   ("response.output_text.done", {"type": "response.output_text.done", "item_id": item["id"],
                                                  "output_index": i, "content_index": 0, "text": texto}),
                   ("response.content_part.done", {"type": "response.content_part.done", "item_id": item["id"],
                                                   "output_index": i, "content_index": 0, "part": parte})]
        ev.append(("response.output_item.done", {"type": "response.output_item.done", "output_index": i, "item": item}))
    ev.append(("response.completed", {"type": "response.completed", "response": resp}))
    return "text/event-stream", _sse(ev)


def resp_responses(acao, nome, args, texto, stream, grupo=None):
    chamada = {"id": IDS_FALSOS["responses"], "name": nome, "args": args}
    if grupo:
        chamada["namespace"] = grupo
    chamadas = [chamada] if acao == "chamada" else []
    return resp_responses_multi("" if chamadas else texto, chamadas, stream)


def instancia_do_esquema(esq):
    """Um valor mínimo que cumpre o esquema JSON (tipos em maiúsculas ou minúsculas)."""
    tipo = str(esq.get("type", "")).lower()
    if tipo == "object":
        return {k: instancia_do_esquema(v) for k, v in (esq.get("properties") or {}).items()}
    if tipo == "array":
        return []
    if tipo in ("integer", "number"):
        return esq.get("minimum", 1)
    if tipo == "boolean":
        return False
    return (esq.get("enum") or ["ok"])[0]


def texto_final(corpo):
    """"ok", ou um JSON mínimo quando o pedido exige saída estruturada (response_format)."""
    esq = None
    if isinstance(corpo.get("response_format"), dict):
        esq = (corpo["response_format"].get("json_schema") or {}).get("schema")
    return json.dumps(instancia_do_esquema(esq)) if isinstance(esq, dict) else "ok"


def monta_resposta_multi(formato, texto, chamadas, corpo, caminho, modelo=MODELO, tokens=(10, 5)):
    """(tipo, bytes) da resposta no dialeto do cliente, com texto e zero ou mais chamadas."""
    if formato == "anthropic":
        return resp_anthropic_multi(texto, chamadas, bool(corpo.get("stream")), modelo, tokens)
    if formato == "chat":
        return resp_chat_multi(texto, chamadas, bool(corpo.get("stream")), modelo, tokens)
    if formato == "responses":
        return resp_responses_multi(texto, chamadas, bool(corpo.get("stream")), modelo, tokens)
    raise ValueError(f"dialeto desconhecido: {formato}")


def monta_resposta(formato, acao, nome, args, corpo, caminho, alvo_gemeo=False):
    """(tipo, bytes) da resposta no dialeto do cliente."""
    if formato == "contagem":
        return "application/json", json.dumps({"input_tokens": 10}).encode()
    if formato == "anthropic":
        return resp_anthropic(acao, nome, args, texto_final(corpo), bool(corpo.get("stream")))
    if formato == "chat":
        return resp_chat(acao, nome, args, texto_final(corpo), bool(corpo.get("stream")))
    if formato == "responses":
        return resp_responses(acao, nome, args, texto_final(corpo), bool(corpo.get("stream")),
                              namespace_de(corpo, nome, alvo_gemeo))
    raise ValueError(f"dialeto desconhecido: {formato}")


def erro_503(formato):
    """O corpo de um erro 503 no dialeto do cliente (sem detalhe da falha: o texto fica em `ep.falha_provedor`)."""
    msg = "provedor do experimento indisponivel"
    if formato == "anthropic":
        return {"type": "error", "error": {"type": "api_error", "message": msg}}
    return {"error": {"message": msg, "type": "server_error", "code": "provedor_indisponivel"}}
