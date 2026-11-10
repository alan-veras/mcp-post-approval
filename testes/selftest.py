"""O autoteste: confere os módulos sem nenhum cliente e sem nenhum modelo.

Uma linha por verificação, OK ou FALHA; código de saída 0 só se todas passarem. Cada grupo mora num módulo
`verifica_*.py`, um por pacote do instrumento, e registra as verificações em `base.RESULTADOS`.
"""
from testes import (verifica_analise, verifica_coleta, verifica_dominio, verifica_endpoint_repasse, verifica_forcar_shell, verifica_higiene,
                    verifica_obediencia, verifica_partes, verifica_regras, verifica_revisao, verifica_simulacao)
from testes.base import RESULTADOS

GRUPOS = [
    verifica_dominio.verifica_cargas, verifica_dominio.verifica_desfechos, verifica_dominio.verifica_ordem,
    verifica_dominio.verifica_roteiro_gemeo,
    verifica_analise.verifica_estatistica, verifica_analise.verifica_variacao_gemeo, verifica_analise.verifica_analise,
    verifica_coleta.verifica_pausa, verifica_coleta.verifica_confirmatoria, verifica_coleta.verifica_paradas,
    verifica_simulacao.verifica_servidor, verifica_simulacao.verifica_endpoint,
    verifica_obediencia.verifica_obediencia_fluxo, verifica_obediencia.verifica_obediencia_regras,
    verifica_obediencia.verifica_obediencia_chave, verifica_obediencia.verifica_obediencia_fase_b_dois_tempos,
    verifica_endpoint_repasse.verifica_repasse, verifica_forcar_shell.verifica_forcar_shell, verifica_forcar_shell.verifica_tela_real_de_shell_cc, verifica_forcar_shell.verifica_roteirizado_shell,
    verifica_simulacao.verifica_registro, verifica_simulacao.verifica_pacote,
    verifica_partes.verifica_instalacao, verifica_partes.verifica_ponta_a_ponta, verifica_partes.verifica_clientes,
    verifica_partes.verifica_parte1_fluxo, verifica_partes.verifica_comandos,
    verifica_revisao.verifica_a1_cadastrou_gemeo_pela_estrutura, verifica_revisao.verifica_a2_aprovacoes_da_parte2,
    verifica_revisao.verifica_a3_pedido_na_partida, verifica_revisao.verifica_m1_acentos,
    verifica_revisao.verifica_m2_m3_m4, verifica_revisao.verifica_m6_instalacao, verifica_revisao.verifica_b_higiene,
    verifica_regras.verifica_regras, verifica_higiene.verifica_higiene,
]


def roda():
    for grupo in GRUPOS:
        grupo()
    for nome, ok, detalhe in RESULTADOS:
        print(("OK     " if ok else "FALHA  ") + nome + (f"  [{detalhe}]" if detalhe and not ok else ""))
    falhas = [r for r in RESULTADOS if not r[1]]
    print(f"\n{len(RESULTADOS) - len(falhas)} de {len(RESULTADOS)} verificações OK"
          + (f", {len(falhas)} FALHA(S)" if falhas else ""))
    return 1 if falhas else 0
