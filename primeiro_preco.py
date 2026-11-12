"""Busca o 1º preço da Binance pelo Python, em paralelo com a abertura da janela.

A página só existe depois que o .NET e o WebView2 sobem (~650 ms), e só então começa a
pedir o preço (~375 ms de rede). Aqui a mesma requisição sai logo no início do main(),
numa thread, e a página recebe o resultado pela ponte do pywebview (ExposedApi.primeiro_preco).
A página continua pedindo pelo REST em paralelo e usa o que chegar primeiro.

Só biblioteca padrão; os imports de rede ficam dentro da thread para não atrasar a abertura.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import quote

logger = logging.getLogger("btcstatus.primeiro_preco")

# Mesmo pedido do script.js (URL_TICKERS): os dois pares numa requisição só.
URL_TICKERS = "https://api.binance.com/api/v3/ticker/24hr?symbols=" + quote('["BTCBRL","BTCUSDT"]', safe="")
TIMEOUT_S = 5.0
# Mais velho que isso, o resultado não é entregue (a página usa o REST).
VALIDADE_S = 15.0


def validar_tickers(dados) -> list[dict]:
    """A resposta precisa ser uma lista de objetos com "symbol" (o script.js valida os campos)."""
    if not isinstance(dados, list) or not dados or not all(isinstance(item, dict) and "symbol" in item for item in dados):
        raise ValueError("resposta da Binance em formato inesperado")
    return dados


class BuscaPrimeiroPreco:
    """Uma requisição, feita uma vez numa thread; o resultado é entregue no máximo uma vez."""

    def __init__(self, metricas, url: str = URL_TICKERS, timeout_s: float = TIMEOUT_S,
                 validade_s: float = VALIDADE_S) -> None:
        self._metricas = metricas
        self._url = url
        self._timeout_s = timeout_s
        self._validade_s = validade_s
        self._pronto = threading.Event()
        self._trava = threading.Lock()
        self._iniciada = False
        self._entregue = False
        self._dados: list[dict] | None = None
        self._recebido_em: float | None = None

    def iniciar(self) -> None:
        with self._trava:
            if self._iniciada:
                return
            self._iniciada = True
        threading.Thread(target=self._buscar, name="primeiro-preco", daemon=True).start()

    def _buscar(self) -> None:
        self._metricas.marcar("preco_python_inicio")
        try:
            import urllib.request  # aqui, e não no topo: não pesa na abertura

            pedido = urllib.request.Request(self._url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(pedido, timeout=self._timeout_s) as resposta:
                dados = validar_tickers(json.loads(resposta.read()))
            self._dados = dados
            self._recebido_em = time.monotonic()
            self._metricas.marcar("preco_python_resposta")
        except Exception as erro:  # noqa: BLE001 - qualquer falha: a página usa o REST
            logger.warning("1º preço pelo Python falhou: %s", erro)
            self._metricas.marcar("preco_python_falha")
        finally:
            self._pronto.set()

    def resultado(self, espera_s: float) -> list[dict] | None:
        """Espera a busca terminar (até espera_s) e entrega os dados uma única vez.

        Devolve None se a busca não foi iniciada, falhou, demorou demais, já foi
        entregue ou está velha demais.
        """
        if not self._iniciada or not self._pronto.wait(espera_s):
            return None
        with self._trava:
            if self._entregue or self._dados is None:
                return None
            self._entregue = True
            if time.monotonic() - self._recebido_em > self._validade_s:
                return None
            return self._dados
