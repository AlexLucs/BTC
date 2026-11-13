"""BTC_Monitor.py: posição, modo compacto e configuração da janela (sem abrir janela)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

RAIZ = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(importlib.util.find_spec("webview") is None, reason="pywebview não instalado")

sys.path.insert(0, str(RAIZ))
import BTC_Monitor as app  # noqa: E402

MONITOR = SimpleNamespace(x=0, y=0, width=1920, height=1080)
MONITOR_DIREITA = SimpleNamespace(x=1920, y=0, width=1280, height=1024)
# Como o pywebview 6.2.1 no Windows: "frame" é o Screen.WorkingArea do WinForms (sem a
# barra de tarefas, aqui embaixo, com 40 px).
MONITOR_COM_BARRA = SimpleNamespace(
    x=0, y=0, width=1920, height=1080, frame=SimpleNamespace(X=0, Y=0, Width=1920, Height=1040)
)


class JanelaFalsa:
    """Imita o webview.Window: resize mantém o topo (FixPoint padrão), move muda o canto."""

    def __init__(self, x: int, y: int, altura: int = app.WINDOW_HEIGHT, falhar: bool = False) -> None:
        self.x, self.y, self.width, self.height = x, y, app.WINDOW_WIDTH, altura
        self.falhar = falhar
        self.chamadas: list[tuple] = []

    def resize(self, largura: int, altura: int) -> None:
        if self.falhar:
            raise RuntimeError("falha simulada")
        self.chamadas.append(("resize", largura, altura))
        self.width, self.height = largura, altura

    def move(self, x: int, y: int) -> None:
        self.chamadas.append(("move", x, y))
        self.x, self.y = x, y


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "webview", SimpleNamespace(screens=[MONITOR, MONITOR_DIREITA]))
    return app.ExposedApi(app.RepositorioAlertas(tmp_path), app.METRICAS)


@pytest.fixture
def config(monkeypatch, tmp_path):
    arquivo = tmp_path / "BTC Monitor.ini"
    monkeypatch.setattr(app, "PASTA_DADOS", tmp_path)
    monkeypatch.setattr(app, "ARQUIVO_CONFIG", arquivo)
    return arquivo


def test_altura_da_janela():
    assert app.altura_da_janela(False) == 810
    assert app.altura_da_janela(True) == 388


@pytest.mark.parametrize(("x", "y", "altura", "esperado"), [
    (100, 100, 810, (100, 100)),       # cabe: não mexe
    (100, 900, 810, (100, 270)),       # passa da borda de baixo: sobe o necessário
    (1800, 50, 388, (1420, 50)),       # passa da borda direita
    (-30, -10, 388, (0, 0)),           # antes da origem
    (100, 50, 2000, (100, 0)),         # maior que o monitor: prevalece o topo
])
def test_posicao_dentro_do_monitor(x, y, altura, esperado):
    assert app.posicao_dentro_do_monitor(x, y, app.WINDOW_WIDTH, altura, MONITOR) == esperado


def test_posicao_dentro_de_um_monitor_que_nao_comeca_na_origem():
    assert app.posicao_dentro_do_monitor(2900, 900, 500, 810, MONITOR_DIREITA) == (2700, 214)


def test_posicao_centralizada_usa_a_altura_pedida():
    assert app.posicao_centralizada(MONITOR) == (710, 135)
    assert app.posicao_centralizada(MONITOR, 500, 388) == (710, 346)


def test_configuracao_guarda_posicao_e_modo(config):
    assert app.carregar_modo_compacto() is False  # sem arquivo
    app.salvar_configuracao(30, 40, True)
    assert app.carregar_modo_compacto() is True
    assert app.carregar_posicao([MONITOR]) == (30, 40)
    app.salvar_configuracao(30, 40, False)
    assert app.carregar_modo_compacto() is False


def test_configuracao_antiga_sem_o_modo_abre_no_modo_completo(config):
    config.write_text("[Position]\nx = 10\ny = 20\n", encoding="utf-8")
    assert app.carregar_modo_compacto() is False
    assert app.carregar_posicao([MONITOR]) == (10, 20)


def test_modo_invalido_abre_no_modo_completo(config):
    config.write_text("[Position]\nx = 10\ny = 20\n[Janela]\ncompacto = talvez\n", encoding="utf-8")
    assert app.carregar_modo_compacto() is False
    assert app.carregar_posicao([MONITOR]) == (10, 20)


def test_compactar_mantem_o_topo(api):
    janela = JanelaFalsa(100, 200)
    api._vincular(janela)
    assert api.definir_compacto(True) is True
    assert janela.chamadas == [("resize", 500, 388)]
    assert (janela.x, janela.y) == (100, 200)
    assert api._modo_compacto() is True


def test_expandir_perto_da_borda_de_baixo_sobe_a_janela(api):
    janela = JanelaFalsa(100, 650, altura=388)  # compacta, com o fim em 1038 (cabe)
    api._vincular(janela)
    api._compacto = True
    assert api.definir_compacto(False) is True
    # Com 810 de altura, o fim iria a 1460: a janela sobe até o fim coincidir com o monitor.
    assert janela.chamadas == [("resize", 500, 810), ("move", 100, 270)]
    assert api._modo_compacto() is False


def test_expandir_no_segundo_monitor_usa_os_limites_dele(api):
    janela = JanelaFalsa(2000, 700, altura=388)
    api._vincular(janela)
    api.definir_compacto(False)
    assert janela.chamadas[-1] == ("move", 2000, 214)


def test_falha_ao_redimensionar_nao_muda_o_modo(api):
    api._vincular(JanelaFalsa(100, 100, falhar=True))
    assert api.definir_compacto(True) is False
    assert api._modo_compacto() is False


def test_sem_janela_nao_faz_nada(api):
    assert api.definir_compacto(True) is False


def test_centralizar_usa_a_altura_do_modo_atual(api):
    janela = JanelaFalsa(100, 100, altura=388)
    api._vincular(janela)
    api._compacto = True
    api.centralizar()
    assert janela.chamadas == [("move", 710, 346)]


def test_modo_compacto_nao_e_exposto_ao_js(api):
    """O pywebview expõe ao JS todo atributo público: o estado fica em "_"."""
    publicos = {nome for nome in dir(api) if not nome.startswith("_")}
    assert "definir_compacto" in publicos
    assert not {"compacto", "modo_compacto"} & publicos


class EventoFalso:
    """Imita os eventos do pywebview: "+=" registra o handler; disparar() o executa."""

    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def disparar(self) -> None:
        for handler in self.handlers:
            handler()


@pytest.mark.parametrize(("compacto", "altura"), [(False, 810), (True, 388)])
def test_tamanho_e_corrigido_quando_a_janela_aparece(api, compacto, altura):
    """O pywebview aplica o frameless depois do tamanho e a janela nasce menor pela moldura:
    no evento shown, o app pede o tamanho exato do modo salvo."""
    janela = JanelaFalsa(100, 100, altura=altura - 39)  # como o WinForms a deixa
    janela.events = SimpleNamespace(shown=EventoFalso())
    api._compacto = compacto
    app.registrar_ajuste_de_tamanho(janela, api)
    assert janela.chamadas == []  # nada antes de a janela aparecer
    janela.events.shown.disparar()
    assert janela.chamadas == [("resize", 500, altura)]
    # Handler sem parâmetros (o pywebview passaria os argumentos do evento) e sem retorno.
    handler = janela.events.shown.handlers[0]
    assert handler.__code__.co_argcount == 0


def test_falha_ao_corrigir_o_tamanho_nao_derruba_a_abertura(api):
    janela = JanelaFalsa(100, 100, falhar=True)
    janela.events = SimpleNamespace(shown=EventoFalso())
    app.registrar_ajuste_de_tamanho(janela, api)
    janela.events.shown.disparar()  # não levanta


# ---------------------------------------------------------------------------
# Área livre (barra de tarefas) e arraste
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("x", "y", "altura", "esperado"), [
    (100, 100, 810, (100, 100)),      # cabe: não mexe
    (100, 900, 810, (100, 230)),      # sobre a barra de tarefas: sobe até a base dela
    (100, 700, 388, (100, 652)),      # idem no modo compacto
])
def test_posicao_dentro_do_monitor_respeita_a_barra_de_tarefas(x, y, altura, esperado):
    assert app.posicao_dentro_do_monitor(x, y, app.WINDOW_WIDTH, altura, MONITOR_COM_BARRA) == esperado


def test_posicao_centralizada_usa_a_area_livre():
    assert app.posicao_centralizada(MONITOR_COM_BARRA) == (710, 115)
    assert app.posicao_centralizada(MONITOR_COM_BARRA, 500, 388) == (710, 326)


def test_expandir_perto_da_barra_de_tarefas_sobe_acima_dela(api, monkeypatch):
    monkeypatch.setattr(app, "webview", SimpleNamespace(screens=[MONITOR_COM_BARRA]))
    janela = JanelaFalsa(100, 640, altura=388)
    api._vincular(janela)
    api._compacto = True
    assert api.definir_compacto(False) is True
    assert janela.chamadas == [("resize", 500, 810), ("move", 100, 230)]


def test_centralizar_usa_a_area_livre(api, monkeypatch):
    monkeypatch.setattr(app, "webview", SimpleNamespace(screens=[MONITOR_COM_BARRA]))
    janela = JanelaFalsa(100, 100)
    api._vincular(janela)
    api.centralizar()
    assert janela.chamadas == [("move", 710, 115)]


class ArrastadorFalso:
    def __init__(self, resposta: bool) -> None:
        self.resposta = resposta
        self.pedidos = 0

    def iniciar(self) -> bool:
        self.pedidos += 1
        return self.resposta


@pytest.mark.parametrize("resposta", [True, False])
def test_iniciar_arraste_repassa_ao_arrastador(api, resposta):
    api._arrastador = ArrastadorFalso(resposta)
    assert api.iniciar_arraste() is resposta
    assert api._arrastador.pedidos == 1


def test_arrastador_usa_o_handle_da_janela(api):
    """O arrastador acha a janela pelo mesmo caminho da fixação no topo (título + PID)."""
    assert api._arrastador._obter_hwnd == api._handle_janela


def test_arraste_expoe_so_o_metodo_ao_js(api):
    publicos = {nome for nome in dir(api) if not nome.startswith("_")}
    assert "iniciar_arraste" in publicos
    assert not {"arrastador", "arraste"} & publicos


class EventosFalsos:
    """Qualquer evento pedido (shown, closing, loaded...) vira um EventoFalso."""

    def __getattr__(self, nome: str) -> EventoFalso:
        evento = EventoFalso()
        setattr(self, nome, evento)
        return evento


def test_janela_e_criada_sem_o_easy_drag(monkeypatch, config, tmp_path):
    """O arraste do pywebview ignora as bordas da tela; o app usa o próprio."""
    opcoes: dict = {}
    janela = JanelaFalsa(0, 0)
    janela.events = EventosFalsos()

    def criar_janela(*_args, **kwargs):
        opcoes.update(kwargs)
        return janela

    monkeypatch.setattr(app, "webview", SimpleNamespace(
        screens=[MONITOR_COM_BARRA], create_window=criar_janela, start=lambda **_kwargs: None))
    monkeypatch.setattr(app, "PASTA_WEBVIEW", tmp_path / "webview")
    app.abrir_janela()
    assert opcoes["frameless"] is True
    assert opcoes["easy_drag"] is False
    # Sem posição salva: centralizada na área livre.
    assert (opcoes["x"], opcoes["y"]) == (710, 115)


def test_index_nao_usa_a_regiao_de_arrasto_do_pywebview():
    """A classe "pywebview-drag-region" ligaria o arraste pelo JS do pywebview mesmo com
    easy_drag=False (ele sempre escuta o DRAG_REGION_SELECTOR)."""
    html = (RAIZ / "index.html").read_text(encoding="utf-8")
    assert re.search(r'class="[^"]*pywebview-drag-region', html) is None
    assert 'class="regiao-arraste"' in html
