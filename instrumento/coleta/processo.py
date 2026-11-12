"""O processo da coleta: o laço da fila, o início em segundo plano e as ações da linha de comando."""

import hashlib
import os
import signal
import subprocess
import sys
import time

from instrumento import config
from instrumento.coleta.diario import LOG, PASTA, PID, agora, anota, estado, grava_estado, pega_trava, pid_vivo
from instrumento.coleta.fila import CODIGO_PARADA_INSTRUMENTO, CODIGO_PARADA_PROVEDOR, FILA
from instrumento.coleta.progresso import progresso, retrato
from instrumento.coleta.verificacao import ambiente_da_coleta, problemas, versoes_atuais


def sha_emendas():
    f = config.RAIZ / "EMENDAS.md"
    return hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else ""


def confere_emendas():
    """Depois de uma parada que exige decisão (instrumento ou provedor além do tecto), nada recomeça sem EMENDAS.md diferente."""
    parada = estado().get("parada_decisao")
    if parada and parada.get("emendas_sha256") == sha_emendas():
        sys.exit("coleta: parou em " + parada.get("quando", "?") + " (" + parada.get("motivo", "?") + ") e o EMENDAS.md não mudou "
                 "desde então. Registre a decisão em EMENDAS.md e commite antes de retomar.")


def grava_parada(nome, motivo):
    e = estado()
    e["parada_decisao"] = {"quando": agora(), "passo": nome, "motivo": motivo, "emendas_sha256": sha_emendas()}
    grava_estado(e)


def trabalha():
    """O laço da fila (roda no processo destacado, ou no terminal com --primeiro-plano)."""
    trava = pega_trava("coleta")  # fica aberta até o fim do processo
    if trava is None:
        anota("RECUSADO: já existe uma coleta em curso (trava coleta/coleta.lock)")
        return 7
    PASTA.mkdir(parents=True, exist_ok=True)
    PID.write_text(str(os.getpid()))
    e = estado()
    e.pop("parada_decisao", None)  # chegou aqui: a emenda foi conferida em inicia()
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
            # um `rodar` órfão (a coleta anterior morreu com kill -9 e o filho seguiu) segura rodar.lock: espera ele acabar
            while True:
                orfao = pega_trava("rodar")
                if orfao:
                    orfao.close()
                    break
                if config.PAUSA.exists():
                    anota("PAUSADO-pedido enquanto esperava o rodar anterior")
                    return config.CODIGO_PAUSA_PEDIDA
                anota("esperando um rodar anterior (órfão) terminar; ele segue a fila e pausa com PAUSAR")
                time.sleep(30)
            anota(f"passo {nome}: python3 experimento.py {' '.join(argv)}")
            with open(LOG, "a", encoding="utf-8") as f:
                cod = subprocess.run([sys.executable, str(config.EXPERIMENTO)] + argv, cwd=config.RAIZ,
                                     env=ambiente_da_coleta(), stdout=f, stderr=subprocess.STDOUT).returncode
            if cod == 7:
                anota(f"RECUSADO no passo {nome}: outro rodar está gravando; nada foi feito")
                return cod
            if cod == config.CODIGO_PAUSA_PEDIDA:
                anota(f"PAUSADO-pedido no passo {nome}; retome com: python3 experimento.py coleta retomar")
                return cod
            if cod == CODIGO_PARADA_INSTRUMENTO:
                grava_parada(nome, "instrumento")
                anota(f"PARADO por problema de instrumento no passo {nome} (ver o fim do log); a decisão vira emenda "
                      "em EMENDAS.md antes de retomar")
                return cod
            if cod == CODIGO_PARADA_PROVEDOR:
                grava_parada(nome, "provedor")
                anota(f"PARADO no passo {nome}: provedor ou rede indisponível além do tecto (ou erro permanente do provedor); "
                      "nenhuma execução foi pulada. Veja o fim do log; para continuar do mesmo ponto: "
                      "python3 experimento.py coleta retomar")
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
    confere_emendas()
    trava = pega_trava("coleta")
    if trava is None or pid_vivo():
        sys.exit(f"coleta: já está rodando (pid {pid_vivo() or '?'}); use: python3 experimento.py coleta monitor")
    trava.close()   # só a checagem rápida; a trava de verdade é a do trabalha()
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
    if acao == "verificar":
        from instrumento.coleta.progresso import verifica
        print(verifica())
        return 0
    try:
        while True:
            print("\033[2J\033[H" + retrato() + f"\n\n(atualiza a cada {intervalo} s; Ctrl+C sai do monitor, a coleta segue)",
                  flush=True)
            time.sleep(intervalo)
    except KeyboardInterrupt:
        return 0
