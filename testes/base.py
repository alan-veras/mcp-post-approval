"""O que todos os grupos do autoteste usam: o registro das verificações (`ver`, `igual`) e os dados comuns."""

from pathlib import Path

from instrumento.dominio import cargas


AQUI = Path(__file__).resolve().parents[1]  # a raiz do experimento


INSTRUMENTO = AQUI / "instrumento"


RESULTADOS = []


TOOL = "mcp__servidor-teste__consulta_teste"


BASE = cargas.BASE_ENTREGA


TAGGED = BASE + "\n" + cargas.tag_codifica("Nota oculta (marcador).")


TRAVESSAO = chr(0x2014)  # o travessão longo, que nenhum arquivo desta pasta pode ter


def ver(nome, condicao, detalhe=""):
    RESULTADOS.append((nome, bool(condicao), detalhe))


def igual(nome, obtido, esperado):
    ver(nome, obtido == esperado, "" if obtido == esperado else f"obtido {obtido!r}, esperado {esperado!r}")


def protegido(grupo):
    """Roda um grupo de verificações; uma exceção vira uma FALHA do grupo."""
    def embrulho():
        try:
            grupo()
        except Exception as erro:
            ver(f"{grupo.__name__} (exceção)", False, f"{type(erro).__name__}: {erro}")
    return embrulho
