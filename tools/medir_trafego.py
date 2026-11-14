"""Mede quanto de rede o WebView2 do BTC Status usa, por servidor.

Sobe um proxy local que só conta bytes (não lê o conteúdo: o HTTPS passa cifrado por um
túnel CONNECT) e abre o app com "--proxy-server" apontando para ele, pela variável
WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS. Serve para duas coisas:

1. Ver o tráfego real do app, inclusive o que não vem da página (o próprio WebView2);
2. Comparar com e sem os argumentos do WebView2 adotados pelo app (argumentos_webview2.py),
   ou testar outros além deles.

Uso (na raiz do projeto, com o app fechado):
    .venv\\Scripts\\python.exe tools\\medir_trafego.py                          # 120 s, o app como ele é
    .venv\\Scripts\\python.exe tools\\medir_trafego.py --comparar-adotados      # sem e depois com os adotados
    .venv\\Scripts\\python.exe tools\\medir_trafego.py --argumentos "--disable-sync --no-pings"   # outros, além dos adotados
    .venv\\Scripts\\python.exe tools\\medir_trafego.py --exe "dist\\BTC Monitor\\BTC Monitor.exe"

A cada --parcial segundos (padrão 30) sai o tráfego do período: minimize a janela no meio
da medição para ver o que muda com ela oculta.

Observações:
- A busca do 1º preço pelo Python (WinHTTP) não passa pelo proxy: não aparece aqui.
- A página local (127.0.0.1) também não: o Chromium não usa proxy para o próprio computador.
- O tráfego conta os bytes do TLS (cabeçalhos, certificados), como a banda de verdade.
- Um argumento desconhecido é ignorado pelo Chromium sem aviso: o que vale é a diferença medida.
- O app é encerrado à força no fim de cada medição.
- --comparar-adotados usa a variável BTC_SEM_ARGUMENTOS_WEBVIEW2, que só vale com a medição
  (pelo Python do venv ou no build -ComMedicao; o .exe de produção a ignora).
"""

from __future__ import annotations

import argparse
import os
import select
import socket
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tools"))

import argumentos_webview2  # noqa: E402

LIMITE_CABECALHO = 65536
ESPERA_CONEXAO_S = 10.0


@dataclass
class Trafego:
    conexoes: int = 0
    enviados: int = 0   # do app para o servidor
    recebidos: int = 0  # do servidor para o app

    @property
    def total(self) -> int:
        return self.enviados + self.recebidos

    def menos(self, outro: "Trafego") -> "Trafego":
        return Trafego(self.conexoes - outro.conexoes, self.enviados - outro.enviados, self.recebidos - outro.recebidos)


@dataclass
class ProxyContador:
    """Proxy HTTP mínimo (CONNECT e pedidos http://), em threads, que conta bytes por servidor."""

    conectar: object = socket.create_connection
    _trafego: dict[str, Trafego] = field(default_factory=lambda: defaultdict(Trafego))
    _trava: threading.Lock = field(default_factory=threading.Lock)
    _servidor: socket.socket | None = None
    _abertos: set = field(default_factory=set)
    porta: int = 0

    def iniciar(self) -> int:
        self._servidor = socket.create_server(("127.0.0.1", 0))
        self.porta = self._servidor.getsockname()[1]
        threading.Thread(target=self._aceitar, name="proxy-contador", daemon=True).start()
        return self.porta

    def parar(self) -> None:
        servidor, self._servidor = self._servidor, None
        if servidor:
            servidor.close()
        with self._trava:
            abertos = list(self._abertos)
        for conexao in abertos:
            _fechar(conexao)

    def retrato(self) -> dict[str, Trafego]:
        with self._trava:
            return {nome: Trafego(t.conexoes, t.enviados, t.recebidos) for nome, t in self._trafego.items()}

    def _somar(self, servidor: str, conexoes: int = 0, enviados: int = 0, recebidos: int = 0) -> None:
        with self._trava:
            trafego = self._trafego[servidor]
            trafego.conexoes += conexoes
            trafego.enviados += enviados
            trafego.recebidos += recebidos

    def _aceitar(self) -> None:
        servidor = self._servidor
        while servidor is not None:
            try:
                cliente, _ = servidor.accept()
            except OSError:
                return
            threading.Thread(target=self._atender, args=(cliente,), daemon=True).start()

    def _atender(self, cliente: socket.socket) -> None:
        destino = None
        with self._trava:
            self._abertos.add(cliente)
        try:
            cliente.settimeout(ESPERA_CONEXAO_S)
            cabecalho, resto = _ler_cabecalho(cliente)
            pedido = interpretar_pedido(cabecalho)
            if pedido is None:
                cliente.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                return
            nome = pedido.servidor
            try:
                destino = self.conectar((pedido.host, pedido.porta), ESPERA_CONEXAO_S)
            except OSError:
                self._somar(nome + " (sem conexão)", conexoes=1)
                cliente.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                return
            with self._trava:
                self._abertos.add(destino)
            self._somar(nome, conexoes=1)
            if pedido.tunel:
                cliente.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                inicial = resto
            else:
                inicial = pedido.cabecalho_para_o_servidor + resto
            if inicial:
                destino.sendall(inicial)
                self._somar(nome, enviados=len(inicial))
            self._repassar(cliente, destino, nome)
        except OSError:
            pass
        finally:
            for conexao in (cliente, destino):
                if conexao is not None:
                    _fechar(conexao)
                    with self._trava:
                        self._abertos.discard(conexao)

    def _repassar(self, cliente: socket.socket, destino: socket.socket, nome: str) -> None:
        cliente.settimeout(None)
        destino.settimeout(None)
        while True:
            prontos, _, _ = select.select([cliente, destino], [], [], 60)
            for origem in prontos:
                dados = origem.recv(65536)
                if not dados:
                    return
                if origem is cliente:
                    destino.sendall(dados)
                    self._somar(nome, enviados=len(dados))
                else:
                    cliente.sendall(dados)
                    self._somar(nome, recebidos=len(dados))


def _fechar(conexao: socket.socket) -> None:
    try:
        conexao.close()
    except OSError:
        pass


def _ler_cabecalho(cliente: socket.socket) -> tuple[bytes, bytes]:
    """Lê até a linha em branco; devolve (cabeçalho com ela, bytes que vieram depois)."""
    dados = b""
    while b"\r\n\r\n" not in dados:
        parte = cliente.recv(4096)
        if not parte or len(dados) > LIMITE_CABECALHO:
            return dados, b""
        dados += parte
    fim = dados.index(b"\r\n\r\n") + 4
    return dados[:fim], dados[fim:]


@dataclass
class Pedido:
    host: str
    porta: int
    tunel: bool
    cabecalho_para_o_servidor: bytes = b""

    @property
    def servidor(self) -> str:
        padrao = 443 if self.tunel else 80
        return self.host if self.porta == padrao else f"{self.host}:{self.porta}"


def _separar_host(texto: str, porta_padrao: int) -> tuple[str, int] | None:
    host, separador, porta = texto.rpartition(":")
    if not separador or "]" in porta:  # sem porta (ou IPv6 sem porta)
        host, porta = texto, str(porta_padrao)
    host = host.strip("[]")
    if not host or not porta.isdigit():
        return None
    return host, int(porta)


def interpretar_pedido(cabecalho: bytes) -> Pedido | None:
    """CONNECT host:porta, ou GET http://host/caminho (reescrito para o formato do servidor)."""
    try:
        linha, _, restante = cabecalho.partition(b"\r\n")
        metodo, alvo, versao = linha.decode("latin-1").split(" ", 2)
    except ValueError:
        return None
    if metodo.upper() == "CONNECT":
        endereco = _separar_host(alvo, 443)
        return Pedido(*endereco, tunel=True) if endereco else None
    if not alvo.lower().startswith("http://"):
        return None
    local, barra, caminho = alvo[len("http://"):].partition("/")
    endereco = _separar_host(local, 80)
    if not endereco:
        return None
    nova_linha = f"{metodo} /{caminho if barra else ''} {versao}".encode("latin-1")
    return Pedido(*endereco, tunel=False, cabecalho_para_o_servidor=nova_linha + b"\r\n" + restante)


# ---------------------------------------------------------------------------
# Medição
# ---------------------------------------------------------------------------

def ambiente_do_app(porta_proxy: int, argumentos: list[str], base: dict[str, str] | None = None) -> dict[str, str]:
    base = dict(os.environ if base is None else base)
    extras = [f"--proxy-server=http://127.0.0.1:{porta_proxy}", *argumentos]
    base[argumentos_webview2.VARIAVEL] = argumentos_webview2.valor_da_variavel(extras, base.get(argumentos_webview2.VARIAVEL))
    return base


def formatar_bytes(valor: float) -> str:
    if abs(valor) < 1024:
        return f"{valor:.0f} B"
    if abs(valor) < 1024 * 1024:
        return f"{valor / 1024:.1f} KB"
    return f"{valor / (1024 * 1024):.2f} MB"


def diferenca(agora: dict[str, Trafego], antes: dict[str, Trafego]) -> dict[str, Trafego]:
    partes = {nome: trafego.menos(antes.get(nome, Trafego())) for nome, trafego in agora.items()}
    return {nome: t for nome, t in partes.items() if t.conexoes or t.total}


def tabela(trafego: dict[str, Trafego], segundos: float) -> list[str]:
    linhas = [f"{'Servidor':<44}{'Conexões':>9}{'Enviado':>12}{'Recebido':>12}{'Total':>12}"]
    for nome, t in sorted(trafego.items(), key=lambda item: -item[1].total):
        linhas.append(f"{nome[:43]:<44}{t.conexoes:>9}{formatar_bytes(t.enviados):>12}"
                      f"{formatar_bytes(t.recebidos):>12}{formatar_bytes(t.total):>12}")
    soma = Trafego(sum(t.conexoes for t in trafego.values()), sum(t.enviados for t in trafego.values()),
                   sum(t.recebidos for t in trafego.values()))
    linhas.append(f"{'TOTAL':<44}{soma.conexoes:>9}{formatar_bytes(soma.enviados):>12}"
                  f"{formatar_bytes(soma.recebidos):>12}{formatar_bytes(soma.total):>12}")
    if segundos > 0:
        linhas.append(f"Média: {formatar_bytes(soma.total / segundos * 60)} por minuto "
                      f"({formatar_bytes(soma.total / segundos * 3600)} por hora)")
    return linhas


def comparacao(sem: dict[str, Trafego], com: dict[str, Trafego]) -> list[str]:
    linhas = [f"{'Servidor':<44}{'Sem':>12}{'Com':>12}{'Diferença':>13}"]
    nomes = sorted(set(sem) | set(com), key=lambda n: -(sem.get(n, Trafego()).total + com.get(n, Trafego()).total))
    for nome in nomes:
        a, b = sem.get(nome, Trafego()).total, com.get(nome, Trafego()).total
        linhas.append(f"{nome[:43]:<44}{formatar_bytes(a):>12}{formatar_bytes(b):>12}{formatar_bytes(b - a):>13}")
    a = sum(t.total for t in sem.values())
    b = sum(t.total for t in com.values())
    linhas.append(f"{'TOTAL':<44}{formatar_bytes(a):>12}{formatar_bytes(b):>12}{formatar_bytes(b - a):>13}")
    return linhas


VARIAVEL_SEM_ADOTADOS = "BTC_SEM_ARGUMENTOS_WEBVIEW2"  # o mesmo nome usado em BTC_Monitor.py


def medir(opcoes: argparse.Namespace, argumentos: list[str], titulo: str, sem_adotados: bool = False) -> dict[str, Trafego]:
    from medir_abertura import encerrar, garantir_porta_livre

    garantir_porta_livre()
    proxy = ProxyContador()
    porta = proxy.iniciar()
    comando = [str(opcoes.exe)] if opcoes.exe else [sys.executable, str(RAIZ / "BTC_Monitor.py")]
    print(f"\n=== {titulo}: {opcoes.segundos:.0f} s ===")
    print(f"Argumentos do app: {'desligados' if sem_adotados else 'adotados'}; outros: {' '.join(argumentos) or '(nenhum)'}")
    ambiente = ambiente_do_app(porta, argumentos)
    ambiente[VARIAVEL_SEM_ADOTADOS] = "1" if sem_adotados else "0"
    processo = subprocess.Popen(comando, cwd=RAIZ, env=ambiente)
    inicio = time.monotonic()
    anterior: dict[str, Trafego] = {}
    try:
        while (decorrido := time.monotonic() - inicio) < opcoes.segundos:
            if processo.poll() is not None:
                print("O app fechou antes do fim da medição.")
                break
            time.sleep(min(opcoes.parcial, opcoes.segundos - decorrido))
            agora = proxy.retrato()
            periodo = diferenca(agora, anterior)
            anterior = agora
            resumo = ", ".join(f"{nome} {formatar_bytes(t.total)}"
                               for nome, t in sorted(periodo.items(), key=lambda item: -item[1].total)) or "nada"
            print(f"  até {time.monotonic() - inicio:5.0f} s: {resumo}")
    finally:
        encerrar(processo)
        duracao = time.monotonic() - inicio
        total = proxy.retrato()
        proxy.parar()
    print()
    print("\n".join(tabela(total, duracao)))
    if not total:
        print("Nenhuma conexão passou pelo proxy: o WebView2 não aceitou o --proxy-server "
              "(ou o app não abriu; veja o btcstatus.log).")
    time.sleep(opcoes.pausa)
    return total


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mede o tráfego do WebView2 do BTC Status por servidor")
    parser.add_argument("--segundos", type=float, default=120.0, help="duração de cada medição")
    parser.add_argument("--parcial", type=float, default=30.0, help="intervalo dos resumos parciais")
    parser.add_argument("--pausa", type=float, default=3.0, help="segundos entre uma medição e outra")
    parser.add_argument("--exe", type=Path, help="executável gerado pelo PyInstaller (padrão: BTC_Monitor.py com este Python)")
    parser.add_argument("--argumentos", help=f"grupo ({', '.join(argumentos_webview2.GRUPOS)}) ou argumentos entre aspas: "
                                             "mede sem e depois com eles, além dos adotados pelo app")
    parser.add_argument("--comparar-adotados", action="store_true",
                        help="mede sem e depois com os argumentos adotados pelo app (exige a medição)")
    opcoes = parser.parse_args(argumentos)
    if opcoes.argumentos and opcoes.comparar_adotados:
        parser.error("use --argumentos ou --comparar-adotados, um de cada vez")
    if opcoes.segundos <= 0 or opcoes.parcial <= 0:
        parser.error("--segundos e --parcial precisam ser positivos")
    try:
        extras = argumentos_webview2.resolver(opcoes.argumentos) if opcoes.argumentos else []
    except ValueError as erro:
        parser.error(str(erro))

    if opcoes.comparar_adotados:
        sem = medir(opcoes, [], "Sem os argumentos adotados", sem_adotados=True)
        com = medir(opcoes, [], "Com os argumentos adotados")
    else:
        sem = medir(opcoes, [], "O app como ele é")
        if not extras:
            return 0 if sem else 1
        com = medir(opcoes, extras, "Com outros argumentos")
    print("\n=== Comparação (total por servidor) ===")
    print("\n".join(comparacao(sem, com)))
    print("\nA 1ª medição depois de ligar o PC costuma ter tráfego a mais (atualizações do WebView2):")
    print("repita a comparação antes de concluir.")
    return 0 if sem and com else 1


if __name__ == "__main__":
    raise SystemExit(main())
