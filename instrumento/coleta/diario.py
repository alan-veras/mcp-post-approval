"""O estado da coleta em disco: passos concluídos, o pid do processo e o log."""

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
    PASTA.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")


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
