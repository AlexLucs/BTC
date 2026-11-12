"""primeiro_preco.py: busca do 1º preço pelo Python (servidor HTTP local no lugar da Binance)."""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from primeiro_preco import URL_TICKERS, BuscaPrimeiroPreco, validar_tickers  # noqa: E402

TICKERS = [{"symbol": "BTCBRL", "lastPrice": "500000"}, {"symbol": "BTCUSDT", "lastPrice": "90000"}]


class MetricasFalsas:
    def __init__(self) -> None:
        self.marcos: list[str] = []

    def marcar(self, nome: str) -> None:
        self.marcos.append(nome)


@pytest.fixture
def servidor():
    """Servidor local; resposta e atraso configuráveis por teste."""
    config = {"corpo": json.dumps(TICKERS).encode(), "status": 200, "atraso": 0.0, "pedidos": 0}

    class Tratador(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            config["pedidos"] += 1
            time.sleep(config["atraso"])
            self.send_response(config["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(config["corpo"])

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    config["url"] = f"http://127.0.0.1:{http.server_address[1]}/tickers"
    yield config
    http.shutdown()


def test_url_igual_a_do_script_js():
    script = (Path(__file__).resolve().parent.parent / "script.js").read_text(encoding="utf-8")
    assert "https://api.binance.com/api/v3/ticker/24hr?symbols=" in script
    assert URL_TICKERS == "https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%22BTCBRL%22%2C%22BTCUSDT%22%5D"


def test_entrega_os_dados_uma_vez_so(servidor):
    metricas = MetricasFalsas()
    busca = BuscaPrimeiroPreco(metricas, url=servidor["url"])
    busca.iniciar()
    busca.iniciar()  # a 2ª chamada não faz outra requisição
    assert busca.resultado(espera_s=5) == TICKERS
    assert busca.resultado(espera_s=5) is None  # já entregue (ex.: página recarregada)
    assert servidor["pedidos"] == 1
    assert metricas.marcos == ["preco_python_inicio", "preco_python_resposta"]


def test_sem_iniciar_nao_espera_nem_entrega():
    busca = BuscaPrimeiroPreco(MetricasFalsas(), url="http://127.0.0.1:9/nada")
    inicio = time.monotonic()
    assert busca.resultado(espera_s=5) is None
    assert time.monotonic() - inicio < 0.5


@pytest.mark.parametrize("status,corpo", [(500, b"{}"), (200, b"nao e json"), (200, b'{"symbol": "BTCBRL"}'), (200, b"[]")])
def test_falha_ou_resposta_invalida_devolve_none(servidor, status, corpo):
    servidor["status"], servidor["corpo"] = status, corpo
    metricas = MetricasFalsas()
    busca = BuscaPrimeiroPreco(metricas, url=servidor["url"])
    busca.iniciar()
    assert busca.resultado(espera_s=5) is None
    assert metricas.marcos == ["preco_python_inicio", "preco_python_falha"]


def test_resposta_demorada_nao_segura_a_chamada_alem_da_espera(servidor):
    servidor["atraso"] = 1.0
    busca = BuscaPrimeiroPreco(MetricasFalsas(), url=servidor["url"])
    busca.iniciar()
    inicio = time.monotonic()
    assert busca.resultado(espera_s=0.2) is None
    assert time.monotonic() - inicio < 0.6
    assert busca.resultado(espera_s=5) == TICKERS  # quem perguntar depois ainda recebe


def test_resultado_velho_demais_nao_e_entregue(servidor):
    busca = BuscaPrimeiroPreco(MetricasFalsas(), url=servidor["url"], validade_s=0.1)
    busca.iniciar()
    busca._pronto.wait(5)
    time.sleep(0.2)
    assert busca.resultado(espera_s=1) is None


def test_validar_tickers():
    assert validar_tickers(TICKERS) == TICKERS
    for invalido in ([], {}, [1], [{"preco": 1}], None):
        with pytest.raises(ValueError):
            validar_tickers(invalido)
