"""Autoteste das regras da casa: só biblioteca padrão, sem em dash, pastas no lugar."""

import ast
import sys

from instrumento import config
from testes.base import AQUI, INSTRUMENTO, TRAVESSAO, protegido, ver


@protegido
def verifica_regras():
    codigo = [AQUI / "experimento.py", *INSTRUMENTO.rglob("*.py"), *(AQUI / "testes").glob("*.py")]
    locais = {"instrumento", "testes", "experimento"}
    for p in sorted(codigo):
        arvore = ast.parse(p.read_text(encoding="utf-8"))
        mods = set()
        for n in ast.walk(arvore):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.level == 0:
                mods.add((n.module or "").split(".")[0])
        fora = sorted(m for m in mods if m not in sys.stdlib_module_names and m not in locais)
        ver(f"regras: {p.relative_to(AQUI)} importa só biblioteca padrão e arquivos desta pasta", not fora, f"fora: {fora}")
    com_travessao = []
    for p in AQUI.rglob("*"):
        if p.is_file() and "execucoes" not in p.relative_to(AQUI).parts and p.suffix in (".py", ".md", ".csv", ".gitignore", ".ots", ""):
            try:
                if TRAVESSAO in p.read_text(encoding="utf-8"):
                    com_travessao.append(str(p.relative_to(AQUI)))
            except (UnicodeDecodeError, OSError):
                pass
    ver("regras: nenhum arquivo tem o travessão longo", not com_travessao, str(com_travessao))
    ign = {l.strip() for l in (AQUI / ".gitignore").read_text(encoding="utf-8").splitlines()
           if l.strip() and not l.strip().startswith("#")}
    ver("regras: saida-local/ fora do git e resultados/ e PLANO.md dentro (repo público, 6/nov/2026)",
        "saida-local/" in ign and "resultados/" not in ign and "PLANO.md" not in ign)
    soltos = sorted(p.name for p in AQUI.iterdir()
                    if p.is_file() and p.name not in ("experimento.py", ".gitignore", ".env", "LICENSE", "LICENSE-DATA", "TRAVA-COLETA", "PAUSAR") and p.suffix != ".md")
    ver("regras: na raiz só ficam experimento.py e textos de leitura (o resto mora nas pastas)", not soltos, str(soltos))
    ver("regras: o ensaio grava em saida-local/, nunca em resultados/",
        config.SAIDA_LOCAL != config.RESULTADOS and "saida-local/" in ign)
