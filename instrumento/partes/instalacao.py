"""A parte "instalação": a atualização chega pelo npx e pelo uvx.

Nas outras partes a versão B do servidor é trocada por um arquivo de estado. Aqui a troca chega como na vida real: o
cliente guarda `npx -y servidor-teste-mcp` ou `uvx servidor-teste-mcp`, sem versão fixa, e a 1.0.1 sobe quando o
gerenciador a busca. Entre as fases só se publica a 1.0.1 no registro local; nem a configuração do cliente nem
nenhum arquivo de estado mudam.

Duas coisas aqui: `roda_uma` (cliente, canal), que reaproveita `reconsentimento.roda_fase`, e `sonda`, que
mede o mecanismo sozinho, sem cliente. Observações próprias: buscou, baixou e a versão que rodou (`versao_instalada`); ver registro.py.
"""
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from instrumento import clientes
from instrumento.analise import csvs
from instrumento.clientes import isolamento
from instrumento.clientes.configuracao import escreve
from instrumento.dominio import cargas, desfechos
from instrumento.partes import comum, reconsentimento
from instrumento.simulacao import registro
from instrumento.simulacao.endpoint import servidor_http

CANAIS = {"npx": ["npx", "-y", registro.PACOTE], "uvx": ["uvx", registro.PACOTE]}  # sem versão fixa
CELULA = cargas.CELULA_DO_CODIGO  # a confirmação usa a célula em que só o código muda
CABECALHOS = "sem-cache"  # a confirmação com cliente revalida sempre (como na rodada 1); a sonda usa os cabeçalhos reais
CAMPOS = ["cliente", "versao", "sha256_binario", "canal", "cabecalhos", "celula", "rep", "pediu_fase_a", "opcao_aprovada",
          "versao_instalada", "modelo_pediu", "rodou_sem_aviso", "pediu_aprovacao", "bloqueado_sem_explicacao",
          "chegou_intacta", "duracao_s", "rede_bloqueada", "falha_instrumento", "evidencia"]
CHAVE = ("cliente", "canal", "cabecalhos", "celula", "rep")
CAMPOS_SONDA = ["canal", "cabecalhos", "passo", "publicada", "buscou", "baixou", "versao_rodou", "saida_codigo",
                "requisicoes", "rede_externa", "duracao_s", "falha_instrumento", "erro", "evidencia"]
CABECALHOS_DA_SONDA = ["real"]
ESPERA_SONDA = 60  # o passo "depois de 1 minuto"
LIMITE_SONDA = 120  # segundos por passo da sonda
EXTERNOS = re.compile(r"https?://(?!127\.0\.0\.1[:/])([\w.-]+)")
HOSTS_REAIS = ("registry.npmjs.org", "pypi.org", "files.pythonhosted.org")
# os passos da sonda e o que se faz antes de cada um
PASSOS_DA_SONDA = [("1-publicada-1.0.0", None), ("1b-repete-sem-publicar", None), ("2-publicada-1.0.1", "publica"),
                   ("3-depois-de-espera", "espera"), ("4-sem-cache", "apaga")]


# ---- ambiente do gerenciador ------------------------------------------------------------------------

def prepara_gerenciador(pasta, reg, depuracao=False):
    """Aponta o npm e o uv para o registro local. Devolve as variáveis de ambiente (os `extras` do ambiente) e também
    escreve ~/.npmrc e ~/.config/uv/uv.toml no HOME isolado, porque alguns clientes repassam ao servidor só um ambiente
    mínimo e o gerenciador ainda acharia o registro pelo HOME. O cache fica em $HOME/.npm e em $XDG_CACHE_HOME/uv, os
    mesmos nas duas fases, como na máquina de um usuário."""
    home = isolamento.home(pasta)
    escreve(home / ".npmrc", f"registry={reg.url_npm}\nupdate-notifier=false\nfund=false\naudit=false\n")
    escreve(home / ".config" / "uv" / "uv.toml", 'python-downloads = "never"\npython-preference = "only-system"\n'
            f'\n[[index]]\nurl = "{reg.url_simple}"\ndefault = true\n')
    python = shutil.which("python3") or "python3"
    extras = {"npm_config_registry": reg.url_npm, "npm_config_update_notifier": "false", "npm_config_fund": "false",
              "npm_config_audit": "false", "UV_DEFAULT_INDEX": reg.url_simple, "UV_PYTHON_DOWNLOADS": "never",
              "UV_PYTHON": python}
    if depuracao:
        extras.update(npm_config_loglevel="http", RUST_LOG="uv=debug")
    return extras


def comando_canal(canal, celula, pasta):
    """A linha de comando que o cliente guarda: a mesma nas duas fases."""
    return CANAIS[canal] + ["--celula", celula, "--registro", str(Path(pasta) / "registro-servidor.jsonl")]


def hosts_externos(texto):
    """Os nomes de máquina que não são 127.0.0.1 citados em URLs do texto (registry.npmjs.org, pypi.org...)."""
    return sorted(set(EXTERNOS.findall(texto)))


def tentou_rede_externa(pasta, historicos):
    """Hosts externos nos logs do npm (HOME/.npm/_logs) e no histórico das telas."""
    textos = list(historicos)
    for f in (isolamento.home(pasta) / ".npm" / "_logs").glob("*.log"):
        textos.append(f.read_text(encoding="utf-8", errors="replace"))
    achados = hosts_externos("\n".join(textos))
    for h in HOSTS_REAIS:
        if any(h in t for t in historicos) and h not in achados:
            achados.append(h)
    return sorted(achados)


# ---- uma execução (cliente, canal, célula) --------------------------------------------------------------

def intacta_da_instalacao(versao, b):
    """Se a 1.0.1 não rodou, a definição B nunca foi anunciada: `chegou_intacta` não se aplica (vazio), para não misturar
    "a atualização não chegou" com "o cliente mexeu no texto". O que mede a atualização é `versao_instalada`."""
    if versao != "1.0.1":
        return ""
    return desfechos.chegou_intacta(cargas.textos_enviados(cargas.ferramenta_teste(CELULA, "B")), b["pedidos"])


def roda_uma(aqui, modo, rotulo, canal, rep, pasta_raiz=None, cabecalhos=CABECALHOS):
    """Uma execução (cliente, canal, repetição). Devolve a linha do CSV."""
    celula = CELULA
    modulo = clientes.cliente(rotulo)
    destino = (Path(pasta_raiz or aqui) / "execucoes" / modo / "instalacao" / rotulo / f"{canal}-{cabecalhos}"
               / comum.nome_da_execucao(celula, rep))
    pasta = isolamento.pasta_de_trabalho()
    linha = comum.nova_linha(CAMPOS, modulo, rotulo, canal=canal, cabecalhos=cabecalhos, celula=celula, rep=rep,
                             evidencia=comum.relativo(destino, aqui))
    inicio, falhas = time.time(), []
    reg = registro.Registro(pasta / "registro", cabecalhos).inicia()
    ep = servidor_http.Endpoint(pasta / "faseA", "roteirizado").inicia()
    try:
        extras = prepara_gerenciador(pasta, reg)
        comando = comando_canal(canal, celula, pasta)
        reg.fase("A")
        a = reconsentimento.roda_fase(modulo, ep, pasta, celula, "A", reconsentimento.LIMITE_FASE_A,
                                      comando=comando, extras=extras)
        comum.registra_fase_a(linha, a, falhas)
        if registro.versao_rodou(a["registro"]) != "1.0.0":
            falhas.append("A:pacote-nao-rodou-1.0.0")
        if not comum.recebeu_tools_call(a["registro"]):
            falhas.append("A:servidor-nao-recebeu-tools/call")
        reg.publica("1.0.1")  # a única mudança entre as fases: a 1.0.1 passa a existir no registro
        reg.fase("B")
        b = reconsentimento.roda_fase(modulo, ep, pasta, celula, "B", reconsentimento.LIMITE_FASE_B,
                                      comando=comando, extras=extras)
        linha["rede_bloqueada"] = comum.rede_bloqueada(a["historico"], b["historico"])
        if b["falha"]:
            falhas.append("B:" + b["falha"])
        linha["versao_instalada"] = registro.versao_rodou(b["registro"])
        falha_modelo = comum.registra_desfechos_cliente(linha, b)
        if falha_modelo:
            falhas.append(falha_modelo)
        linha["chegou_intacta"] = intacta_da_instalacao(linha["versao_instalada"], b)
        externos = tentou_rede_externa(pasta, [a["historico"], b["historico"]])
        if externos:
            falhas.append("rede-externa:" + ",".join(externos))
    except Exception as erro:
        falhas.append(comum.descreve_excecao(erro))
    finally:
        ep.para()
        reg.para()
    return comum.fecha_execucao(linha, falhas, inicio, pasta, destino)


# ---- a sonda sem cliente -------------------------------------------------------------------------------

def versao_na_saida(saida):
    """A versão que o servidor declarou no `initialize`, lida da saída padrão do gerenciador."""
    versao = ""
    for l in saida.splitlines():
        try:
            versao = (json.loads(l).get("result") or {}).get("serverInfo", {}).get("version") or versao
        except ValueError:
            pass
    return versao


def roda_gerenciador(canal, celula, pasta, env, reg, passo):
    """Roda o comando do canal com um initialize e um tools/list. Devolve a linha do passo."""
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    reg.fase(passo)
    inicio = time.time()
    falhas, erro = [], ""
    try:
        r = subprocess.run(comando_canal(canal, celula, pasta), input="\n".join(json.dumps(m) for m in msgs) + "\n",
                           capture_output=True, text=True, env=env, cwd=str(isolamento.projeto(pasta)),
                           timeout=LIMITE_SONDA)
        codigo, saida, erro = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        codigo, saida = "timeout", ""
        falhas.append(f"gerenciador-estourou-{LIMITE_SONDA}s")
    requisicoes = registro.le_requisicoes(reg.log)
    servidor = [l for l in comum.le_registro(Path(pasta) / "registro-servidor.jsonl") if l["t"] >= inicio]
    baixadas = sorted({r["versao_servida"] for r in requisicoes if r["fase"] == passo and r.get("tipo") in ("tarball", "wheel")
                       and r.get("status") == 200})
    versao_stdout = versao_na_saida(saida)
    rodou = registro.versao_rodou(servidor)
    if (versao_stdout or "nenhuma") != rodou:
        falhas.append(f"versao-diverge:stdout={versao_stdout or 'nenhuma'},registro={rodou}")
    externos = hosts_externos(erro + saida)
    if externos:
        falhas.append("rede-externa:" + ",".join(externos))
    return {"passo": passo, "publicada": reg.ultima(), "buscou": registro.buscou_registro(requisicoes, passo),
            "baixou": "+".join(baixadas) or "nao", "versao_rodou": rodou, "saida_codigo": codigo,
            "requisicoes": " ".join(f"{r['metodo']} {r['tipo']} {r['status']}" for r in requisicoes if r["fase"] == passo),
            "rede_externa": ",".join(externos), "duracao_s": round(time.time() - inicio, 1),
            "falha_instrumento": "; ".join(falhas), "erro": re.sub(r"\s+", " ", erro.strip())[-300:]}


def prepara_passo(antes, reg, pasta, espera):
    if antes == "publica":
        reg.publica("1.0.1")
    elif antes == "espera":
        time.sleep(espera)
    elif antes == "apaga":
        for d in (isolamento.home(pasta) / ".npm", isolamento.home(pasta) / ".cache"):
            shutil.rmtree(d, ignore_errors=True)


def sonda_canal(aqui, modo, canal, cabecalhos, celula=CELULA, espera=ESPERA_SONDA, pasta_raiz=None):
    """Os cinco passos de um canal, com HOME isolado e registro novo:
    1. publica a 1.0.0 e roda; 1b. roda de novo sem publicar nada (controle);
    2. publica a 1.0.1 e roda; 3. roda de novo depois de `espera` s;
    4. apaga o cache e roda. Devolve as linhas do CSV da sonda."""
    destino = Path(pasta_raiz or aqui) / "execucoes" / modo / "instalacao-sonda" / f"{canal}-{cabecalhos}"
    pasta = isolamento.pasta_de_trabalho()
    reg = registro.Registro(pasta / "registro", cabecalhos).inicia()
    linhas = []
    try:
        env = isolamento.ambiente(pasta, **prepara_gerenciador(pasta, reg, depuracao=True))
        for passo, antes in PASSOS_DA_SONDA:
            prepara_passo(antes, reg, pasta, espera)
            linha = roda_gerenciador(canal, celula, pasta, env, reg, passo)
            linha.update(canal=canal, cabecalhos=cabecalhos, evidencia=comum.relativo(destino, aqui))
            linhas.append(linha)
    finally:
        reg.para()
    isolamento.guarda_evidencia(pasta, destino)
    return linhas


def descreve_sonda(linha):
    return (f"sonda   {linha['canal']:6} {linha['cabecalhos']:9} {linha['passo']:24} buscou={linha['buscou']} "
            f"baixou={linha['baixou']} rodou={linha['versao_rodou']} {linha['falha_instrumento']}")


def sonda(aqui, modo, canais=None, espera=ESPERA_SONDA):
    """A sonda nos canais, nos dois perfis de cabeçalho de cache, em paralelo (cada um com HOME e registro próprios).
    Grava instalacao-sonda-<modo>.csv. Devolve o número de falhas."""
    csv_sonda = Path(aqui) / f"instalacao-sonda-{modo}.csv"
    feitos = {(r["canal"], r["cabecalhos"]) for r in csvs.le_csv(csv_sonda) if r["passo"].startswith("4")}
    pendentes = [(c, h) for c in (canais or list(CANAIS)) for h in CABECALHOS_DA_SONDA if (c, h) not in feitos]
    resultados, erros = {}, {}

    def trabalho(canal, cabecalhos):
        try:
            resultados[(canal, cabecalhos)] = sonda_canal(aqui, modo, canal, cabecalhos, espera=espera)
        except Exception as erro:
            erros[(canal, cabecalhos)] = comum.descreve_excecao(erro)

    threads = [threading.Thread(target=trabalho, args=p) for p in pendentes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    falhas = len(erros)
    for chave in pendentes:
        for linha in resultados.get(chave, []):
            csvs.grava_linha(csv_sonda, CAMPOS_SONDA, linha)
            falhas += bool(linha["falha_instrumento"])
            print(descreve_sonda(linha), flush=True)
    for chave, texto in erros.items():
        print(f"sonda   {chave}: {texto}", flush=True)
    return falhas


# ---- a linha de uma execução ----------------------------------------------------------------------------

def descreve(linha):
    return (f"instal  {linha['cliente']:4} {linha['canal']:6} rep{linha['rep']} versao={linha['versao_instalada']} "
            f"sem_aviso={linha['rodou_sem_aviso']} pediu={linha['pediu_aprovacao']} "
            f"intacta={linha['chegou_intacta']} {linha['falha_instrumento']}")
