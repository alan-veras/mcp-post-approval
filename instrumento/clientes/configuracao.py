"""Os arquivos de configuração que o cliente lê: o servidor MCP a registrar e a escrita sem perder o que já existe."""
import json
from dataclasses import dataclass
from pathlib import Path

NOME_SERVIDOR = "servidor-teste"
# na fase B da servidor_renomeado (controle positivo) o servidor ganha outro nome; a entrada com o nome antigo sai do arquivo
NOME_SERVIDOR_RENOMEADO = "servidor-teste-b"


@dataclass(frozen=True)
class ServidorMCP:
    """O servidor MCP que o cliente registra: a linha de comando e o nome na configuração."""
    comando: list
    nome: str = NOME_SERVIDOR


def so_o_servidor_atual(caminho, nome_atual, *chaves):
    """Tira do JSON as entradas servidor-teste* que não são o servidor atual (`nome_atual`), sob
    as chaves dadas: renomear é trocar a entrada, não acrescentar uma segunda."""
    caminho = Path(caminho)
    if not caminho.exists():
        return
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except ValueError:
        return
    alvo = dados
    for k in chaves:
        alvo = alvo.get(k) if isinstance(alvo, dict) else None
    if isinstance(alvo, dict):
        for nome in [n for n in alvo if n.startswith("servidor-teste") and n != nome_atual]:
            del alvo[nome]
        caminho.write_text(json.dumps(dados, indent=1), encoding="utf-8")


def escreve(caminho, texto):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")


def mescla_json(caminho, novo):
    """Atualiza só as chaves de `novo` (mescla funda), preservando o resto: a
    aprovação da fase A mora nos mesmos arquivos que a fase B reescreve."""
    caminho = Path(caminho)
    atual = {}
    if caminho.exists():
        try:
            atual = json.loads(caminho.read_text(encoding="utf-8"))
        except ValueError:
            atual = {}

    def junta(a, b):
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                junta(a[k], v)
            else:
                a[k] = v
    junta(atual, novo)
    escreve(caminho, json.dumps(atual, indent=1, ensure_ascii=False))
