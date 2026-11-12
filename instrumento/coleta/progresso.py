"""O progresso de cada passo, lido dos CSVs, e o retrato que o status e o monitor mostram."""

import csv
import io

from instrumento import config
from instrumento.analise import csvs
from instrumento.coleta.diario import AQUI, LOG, agora, estado, pid_vivo
from instrumento.coleta.fila import FILA


def le(nome):
    return csvs.le_csv(AQUI / nome)


def unicas(linhas, campos, ignora_pausa=False):
    """Execuções distintas concluídas. Com `ignora_pausa` (Parte 2), a mesma regra de `obediencia.ja_feita`: a chave só
    conta se alguma linha não é falha de infraestrutura (provedor, rede ou erro permanente) nem `nao_usou_ferramenta`,
    ou se a fase A ficou sem a ferramenta em todas as 1 + 2 tentativas; senão a execução continua pendente."""
    grupos = {}
    for r in linhas:
        grupos.setdefault(tuple(r.get(c, "") for c in campos), []).append(r)
    if not ignora_pausa:
        return len(grupos)
    infra = lambda r: (r.get("falha_instrumento") or "").startswith(("provedor:", "rede:", "permanente:"))
    sem = lambda r: r.get("nao_usou_ferramenta") == "sim" and not infra(r)
    return sum(any(not infra(r) and not sem(r) for r in rs) or sum(sem(r) for r in rs) >= 3 for rs in grupos.values())


def progresso():
    """[(passo, feitas, esperadas, falhas, duração média em s)] direto dos CSVs de cada passo."""
    saida = []
    for passo in FILA:
        feitas = esperado = falhas = 0
        dur = []
        for s in passo.saidas:
            linhas = le(s.csv)
            feitas += min(unicas(linhas, s.chave, ignora_pausa=passo.gasta_api), s.esperadas)
            esperado += s.esperadas
            falhas += sum(bool(r.get("falha_instrumento")) for r in linhas)
            dur += [float(r["duracao_s"]) for r in linhas if r.get("duracao_s")]
        saida.append((passo.nome, feitas, esperado, falhas, sum(dur) / len(dur) if dur else None))
    return saida


def barra(feitas, total, largura=24):
    cheio = int(largura * feitas / total) if total else 0
    return "#" * cheio + "." * (largura - cheio)


def hms(s):
    s = int(s)
    return f"{s // 3600}h{s % 3600 // 60:02d}m"


def retrato():
    pid, e = pid_vivo(), estado()
    if pid and config.PAUSA.exists():
        situacao = f"PAUSANDO (pid {pid}): a execução atual termina e a coleta para"
    elif pid:
        situacao = f"RODANDO (pid {pid})"
    elif config.PAUSA.exists():
        situacao = "PAUSADA (retome com: python3 experimento.py coleta retomar)"
    elif len(e["concluidos"]) == len(FILA):
        situacao = "CONCLUÍDA"
    else:
        situacao = "PARADA (veja o fim do log; retome com: python3 experimento.py coleta retomar)"
    linhas = [f"Coleta da rodada 2  {agora()}  {situacao}", ""]
    total_f = total_e = 0
    resta = 0.0
    for nome, feitas, esperadas, falhas, media in progresso():
        feitas = min(feitas, esperadas)
        total_f, total_e = total_f + feitas, total_e + esperadas
        if media:
            resta += (esperadas - feitas) * media
        linhas.append(f"  {nome:38} [{barra(feitas, esperadas)}] {feitas:4}/{esperadas:<4}"
                      f"{'  falhas ' + str(falhas) if falhas else ''}")
    linhas += ["", f"  total {total_f}/{total_e} ({100 * total_f / total_e:.1f}%)"
               + (f"   restante estimado (pela média de cada parte já começada): {hms(resta)}" if resta else ""),
               "", "Passos: " + "  ".join(f"{'[x]' if n in e['concluidos'] else '[ ]'} {n}" for n in (p.nome for p in FILA)), "",
               "Últimas linhas do log:"]
    try:
        cauda = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]
    except OSError:
        cauda = ["(sem log ainda)"]
    linhas += ["  " + c[:160] for c in cauda]
    return "\n".join(linhas)


def verifica():
    """Só leitura: confere os CSVs da coleta e diz o que falta e por quê. Não altera nenhum arquivo."""
    from instrumento.dominio import ordem
    saida = []
    for passo in FILA:
        for s in passo.saidas:
            f = AQUI / s.csv
            if not f.exists():
                saida.append(f"{s.csv}: ainda não existe (0 de {s.esperadas})")
                continue
            bruto = f.read_bytes()
            corte = csvs.fim_do_ultimo_registro(bruto)
            completo = bruto[:corte]
            linhas = list(csv.DictReader(io.StringIO(completo.decode("utf-8", "replace"), newline="")))  # sem a cauda incompleta
            if corte != len(bruto):
                saida.append(f"{s.csv}: ATENÇÃO: a última linha está sem quebra (cauda incompleta; a próxima gravação a guarda em .parcial)")
            cabecalhos = sum(1 for l in bruto.decode("utf-8", "replace").splitlines()[1:] if l.startswith(s.chave[0] + ","))
            por_chave = {}
            for r in linhas:
                por_chave.setdefault(tuple(r.get(c, "") for c in s.chave), []).append(r)
            infra = lambda r: (r.get("falha_instrumento") or "").startswith(("provedor:", "rede:", "permanente:"))
            concluidas = [k for k, rs in por_chave.items() if not all(infra(r) for r in rs)]
            repetidas = [k for k, rs in por_chave.items() if len(rs) > 1 and not any(infra(r) or r.get("nao_usou_ferramenta") == "sim" for r in rs[:-1])
                         and passo.nome != "parte1"]
            saida.append(f"{s.csv}: {len(concluidas)} de {s.esperadas} concluídas, {len(linhas)} linhas"
                         + (f", {cabecalhos} cabeçalho(s) repetido(s)" if cabecalhos else ""))
            if repetidas:
                saida.append(f"   chaves repetidas sem causa de refação: {len(repetidas)}")
            if passo.nome == "parte2":
                esperadas = {(i.cliente, i.valor, str(i.rep), i.modelo) for i in ordem.ordem_parte2(ordem.REPS_PARTE2)}
                faltam = sorted(esperadas - set(concluidas))
                estranhas = sorted(set(por_chave) - esperadas)
                saida.append(f"   faltam {len(faltam)} das {len(esperadas)} chaves esperadas"
                             + (f"; {len(estranhas)} chave(s) que não são da ordem sorteada" if estranhas else ""))
                for k in faltam:
                    if k in por_chave:
                        ultimo = (por_chave[k][-1].get("falha_instrumento") or "sem ferramenta na fase A")[:100]
                        saida.append(f"   pendente com tentativas: {'/'.join(k)}: {len(por_chave[k])} linha(s); última: {ultimo}")
                for k in sorted(k for k, rs in por_chave.items() if all(r.get("nao_usou_ferramenta") == "sim" for r in rs)):
                    saida.append(f"   nao_usou_ferramenta: {'/'.join(k)}")
    return "\n".join(saida)
