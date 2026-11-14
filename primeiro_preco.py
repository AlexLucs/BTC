"""Busca o 1º preço da Binance pelo Python, em paralelo com a abertura da janela.

A página só existe depois que o .NET e o WebView2 sobem (~600 ms), e só então começaria a
pedir o preço (~350-500 ms de rede). Aqui a mesma requisição sai numa thread logo que o
script começa, ANTES dos imports pesados do app (ver o início de BTC_Monitor.py), e o
servidor local (servidor_local.py) entrega o resultado à página dentro do HTML ou em
/preco-inicial.

Por isso este módulo é leve de propósito: no topo só importa threading e time. O json, o
logging e o baixar_winhttp são importados dentro da thread (não mudar: cada import no topo
atrasa o início da requisição).

A requisição vai pelo WinHTTP do Windows (baixar_winhttp.py), não pelo urllib: assim o
executável não precisa do módulo ssl nem do OpenSSL (ver exclusoes_build.py).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

# Mesmo pedido do script.js (URL_TICKERS): os dois pares numa requisição só. O valor de
# "symbols" é ["BTCBRL","BTCUSDT"] já codificado (escrito à mão para não importar o
# urllib.parse aqui; tests/test_primeiro_preco.py confere com urllib.parse.quote).
URL_TICKERS = "https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%22BTCBRL%22%2C%22BTCUSDT%22%5D"
TIMEOUT_S = 5.0
# Um preço mais velho que isto não é entregue à página (ela busca pelo REST).
VALIDADE_S = 15.0
NOME_DO_LOG = "btcstatus.primeiro_preco"


def validar_tickers(dados) -> list[dict]:
    """A resposta precisa ser uma lista de objetos com "symbol" (o script.js valida os campos)."""
    if not isinstance(dados, list) or not dados or not all(isinstance(item, dict) and "symbol" in item for item in dados):
        raise ValueError("resposta da Binance em formato inesperado")
    return dados


class BuscaPrimeiroPreco:
    """Uma requisição, feita uma vez numa thread; o resultado é entregue no máximo uma vez."""

    def __init__(self, metricas=None, url: str = URL_TICKERS, timeout_s: float = TIMEOUT_S,
                 validade_s: float = VALIDADE_S,
                 baixar: Callable[[str, float], bytes] | None = None,
                 adiar_log: bool = False) -> None:
        """
        Args:
            metricas: objeto com marcar(nome). None: os marcos ficam guardados, com o
                instante de cada um, até ligar_metricas() (o app inicia a busca antes de
                o registro de métricas existir).
            url: endereço dos tickers.
            timeout_s: prazo de cada etapa da requisição.
            validade_s: idade máxima do resultado para ser entregue.
            baixar: função (url, timeout_s) -> corpo da resposta; None usa o WinHTTP
                (baixar_winhttp.baixar). Os testes fora do Windows passam outra.
            adiar_log: guarda o aviso de falha até liberar_log(). O app inicia a busca
                antes de configurar o log em arquivo; sem isto, uma falha rápida (ex.:
                sem internet) não ficaria no btcstatus.log.
        """
        self._log_liberado = not adiar_log
        self._falha_a_registrar: str | None = None
        self._metricas = metricas
        self._marcos_guardados: list[tuple[str, float]] = []
        self._baixar = baixar
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
        """Dispara a requisição numa thread. Chamadas seguintes não fazem nada."""
        with self._trava:
            if self._iniciada:
                return
            self._iniciada = True
        threading.Thread(target=self._buscar, name="primeiro-preco", daemon=True).start()

    def ligar_metricas(self, metricas) -> None:
        """Passa a registrar os marcos em metricas e entrega os já guardados, cada um com
        o instante em que ocorreu: metricas.marcar(nome, instante de time.perf_counter())."""
        with self._trava:
            self._metricas = metricas
            guardados, self._marcos_guardados = self._marcos_guardados, []
        for nome, instante in guardados:
            metricas.marcar(nome, instante)

    def liberar_log(self) -> None:
        """O log já está configurado: registra a falha guardada, se houve, e as próximas na hora."""
        with self._trava:
            self._log_liberado = True
            falha, self._falha_a_registrar = self._falha_a_registrar, None
        if falha is not None:
            self._registrar_falha(falha)

    @staticmethod
    def _registrar_falha(falha: str) -> None:
        import logging  # noqa: PLC0415 - aqui, e não no topo: ver a docstring do módulo

        logging.getLogger(NOME_DO_LOG).warning("1º preço pelo Python falhou: %s", falha)

    def _marcar(self, nome: str) -> None:
        with self._trava:
            metricas = self._metricas
            if metricas is None:
                self._marcos_guardados.append((nome, time.perf_counter()))
                return
        metricas.marcar(nome)

    def _buscar(self) -> None:
        self._marcar("preco_python_inicio")
        try:
            import json  # noqa: PLC0415 - aqui, e não no topo: ver a docstring do módulo

            if self._baixar is None:
                from baixar_winhttp import baixar  # noqa: PLC0415

                corpo = baixar(self._url, self._timeout_s, marcar=self._marcar)
            else:
                corpo = self._baixar(self._url, self._timeout_s)
            dados = validar_tickers(json.loads(corpo))
            self._dados = dados
            self._recebido_em = time.monotonic()
            self._marcar("preco_python_resposta")
        except Exception as erro:  # noqa: BLE001 - qualquer falha: a página usa o REST
            with self._trava:
                registrar_agora = self._log_liberado
                if not registrar_agora:
                    self._falha_a_registrar = str(erro)
            if registrar_agora:
                self._registrar_falha(str(erro))
            self._marcar("preco_python_falha")
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
