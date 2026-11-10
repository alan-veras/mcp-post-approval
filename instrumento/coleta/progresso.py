"""O progresso de cada passo, lido dos CSVs, e o retrato que o status e o monitor mostram."""

import csv

from instrumento import config
from instrumento.coleta.diario import AQUI, LOG, agora, estado, pid_vivo
from instrumento.coleta.fila import FILA


def le(nome):
    f = AQUI / nome
    if not f.exists():
        return []
    with open(f, newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def unicas(linhas, campos, ignora_pausa=False):
    """Execuções distintas concluídas. Com `ignora_pausa` (Parte 2), a chave só entra se alguma linha não é pausa do
    provedor, ou se o provedor falhou em todas as 1 + 3 tentativas (a falha fica registrada e a coleta segue)."""
    vistas, pausas = set(), {}
    for r in linhas:
        chave = tuple(r.get(c, "") for c in campos)
        if ignora_pausa and (r.get("falha_instrumento") or "").startswith("provedor:"):
            pausas[chave] = pausas.get(chave, 0) + 1
            if pausas[chave] >= 4:
                vistas.add(chave)
            continue
        vistas.add(chave)
    return len(vistas)


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
        situacao = "PARADA (veja o fim do log; retome com: python3 experimento.py coleta iniciar)"
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
