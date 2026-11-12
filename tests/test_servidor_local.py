"""servidor_local.py: a página, os arquivos dela e /preco-inicial."""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("bottle", reason="o bottle vem com o pywebview (requirements.txt)")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))

import servidor_local  # noqa: E402

TICKERS = [{"symbol": "BTCBRL", "lastPrice": "1"}]


class BuscaFalsa:
    def __init__(self, dados=None, atraso_s: float = 0.0) -> None:
        self.dados, self.atraso_s, self.esperas = dados, atraso_s, []

    def resultado(self, espera_s: float):
        self.esperas.append(espera_s)
        time.sleep(min(self.atraso_s, espera_s))
        dados, self.dados = self.dados, None  # entrega única, como a BuscaPrimeiroPreco
        return dados


@pytest.fixture
def servidor():
    criados = []

    def criar(busca, **opcoes):
        from apoio_pagina import ServidorDaPagina  # noqa: PLC0415 - exige o playwright só para o import
        s = ServidorDaPagina(busca, **opcoes)
        criados.append(s)
        return s

    yield criar
    for s in criados:
        s.fechar()


def pedir(url: str) -> tuple[int, dict, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resposta:
            return resposta.status, dict(resposta.headers), resposta.read()
    except urllib.error.HTTPError as erro:
        return erro.code, dict(erro.headers), erro.read()


def test_pagina_e_arquivos_sem_cache(servidor):
    s = servidor(BuscaFalsa())
    status, cabecalhos, corpo = pedir(s.url)
    assert status == 200 and cabecalhos["Content-Type"].startswith("text/html")
    html = (RAIZ / "index.html").read_text(encoding="utf-8")
    assert corpo.decode("utf-8") == servidor_local.ajustar_preload_para_http(html)
    assert cabecalhos["Cache-Control"] == "no-cache, no-store, must-revalidate"
    for nome in sorted(servidor_local.ARQUIVOS_DA_PAGINA):
        status, cabecalhos, corpo = pedir(s.url + nome)
        assert status == 200, nome
        assert corpo == (RAIZ / nome).read_bytes(), nome
        assert cabecalhos["Cache-Control"] == "no-cache, no-store, must-revalidate", nome


def test_todos_os_arquivos_que_o_html_pede_estao_na_lista():
    html = (RAIZ / "index.html").read_text(encoding="utf-8")
    import re
    locais = {m for m in re.findall(r'(?:href|src)="([^":]+)"', html)}
    assert locais <= set(servidor_local.ARQUIVOS_DA_PAGINA), locais - set(servidor_local.ARQUIVOS_DA_PAGINA)
    assert "alerta.mp3" in (RAIZ / "script.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("caminho", ["BTC_Monitor.py", "servidor_local.py", "requirements.txt",
                                     "tests/apoio_pagina.py", "..%2FBTC_Monitor.py", "%2e%2e/index.html"])
def test_nao_entrega_outros_arquivos(servidor, caminho):
    s = servidor(BuscaFalsa())
    assert pedir(s.url + caminho)[0] == 404


def test_preco_inicial_entrega_uma_vez(servidor):
    busca = BuscaFalsa(TICKERS)
    s = servidor(busca)
    status, cabecalhos, corpo = pedir(s.url + "preco-inicial")
    assert status == 200 and json.loads(corpo) == TICKERS
    assert cabecalhos["Content-Type"] == "application/json"
    assert cabecalhos["Cache-Control"] == "no-cache, no-store, must-revalidate"
    assert pedir(s.url + "preco-inicial")[0] == 204
    assert busca.esperas == [servidor_local.ESPERA_PRECO_INICIAL_S] * 2


def test_pedidos_de_arquivos_nao_esperam_o_preco(servidor):
    """O servidor atende em paralelo: a espera de /preco-inicial não segura a página."""
    s = servidor(BuscaFalsa(atraso_s=1.0))
    threading.Thread(target=pedir, args=(s.url + "preco-inicial",), daemon=True).start()
    time.sleep(0.05)
    inicio = time.monotonic()
    assert pedir(s.url + "script.js")[0] == 200
    assert time.monotonic() - inicio < 0.5


def test_preload_da_fonte_ganha_crossorigin_so_pelo_servidor(servidor):
    html = (RAIZ / "index.html").read_text(encoding="utf-8")
    assert html.count(servidor_local.PRELOAD_FONTE) == 1  # a linha que o servidor procura existe
    assert servidor_local.PRELOAD_FONTE_HTTP not in html  # por file:// vai sem o atributo
    corpo = pedir(servidor(BuscaFalsa()).url)[2].decode("utf-8")
    assert servidor_local.PRELOAD_FONTE_HTTP in corpo and servidor_local.PRELOAD_FONTE not in corpo
    assert corpo == servidor_local.ajustar_preload_para_http(html)


def test_marcos_do_servidor_so_com_a_medicao(servidor):
    marcos: list[str] = []
    s = servidor(BuscaFalsa(), marcar=marcos.append)
    assert pedir(s.url + "script.js")[0] == 200
    assert pedir(s.url)[0] == 200
    time.sleep(0.1)  # o close() da resposta roda depois do envio
    assert marcos == ["servidor_pedido:script.js", "servidor_fim:script.js",
                      "servidor_pedido:index.html", "servidor_fim:index.html"]


def test_sem_medicao_o_aplicativo_e_o_bottle_direto():
    import bottle
    aplicativo = servidor_local.criar_aplicativo(RAIZ, lambda: "", BuscaFalsa())
    assert isinstance(aplicativo, bottle.Bottle)


def test_tipos_dos_arquivos(servidor):
    s = servidor(BuscaFalsa())
    esperados = {
        "style.css": "text/css; charset=UTF-8",
        "script.js": "application/javascript; charset=UTF-8",
        "Roboto.woff2": "font/woff2",
        "btc-logo.svg": "image/svg+xml",
        "alerta.mp3": "audio/mpeg",
    }
    for nome, tipo in esperados.items():
        assert pedir(s.url + nome)[1]["Content-Type"] == tipo, nome


ENTREGAR_SEM_INICIAR_MIMETYPES = r"""
import json, sys, threading, urllib.request
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server
raiz = Path(sys.argv[1]); tipos_fixos = sys.argv[2] == "1"
sys.path.insert(0, str(raiz))
import mimetypes
import servidor_local

class Silencioso(WSGIRequestHandler):
    def log_message(self, *args): pass

class SemPreco:
    def resultado(self, espera_s): return None

app = servidor_local.criar_aplicativo(raiz, lambda: "", SemPreco(), tipos_fixos=tipos_fixos)
http = make_server("127.0.0.1", 0, app, handler_class=Silencioso)
threading.Thread(target=http.serve_forever, daemon=True).start()
for nome in sorted(servidor_local.ARQUIVOS_DA_PAGINA):
    urllib.request.urlopen(f"http://127.0.0.1:{http.server_port}/{nome}", timeout=5).read()
print(json.dumps({"iniciado": mimetypes.inited}))
"""


@pytest.mark.parametrize("tipos_fixos,iniciado", [(True, False), (False, True)])
def test_entregar_arquivos_nao_inicia_o_mimetypes(tipos_fixos, iniciado):
    """Num Python novo: entregar todos os arquivos da página não pode iniciar o mimetypes
    (no Windows, a 1ª consulta lê o registro e segurava CSS e JS na abertura). O caso de
    controle (tipos_fixos=False) confirma que o teste enxerga o problema."""
    import subprocess
    saida = subprocess.run([sys.executable, "-c", ENTREGAR_SEM_INICIAR_MIMETYPES, str(RAIZ), "1" if tipos_fixos else "0"],
                           capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, saida.stderr
    assert json.loads(saida.stdout.strip().splitlines()[-1]) == {"iniciado": iniciado}


def test_preco_vai_no_html_quando_ja_esta_pronto(servidor):
    busca = BuscaFalsa(TICKERS)
    s = servidor(busca)
    corpo = pedir(s.url)[2].decode("utf-8")
    bloco = f'<script type="application/json" id="{servidor_local.ID_PRECO_NO_HTML}">'
    assert corpo.count(bloco) == 1 and corpo.index(bloco) < corpo.index("</head>")
    inicio = corpo.index(bloco) + len(bloco)
    assert json.loads(corpo[inicio:corpo.index("</script>", inicio)]) == TICKERS
    assert busca.esperas == [0]  # o "/" não espera a busca
    assert pedir(s.url + "preco-inicial")[0] == 204  # entrega única
    assert bloco not in pedir(s.url)[2].decode("utf-8")  # nem num 2º "/" (recarga)


def test_sem_preco_pronto_o_html_vai_sem_o_bloco(servidor):
    s = servidor(BuscaFalsa(None))
    assert f'id="{servidor_local.ID_PRECO_NO_HTML}"' not in pedir(s.url)[2].decode("utf-8")


def test_preco_no_html_desligado_deixa_para_o_preco_inicial(servidor):
    busca = BuscaFalsa(TICKERS)
    s = servidor(busca, preco_no_html=False)
    assert f'id="{servidor_local.ID_PRECO_NO_HTML}"' not in pedir(s.url)[2].decode("utf-8")
    assert json.loads(pedir(s.url + "preco-inicial")[2]) == TICKERS


def test_texto_do_bloco_nunca_fecha_a_tag():
    html = servidor_local.embutir_preco("<head></head>", [{"symbol": "</script><img src=x>"}])
    bloco = html[html.index('">') + 2:html.index("</script>")]
    assert "<" not in bloco
    assert json.loads(bloco) == [{"symbol": "</script><img src=x>"}]
