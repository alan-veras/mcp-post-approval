#!/usr/bin/env python3
"""Gera `LEIA-ME-EXECUCOES.md`: uma seção por execução, lida dos CSVs e das pastas de evidência. Só leitura (escreve só o .md).

Uso: python3 publicacao/resumo_execucoes.py [pasta]      (padrão: resultados/; para o ensaio: saida-local/)
Os CSVs e as pastas `execucoes/...` da pasta dada são a fonte; nada é interpretado além do que já está registrado.
"""
import csv
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from instrumento.analise import csvs  # noqa: E402
CSVS = [("Parte 1: reconsentimento", "reconsentimento", ("cliente", "celula", "rep")),
        ("Parte 1: entrega", "entrega", ("cliente", "tecnica", "rep")),
        ("Parte 1: instalação", "instalacao", ("cliente", "canal", "celula", "rep")),
        ("Parte 1: gêmeo invisível", "gemeo", ("cliente", "rep")),
        ("Parte 1: sonda de instalação", "instalacao-sonda", ("canal", "cabecalhos", "passo")),
        ("Parte 2: obediência (modelo real)", "obediencia", ("cliente", "celula", "rep", "modelo", "tentativa"))]
ARQUIVOS = ["tela-A.txt", "tela-B.txt", "historico-A.txt", "historico-B.txt", "repasses.json", "registro-servidor.jsonl", "linha.json"]
TEXTO = "texto_modelo_B"
OCULTOS = {"sha256_binario", TEXTO, "evidencia"}


def le(caminho):
    """Só os registros completos (uma cauda cortada não vira seção)."""
    return csvs.le_csv(caminho)


def secao(pasta, tipo, linha, chaves):
    titulo = " · ".join(f"{c}={linha.get(c)}" for c in chaves if linha.get(c) not in (None, ""))
    out = [f"### {titulo}", ""]
    out.append("| campo | valor |\n|---|---|")
    for k, v in linha.items():
        if k not in OCULTOS and v not in ("", None):
            out.append(f"| {k} | {str(v).replace('|', chr(92) + '|').replace(chr(10), ' ')} |")
    if linha.get("sha256_binario"):
        out.append(f"| sha256 do binário | `{linha['sha256_binario']}` |")
    if linha.get(TEXTO):
        out += ["", "O que o modelo disse (fase B), como gravado:", ""]
        out += ["> " + t for t in linha[TEXTO].replace(" || ", "\n\n---\n\n").splitlines()]
    ev = linha.get("evidencia")
    if ev and (pasta / ev).is_dir():
        achados = [a for a in ARQUIVOS if (pasta / ev / a).exists()]
        if achados:
            out += ["", "Evidência: " + " · ".join(f"[{a}]({ev}/{a})" for a in achados)]
        fases = [f for f in ("faseA", "faseB") if (pasta / ev / f).is_dir()]
        if fases:
            out += ["", "O que o cliente mandou ao endereço local (`req-NNN.json`) e, na Parte 2, o que foi ao provedor (`prov-NNN-ida.json`) e voltou (`prov-NNN-volta.json`): "
                    + " · ".join(f"[{f}/]({ev}/{f}/)" for f in fases)]
    elif ev:
        out += ["", f"Evidência: `{ev}` (pasta não está nesta cópia)"]
    return out + [""]


def gera(pasta):
    pasta = Path(pasta)
    corpo, indice, total = [], [], 0
    for titulo, nome, chaves in CSVS:
        achados = sorted(pasta.glob(f"{nome}-*.csv")) if nome != "instalacao" else \
            [p for p in sorted(pasta.glob("instalacao-*.csv")) if "sonda" not in p.name]
        for arq in achados:
            if nome == "entrega" and "sonda" in arq.name:
                continue
            linhas = le(arq)
            total += len(linhas)
            indice.append(f"- {titulo}: {len(linhas)} execuções (`{arq.name}`)")
            corpo += [f"## {titulo}", "", f"Fonte: `{arq.name}`. {len(linhas)} linhas.", ""]
            for l in linhas:
                corpo += secao(pasta, nome, l, chaves)
    cab = ["# Execuções, uma por uma", "",
           "Gerado por `publicacao/resumo_execucoes.py` a partir dos CSVs e das pastas de evidência desta pasta. "
           "Nada aqui foi escrito à mão. Cada seção traz os campos registrados, o que o modelo disse (Parte 2) e os links "
           "para a tela do cliente, o histórico, o que foi repassado ao modelo e o registro do servidor.", "",
           f"Total de linhas: {total}. Uma execução refeita aparece em mais de uma linha: na Parte 2 pela coluna `tentativa`; na Parte 1 a evidência da tentativa anterior fica na pasta `<pasta>-t<n>` e a seção da linha mais recente é a que vale.", ""] + indice + [""]
    (pasta / "LEIA-ME-EXECUCOES.md").write_text("\n".join(cab + corpo), encoding="utf-8")
    return total


if __name__ == "__main__":
    alvo = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "resultados"
    print(f"{gera(alvo)} execuções resumidas em {alvo / 'LEIA-ME-EXECUCOES.md'}")
