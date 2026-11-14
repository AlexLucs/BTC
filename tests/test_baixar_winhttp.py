"""baixar_winhttp.py: GET pelo WinHTTP do Windows, no lugar do urllib + ssl.

Três grupos:
- em qualquer sistema: a divisão da URL e o fluxo de chamadas, com uma winhttp.dll falsa;
- só no Windows: a winhttp.dll de verdade contra um servidor HTTP local;
- só com BTC_REDE_REAL=1 (e no Windows): HTTPS de verdade contra a Binance.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import baixar_winhttp  # noqa: E402
from baixar_winhttp import ErroDeRequisicao, baixar, separar_url  # noqa: E402

so_no_windows = pytest.mark.skipif(sys.platform != "win32", reason="o WinHTTP só existe no Windows")


# ---------------------------------------------------------------------------
# Divisão da URL
# ---------------------------------------------------------------------------

def test_separar_url_https_com_consulta():
    url = "https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%22BTCBRL%22%2C%22BTCUSDT%22%5D"
    assert separar_url(url) == (
        True, "api.binance.com", 443, "/api/v3/ticker/24hr?symbols=%5B%22BTCBRL%22%2C%22BTCUSDT%22%5D")


def test_separar_url_http_com_porta_e_sem_caminho():
    assert separar_url("http://127.0.0.1:8123/tickers") == (False, "127.0.0.1", 8123, "/tickers")
    assert separar_url("http://exemplo.invalid") == (False, "exemplo.invalid", 80, "/")


@pytest.mark.parametrize("url", ["ftp://exemplo.invalid/a", "file:///c:/a.txt", "/so/caminho", "https:///sem-servidor", ""])
def test_separar_url_recusa_o_que_nao_e_http(url):
    with pytest.raises(ValueError):
        separar_url(url)


def test_url_dos_tickers_e_aceita():
    from primeiro_preco import URL_TICKERS  # noqa: PLC0415

    seguro, servidor, porta, caminho = separar_url(URL_TICKERS)
    assert (seguro, servidor, porta) == (True, "api.binance.com", 443)
    assert caminho.startswith("/api/v3/ticker/24hr?symbols=")


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows o WinHTTP existe")
def test_fora_do_windows_falha_com_erro_de_requisicao():
    with pytest.raises(ErroDeRequisicao):
        baixar("http://127.0.0.1:9/nada", 1)


# ---------------------------------------------------------------------------
# Fluxo de chamadas, com uma winhttp.dll falsa (qualquer sistema)
# ---------------------------------------------------------------------------

class WinHttpFalsa:
    """Registra as chamadas e entrega um corpo em blocos; "falhar" faz uma função devolver 0."""

    def __init__(self, corpo: bytes = b"[]", status: int = 200, falhar: str | None = None) -> None:
        self.corpo, self.status, self.falhar = corpo, status, falhar
        self.chamadas: list[tuple] = []
        self.fechados: list[int] = []
        self._lido = 0

    def _resultado(self, nome: str, valor):
        return 0 if self.falhar == nome else valor

    def WinHttpOpen(self, agente, acesso, proxy, desvio, flags):  # noqa: N802
        self.chamadas.append(("WinHttpOpen", acesso, proxy))
        return self._resultado("WinHttpOpen", 101)

    def WinHttpSetTimeouts(self, sessao, *prazos):  # noqa: N802
        self.chamadas.append(("WinHttpSetTimeouts", sessao, prazos))
        return self._resultado("WinHttpSetTimeouts", 1)

    def WinHttpConnect(self, sessao, servidor, porta, reservado):  # noqa: N802
        self.chamadas.append(("WinHttpConnect", sessao, servidor, porta))
        return self._resultado("WinHttpConnect", 102)

    def WinHttpOpenRequest(self, conexao, verbo, caminho, versao, origem, tipos, flags):  # noqa: N802
        self.chamadas.append(("WinHttpOpenRequest", conexao, verbo, caminho, flags))
        return self._resultado("WinHttpOpenRequest", 103)

    def WinHttpSendRequest(self, pedido, cabecalhos, comprimento, corpo, n1, n2, contexto):  # noqa: N802
        self.chamadas.append(("WinHttpSendRequest", pedido, cabecalhos, comprimento))
        return self._resultado("WinHttpSendRequest", 1)

    def WinHttpReceiveResponse(self, pedido, reservado):  # noqa: N802
        return self._resultado("WinHttpReceiveResponse", 1)

    def WinHttpQueryHeaders(self, pedido, nivel, nome, destino, tamanho, indice):  # noqa: N802
        self.chamadas.append(("WinHttpQueryHeaders", pedido, nivel))
        destino._obj.value = self.status  # byref(status)
        return self._resultado("WinHttpQueryHeaders", 1)

    def WinHttpReadData(self, pedido, bloco, tamanho, lidos):  # noqa: N802
        parte = self.corpo[self._lido:self._lido + tamanho]
        ctypes.memmove(bloco, parte, len(parte))
        self._lido += len(parte)
        lidos._obj.value = len(parte)
        return self._resultado("WinHttpReadData", 1)

    def WinHttpCloseHandle(self, handle):  # noqa: N802
        self.fechados.append(handle)
        return 1


@pytest.fixture
def com_dll_falsa(monkeypatch):
    def instalar(**opcoes) -> WinHttpFalsa:
        dll = WinHttpFalsa(**opcoes)
        # O ctypes de verdade, mais o get_last_error (que só existe no Windows) fixo em 12002.
        ctypes_falso = types.SimpleNamespace(
            byref=ctypes.byref, sizeof=ctypes.sizeof, c_ulong=ctypes.c_ulong,
            create_string_buffer=ctypes.create_string_buffer, get_last_error=lambda: 12002)
        monkeypatch.setattr(baixar_winhttp, "_carregar", lambda: (dll, ctypes_falso))
        monkeypatch.setattr(baixar_winhttp.sys, "platform", "win32")
        return dll
    return instalar


def test_fluxo_https_devolve_o_corpo_e_fecha_os_handles(com_dll_falsa):
    corpo = b"x" * (baixar_winhttp.TAMANHO_BLOCO * 2 + 7)  # três leituras e a leitura vazia do fim
    dll = com_dll_falsa(corpo=corpo)
    assert baixar("https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%5D", 5) == corpo

    nomes = [chamada[0] for chamada in dll.chamadas]
    assert nomes == ["WinHttpOpen", "WinHttpSetTimeouts", "WinHttpConnect", "WinHttpOpenRequest",
                     "WinHttpSendRequest", "WinHttpQueryHeaders"]
    assert dll.chamadas[0] == ("WinHttpOpen", baixar_winhttp.WINHTTP_ACCESS_TYPE_NO_PROXY, None)
    assert dll.chamadas[1] == ("WinHttpSetTimeouts", 101, (5000, 5000, 5000, 5000))
    assert dll.chamadas[2] == ("WinHttpConnect", 101, "api.binance.com", 443)
    assert dll.chamadas[3] == ("WinHttpOpenRequest", 102, "GET", "/api/v3/ticker/24hr?symbols=%5B%5D",
                               baixar_winhttp.WINHTTP_FLAG_SECURE)
    assert dll.chamadas[4] == ("WinHttpSendRequest", 103, "Accept: application/json\r\n", 0xFFFFFFFF)
    assert dll.chamadas[5] == ("WinHttpQueryHeaders", 103, 19 | 0x20000000)
    assert dll.fechados == [103, 102, 101]  # pedido, conexão e sessão, nessa ordem


def test_marcar_recebe_as_etapas_da_requisicao_na_ordem(com_dll_falsa):
    com_dll_falsa(corpo=b"ok")
    etapas: list[str] = []
    assert baixar("https://exemplo.invalid/t", 1, marcar=etapas.append) == b"ok"
    assert etapas == ["preco_python_enviado", "preco_python_cabecalhos"]


def test_marcar_para_na_etapa_que_falhou(com_dll_falsa):
    com_dll_falsa(falhar="WinHttpReceiveResponse")
    etapas: list[str] = []
    with pytest.raises(ErroDeRequisicao):
        baixar("https://exemplo.invalid/t", 1, marcar=etapas.append)
    assert etapas == ["preco_python_enviado"]


def test_http_simples_nao_pede_tls(com_dll_falsa):
    dll = com_dll_falsa(corpo=b"ok")
    assert baixar("http://127.0.0.1:8123/t", 0.25) == b"ok"
    assert dll.chamadas[1][2] == (250, 250, 250, 250)
    assert dll.chamadas[2] == ("WinHttpConnect", 101, "127.0.0.1", 8123)
    assert dll.chamadas[3][-1] == 0


def test_status_diferente_de_200_e_erro_e_fecha_os_handles(com_dll_falsa):
    dll = com_dll_falsa(status=500)
    with pytest.raises(ErroDeRequisicao, match="HTTP 500"):
        baixar("http://127.0.0.1:8123/t", 1)
    assert dll.fechados == [103, 102, 101]


@pytest.mark.parametrize("funcao,abertos", [
    ("WinHttpOpen", []),
    ("WinHttpSetTimeouts", [101]),
    ("WinHttpConnect", [101]),
    ("WinHttpOpenRequest", [102, 101]),
    ("WinHttpSendRequest", [103, 102, 101]),
    ("WinHttpReceiveResponse", [103, 102, 101]),
    ("WinHttpQueryHeaders", [103, 102, 101]),
    ("WinHttpReadData", [103, 102, 101]),
])
def test_falha_em_cada_etapa_diz_a_funcao_e_fecha_o_que_abriu(com_dll_falsa, funcao, abertos):
    dll = com_dll_falsa(falhar=funcao)
    with pytest.raises(ErroDeRequisicao, match=f"{funcao} falhou: erro 12002 \\(tempo esgotado\\)"):
        baixar("https://exemplo.invalid/t", 1)
    assert dll.fechados == abertos


def test_resposta_grande_demais_e_recusada(com_dll_falsa, monkeypatch):
    monkeypatch.setattr(baixar_winhttp, "TAMANHO_MAXIMO", 100)
    dll = com_dll_falsa(corpo=b"x" * 101)
    with pytest.raises(ErroDeRequisicao, match="maior que 100"):
        baixar("http://127.0.0.1:8123/t", 1)
    assert dll.fechados == [103, 102, 101]


# ---------------------------------------------------------------------------
# A winhttp.dll de verdade, contra um servidor HTTP local (só no Windows)
# ---------------------------------------------------------------------------

@pytest.fixture
def servidor():
    config = {"corpo": b"[]", "status": 200, "atraso": 0.0, "cabecalhos": []}

    class Tratador(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            config["cabecalhos"].append(dict(self.headers))
            config["caminho"] = self.path
            time.sleep(config["atraso"])
            self.send_response(config["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(config["corpo"])))
            self.end_headers()
            self.wfile.write(config["corpo"])

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    config["porta"] = http.server_address[1]
    config["url"] = f"http://127.0.0.1:{config['porta']}/tickers?symbols=%5B%22BTCBRL%22%5D"
    yield config
    http.shutdown()
    http.server_close()


@so_no_windows
def test_winhttp_de_verdade_devolve_o_corpo(servidor):
    servidor["corpo"] = json.dumps([{"symbol": "BTCBRL"}]).encode()
    assert baixar(servidor["url"], 5) == servidor["corpo"]
    assert servidor["caminho"] == "/tickers?symbols=%5B%22BTCBRL%22%5D"  # sem escapar de novo o "%"
    assert servidor["cabecalhos"][0].get("Accept") == "application/json"


@so_no_windows
def test_winhttp_de_verdade_le_resposta_maior_que_um_bloco(servidor):
    servidor["corpo"] = bytes(range(256)) * 200  # 51 200 bytes: mais de 3 blocos
    assert baixar(servidor["url"], 5) == servidor["corpo"]


@so_no_windows
def test_winhttp_de_verdade_status_de_erro(servidor):
    servidor["status"] = 500
    with pytest.raises(ErroDeRequisicao, match="HTTP 500"):
        baixar(servidor["url"], 5)


@so_no_windows
def test_winhttp_de_verdade_respeita_o_prazo(servidor):
    servidor["atraso"] = 3.0
    inicio = time.monotonic()
    with pytest.raises(ErroDeRequisicao):
        baixar(servidor["url"], 0.3)
    assert time.monotonic() - inicio < 2.5


@so_no_windows
def test_winhttp_de_verdade_sem_servidor_na_porta(servidor):
    porta_livre = servidor["porta"]
    # Outra porta, sem ninguém escutando: a do servidor + 1 pode estar em uso; usa a 9 (discard).
    with pytest.raises(ErroDeRequisicao):
        baixar("http://127.0.0.1:9/nada", 2)
    assert baixar(f"http://127.0.0.1:{porta_livre}/t", 5) == b"[]"  # o módulo continua utilizável


@so_no_windows
def test_winhttp_de_verdade_em_varias_threads(servidor):
    servidor["corpo"] = b"[1, 2, 3]"
    resultados: list[bytes] = []
    trava = threading.Lock()

    def uma():
        dados = baixar(servidor["url"], 5)
        with trava:
            resultados.append(dados)

    threads = [threading.Thread(target=uma) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert resultados == [b"[1, 2, 3]"] * 8


# ---------------------------------------------------------------------------
# HTTPS de verdade (opcional: BTC_REDE_REAL=1)
# ---------------------------------------------------------------------------

@so_no_windows
@pytest.mark.skipif(os.getenv("BTC_REDE_REAL") != "1", reason="usa a internet: rodar com BTC_REDE_REAL=1")
def test_https_de_verdade_na_binance():
    from primeiro_preco import URL_TICKERS, validar_tickers  # noqa: PLC0415

    dados = validar_tickers(json.loads(baixar(URL_TICKERS, 8)))
    assert {item["symbol"] for item in dados} == {"BTCBRL", "BTCUSDT"}
