"""O estado da coleta em disco: passos concluídos, o pid do processo e o log."""

import fcntl
import json
import os
from datetime import datetime

from instrumento import config


AQUI = config.RESULTADOS


PASTA = AQUI / "coleta"


LOG = PASTA / "coleta.log"


PID = PASTA / "coleta.pid"


ESTADO = PASTA / "estado.json"


def estado():
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"concluidos": {}, "historico": []}


def grava_estado(e):
    """Atômico: grava num temporário, fsync e renomeia; um kill -9 no meio nunca deixa estado.json cortado."""
    PASTA.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False, indent=1))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ESTADO)


def pega_trava(nome):
    """flock exclusivo e sem espera em coleta/<nome>.lock; devolve o arquivo aberto (guarde-o até o fim do processo) ou
    None se outro processo já o tem. O sistema solta a trava quando o processo morre, mesmo com kill -9."""
    PASTA.mkdir(parents=True, exist_ok=True)
    f = open(PASTA / f"{nome}.lock", "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def pid_vivo():
    try:
        pid = int(PID.read_text())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def anota(texto):
    PASTA.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[coleta {agora()}] {texto}\n")
    print(f"[coleta {agora()}] {texto}", flush=True)
