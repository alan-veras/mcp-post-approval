"""O ambiente isolado de cada execução: pasta fora da árvore do usuário, HOME próprio, sem chave real e com a
trava de proxy em 127.0.0.1:9. Também acha o binário de um cliente e a versão dele."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

PREFIXOS_DE_CHAVE = ("ANTHROPIC_", "OPENAI_", "GOOGLE_", "OPENROUTER", "NVIDIA", "CLAUDE_", "CODEX_", "QWEN", "DASHSCOPE",
                     "XDG_", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
SUFIXOS_DE_SEGREDO = ("API_KEY", "APIKEY", "TOKEN", "SECRET", "PASSWORD", "ACCESS_KEY")  # qualquer *_API_KEY, *_TOKEN...


def sem_chaves(env):
    """O ambiente sem variável de chave: pelos prefixos de provedor e por qualquer nome que termine em chave, token ou
    segredo. É o que todo processo filho da coleta (clientes, `--version`, o próprio rodar) recebe."""
    return {k: v for k, v in env.items()
            if not k.upper().startswith(PREFIXOS_DE_CHAVE) and not any(s in k.upper() for s in SUFIXOS_DE_SEGREDO)}
TRAVA = "http://127.0.0.1:9"  # o proxy fechado: o que tentar sair por ele falha e fica no log


def pasta_de_trabalho():
    """Uma pasta nova FORA da árvore do usuário (em /tmp). Os clientes sobem a árvore de
    diretórios atrás de CLAUDE.md, AGENTS.md e do git: dentro do HOME real o Claude
    Code carregaria o ~/.claude/CLAUDE.md real, que é um ancestral do projeto."""
    return Path(tempfile.mkdtemp(prefix="pergunta1-"))


def guarda_evidencia(trabalho, destino):
    """Passa a pasta de trabalho para execucoes/..., onde a evidência fica."""
    destino = Path(destino)
    shutil.rmtree(destino, ignore_errors=True)
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(trabalho), str(destino))


def ambiente(pasta, **extras):
    """O ambiente limpo de um cliente: HOME isolado, sem chave real, com a trava
    de proxy em 127.0.0.1:9 e as chaves falsas que o cliente precisar (extras)."""
    pasta = Path(pasta)
    home = pasta / "home"
    for d in (home, pasta / "projeto"):
        d.mkdir(parents=True, exist_ok=True)
    env = sem_chaves(os.environ)
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env[var] = env[var.lower()] = TRAVA
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local/share"), XDG_CACHE_HOME=str(home / ".cache"),
               XDG_STATE_HOME=str(home / ".local/state"), PWD=str(pasta / "projeto"),
               DO_NOT_TRACK="1")
    env.update(extras)
    return env


def projeto(pasta):
    return Path(pasta) / "projeto"


def home(pasta):
    return Path(pasta) / "home"


def acha_binario(nome):
    return shutil.which(nome)


def versao_de(argv):
    try:
        saida = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                               env={**sem_chaves(os.environ), "HTTPS_PROXY": TRAVA, "HTTP_PROXY": TRAVA}).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "desconhecida"
    m = re.search(r"\d+\.\d+\.\d+\S*", saida)
    return m.group(0) if m else saida.strip()[:40]
