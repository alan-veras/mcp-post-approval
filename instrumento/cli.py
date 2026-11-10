"""O único comando do experimento (rodada 2).

  experimento.py selftest
  experimento.py servidor --tecnica T --registro ARQUIVO
  experimento.py servidor --celula CELULA --versao A|B --registro ARQUIVO [--perfil b] [--estado ARQUIVO]
                          [--comando-gemeo LINHA]
  experimento.py servidor --gemeo --registro ARQUIVO
  experimento.py rodar --parte parte1|parte2|sonda [--ensaio] [filtros]
       parte1: reconsentimento, entrega, instalação (confirmação) e gêmeo invisível, sem API, na ordem sorteada
       parte2: as 6 células da obediência, com API, na ordem sorteada (gasta API: só roda pedida pelo nome)
       sonda:  a sonda dos gerenciadores npx e uvx, sem cliente
       filtros (ensaio): --componentes, --clientes cc,qw,cx --celulas --tecnicas --canais --modelos --reps N
  experimento.py analise [--ensaio]
  experimento.py coleta iniciar|pausar|retomar|status|monitor [--primeiro-plano] [--intervalo S]

Só lê os argumentos e chama os módulos de instrumento/. O rodar grava em resultados/ e só roda com o arquivo
TRAVA-COLETA; com --ensaio, grava em saida-local/, sem trava, para testar o instrumento. A ordem das execuções é a
sorteada com a semente 20261109 (instrumento/dominio/ordem.py). Os números de repetições são os do pré-registro (1 na
Parte 1, 5 na Parte 2); --reps só vale no ensaio.
"""
import argparse
import sys
from functools import partial

from instrumento import clientes, config
from instrumento.dominio import cargas, ordem
from instrumento.execucao import Recusa, Tarefa, percorre
from instrumento.parada import Parada, motivo_de_parada

PARTES = ["parte1", "parte2", "sonda"]


def le_argumentos(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("selftest", help="verifica os módulos, sem nenhum cliente e sem API")
    s = sub.add_parser("servidor", help="o servidor MCP de teste (os clientes o executam)")
    s.add_argument("--tecnica")
    s.add_argument("--celula")
    s.add_argument("--versao", default="A", choices=["A", "B"])
    s.add_argument("--perfil", default="a")
    s.add_argument("--registro")
    s.add_argument("--estado", help="arquivo com a versão (A ou B); vence --versao")
    s.add_argument("--gemeo", action="store_true", help="o servidor gêmeo: só a consulta_teste simples")
    s.add_argument("--comando-gemeo", help="célula gemeo_com_sufixo: a linha de comando do gêmeo que a instrução entrega")
    r = sub.add_parser("rodar", help="executa as sessões e grava os CSVs")
    r.add_argument("--parte", required=True, choices=PARTES)
    r.add_argument("--ensaio", action="store_true", help="grava em saida-local/, sem TRAVA-COLETA")
    r.add_argument("--componentes", help="parte1: reconsentimento,entrega,instalacao,gemeo (filtro do ensaio)")
    r.add_argument("--clientes")
    r.add_argument("--tecnicas")
    r.add_argument("--celulas")
    r.add_argument("--canais")
    r.add_argument("--modelos", help="parte2: ids dos modelos (padrão: os dois do pré-registro)")
    r.add_argument("--reps", type=int, default=None, help="só no ensaio")
    r.add_argument("--forcar-shell", action="store_true",
                   help="só no ensaio, parte2: a tarefa pede o cadastro do gêmeo (grava a tela de shell); CSV próprio")
    r.add_argument("--roteirizado", action="store_true",
                   help="só no ensaio, com --forcar-shell: o modelo roteirizado (sem API) pede o shell do cliente; CSV próprio")
    a = sub.add_parser("analise", help="gera o RELATORIO-<modo>.md")
    a.add_argument("--ensaio", action="store_true", help="lê saida-local/ em vez de resultados/")
    c = sub.add_parser("coleta", help="a coleta inteira: iniciar, pausar, retomar, status, monitor")
    c.add_argument("acao", choices=["iniciar", "pausar", "retomar", "status", "monitor", "_trabalhar"])
    c.add_argument("--primeiro-plano", action="store_true")
    c.add_argument("--intervalo", type=int, default=10)
    ns = p.parse_args(argv)
    if ns.comando in ("rodar", "analise"):
        ns.modo = "ensaio" if ns.ensaio else "confirmatoria"
    return ns


def principal(argv=None):
    a = le_argumentos(argv)
    if a.comando == "servidor":
        return servidor(a)
    if a.comando == "selftest":
        from testes import selftest
        return selftest.roda()
    if a.comando == "rodar":
        return rodar(a)
    if a.comando == "coleta":
        from instrumento.coleta import processo
        return processo.principal(a.acao, a.primeiro_plano, a.intervalo)
    from instrumento.analise import relatorio
    return relatorio.roda(a.modo, config.pasta_do_modo(a.modo))


def servidor(a):
    from instrumento.simulacao import servidor_mcp
    if not a.gemeo and bool(a.tecnica) == bool(a.celula):
        sys.exit("servidor: informe --tecnica (entrega), --celula (reconsentimento ou Parte 2) ou --gemeo")
    servidor_mcp.principal(a.tecnica, a.celula, a.versao, a.perfil, a.registro, a.estado, a.gemeo, a.comando_gemeo)
    return 0


def rodar(a):
    """Percorre a fila sorteada e grava uma linha de CSV por execução. Com o arquivo PAUSAR na raiz, sai antes da próxima
    execução com o código 4; o mesmo comando retoma. Problema de instrumento: código 5."""
    try:
        return _rodar(a)
    except config.PausaPedida:
        print("PAUSADO-pedido: achei o arquivo PAUSAR; nenhuma execução ficou pela metade. "
              "Apague-o e rode o mesmo comando para retomar.", flush=True)
        return config.CODIGO_PAUSA_PEDIDA
    except Recusa as erro:
        sys.exit(f"rodar recusado: {erro}")
    except Parada as motivo:
        print(f"PARADO-instrumento: {motivo}. A decisão vira emenda em EMENDAS.md antes de retomar.", flush=True)
        from instrumento.coleta.fila import CODIGO_PARADA_INSTRUMENTO
        return CODIGO_PARADA_INSTRUMENTO


def confere_trava(a):
    if getattr(a, "roteirizado", False) and not (a.forcar_shell and a.modo == "ensaio" and a.parte == "parte2"):
        sys.exit("rodar recusado: --roteirizado só existe com --ensaio, --parte parte2 e --forcar-shell (nunca entra na coleta)")
    if a.forcar_shell and (a.modo != "ensaio" or a.parte != "parte2"):
        sys.exit("rodar recusado: --forcar-shell só existe com --ensaio e --parte parte2 (nunca entra na coleta)")
    if a.modo == "confirmatoria" and not config.TRAVA.exists():
        sys.exit("rodar recusado: não existe o arquivo TRAVA-COLETA (quem cria é o Alan, depois do selo); "
                 "para testar o instrumento, use --ensaio")
    if a.modo == "confirmatoria" and (a.reps is not None or a.componentes or a.clientes or a.celulas or a.tecnicas
                                      or a.canais or a.modelos):
        sys.exit("rodar recusado: filtros e --reps só valem no ensaio (a confirmatória é a fila inteira do pré-registro)")


def filtra(itens, a):
    """Aplica os filtros do ensaio sem mudar a ordem sorteada."""
    def lista(texto):
        return texto.split(",") if texto else None
    comps, clis, vals = lista(a.componentes), lista(a.clientes), (lista(a.celulas) or []) + (lista(a.tecnicas) or []) + (lista(a.canais) or [])
    mods = lista(a.modelos)
    for rotulo in clis or []:
        if rotulo not in clientes.CLIENTES:
            raise Recusa(f"cliente desconhecido: {rotulo} (use {','.join(clientes.CLIENTES)})")
    return [i for i in itens if (not comps or i.componente in comps) and (not clis or i.cliente in clis)
            and (not vals or i.valor in vals) and (not mods or i.modelo in mods)]


def tarefa(aqui, modo, item):
    """A tarefa da fila para o item: o módulo, o CSV, a chave e a função que roda."""
    from instrumento.partes import entrega, gemeo, instalacao, obediencia, reconsentimento
    c, r = item.cliente, str(item.rep)
    if item.componente == "reconsentimento":
        return Tarefa(aqui / f"reconsentimento-{modo}.csv", reconsentimento.CAMPOS, reconsentimento.CHAVE, (c, item.valor, r),
                      partial(reconsentimento.roda_uma, aqui, modo, c, item.valor, item.rep), reconsentimento.descreve,
                      item.componente)
    if item.componente == "entrega":
        return Tarefa(aqui / f"entrega-{modo}.csv", entrega.CAMPOS, entrega.CHAVE, (c, item.valor, r),
                      partial(entrega.roda_uma, aqui, modo, c, item.valor, item.rep), entrega.descreve, item.componente)
    if item.componente == "instalacao":
        return Tarefa(aqui / f"instalacao-{modo}.csv", instalacao.CAMPOS, instalacao.CHAVE,
                      (c, item.valor, instalacao.CABECALHOS, instalacao.CELULA, r),
                      partial(instalacao.roda_uma, aqui, modo, c, item.valor, item.rep), instalacao.descreve, item.componente)
    return Tarefa(aqui / f"gemeo-{modo}.csv", gemeo.CAMPOS, gemeo.CHAVE, (c, r),
                  partial(gemeo.roda_uma, aqui, modo, c, item.rep), gemeo.descreve, item.componente)


def _rodar(a):
    from instrumento.coleta.fila import FIXADAS
    from instrumento.partes import instalacao, obediencia
    config.checa_pausa()
    confere_trava(a)
    aqui = config.pasta_do_modo(a.modo)
    aqui.mkdir(exist_ok=True)
    confirmatoria = a.modo == "confirmatoria"
    parar = lambda linha, comp: motivo_de_parada(linha, comp, FIXADAS, confirmatoria)
    if a.parte == "sonda":
        return instalacao.sonda(aqui, a.modo, a.canais.split(",") if a.canais else None)
    if a.parte == "parte1":
        itens = filtra(ordem.ordem_parte1(a.reps or ordem.REPS_PARTE1), a)
        return 1 if percorre([tarefa(aqui, a.modo, i) for i in itens], parar) else 0
    return rodar_parte2(aqui, a, parar, obediencia)


def rodar_parte2(aqui, a, parar, obediencia):
    """A Parte 2 na ordem sorteada, os dois modelos intercalados. Devolve 0 ou 1 (falha de instrumento ou de provedor
    registrada)."""
    from instrumento.analise import csvs
    itens = filtra(ordem.ordem_parte2(a.reps or ordem.REPS_PARTE2), a)
    if getattr(a, "forcar_shell", False):  # ensaio: só a célula do gêmeo, num CSV à parte
        itens = [i for i in itens if i.valor == cargas.CELULA_GEMEO]
    roteirizado = getattr(a, "roteirizado", False)
    if roteirizado:  # sem API: nenhum provedor, nenhuma chave; o modelo é o endpoint roteirizado
        itens = list(dict.fromkeys(i._replace(modelo=obediencia.MODELO_ROTEIRIZADO) for i in itens))
        provedores = {obediencia.MODELO_ROTEIRIZADO: None}
    else:
        provedores = {m: obediencia.cria_provedor(m) for m in dict.fromkeys(i.modelo for i in itens)}
    csv = aqui / (f"obediencia-{a.modo}-shell{'-roteirizado' if roteirizado else ''}.csv" if getattr(a, "forcar_shell", False) else f"obediencia-{a.modo}.csv")
    falhas = 0
    for item in itens:
        if obediencia.ja_feita(csv, (item.cliente, item.valor, str(item.rep), item.modelo)):
            continue
        config.checa_pausa()
        linha = obediencia.roda_com_tentativas(aqui, a.modo, item, provedores[item.modelo], csv,
                                                 *((True, roteirizado) if getattr(a, "forcar_shell", False) else ()))
        falhas += bool(linha["falha_instrumento"])
        motivo = parar(linha, "obediencia")
        if motivo:
            raise Parada(motivo)
    return 1 if falhas else 0
