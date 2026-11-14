"""primeiro_preco.py: busca do 1º preço pelo Python (servidor HTTP local no lugar da Binance).

No Windows a requisição vai pelo WinHTTP, como no app (baixar_winhttp.py). Fora do Windows
o WinHTTP não existe: os testes passam um "baixar" de apoio (urllib) e conferem só a
lógica da BuscaPrimeiroPreco.
"""

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


def baixar_de_apoio(url: str, timeout_s: float) -> bytes:
    """Só para os testes fora do Windows (o app usa o WinHTTP)."""
    import urllib.request  # noqa: PLC0415

    with urllib.request.urlopen(url, timeout=timeout_s) as resposta:
        return resposta.read()


# None: a BuscaPrimeiroPreco usa o WinHTTP, como no app.
BAIXAR = None if sys.platform == "win32" else baixar_de_apoio
# Com o WinHTTP, a requisição também marca as etapas dela (só a medição as usa).
ETAPAS_DO_WINHTTP = ["preco_python_enviado", "preco_python_cabecalhos"] if BAIXAR is None else []


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
    busca = BuscaPrimeiroPreco(metricas, url=servidor["url"], baixar=BAIXAR)
    busca.iniciar()
    busca.iniciar()  # a 2ª chamada não faz outra requisição
    assert busca.resultado(espera_s=5) == TICKERS
    assert busca.resultado(espera_s=5) is None  # já entregue (ex.: página recarregada)
    assert servidor["pedidos"] == 1
    assert metricas.marcos == ["preco_python_inicio", *ETAPAS_DO_WINHTTP, "preco_python_resposta"]


def test_sem_iniciar_nao_espera_nem_entrega():
    busca = BuscaPrimeiroPreco(MetricasFalsas(), url="http://127.0.0.1:9/nada")
    inicio = time.monotonic()
    assert busca.resultado(espera_s=5) is None
    assert time.monotonic() - inicio < 0.5


@pytest.mark.parametrize("status,corpo", [(500, b"{}"), (200, b"nao e json"), (200, b'{"symbol": "BTCBRL"}'), (200, b"[]")])
def test_falha_ou_resposta_invalida_devolve_none(servidor, status, corpo):
    servidor["status"], servidor["corpo"] = status, corpo
    metricas = MetricasFalsas()
    busca = BuscaPrimeiroPreco(metricas, url=servidor["url"], baixar=BAIXAR)
    busca.iniciar()
    assert busca.resultado(espera_s=5) is None
    # Com status 500 o WinHTTP chega a enviar e a receber os cabeçalhos antes de falhar.
    assert metricas.marcos == ["preco_python_inicio", *ETAPAS_DO_WINHTTP, "preco_python_falha"]


def test_resposta_demorada_nao_segura_a_chamada_alem_da_espera(servidor):
    servidor["atraso"] = 1.0
    busca = BuscaPrimeiroPreco(MetricasFalsas(), url=servidor["url"], baixar=BAIXAR)
    busca.iniciar()
    inicio = time.monotonic()
    assert busca.resultado(espera_s=0.2) is None
    assert time.monotonic() - inicio < 0.6
    assert busca.resultado(espera_s=5) == TICKERS  # quem perguntar depois ainda recebe


def test_resultado_velho_demais_nao_e_entregue(servidor):
    busca = BuscaPrimeiroPreco(MetricasFalsas(), url=servidor["url"], baixar=BAIXAR, validade_s=0.1)
    busca.iniciar()
    busca._pronto.wait(5)
    time.sleep(0.2)
    assert busca.resultado(espera_s=1) is None


def test_baixar_e_injetavel_e_recebe_url_e_prazo():
    chamadas = []

    def baixar(url: str, timeout_s: float) -> bytes:
        chamadas.append((url, timeout_s))
        return json.dumps(TICKERS).encode()

    busca = BuscaPrimeiroPreco(MetricasFalsas(), url="https://exemplo.invalid/t", timeout_s=3.5, baixar=baixar)
    busca.iniciar()
    assert busca.resultado(espera_s=5) == TICKERS
    assert chamadas == [("https://exemplo.invalid/t", 3.5)]


def test_erro_do_baixar_vira_falha_sem_derrubar_a_thread():
    def baixar(url: str, timeout_s: float) -> bytes:
        raise OSError("sem rede")

    metricas = MetricasFalsas()
    busca = BuscaPrimeiroPreco(metricas, baixar=baixar)
    busca.iniciar()
    assert busca.resultado(espera_s=5) is None
    assert metricas.marcos == ["preco_python_inicio", "preco_python_falha"]


def test_primeiro_preco_nao_usa_mais_o_urllib_request():
    """O urllib.request traria de volta a dependência do ssl (ver exclusoes_build.py)."""
    fonte = (Path(__file__).resolve().parent.parent / "primeiro_preco.py").read_text(encoding="utf-8")
    assert "urllib.request" not in fonte
    assert "from baixar_winhttp import baixar" in fonte


def test_url_e_a_lista_dos_dois_pares_codificada():
    """A URL está escrita à mão (o módulo não importa o urllib.parse): confere a codificação."""
    from urllib.parse import quote  # noqa: PLC0415

    assert URL_TICKERS == ("https://api.binance.com/api/v3/ticker/24hr?symbols="
                           + quote('["BTCBRL","BTCUSDT"]', safe=""))


def test_importar_o_modulo_e_leve():
    """A requisição sai antes dos imports pesados do app: o próprio módulo não pode trazer
    json, logging, urllib.parse nem ctypes no import (só dentro da thread)."""
    import subprocess  # noqa: PLC0415

    codigo = ("import sys; antes = set(sys.modules); import primeiro_preco; "
              "print(sorted(m for m in ('json', 'logging', 'urllib.parse', 'ctypes', 'baixar_winhttp') "
              "if m in sys.modules and m not in antes))")
    saida = subprocess.run([sys.executable, "-S", "-c", codigo], cwd=Path(__file__).resolve().parent.parent,
                           capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, saida.stderr
    assert saida.stdout.strip() == "[]"


class MetricasComInstante:
    def __init__(self) -> None:
        self.marcos: list[tuple] = []

    def marcar(self, nome: str, instante_perf: float | None = None) -> None:
        self.marcos.append((nome, instante_perf))


def test_marcos_antes_de_ligar_as_metricas_sao_guardados_com_o_instante():
    """No app a busca começa antes de o registro de métricas existir."""
    liberar = threading.Event()

    def baixar(url: str, timeout_s: float) -> bytes:
        liberar.wait(5)
        return json.dumps(TICKERS).encode()

    busca = BuscaPrimeiroPreco(baixar=baixar)
    antes = time.perf_counter()
    busca.iniciar()
    time.sleep(0.05)  # a thread já marcou o início; ainda não há onde registrar
    metricas = MetricasComInstante()
    depois = time.perf_counter()
    busca.ligar_metricas(metricas)
    assert [nome for nome, _ in metricas.marcos] == ["preco_python_inicio"]
    assert antes <= metricas.marcos[0][1] <= depois, "o marco guardado leva o instante em que ocorreu"

    liberar.set()
    assert busca.resultado(espera_s=5) == TICKERS
    # Depois de ligadas, os marcos vão direto (sem instante: é o de agora).
    assert metricas.marcos[1:] == [("preco_python_resposta", None)]


def test_sem_metricas_a_busca_funciona_e_nao_falha():
    busca = BuscaPrimeiroPreco(baixar=lambda url, timeout_s: json.dumps(TICKERS).encode())
    busca.iniciar()
    assert busca.resultado(espera_s=5) == TICKERS


def falhar(url: str, timeout_s: float) -> bytes:
    raise OSError("sem rede")


def test_falha_e_registrada_no_log_na_hora(caplog):
    busca = BuscaPrimeiroPreco(baixar=falhar)
    with caplog.at_level("WARNING", logger="btcstatus.primeiro_preco"):
        busca.iniciar()
        assert busca.resultado(espera_s=5) is None
        busca._pronto.wait(5)
    assert [r.getMessage() for r in caplog.records] == ["1º preço pelo Python falhou: sem rede"]


def test_com_o_log_adiado_a_falha_so_e_registrada_ao_liberar(caplog):
    """No app a busca começa antes de o log em arquivo existir: a falha rápida (sem
    internet) precisa aparecer no btcstatus.log mesmo assim."""
    busca = BuscaPrimeiroPreco(baixar=falhar, adiar_log=True)
    with caplog.at_level("WARNING", logger="btcstatus.primeiro_preco"):
        busca.iniciar()
        busca._pronto.wait(5)
        assert caplog.records == []
        busca.liberar_log()
        assert [r.getMessage() for r in caplog.records] == ["1º preço pelo Python falhou: sem rede"]
        busca.liberar_log()  # não repete
        assert len(caplog.records) == 1


def test_falha_depois_de_liberar_o_log_e_registrada_na_hora(caplog):
    liberar = threading.Event()

    def falhar_depois(url: str, timeout_s: float) -> bytes:
        liberar.wait(5)
        raise OSError("caiu")

    busca = BuscaPrimeiroPreco(baixar=falhar_depois, adiar_log=True)
    with caplog.at_level("WARNING", logger="btcstatus.primeiro_preco"):
        busca.iniciar()
        busca.liberar_log()
        assert caplog.records == []
        liberar.set()
        busca._pronto.wait(5)
        time.sleep(0.05)
    assert [r.getMessage() for r in caplog.records] == ["1º preço pelo Python falhou: caiu"]


def test_validar_tickers():
    assert validar_tickers(TICKERS) == TICKERS
    for invalido in ([], {}, [1], [{"preco": 1}], None):
        with pytest.raises(ValueError):
            validar_tickers(invalido)
