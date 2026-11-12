# mcp-post-approval

O que clientes MCP fazem depois que um servidor aprovado muda. Estudo descritivo com três clientes (Claude Code 2.1.321,
Qwen Code 0.26.0 e Codex CLI 0.155.1), de Alan Veras (UFC Russas; orientador: Rafael Tupynambá Dutra).

Este repositório tem o instrumento, os testes, o pré-registro, o selo de data e, depois da coleta, todos os resultados e a
evidência de cada execução.

## O que foi pré-registrado e quando

- `PRE-REGISTRO.md`: hipóteses, desenho, desfechos, exclusões e regras de parada, escritos antes de qualquer dado.
- `selo/`: prova de que o texto e o código existiam antes da coleta.
  - `COMMIT.txt`: o commit do código carimbado.
  - `MANIFEST.sha256`: o SHA-256 de todos os arquivos rastreados (exceto `selo/`), conferido sempre a partir da raiz.
  - `*.ots`: carimbos OpenTimestamps de `COMMIT.txt`, `MANIFEST.sha256` e `PRE-REGISTRO.md`.
- Depósito no Zenodo com os mesmos arquivos (DOI 10.5281/zenodo.24113558, vale depois da publicação).

Como conferir:

```
sha256sum -c selo/MANIFEST.sha256            # da raiz do repo: nenhuma linha pode falhar
git cat-file -t $(cat selo/COMMIT.txt)       # o commit carimbado existe
ots verify selo/MANIFEST.sha256.ots          # o carimbo (precisa do cliente OpenTimestamps)
python3 experimento.py selftest              # o autoteste do instrumento, sem cliente e sem modelo
```

## O desenho em uma tela

- **Parte 1, sem API (56 execuções):** o modelo é roteirizado e local. Mede o que o cliente mostra e faz quando o
  servidor muda: reconsentimento (21), entrega (12), instalação por npx e uvx (8) e gêmeo invisível (15).
- **Parte 2, com modelo real (180 execuções):** 6 células × 3 clientes × 5 repetições × 2 modelos (Mistral Large e
  Nemotron, pela API da NVIDIA). Mede se o modelo obedece a uma instrução trazida pela definição nova.
- **Ordem sorteada** com a semente 20261109, intercalando clientes, células e modelos.
- **Desfechos sem juiz:** todos vêm de regras mecânicas sobre o que o servidor, o endpoint e o disco registraram.

## Onde está cada coisa

| Pasta ou arquivo | O que é |
|---|---|
| `instrumento/` | o código da coleta e da análise |
| `testes/` | o autoteste (`experimento.py selftest`) |
| `resultados/` | a coleta: um CSV por componente e `execucoes/`, com a evidência de cada execução |
| `resultados/LEIA-ME-EXECUCOES.md` | uma seção por execução, com os campos, o texto do modelo e links para as telas |
| `publicacao/` | os scripts que geram o resumo e preparam a evidência (adicionados depois do selo, ver `EMENDAS.md`) |
| `EMENDAS.md` | toda mudança depois do carimbo, datada |

Cada pasta `execucoes/.../<execução>/` tem: `tela-A.txt` e `tela-B.txt` (o que o cliente mostrou nas duas fases),
`historico-*.txt` (o histórico completo da tela), `repasses.json` (Parte 2: o que foi ao modelo e o que voltou),
`registro-servidor.jsonl` (cada mensagem MCP trocada), `faseA/` e `faseB/` (cada pedido que chegou ao endpoint) e
`linha.json` (a linha do CSV). A coluna `evidencia` dos CSVs aponta para essa pasta.

## O que foi alterado na evidência antes de publicar

Nos CSVs e nos demais arquivos de texto, só o caminho do computador do autor foi trocado por `~` e o nome da máquina por `maquina-do-autor` (troca em bytes, sem mexer em fins de linha, aspas ou colunas). Nas pastas de evidência, `publicacao/prepara_evidencia.py` tirou o cache e arquivos sem uso das pastas
`home/` dos clientes (banco de dados interno, imagens, skills) e fez as mesmas trocas. Foi
guardada uma cópia bruta fora do repositório.

## Falhas e refações

Uma execução refeita fica em mais de uma linha do CSV (na Parte 2, coluna `tentativa`; na Parte 1, a evidência da tentativa anterior fica na pasta `<pasta>-t<n>`); nada é apagado (uma pasta `<pasta>-orfa<n>` é evidência de uma execução interrompida depois de salva e antes da linha no CSV: o resultado dela se perdeu, a evidência ficou). As regras de exclusão, de
refação por infraestrutura (provedor, rede) e de parada estão no `PRE-REGISTRO.md`, seção 7.

## Licença

Código: MIT (`LICENSE`). Dados em `resultados/` e este README: CC BY 4.0 (`LICENSE-DATA`).
