"""Agrupar as linhas dos CSVs: a última linha de cada execução, o que entra no denominador e a ordem dos clientes."""

from instrumento import clientes


def ordem(rotulos):
    base = clientes.ORDEM_RECONSENTIMENTO
    return sorted(set(rotulos), key=lambda r: base.index(r) if r in base else 99)


def agrupa(linhas, campos):
    """{tupla dos campos: [linhas]}, na ordem em que aparecem."""
    g = {}
    for r in linhas:
        g.setdefault(tuple(r.get(c, "") for c in campos), []).append(r)
    return g


def ultimas_por_chave(linhas, chave):
    """A última linha de cada execução (pela `chave`): uma execução refeita (pausa do provedor, fase A sem a
    ferramenta) substitui a antiga, que continua no CSV."""
    ultima = {}
    for r in linhas:
        ultima[tuple(r.get(c, "") for c in chave)] = r
    return list(ultima.values())


def falhou(r):
    return bool(r.get("falha_instrumento") or "")


def sem_ferramenta(r):
    return r.get("nao_usou_ferramenta") == "sim"


def no_denominador(r):
    """Entra no denominador: sem falha de instrumento e sem `nao_usou_ferramenta`."""
    return not falhou(r) and not sem_ferramenta(r)
