"""O texto dos relatórios: tabela em Markdown e a nota de cada modo."""


def tabela(cabecalho, linhas):
    saida = ["| " + " | ".join(cabecalho) + " |", "|" + "---|" * len(cabecalho)]
    saida += ["| " + " | ".join(str(c) for c in l) + " |" for l in linhas]
    return "\n".join(saida)


ARG_ENSAIO = {"confirmatoria": "", "ensaio": " --ensaio"}


NOTA_DO_MODO = {"confirmatoria": "Rodada 2: vale o que o pré-registro fixou.",
                "ensaio": "**Ensaio: teste do instrumento, não é resultado.**"}
