"""A sessão interativa por pty: abrir, ler a tela sem códigos de escape, mandar
tecla, esperar texto.

Só biblioteca padrão. Inclui um emulador de tela mínimo (cursor, apagar, rolar)
para que `tela()` devolva o que um humano veria, e responde às perguntas que
os clientes de terminal fazem ao emulador (posição do cursor, atributos).
"""
import codecs
import fcntl
import os
import re
import select
import signal
import struct
import subprocess
import termios
import time

TECLAS = {"enter": "\r", "esc": "\x1b", "cima": "\x1b[A", "baixo": "\x1b[B", "direita": "\x1b[C",
          "esquerda": "\x1b[D", "tab": "\t", "espaco": " ", "ctrl-c": "\x03", "ctrl-d": "\x04",
          "backspace": "\x7f"}

ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]|\x1b[@-Z\\-_=>78]")


def sem_escapes(texto):
    """O texto sem códigos de escape; avanço de cursor vira espaço e salto de linha vira quebra."""
    texto = re.sub(r"\x1b\[(\d*)C", lambda m: " " * int(m.group(1) or 1), texto)
    texto = re.sub(r"\x1b\[\d*(?:;\d*)?[HBEd]", "\n", texto)
    return ESCAPES.sub("", texto).replace("\r", "")


class Tela:
    """Emulador mínimo: o suficiente para ler uma interface de linha de comando."""

    def __init__(self, linhas=50, colunas=160):
        self.n, self.m = linhas, colunas
        self.grade = [[" "] * colunas for _ in range(linhas)]
        self.y = self.x = 0
        self.topo, self.base = 0, linhas - 1
        self.salvo = (0, 0)
        self.resto = ""

    def _rola(self, cima=True):
        if cima:
            del self.grade[self.topo]
            self.grade.insert(self.base, [" "] * self.m)
        else:
            del self.grade[self.base]
            self.grade.insert(self.topo, [" "] * self.m)

    def _avanca_linha(self):
        if self.y == self.base:
            self._rola()
        else:
            self.y = min(self.y + 1, self.n - 1)

    def _poe(self, ch):
        if self.x >= self.m:
            self.x = 0
            self._avanca_linha()
        self.grade[self.y][self.x] = ch
        self.x += 1

    def _apaga(self, y, x0, x1):
        for x in range(max(x0, 0), min(x1, self.m)):
            self.grade[y][x] = " "

    def _csi(self, params, final):
        priv = params[:1] in ("?", ">", "<", "=")
        nums = [int(p) if p.isdigit() else 0 for p in params.lstrip("?<>=").split(";") if p != ""] or []
        a = nums[0] if nums else 0
        um = lambda v=None: max(1, a if v is None else v)
        if priv:
            return
        if final == "A":
            self.y = max(self.topo, self.y - um())
        elif final == "B":
            self.y = min(self.base, self.y + um())
        elif final == "C":
            self.x = min(self.m - 1, self.x + um())
        elif final == "D":
            self.x = max(0, self.x - um())
        elif final == "E":
            self.y, self.x = min(self.base, self.y + um()), 0
        elif final == "F":
            self.y, self.x = max(self.topo, self.y - um()), 0
        elif final == "G":
            self.x = min(self.m - 1, um() - 1)
        elif final == "d":
            self.y = min(self.n - 1, um() - 1)
        elif final in ("H", "f"):
            self.y = min(self.n - 1, max(0, (nums[0] if nums else 1) - 1))
            self.x = min(self.m - 1, max(0, (nums[1] if len(nums) > 1 else 1) - 1))
        elif final == "J":
            if a in (2, 3):
                for y in range(self.n):
                    self._apaga(y, 0, self.m)
            elif a == 0:
                self._apaga(self.y, self.x, self.m)
                for y in range(self.y + 1, self.n):
                    self._apaga(y, 0, self.m)
            elif a == 1:
                self._apaga(self.y, 0, self.x + 1)
                for y in range(self.y):
                    self._apaga(y, 0, self.m)
        elif final == "K":
            self._apaga(self.y, *({0: (self.x, self.m), 1: (0, self.x + 1), 2: (0, self.m)}.get(a, (0, 0))))
        elif final == "X":
            self._apaga(self.y, self.x, self.x + um())
        elif final == "P":
            linha = self.grade[self.y]
            del linha[self.x:self.x + um()]
            linha.extend([" "] * (self.m - len(linha)))
        elif final == "@":
            linha = self.grade[self.y]
            linha[self.x:self.x] = [" "] * um()
            del linha[self.m:]
        elif final in ("L", "M") and self.topo <= self.y <= self.base:
            t0 = self.topo
            self.topo = self.y
            for _ in range(um()):
                self._rola(cima=(final == "M"))
            self.topo = t0
        elif final in ("S", "T"):
            for _ in range(um()):
                self._rola(cima=(final == "S"))
        elif final == "r":
            self.topo = max(0, (nums[0] if nums else 1) - 1)
            self.base = min(self.n - 1, (nums[1] if len(nums) > 1 else self.n) - 1)
            self.y = self.x = 0
        elif final == "s":
            self.salvo = (self.y, self.x)
        elif final == "u":
            self.y, self.x = self.salvo

    def alimenta(self, texto):
        texto = self.resto + texto
        self.resto = ""
        i, n = 0, len(texto)
        while i < n:
            ch = texto[i]
            if ch == "\x1b":
                if i + 1 >= n:
                    self.resto = texto[i:]
                    return
                prox = texto[i + 1]
                if prox == "[":
                    j = i + 2
                    while j < n and not ("@" <= texto[j] <= "~"):
                        j += 1
                    if j >= n:
                        self.resto = texto[i:]
                        return
                    self._csi(texto[i + 2:j], texto[j])
                    i = j + 1
                elif prox == "]":
                    j = i + 2
                    while j < n and texto[j] != "\x07" and not texto.startswith("\x1b\\", j):
                        j += 1
                    if j >= n:
                        self.resto = texto[i:]
                        return
                    i = j + (1 if texto[j] == "\x07" else 2)
                elif prox in "()":
                    i += 3
                elif prox == "7":
                    self.salvo, i = (self.y, self.x), i + 2
                elif prox == "8":
                    (self.y, self.x), i = self.salvo, i + 2
                elif prox == "M":
                    if self.y == self.topo:
                        self._rola(cima=False)
                    else:
                        self.y -= 1
                    i += 2
                else:
                    i += 2
            elif ch == "\n":
                self._avanca_linha()
                i += 1
            elif ch == "\r":
                self.x, i = 0, i + 1
            elif ch == "\b":
                self.x, i = max(0, self.x - 1), i + 1
            elif ch == "\t":
                self.x, i = min(self.m - 1, (self.x // 8 + 1) * 8), i + 1
            elif ch < " " or ch == "\x7f":
                i += 1
            else:
                self._poe(ch)
                i += 1

    def texto(self):
        linhas = ["".join(l).rstrip() for l in self.grade]
        while linhas and not linhas[-1]:
            linhas.pop()
        return "\n".join(linhas)


# perguntas que os clientes fazem ao terminal e as respostas
def _respostas(bruto, tela):
    r = ""
    for casa in re.finditer(r"\x1b\[6n", bruto):
        r += f"\x1b[{tela.y + 1};{tela.x + 1}R"
    if re.search(r"\x1b\[(0)?c", bruto):
        r += "\x1b[?62;22c"
    if "\x1b[>c" in bruto or "\x1b[>0c" in bruto:
        r += "\x1b[>0;0;0c"
    if "\x1b[?u" in bruto:
        r += "\x1b[?0u"
    if "\x1b]10;?" in bruto:
        r += "\x1b]10;rgb:ffff/ffff/ffff\x1b\\"
    if "\x1b]11;?" in bruto:
        r += "\x1b]11;rgb:0000/0000/0000\x1b\\"
    if "\x1b[18t" in bruto:
        r += f"\x1b[8;{tela.n};{tela.m}t"
    if "\x1b[?996n" in bruto:
        r += "\x1b[?997;1n"
    return r


class Sessao:
    """Um cliente rodando sob pty. A tela e o histórico ficam em memória."""

    def __init__(self, argv, env, cwd, linhas=50, colunas=160):
        self.argv, self.env, self.cwd = argv, env, cwd
        self.tela_atual = Tela(linhas, colunas)
        self.historico = ""
        self.linhas, self.colunas = linhas, colunas
        self.decodificador = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.processo = None
        self.mestre = None

    def abre(self):
        self.mestre, escravo = os.openpty()
        fcntl.ioctl(escravo, termios.TIOCSWINSZ, struct.pack("HHHH", self.linhas, self.colunas, 0, 0))
        env = dict(self.env, TERM="xterm-256color", COLUMNS=str(self.colunas), LINES=str(self.linhas))
        self.processo = subprocess.Popen(
            self.argv, env=env, cwd=self.cwd, stdin=escravo, stdout=escravo, stderr=escravo,
            start_new_session=True, close_fds=True,
            preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
        os.close(escravo)
        return self

    def vivo(self):
        return self.processo is not None and self.processo.poll() is None

    def le(self, limite=0.3):
        """Lê o que houver por até `limite` segundos; devolve o texto novo."""
        novo = ""
        fim = time.time() + limite
        while True:
            restante = fim - time.time()
            if restante <= 0:
                break
            pronto, _, _ = select.select([self.mestre], [], [], min(restante, 0.1))
            if not pronto:
                continue
            try:
                dados = os.read(self.mestre, 65536)
            except OSError:
                break
            if not dados:
                break
            texto = self.decodificador.decode(dados)
            self.tela_atual.alimenta(texto)
            resposta = _respostas(texto, self.tela_atual)
            if resposta:
                os.write(self.mestre, resposta.encode())
            novo += texto
            fim = max(fim, time.time() + 0.05)
        self.historico += sem_escapes(novo)
        return sem_escapes(novo)

    def tela(self):
        return self.tela_atual.texto()

    def marca(self):
        """Posição no histórico, para esperar só texto que apareça depois."""
        return len(self.historico)

    def espera(self, padrao, limite=30, desde=0):
        """Espera o padrão (regex, sem distinguir caixa) na tela ou no histórico
        depois de `desde`. Devolve o trecho achado ou None."""
        rx = re.compile(padrao, re.IGNORECASE)
        fim = time.time() + limite
        while time.time() < fim:
            achado = rx.search(self.tela()) or rx.search(self.historico[desde:])
            if achado:
                return achado.group(0)
            if not self.vivo():
                self.le(0.2)
                achado = rx.search(self.tela()) or rx.search(self.historico[desde:])
                return achado.group(0) if achado else None
            self.le(0.2)
        return None

    def quieto(self, segundos=2.0, limite=30):
        """Espera a saída parar por `segundos` (a tela assentou)."""
        fim = time.time() + limite
        ultimo = time.time()
        while time.time() < fim and self.vivo():
            if self.le(0.2):
                ultimo = time.time()
            elif time.time() - ultimo >= segundos:
                return True
        return False

    def manda(self, texto):
        os.write(self.mestre, texto.encode())

    def seleciona(self, regex_opcao, cursor=r"^\s*(?:❯|›|▶|→|>|●)\s", maximo=10):
        """Move o cursor de um menu até a linha da opção (regex) com as setas.
        Devolve True se o cursor chegou nela; não aperta Enter."""
        alvo, marca = re.compile(regex_opcao, re.IGNORECASE), re.compile(cursor)
        for _ in range(maximo):
            linhas = self.tela().split("\n")
            ia = next((i for i, l in enumerate(linhas) if alvo.search(l)), None)
            ic = next((i for i, l in enumerate(linhas) if marca.search(l) and i is not None and alvo.search(l)), None)
            if ic is not None:
                return True
            icur = next((i for i, l in enumerate(linhas) if marca.search(l)), None)
            if ia is None or icur is None:
                return False
            self.tecla("baixo" if ia > icur else "cima")
            self.le(0.4)
        return False

    def tecla(self, nome):
        self.manda(TECLAS.get(nome, nome))

    def digita(self, texto, atraso=0.01):
        for ch in texto:
            self.manda(ch)
            time.sleep(atraso)

    def encerra(self):
        """Ctrl-C duas vezes, depois SIGTERM e SIGKILL no grupo do processo."""
        if self.processo is None:
            return
        try:
            if self.vivo():
                for _ in range(2):
                    self.manda("\x03")
                    self.le(0.5)
            for sinal in (signal.SIGTERM, signal.SIGKILL):
                if not self.vivo():
                    break
                try:
                    os.killpg(self.processo.pid, sinal)
                except ProcessLookupError:
                    break
                try:
                    self.processo.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            try:
                os.close(self.mestre)
            except OSError:
                pass
            self.mestre = None
