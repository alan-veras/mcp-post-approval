"""O processo da coleta: o laço da fila, o início em segundo plano e as ações da linha de comando."""

import os
import signal
import subprocess
import sys
import time

from instrumento import config
from instrumento.coleta.diario import LOG, PASTA, PID, agora, anota, estado, grava_estado, pid_vivo
from instrumento.coleta.fila import CODIGO_PARADA_INSTRUMENTO, FILA
from instrumento.coleta.progresso import progresso, retrato
from instrumento.coleta.verificacao import ambiente_da_coleta, problemas, versoes_atuais


def trabalha():
    """O laço da fila (roda no processo destacado, ou no terminal com --primeiro-plano)."""
    PID.write_text(str(os.getpid()))
    e = estado()
    e["historico"].append({"inicio": agora(), "versoes": versoes_atuais()})
    grava_estado(e)
    try:
        for passo in FILA:
            nome, argv = passo.nome, passo.argv
            if nome in e["concluidos"]:
                continue
            if config.PAUSA.exists():
                anota("PAUSADO-pedido antes do passo " + nome)
                return config.CODIGO_PAUSA_PEDIDA
            precisa = any(p.gasta_api and p.nome not in e["concluidos"] for p in FILA)
            erros = problemas(precisa)
            if erros:
                anota("PARADO: " + " | ".join(erros))
                return 2
            anota(f"passo {nome}: python3 experimento.py {' '.join(argv)}")
            with open(LOG, "a", encoding="utf-8") as f:
                cod = subprocess.run([sys.executable, str(config.EXPERIMENTO)] + argv, cwd=config.RAIZ,
                                     env=ambiente_da_coleta(), stdout=f, stderr=subprocess.STDOUT).returncode
            if cod == config.CODIGO_PAUSA_PEDIDA:
                anota(f"PAUSADO-pedido no passo {nome}; retome com: python3 experimento.py coleta retomar")
                return cod
            if cod == CODIGO_PARADA_INSTRUMENTO:
                anota(f"PARADO por problema de instrumento no passo {nome} (ver o fim do log); a decisão vira emenda "
                      "em EMENDAS.md antes de retomar")
                return cod
            faltam = [p for p in progresso() if p[0] == nome and p[1] < p[2]]
            if cod not in (0, 1) or faltam:
                anota(f"PARADO no passo {nome}: código {cod}; faltam {[(p[0], p[2] - p[1]) for p in faltam]}")
                return 2
            e = estado()
            e["concluidos"][nome] = {"fim": agora(), "codigo": cod}
            grava_estado(e)
            anota(f"passo {nome} concluído (código {cod}: {'com' if cod else 'sem'} falha de instrumento registrada)")
        anota("COLETA CONCLUÍDA: todos os passos da fila. Próximo: experimento.py analise")
        return 0
    finally:
        PID.unlink(missing_ok=True)


def inicia(primeiro_plano):
    if pid_vivo():
        sys.exit(f"coleta: já está rodando (pid {pid_vivo()}); use: python3 experimento.py coleta monitor")
    if config.PAUSA.exists():
        sys.exit("coleta: existe PAUSAR; para continuar use: python3 experimento.py coleta retomar")
    e = estado()
    precisa = any(p.gasta_api and p.nome not in e["concluidos"] for p in FILA)
    erros = problemas(precisa)
    if erros:
        sys.exit("coleta recusada:\n- " + "\n- ".join(erros))
    if primeiro_plano:
        return trabalha()
    PASTA.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        p = subprocess.Popen([sys.executable, str(config.EXPERIMENTO), "coleta", "_trabalhar"], cwd=config.RAIZ,
                             env=ambiente_da_coleta(), stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True)
    print(f"coleta: rodando em segundo plano (pid {p.pid}); fecha o terminal à vontade.\n"
          f"  acompanhar: python3 experimento.py coleta monitor\n"
          f"  pausar:     python3 experimento.py coleta pausar\n"
          f"  log:        {LOG}")
    return 0


def principal(acao, primeiro_plano=False, intervalo=10):
    if acao == "_trabalhar":
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        return trabalha()
    if acao == "iniciar":
        return inicia(primeiro_plano)
    if acao == "pausar":
        config.PAUSA.touch()
        print("coleta: PAUSAR criado. A execução em curso termina (até alguns minutos) e a coleta para, sem perder nada.\n"
              "  retomar: python3 experimento.py coleta retomar")
        return 0
    if acao == "retomar":
        config.PAUSA.unlink(missing_ok=True)
        return inicia(primeiro_plano)
    if acao == "status":
        print(retrato())
        return 0
    try:
        while True:
            print("\033[2J\033[H" + retrato() + f"\n\n(atualiza a cada {intervalo} s; Ctrl+C sai do monitor, a coleta segue)",
                  flush=True)
            time.sleep(intervalo)
    except KeyboardInterrupt:
        return 0
