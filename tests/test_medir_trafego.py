"""tools/medir_trafego.py (proxy que conta bytes) e argumentos_webview2.py (usados pelo app).

O proxy é exercitado de verdade, com servidores locais: um túnel CONNECT e um pedido http://.
O que estes testes NÃO cobrem: se o WebView2 aceita o --proxy-server e os argumentos extras
pela variável de ambiente (só no Windows, com o app).
"""

from __future__ import annotations

import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tools"))

import argumentos_webview2  # noqa: E402
import medir_abertura  # noqa: E402
import medir_trafego  # noqa: E402
from medir_trafego import ProxyContador, Trafego  # noqa: E402


@pytest.fixture
def proxy():
    contador = ProxyContador()
    contador.iniciar()
    yield contador
    contador.parar()


@pytest.fixture
def eco():
    """Servidor TCP que devolve em dobro o que recebe (para enviados != recebidos)."""
    servidor = socket.create_server(("127.0.0.1", 0))

    def atender() -> None:
        while True:
            try:
                conexao, _ = servidor.accept()
            except OSError:
                return
            with conexao:
                while dados := conexao.recv(4096):
                    conexao.sendall(dados * 2)

    threading.Thread(target=atender, daemon=True).start()
    yield servidor.getsockname()[1]
    servidor.close()


def ler_ate(conexao: socket.socket, quantidade: int) -> bytes:
    dados = b""
    while len(dados) < quantidade:
        parte = conexao.recv(4096)
        assert parte, "a conexão fechou antes da hora"
        dados += parte
    return dados


def esperar_trafego(proxy: ProxyContador, nome: str, total: int) -> Trafego:
    import time

    prazo = time.monotonic() + 3
    while time.monotonic() < prazo:
        trafego = proxy.retrato().get(nome)
        if trafego and trafego.total >= total:
            return trafego
        time.sleep(0.01)
    raise AssertionError(f"tráfego de {nome} não chegou a {total}: {proxy.retrato()}")


def test_tunel_connect_repassa_e_conta_os_bytes_de_cada_lado(proxy, eco):
    with socket.create_connection(("127.0.0.1", proxy.porta), 3) as cliente:
        cliente.sendall(f"CONNECT 127.0.0.1:{eco} HTTP/1.1\r\nHost: 127.0.0.1:{eco}\r\n\r\n".encode())
        resposta = ler_ate(cliente, 12)
        assert resposta.startswith(b"HTTP/1.1 200")
        while not resposta.endswith(b"\r\n\r\n"):
            resposta += cliente.recv(4096)
        cliente.sendall(b"x" * 1000)
        assert ler_ate(cliente, 2000) == b"x" * 2000
        trafego = esperar_trafego(proxy, f"127.0.0.1:{eco}", 3000)
    assert (trafego.conexoes, trafego.enviados, trafego.recebidos) == (1, 1000, 2000)


def test_bytes_enviados_junto_com_o_connect_nao_se_perdem(proxy, eco):
    with socket.create_connection(("127.0.0.1", proxy.porta), 3) as cliente:
        cliente.sendall(f"CONNECT 127.0.0.1:{eco} HTTP/1.1\r\n\r\nabc".encode())
        dados = ler_ate(cliente, len(b"HTTP/1.1 200 Connection Established\r\n\r\n") + 6)
        assert dados.endswith(b"abcabc")


def test_pedido_http_e_reescrito_e_contado(proxy):
    caminhos = []

    class Atendente(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            caminhos.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "5")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"12345")

        def log_message(self, *args) -> None:
            pass

    servidor = HTTPServer(("127.0.0.1", 0), Atendente)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    porta = servidor.server_address[1]
    try:
        with socket.create_connection(("127.0.0.1", proxy.porta), 3) as cliente:
            cliente.sendall(f"GET http://127.0.0.1:{porta}/a/b?c=1 HTTP/1.1\r\nHost: 127.0.0.1:{porta}\r\n\r\n".encode())
            resposta = b""
            while parte := cliente.recv(4096):
                resposta += parte
    finally:
        servidor.shutdown()
        servidor.server_close()
    assert resposta.endswith(b"12345")
    assert caminhos == ["/a/b?c=1"], "o servidor recebe o caminho, não a URL inteira"
    trafego = proxy.retrato()[f"127.0.0.1:{porta}"]
    assert trafego.conexoes == 1 and trafego.enviados > 0 and trafego.recebidos == len(resposta)


def test_destino_inalcancavel_devolve_502_e_fica_registrado(proxy):
    def falhar(endereco, espera):
        raise OSError("sem rota")

    proxy.conectar = falhar
    with socket.create_connection(("127.0.0.1", proxy.porta), 3) as cliente:
        cliente.sendall(b"CONNECT exemplo.invalid:443 HTTP/1.1\r\n\r\n")
        assert ler_ate(cliente, 12).startswith(b"HTTP/1.1 502")
    assert proxy.retrato()["exemplo.invalid (sem conexão)"].conexoes == 1


def test_pedido_que_nao_e_de_proxy_recebe_400(proxy):
    with socket.create_connection(("127.0.0.1", proxy.porta), 3) as cliente:
        cliente.sendall(b"GET /index.html HTTP/1.1\r\nHost: x\r\n\r\n")
        assert ler_ate(cliente, 12).startswith(b"HTTP/1.1 400")
    assert proxy.retrato() == {}


@pytest.mark.parametrize(("linha", "esperado"), [
    (b"CONNECT stream.binance.com:9443 HTTP/1.1", ("stream.binance.com", 9443, True, "stream.binance.com:9443")),
    (b"CONNECT api.binance.com:443 HTTP/1.1", ("api.binance.com", 443, True, "api.binance.com")),
    (b"CONNECT [2001:db8::1]:443 HTTP/1.1", ("2001:db8::1", 443, True, "2001:db8::1")),
    (b"GET http://exemplo.com/x HTTP/1.1", ("exemplo.com", 80, False, "exemplo.com")),
    (b"GET http://exemplo.com:8080 HTTP/1.1", ("exemplo.com", 8080, False, "exemplo.com:8080")),
])
def test_interpretar_pedido(linha, esperado):
    pedido = medir_trafego.interpretar_pedido(linha + b"\r\nHost: x\r\n\r\n")
    assert (pedido.host, pedido.porta, pedido.tunel, pedido.servidor) == esperado


@pytest.mark.parametrize("linha", [b"", b"CONNECT", b"CONNECT semporta:abc HTTP/1.1", b"GET ftp://x/ HTTP/1.1"])
def test_interpretar_pedido_invalido(linha):
    assert medir_trafego.interpretar_pedido(linha + b"\r\n\r\n") is None


def test_ambiente_do_app_poe_o_proxy_e_mantem_o_que_ja_havia():
    variavel = argumentos_webview2.VARIAVEL
    ambiente = medir_trafego.ambiente_do_app(5000, ["--no-pings"], base={"PATH": "x"})
    assert ambiente == {"PATH": "x", variavel: "--proxy-server=http://127.0.0.1:5000 --no-pings"}
    ambiente = medir_trafego.ambiente_do_app(5000, [], base={variavel: " --ja-estava "})
    assert ambiente[variavel] == "--ja-estava --proxy-server=http://127.0.0.1:5000"


def test_grupos_de_argumentos():
    assert argumentos_webview2.resolver("rede") == argumentos_webview2.REDE
    assert argumentos_webview2.resolver("todos") == argumentos_webview2.REDE + argumentos_webview2.RECURSOS
    assert argumentos_webview2.resolver("--a --b=c") == ["--a", "--b=c"]
    for invalido in ("", "desconhecido", "--a b"):
        with pytest.raises(ValueError):
            argumentos_webview2.resolver(invalido)
    todos = [a for grupo in argumentos_webview2.GRUPOS.values() for a in grupo]
    # Um --disable-features repetido substitui o do pywebview: o grupo precisa repetir o dele.
    for argumento in todos:
        if argumento.startswith("--disable-features="):
            assert "ElasticOverscroll" in argumento.split("=", 1)[1].split(",")
    # Nada que reduza a segurança ou desligue a GPU entra num grupo.
    proibidos = ("sandbox", "smartscreen", "web-security", "integrity", "disable-gpu", "certificate", "proxy")
    assert not [a for a in todos if any(p in a.lower() for p in proibidos)]


def test_aplicar_preenche_a_variavel_sem_duplicar_e_mantem_o_que_havia():
    variavel = argumentos_webview2.VARIAVEL
    ambiente: dict[str, str] = {}
    valor = argumentos_webview2.aplicar(ambiente)
    assert ambiente[variavel] == valor == " ".join(argumentos_webview2.ADOTADOS)
    assert argumentos_webview2.aplicar(ambiente) == valor, "chamar de novo não duplica"
    ambiente = {variavel: "--proxy-server=http://127.0.0.1:1 --no-pings"}
    partes = argumentos_webview2.aplicar(ambiente).split()
    assert partes[0] == "--proxy-server=http://127.0.0.1:1" and partes.count("--no-pings") == 1
    assert set(argumentos_webview2.ADOTADOS) <= set(partes)
    assert argumentos_webview2.ADOTADOS == argumentos_webview2.GRUPOS["todos"]


def test_app_aplica_os_argumentos_antes_de_criar_o_webview2():
    fonte = (RAIZ / "BTC_Monitor.py").read_text(encoding="utf-8")
    aplicar = fonte.index("argumentos_webview2.aplicar()")
    assert aplicar < fonte.index("webview.start(")
    guarda = fonte[fonte.rindex("\n", 0, fonte.rindex("\n", 0, aplicar)):aplicar]
    assert "recurso_desligado_na_medicao(VARIAVEL_SEM_ARGUMENTOS_WEBVIEW2)" in guarda
    assert medir_abertura.COMPARACOES["argumentos-webview2"][0] == medir_trafego.VARIAVEL_SEM_ADOTADOS
    assert f'"{medir_trafego.VARIAVEL_SEM_ADOTADOS}"' in fonte
    # Módulo leve: entra no caminho da abertura.
    modulo = (RAIZ / "argumentos_webview2.py").read_text(encoding="utf-8")
    importados = [linha for linha in modulo.splitlines() if linha.startswith(("import ", "from "))]
    assert importados == ["from __future__ import annotations", "import os"]


def test_main_recusa_as_duas_comparacoes_juntas():
    with pytest.raises(SystemExit):
        medir_trafego.main(["--argumentos", "rede", "--comparar-adotados"])


def test_pywebview_ainda_passa_so_o_elasticoverscroll():
    """Se o pywebview mudar os argumentos dele, o grupo "recursos" precisa ser revisto."""
    webview = pytest.importorskip("webview")
    fonte = (Path(webview.__file__).parent / "platforms" / "edgechromium.py").read_text(encoding="utf-8")
    assert "props.AdditionalBrowserArguments = '--disable-features=ElasticOverscroll'" in fonte


def test_comparacao_de_abertura_so_muda_o_ambiente_das_execucoes_com():
    variavel = argumentos_webview2.VARIAVEL
    ambiente = medir_abertura.ambiente_dos_argumentos(["--no-pings"], base={})
    assert ambiente(True) == {}
    assert ambiente(False) == {variavel: "--no-pings"}


def test_tabelas():
    sem = {"a.com": Trafego(2, 1024, 3072), "b.com": Trafego(1, 10, 20)}
    com = {"a.com": Trafego(2, 1024, 3072)}
    linhas = medir_trafego.tabela(sem, 60)
    assert linhas[1].startswith("a.com") and "4.0 KB" in linhas[1]
    assert linhas[-2].startswith("TOTAL") and linhas[-1].startswith("Média: 4.0 KB por minuto")
    linhas = medir_trafego.comparacao(sem, com)
    assert "b.com" in linhas[2] and linhas[2].rstrip().endswith("-30 B")
    assert medir_trafego.diferenca(sem, {"a.com": Trafego(2, 1024, 3072)}) == {"b.com": Trafego(1, 10, 20)}


def test_main_recusa_argumentos_invalidos():
    with pytest.raises(SystemExit):
        medir_trafego.main(["--argumentos", "sem-tracos"])
    with pytest.raises(SystemExit):
        medir_trafego.main(["--segundos", "0"])


def test_nao_ha_copia_antiga_do_modulo_em_tools():
    """O módulo mudou para a raiz; uma cópia em tools/ seria importada no lugar pelas ferramentas."""
    assert not (RAIZ / "tools" / "argumentos_webview2.py").exists(), "apague tools/argumentos_webview2.py"
