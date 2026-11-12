"""Servidor local da página (http://127.0.0.1:42001/), no lugar do servidor padrão do pywebview.

O pywebview aceita um aplicativo WSGI como "url" do create_window e o serve na porta
pedida (http_port). Com isso a página ganha o endereço /preco-inicial: o 1º preço que o
Python buscou durante a abertura (primeiro_preco.py) chega à página logo que o script.js
começa, sem esperar o "load" nem a ponte do pywebview.

A ponte JS→Python não passa por este servidor: no Windows (EdgeChromium) ela usa as
mensagens do WebView2 (chrome.webview.postMessage).

O bottle já é dependência obrigatória do pywebview e já é importado com ele.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path

import bottle

# Mesma porta que o pywebview usa com o perfil persistente (settings["DEFAULT_HTTP_PORT"]):
# a origem continua http://127.0.0.1:42001 e o localStorage (último estado) é mantido.
PORTA = 42001
# Só estes arquivos são entregues (o servidor padrão entregava qualquer arquivo da pasta),
# com o tipo já definido. Sem o tipo, o bottle (static_file) chama mimetypes.guess_type, e a
# 1ª chamada do processo lê a tabela de tipos do registro do Windows (mimetypes.init ->
# read_windows_registry, ~22 ms). Na abertura, os 4 pedidos simultâneos faziam isso ao mesmo
# tempo e seguravam CSS e JS por ~60 ms. O registro também pode trazer tipos errados.
ARQUIVOS_DA_PAGINA = {
    "style.css": "text/css",
    "metricas.js": "application/javascript",
    "regras.js": "application/javascript",
    "script.js": "application/javascript",
    "Roboto.woff2": "font/woff2",
    "btc-logo.svg": "image/svg+xml",
    "alerta.mp3": "audio/mpeg",
}
# Os mesmos cabeçalhos do servidor padrão do pywebview 6.2.1.
CABECALHOS_SEM_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}
# Preload da fonte: por file:// (navegador e testes) o Chromium só o aproveita SEM
# "crossorigin"; por http (o app) só COM ele. O index.html vem sem, e este servidor o
# acrescenta. Sem o ajuste, a fonte é lida duas vezes e o preload é descartado.
PRELOAD_FONTE = '<link rel="preload" href="Roboto.woff2" as="font" type="font/woff2">'
PRELOAD_FONTE_HTTP = '<link rel="preload" href="Roboto.woff2" as="font" type="font/woff2" crossorigin>'


def ajustar_preload_para_http(html: str) -> str:
    return html.replace(PRELOAD_FONTE, PRELOAD_FONTE_HTTP, 1)


# Preço no HTML: se o Python já tem o 1º preço quando a página pede o "/", ele vai dentro do
# HTML num bloco de dados (não é executado, então a CSP não muda) e o script.js o lê no
# DOMContentLoaded, antes do "load" e da injeção da ponte pelo pywebview (~50 ms de JS dele
# executados na página logo depois do "load"). Senão, a página usa /preco-inicial.
ID_PRECO_NO_HTML = "preco-inicial"


def embutir_preco(html: str, dados: list) -> str:
    """Acrescenta o bloco de dados antes do </head>. "<" vira \\u003c: o texto nunca fecha a tag."""
    texto = json.dumps(dados).replace("<", "\\u003c")
    bloco = f'<script type="application/json" id="{ID_PRECO_NO_HTML}">{texto}</script>\n'
    return html.replace("</head>", bloco + "</head>", 1)


# Quanto /preco-inicial espera a busca do Python terminar. A página corre o REST em
# paralelo e usa o que chegar antes, então esperar aqui nunca atrasa o 1º preço.
ESPERA_PRECO_INICIAL_S = 1.5


class _AoTerminar:
    """Corpo de resposta WSGI que avisa quando o servidor terminou de enviá-lo (close())."""

    def __init__(self, corpo: Iterable[bytes], ao_terminar: Callable[[], None]) -> None:
        self._corpo, self._ao_terminar = corpo, ao_terminar

    def __iter__(self):
        return iter(self._corpo)

    def close(self) -> None:
        try:
            if hasattr(self._corpo, "close"):
                self._corpo.close()
        finally:
            self._ao_terminar()


def criar_aplicativo(pasta: Path, html_da_pagina: Callable[[], str], busca_preco,
                     ajustar_preload: bool = True, tipos_fixos: bool = True, preco_no_html: bool = True,
                     marcar: Callable[[str], None] | None = None):
    """Aplicativo WSGI da página.

    Args:
        pasta: onde estão os arquivos da página.
        html_da_pagina: devolve o HTML de "/" (lido a cada pedido).
        busca_preco: objeto com resultado(espera_s) -> list | None (BuscaPrimeiroPreco).
        ajustar_preload: acrescenta "crossorigin" ao preload da fonte (desligado só na medição).
        tipos_fixos: entrega os arquivos com o tipo de ARQUIVOS_DA_PAGINA, sem consultar o
            mimetypes (desligado só na medição).
        preco_no_html: embute no HTML o 1º preço, se o Python já o tiver (desligado só na medição).
        marcar: só na medição; recebe os marcos servidor_pedido:<arquivo> (o pedido chegou
            ao aplicativo) e servidor_fim:<arquivo> (o servidor terminou de enviar a resposta).
    """
    aplicativo = _criar_rotas(pasta, html_da_pagina, busca_preco, ajustar_preload, tipos_fixos,
                              preco_no_html, marcar or (lambda nome: None))
    if marcar is None:
        return aplicativo

    def com_marcos(environ, start_response):
        arquivo = environ.get("PATH_INFO", "/").rsplit("/", 1)[-1] or "index.html"
        marcar(f"servidor_pedido:{arquivo}")
        return _AoTerminar(aplicativo(environ, start_response), lambda: marcar(f"servidor_fim:{arquivo}"))

    return com_marcos


def _criar_rotas(pasta: Path, html_da_pagina: Callable[[], str], busca_preco, ajustar_preload: bool,
                 tipos_fixos: bool, preco_no_html: bool, marcar: Callable[[str], None]) -> bottle.Bottle:
    aplicativo = bottle.Bottle()

    def sem_cache(resposta: bottle.BaseResponse) -> bottle.BaseResponse:
        for nome, valor in CABECALHOS_SEM_CACHE.items():
            resposta.set_header(nome, valor)
        return resposta

    @aplicativo.get("/")
    @aplicativo.get("/index.html")
    def pagina():
        html = html_da_pagina()
        if ajustar_preload:
            html = ajustar_preload_para_http(html)
        if preco_no_html and "</head>" in html:
            dados = busca_preco.resultado(0)  # sem esperar; a entrega é única
            if dados is not None:
                html = embutir_preco(html, dados)
                marcar("servidor_preco_no_html")
        return sem_cache(bottle.HTTPResponse(html, status=200,
                                             headers={"Content-Type": "text/html; charset=utf-8"}))

    @aplicativo.get("/preco-inicial")
    def preco_inicial():
        dados = busca_preco.resultado(ESPERA_PRECO_INICIAL_S)
        if dados is None:
            return sem_cache(bottle.HTTPResponse(status=204))
        return sem_cache(bottle.HTTPResponse(json.dumps(dados), status=200,
                                             headers={"Content-Type": "application/json"}))

    @aplicativo.get("/<nome>")
    def arquivo(nome: str):
        if nome not in ARQUIVOS_DA_PAGINA:
            return bottle.HTTPError(404, "Não encontrado")
        tipo = ARQUIVOS_DA_PAGINA[nome] if tipos_fixos else True  # True: o bottle adivinha (mimetypes)
        return sem_cache(bottle.static_file(nome, root=str(pasta), mimetype=tipo))

    return aplicativo
