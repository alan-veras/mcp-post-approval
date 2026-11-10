#!/usr/bin/env python3
"""O único comando do experimento: `python3 experimento.py --help`. A linha de comando mora em instrumento/cli.py."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))  # os pacotes instrumento/ e testes/ moram aqui

from instrumento.cli import principal  # noqa: E402

if __name__ == "__main__":
    sys.exit(principal())
