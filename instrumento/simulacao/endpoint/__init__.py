"""O endpoint falso: responde no lugar do provedor, só em 127.0.0.1.

Fala Anthropic Messages, OpenAI Chat Completions, OpenAI Responses, com e sem SSE. Grava o corpo de cada
requisição (nunca os cabeçalhos, para as chaves jamais entrarem na evidência).

Modos:
  ok             responde só o texto "ok" (parte "entrega")
  roteirizado    se o pedido oferece a ferramenta consulta_teste e ainda não traz
                 o resultado dela, responde uma chamada dela, sem argumentos; se
                 já traz o resultado, ou se não a oferece, responde "ok"
  repasse        (parte "obediencia") o pedido que oferece a ferramenta consulta_teste
                 vai a um modelo real, pelo `Provedor` (provedor.py), traduzido do dialeto
                 do cliente para o OpenAI Chat e de volta; o que não a oferece (título,
                 count_tokens, GET /models) é respondido local, como no modo ok. Só esta
                 thread fala com o provedor, e a chave nunca entra na evidência.

Módulos: formatos (ler o pedido), roteiro (modos ok e roteirizado), respostas (um construtor por
dialeto), repasse (ida e volta do provedor) e servidor_http (o Endpoint).
"""
