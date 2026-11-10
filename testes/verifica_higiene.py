"""Autoteste da higiene das cargas: nenhum caractere invisível ou confundível fora de cargas.py.

O byte U+200B do nome do gêmeo e os caracteres das técnicas de ocultação moram só em
`instrumento/dominio/cargas.py`, que o manifesto sela. Em texto corrido (plano,
README, relatórios), o caractere vai sempre como notação ("U+200B"): um caractere
invisível que escapasse para um documento poderia ser copiado pelo leitor sem ver.
"""

from instrumento.dominio import desfechos
from testes.base import AQUI, protegido, ver

SUFIXOS = (".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".sh", ".cfg", ".ini", ".csv", ".gitignore", "")
PASTAS_FORA = {".git", "__pycache__", "saida-local", "resultados", "node_modules", ".npm", ".cache", "execucoes"}
PERMITIDOS = {"instrumento/dominio/cargas.py"}  # onde os bytes das cargas moram, selados pelo manifesto


@protegido
def verifica_higiene():
    sujos = []
    for p in sorted(AQUI.rglob("*")):
        rel = p.relative_to(AQUI)
        if not p.is_file() or str(rel) in PERMITIDOS or any(x in rel.parts for x in PASTAS_FORA) \
                or p.suffix not in SUFIXOS:
            continue
        try:
            texto = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        fams = {k: v for k, v in desfechos.classes(texto).items() if k != "len" and v}
        if fams:
            sujos.append(f"{rel}: {fams}")
    ver("higiene: nenhum caractere invisível ou confundível fora de cargas.py", not sujos, "; ".join(sujos))
    ver("higiene: cargas.py está na allowlist e é o único lugar dos bytes",
        "instrumento/dominio/cargas.py" in PERMITIDOS and len(PERMITIDOS) == 1)
