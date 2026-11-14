"""Apoio aos testes de página com Playwright: rede simulada, navegador e páginas.

Usado por tests/test_pagina_funcional.py e tests/desempenho/test_pagina.py.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from collections import Counter
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sync_api = pytest.importorskip("playwright.sync_api", reason="instale o playwright (requirements-dev.txt)")

INDEX_URL = (RAIZ / "index.html").as_uri()
ACELERACAO = 50
REDE_REAL = os.getenv("BTC_REDE_REAL") == "1"

CORS = {"Access-Control-Allow-Origin": "*"}  # a página é aberta por file:// (origem nula)
# Preço ÷ abertura nos dados simulados: a página calcula 1,23% de variação.
VARIACAO_SIMULADA = 1.0123

WIDGET_SIMULADO = """
(function () {
    const script = document.currentScript;
    const alvo = script.parentElement.querySelector('.tradingview-widget-container__widget');
    const opcoes = JSON.parse(script.textContent);
    const iframe = document.createElement('iframe');
    iframe.src = 'https://s.tradingview.com/simulado.html';
    iframe.style.border = '0';
    iframe.style.display = 'block';
    // Como o widget real: com "autosize" ocupa 100% do pai; senão, o tamanho fixo.
    iframe.style.width = opcoes.autosize ? '100%' : `${opcoes.width}px`;
    iframe.style.height = opcoes.autosize ? '100%' : `${opcoes.height}px`;
    alvo.append(iframe);
})();
"""

ACELERAR_TIMERS = f"""
(() => {{
    const original = window.setTimeout;
    window.setTimeout = (funcao, espera = 0, ...args) =>
        original(funcao, espera >= 1000 ? espera / {ACELERACAO} : espera, ...args);
}})();
"""


def alertas_que_nunca_disparam() -> list[dict]:
    """100 alertas longe do preço simulado (~500 mil): exercitam a checagem sem abrir diálogo."""
    alertas = [{"id": f"m{i}", "valor": 10_000_000 + i * 1000, "tipo": "maior"} for i in range(50)]
    alertas += [{"id": f"n{i}", "valor": 1000 + i, "tipo": "menor"} for i in range(50)]
    return sorted(alertas, key=lambda a: -a["valor"])


class RedeSimulada:
    """Responde Binance, AwesomeAPI, mempool.space e TradingView sem acessar a internet.

    Para testes funcionais: falhar_binance=True faz a Binance falhar; segurar_binance=True
    guarda os pedidos sem responder até liberar_binance() ser chamado.

    WebSocket da Binance: a conexão é aceita e fica muda (o app continua no REST e a
    vigia de silêncio a fecha). As conexões ficam em self.sockets; o teste envia
    mensagens com enviar_ticker() e derruba a conexão com fechar_socket().

    Limitações do Playwright (sync) contornadas aqui: fechar a conexão DENTRO do
    handler da rota trava, e registrar on_close gera KeyError: 'code' na biblioteca.
    """

    def __init__(self) -> None:
        self.preco = 500_000.0
        self.contagem: Counter[str] = Counter()
        self.falhar_binance = False
        self.segurar_binance = False
        self.sockets: list = []
        self.urls_ws: list[str] = []
        # Mensagens de controle que a página enviou (SUBSCRIBE, UNSUBSCRIBE, LIST_SUBSCRIPTIONS).
        self.controles: list[dict] = []
        # "resultado": responde como a Binance; "erro": recusa; None: não responde (conexão morta).
        self.resposta_controle: str | None = "resultado"
        # Respostas da AwesomeAPI e da mempool.space: o teste pode trocá-las entre consultas.
        self.dolar = {"USDBRL": {"bid": "5.00", "ask": "5.02"}}
        self.taxas = {"fastestFee": 3.4, "halfHourFee": 2.1, "hourFee": 1.5, "minimumFee": 1}
        self._segurados: list = []
        self._aleatorio = random.Random(42)

    def liberar_binance(self) -> None:
        self.segurar_binance = False
        segurados, self._segurados = self._segurados, []
        for rota in segurados:
            self._binance(rota)

    def instalar(self, contexto) -> None:
        if REDE_REAL:
            contexto.on("request", lambda req: "api.binance.com" in req.url and self.contagem.update(["binance"]))
            return
        contexto.route("https://api.binance.com/**", self._binance)
        contexto.route_web_socket(re.compile(r"^wss://stream\.binance\.com(:\d+)?/"), self._websocket)
        contexto.route("https://economia.awesomeapi.com.br/**", self._json("dolar"))
        contexto.route("https://mempool.space/**", self._json("taxas"))
        contexto.route("https://s3.tradingview.com/**", lambda rota: rota.fulfill(body=WIDGET_SIMULADO, content_type="application/javascript", headers=CORS))
        contexto.route("https://s.tradingview.com/**", lambda rota: rota.fulfill(body="<html><body style='background:#000'></body></html>", content_type="text/html"))

    def _websocket(self, ws) -> None:
        self.contagem["ws"] += 1
        self.urls_ws.append(ws.url)
        self.sockets.append(ws)
        ws.on_message(lambda texto: self._controle(ws, texto))

    def _controle(self, ws, texto) -> None:
        mensagem = json.loads(texto)
        self.controles.append(mensagem)
        if self.resposta_controle == "resultado":
            assinados = ["btcbrl@miniTicker"] if mensagem["method"] == "LIST_SUBSCRIPTIONS" else None
            ws.send(json.dumps({"result": assinados, "id": mensagem["id"]}))
        elif self.resposta_controle == "erro":
            ws.send(json.dumps({"code": 2, "msg": "Invalid request"}))

    def metodos(self) -> list[str]:
        return [mensagem["method"] for mensagem in self.controles]

    def fechar_socket(self) -> None:
        """Derruba a conexão mais recente, como se a Binance a tivesse encerrado."""
        self.sockets[-1].close(code=1001, reason="teste")

    def enviar_ticker(self, simbolo: str, preco: float, ws=None) -> None:
        """Envia uma mensagem no formato do stream combinado <par>@miniTicker da Binance.

        O miniTicker não traz o percentual: a abertura ("o") é tal que a variação dá 1,23%.
        """
        dados = {"e": "24hrMiniTicker", "E": int(time.time() * 1000), "s": simbolo, "c": f"{preco:.2f}",
                 "o": f"{preco / VARIACAO_SIMULADA:.2f}", "h": f"{preco * 1.01:.2f}", "l": f"{preco * 0.99:.2f}",
                 "v": "100.00000000", "q": "50000000.00000000"}
        (ws or self.sockets[-1]).send(json.dumps({"stream": f"{simbolo.lower()}@miniTicker", "data": dados}))

    def _binance(self, rota) -> None:
        if self.segurar_binance:
            self._segurados.append(rota)
            return
        self.contagem["binance"] += 1
        if self.falhar_binance:
            rota.abort()
            return
        self.preco *= 1 + self._aleatorio.uniform(-0.0005, 0.0005)
        tickers = [
            {"symbol": simbolo, "lastPrice": f"{preco:.2f}", "priceChangePercent": "1.230",
             "openPrice": f"{preco / VARIACAO_SIMULADA:.2f}",
             "highPrice": f"{preco * 1.01:.2f}", "lowPrice": f"{preco * 0.99:.2f}"}
            for simbolo, preco in (("BTCBRL", self.preco), ("BTCUSDT", self.preco / 5.01))
        ]
        rota.fulfill(body=json.dumps(tickers), content_type="application/json", headers=CORS)

    def _json(self, nome: str):
        """Responde com o valor atual de self.<nome> (dolar ou taxas)."""
        def responder(rota) -> None:
            self.contagem[nome] += 1
            rota.fulfill(body=json.dumps(getattr(self, nome)), content_type="application/json", headers=CORS)
        return responder


@pytest.fixture(scope="module")
def navegador():
    escolha = os.getenv("BTC_NAVEGADOR")
    canais = [escolha] if escolha else ["msedge", "chrome", "chromium"]
    with sync_api.sync_playwright() as playwright:
        for canal in canais:
            try:
                if canal == "chromium":
                    instancia = playwright.chromium.launch()
                else:
                    instancia = playwright.chromium.launch(channel=canal)
            except Exception:  # noqa: BLE001 - tenta o próximo navegador
                continue
            yield instancia
            instancia.close()
            return
        pytest.skip("Nenhum navegador encontrado (Edge/Chrome) e Chromium do Playwright não instalado "
                    "(python -m playwright install chromium)")


def nova_pagina(navegador, rede: RedeSimulada, acelerar: bool, com_alertas: bool | list, **opcoes_contexto):
    contexto = navegador.new_context(viewport={"width": 500, "height": 810}, **opcoes_contexto)
    rede.instalar(contexto)
    if acelerar:
        contexto.add_init_script(ACELERAR_TIMERS)
    if com_alertas:
        # True: 100 alertas que nunca disparam; lista: esses alertas.
        alertas = alertas_que_nunca_disparam() if com_alertas is True else com_alertas
        contexto.add_init_script(f"localStorage.setItem('alertasjson', {json.dumps(json.dumps(alertas))});")
    pagina = contexto.new_page()
    erros: list[str] = []
    pagina.on("pageerror", lambda erro: erros.append(str(erro)))
    return contexto, pagina, erros


def estabilizar_websocket(rede: RedeSimulada, pagina, preco: float = 500_000, limite_s: float = 15) -> None:
    """Envia BTC/BRL à conexão mais recente até o app dizer que está recebendo.

    A conexão simulada nasce muda; se o teste demora a mandar a 1ª mensagem, a vigia
    de silêncio do app a derruba e ele reconecta. Por isso sempre se usa a mais recente.
    """
    prazo = time.monotonic() + limite_s
    while time.monotonic() < prazo:
        if rede.sockets:
            rede.enviar_ticker("BTCBRL", preco)
        pagina.wait_for_timeout(40)
        if pagina.evaluate("wsSaudavel"):
            return
    raise AssertionError("o WebSocket simulado não ficou saudável")


def esperar_carregamento(pagina, timeout_ms: int = 20000) -> None:
    pagina.wait_for_function("document.getElementById('tela-carregamento').style.display === 'none'", timeout=timeout_ms)


def metricas_devtools(cdp) -> dict[str, float]:
    cdp.send("HeapProfiler.collectGarbage")
    return {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}




class ServidorDaPagina:
    """O servidor_local.py de verdade, numa porta livre: a página em http://, como no app.

    busca: objeto com resultado(espera_s) -> list | None (no app, BuscaPrimeiroPreco).
    """

    def __init__(self, busca, ajustar_preload: bool = True, **opcoes) -> None:
        import sys
        import threading
        from socketserver import ThreadingMixIn
        from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

        pytest.importorskip("bottle", reason="o bottle vem com o pywebview (requirements.txt)")
        sys.path.insert(0, str(RAIZ))
        import servidor_local

        class Silencioso(WSGIRequestHandler):
            def log_message(self, *args) -> None:
                pass

        class Servidor(ThreadingMixIn, WSGIServer):
            daemon_threads = True

        aplicativo = servidor_local.criar_aplicativo(
            RAIZ, lambda: (RAIZ / "index.html").read_text(encoding="utf-8"), busca, ajustar_preload, **opcoes)
        self._http = make_server("127.0.0.1", 0, aplicativo, server_class=Servidor, handler_class=Silencioso)
        self.url = f"http://127.0.0.1:{self._http.server_port}/"
        threading.Thread(target=self._http.serve_forever, daemon=True).start()

    def fechar(self) -> None:
        self._http.shutdown()
        self._http.server_close()
