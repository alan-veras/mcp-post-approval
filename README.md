# mcp-post-approval

What do MCP clients do after an approved server changes? A descriptive study with three clients (Claude Code 2.1.321,
Qwen Code 0.26.0 and Codex CLI 0.155.1), by Alan Veras (UFC Russas, Brazil; advisor: Rafael Tupynambá Dutra).

*Português: [README.pt.md](README.pt.md). The pre-registration (`PRE-REGISTRO.md`) and the amendments log
(`EMENDAS.md`) are written in Portuguese; the Portuguese text is the one that was sealed and timestamped.*

This repository holds the instrument, the tests, the pre-registration, the date seal and, after data collection, every
result and the evidence of each run.

## What was pre-registered, and when

- `PRE-REGISTRO.md`: hypotheses, design, outcomes, exclusions and stopping rules, written before any data.
- `selo/`: proof that the text and the code existed before data collection.
  - `COMMIT.txt`: the commit of the timestamped code.
  - `MANIFEST.sha256`: the SHA-256 of every tracked file (except `selo/`), always checked from the repository root.
  - `*.ots`: OpenTimestamps proofs for `COMMIT.txt`, `MANIFEST.sha256` and `PRE-REGISTRO.md`.
- A Zenodo deposit with the same files (DOI 10.5281/zenodo.24113558, valid once published).

How to check:

```
sha256sum -c selo/MANIFEST.sha256            # from the repo root: no line may fail
git cat-file -t $(cat selo/COMMIT.txt)       # the timestamped commit exists
ots verify selo/MANIFEST.sha256.ots          # the timestamp (needs the OpenTimestamps client)
python3 experimento.py selftest              # the instrument's self-test, no client and no model
```

## The design on one screen

- **Part 1, no API (56 runs):** the model is scripted and local. It measures what the client shows and does when the
  server changes: re-consent (21), delivery of the changed text (12), install through npx and uvx (8) and an invisible
  twin server (15).
- **Part 2, real model (180 runs):** 6 cells × 3 clients × 5 repetitions × 2 models (Mistral Large and Nemotron, through
  the NVIDIA API). It measures whether the model follows an instruction carried by the new definition.
- **Randomized order** with seed 20261109, interleaving clients, cells and models.
- **No judge:** every outcome comes from mechanical rules over what the server, the endpoint and the disk recorded.

## Where things are

| Folder or file | What it is |
|---|---|
| `instrumento/` | the collection and analysis code |
| `testes/` | the self-test (`experimento.py selftest`) |
| `resultados/` | the collection: one CSV per component and `execucoes/`, with the evidence of each run |
| `resultados/LEIA-ME-EXECUCOES.md` | one section per run, with the fields, the model text and links to the screens |
| `publicacao/` | the scripts that build the summary and prepare the evidence (added after the seal, see `EMENDAS.md`) |
| `EMENDAS.md` | every change after the timestamp, dated (Portuguese) |

Each `execucoes/.../<run>/` folder has: `tela-A.txt` and `tela-B.txt` (what the client showed in the two phases),
`historico-*.txt` (the full screen history), `repasses.json` (Part 2: what went to the model and what came back),
`registro-servidor.jsonl` (every MCP message exchanged), `faseA/` and `faseB/` (every request that reached the endpoint)
and `linha.json` (the CSV row). The `evidencia` column of the CSVs points to that folder.

## What was altered in the evidence before publishing

In the CSVs and the other text files, only the author's computer path was replaced by `~` and the machine name by
`maquina-do-autor` (byte-level replacement, leaving line endings, quotes and columns untouched). In the evidence folders,
`publicacao/prepara_evidencia.py` removed cache and unused files from the clients' `home/` folders (internal databases,
images, skills) and made the same replacements. A raw copy was kept outside the repository.

## Failures and re-runs

A re-run appears in more than one CSV row (Part 2: column `tentativa`; Part 1: the evidence of the earlier attempt stays
in the folder `<folder>-t<n>`); nothing is deleted. A folder `<folder>-orfa<n>` is the evidence of a run that was
interrupted after it was saved and before its CSV row was written: its result was lost, its evidence was kept. The
exclusion rules, the infrastructure re-run rules (provider, network) and the stopping rules are in `PRE-REGISTRO.md`,
section 7 (Portuguese).

## License

Code: MIT (`LICENSE`). Data in `resultados/` and this README: CC BY 4.0 (`LICENSE-DATA`).
