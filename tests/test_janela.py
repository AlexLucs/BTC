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


# ---------------------------------------------------------------------------
# Camada da janela: normal, topo (topo_janela.py) e fundo (camada_fundo.py)
# ---------------------------------------------------------------------------


class ControladorFalso:
    """Imita o ControladorCamada: registra entradas e saídas do fundo."""

    def __init__(self, entra: bool = True, explode: bool = False) -> None:
        self.entra, self.explode = entra, explode
        self.chamadas: list[str] = []

    def entrar_no_fundo(self) -> bool:
        self.chamadas.append("entrar")
        if self.explode:
            raise OSError("falha simulada")
        return self.entra

    def sair_do_fundo(self) -> bool:
        self.chamadas.append("sair")
        return True

    def encerrar(self) -> None:
        self.chamadas.append("encerrar")

    def destacar(self, ativo: bool) -> bool:
        self.chamadas.append(f"destacar:{ativo}")
        return True


class TopoFalso:
    """Substitui as funções do topo_janela.py usadas pela API."""

    def __init__(self) -> None:
        self.fixada = False
        self.chamadas: list[bool] = []

    def encontrar_janela(self, _titulo: str) -> int:
        return 0x1000

    def definir_topo(self, _hwnd: int, fixar: bool) -> bool:
        self.chamadas.append(fixar)
        self.fixada = fixar
        return fixar

    def esta_no_topo(self, _hwnd: int) -> bool:
        return self.fixada


@pytest.fixture
def camadas(api, monkeypatch):
    """A API com controlador do fundo e topo_janela falsos."""
    topo = TopoFalso()
    monkeypatch.setattr(app, "topo_janela", topo)
    api._controlador_fundo = ControladorFalso()
    return api, api._controlador_fundo, topo


def test_configuracao_guarda_a_camada_fundo(config):
    assert app.carregar_camada() == "normal"  # sem arquivo
    app.salvar_configuracao(30, 40, True, "fundo")
    assert app.carregar_camada() == "fundo"
    assert app.carregar_modo_compacto() is True
    app.salvar_configuracao(30, 40, True)
    assert app.carregar_camada() == "normal"


def test_fixacao_no_topo_nao_e_lembrada(config):
    app.salvar_configuracao(30, 40, False, "topo")
    assert app.carregar_camada() == "normal"


@pytest.mark.parametrize("conteudo", [
    "[Position]\nx = 10\ny = 20\n[Janela]\ncompacto = 1\n",           # .ini antigo, sem a camada
    "[Position]\nx = 10\ny = 20\n[Janela]\ncompacto = 1\ncamada = xyz\n",
])
def test_camada_ausente_ou_invalida_abre_na_normal(config, conteudo):
    config.write_text(conteudo, encoding="utf-8")
    assert app.carregar_camada() == "normal"
    assert app.carregar_modo_compacto() is True


def test_normal_para_fundo_e_de_volta(camadas):
    api, fundo, topo = camadas
    assert api.definir_camada("fundo") == "fundo"
    assert api.camada_atual() == "fundo"
    assert api.definir_camada("normal") == "normal"
    assert fundo.chamadas == ["entrar", "sair"]
    assert topo.chamadas == []


def test_topo_para_fundo_desafixa_antes(camadas):
    api, fundo, topo = camadas
    assert api.definir_camada("topo") == "topo"
    assert api.definir_camada("fundo") == "fundo"
    assert topo.chamadas == [True, False]
    assert fundo.chamadas == ["entrar"]


def test_fundo_para_topo_sai_do_fundo_antes(camadas):
    api, fundo, topo = camadas
    api.definir_camada("fundo")
    assert api.definir_camada("topo") == "topo"
    assert fundo.chamadas == ["entrar", "sair"]
    assert topo.chamadas == [True]


def test_mesma_camada_nao_faz_nada(camadas):
    api, fundo, topo = camadas
    api.definir_camada("fundo")
    assert api.definir_camada("fundo") == "fundo"
    assert fundo.chamadas == ["entrar"]


@pytest.mark.parametrize("valor", ["lateral", "", None, 1, True])
def test_camada_invalida_nao_muda_nada(camadas, valor):
    api, fundo, topo = camadas
    assert api.definir_camada(valor) == "normal"
    assert fundo.chamadas == [] and topo.chamadas == []


def test_falha_ao_entrar_no_fundo_fica_na_normal(camadas):
    api, fundo, _topo = camadas
    fundo.entra = False
    assert api.definir_camada("fundo") == "normal"
    fundo.explode = True
    assert api.definir_camada("fundo") == "normal"  # exceção vai ao log
    assert api.camada_atual() == "normal"


def test_camada_atual_percebe_fixacao_tirada_por_fora(camadas):
    api, _fundo, topo = camadas
    api.definir_camada("topo")
    topo.fixada = False
    assert api.camada_atual() == "normal"


def test_camada_salva_e_informada_antes_e_aplicada_quando_a_janela_aparece(api, monkeypatch, tmp_path):
    api = app.ExposedApi(app.RepositorioAlertas(tmp_path), app.METRICAS, camada="fundo")
    api._controlador_fundo = ControladorFalso()
    janela = JanelaFalsa(100, 100)
    janela.events = SimpleNamespace(shown=EventoFalso())
    app.registrar_camada_inicial(janela, api)
    # A página pode perguntar antes de o handler rodar: já recebe a salva.
    assert api.camada_atual() == "fundo"
    assert api._controlador_fundo.chamadas == []
    janela.events.shown.disparar()
    assert api._controlador_fundo.chamadas == ["entrar"]
    assert api.camada_atual() == "fundo"
    handler = janela.events.shown.handlers[0]
    assert handler.__code__.co_argcount == 0


def test_camada_normal_salva_nao_mexe_na_janela(api):
    janela = JanelaFalsa(100, 100)
    janela.events = SimpleNamespace(shown=EventoFalso())
    api._controlador_fundo = ControladorFalso()
    app.registrar_camada_inicial(janela, api)
    janela.events.shown.disparar()
    assert api._controlador_fundo.chamadas == []
    assert api.camada_atual() == "normal"


def test_pedido_da_pagina_vence_a_camada_salva_ainda_nao_aplicada(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "topo_janela", TopoFalso())
    api = app.ExposedApi(app.RepositorioAlertas(tmp_path), app.METRICAS, camada="fundo")
    api._controlador_fundo = ControladorFalso()
    assert api.definir_camada("topo") == "topo"
    api._aplicar_camada_inicial()  # o shown chegou depois: não desfaz o pedido
    assert api.camada_atual() == "topo"
    assert api._controlador_fundo.chamadas == []


def test_falha_na_camada_inicial_nao_derruba_a_abertura(tmp_path):
    api = app.ExposedApi(app.RepositorioAlertas(tmp_path), app.METRICAS, camada="fundo")
    api._controlador_fundo = ControladorFalso(explode=True)
    janela = JanelaFalsa(100, 100)
    janela.events = SimpleNamespace(shown=EventoFalso())
    app.registrar_camada_inicial(janela, api)
    janela.events.shown.disparar()  # não levanta
    assert api.camada_atual() == "normal"


def test_camada_nao_e_exposta_ao_js(api):
    publicos = {nome for nome in dir(api) if not nome.startswith("_")}
    assert {"definir_camada", "camada_atual"} <= publicos
    assert not {"camada", "controlador_fundo", "trava_camada", "definir_topo", "esta_no_topo"} & publicos


def test_fechar_grava_a_camada_e_para_a_vigia(monkeypatch, config, tmp_path):
    janela = JanelaFalsa(0, 0)
    janela.events = EventosFalsos()
    apis: list = []
    original = app.ExposedApi

    def criar_api(*args, **kwargs):
        api = original(*args, **kwargs)
        api._controlador_fundo = ControladorFalso()
        api._criar_sistema_atalho = None  # no Windows, não registrar o atalho de verdade
        apis.append(api)
        return api

    monkeypatch.setattr(app, "ExposedApi", criar_api)
    monkeypatch.setattr(app, "MEDICAO_ATIVA", False)
    monkeypatch.setattr(app, "webview", SimpleNamespace(
        screens=[MONITOR_COM_BARRA], create_window=lambda *_a, **_k: janela, start=lambda **_k: None))
    monkeypatch.setattr(app, "PASTA_WEBVIEW", tmp_path / "webview")
    config.write_text("[Janela]\ncompacto = 0\ncamada = fundo\n", encoding="utf-8")
    app.abrir_janela()
    api = apis[0]
    janela.events.shown.disparar()
    assert api.camada_atual() == "fundo"
    janela.events.closing.disparar()
    assert app.carregar_camada() == "fundo"
    assert api._controlador_fundo.chamadas == ["entrar", "encerrar"]


# ---------------------------------------------------------------------------
# Cobertura (camada fundo): espera longa da página
# ---------------------------------------------------------------------------


def test_aguardar_estado_janela_volta_na_hora_com_versao_antiga(api):
    assert api.aguardar_estado_janela(-1) == {"versao": 0, "coberto": False, "ausente": False}
    api._estado_janela.publicar(coberto=True)
    assert api.aguardar_estado_janela(0) == {"versao": 1, "coberto": True, "ausente": False}


@pytest.mark.parametrize("versao", ["0", None, 1.5, True, [0]])
def test_aguardar_estado_janela_com_versao_invalida_responde_na_hora(api, versao):
    assert api.aguardar_estado_janela(versao) == {"versao": 0, "coberto": False, "ausente": False}


def test_fechar_libera_a_espera_longa(api):
    import threading
    import time

    resultados: list = []
    espera = threading.Thread(target=lambda: resultados.append(api.aguardar_estado_janela(0)))
    espera.start()
    time.sleep(0.05)
    assert espera.is_alive()
    api._encerrar_camada()
    espera.join(1)
    assert not espera.is_alive() and resultados == [{"versao": 0, "coberto": False, "ausente": False}]


def test_estado_da_janela_nao_e_exposto_ao_js(api):
    publicos = {nome for nome in dir(api) if not nome.startswith("_")}
    assert "aguardar_estado_janela" in publicos
    assert not {"estado_janela", "estado"} & publicos


@pytest.mark.parametrize(("valor", "nivel"), [("1", 10), (None, 0)])  # DEBUG / NOTSET
def test_depurar_fundo_liga_o_log_de_depuracao_da_camada(monkeypatch, tmp_path, valor, nivel):
    import logging

    # configurar_log troca os ganchos globais de exceção: o monkeypatch os devolve no fim.
    monkeypatch.setattr(app.sys, "excepthook", app.sys.excepthook)
    monkeypatch.setattr(app.threading, "excepthook", app.threading.excepthook)
    monkeypatch.setattr(app, "PASTA_DADOS", tmp_path)
    monkeypatch.setattr(app, "ARQUIVO_LOG", tmp_path / "btcstatus.log")
    if valor is None:
        monkeypatch.delenv(app.VARIAVEL_DEPURAR_FUNDO, raising=False)
    else:
        monkeypatch.setenv(app.VARIAVEL_DEPURAR_FUNDO, valor)
    registros = [logging.getLogger(nome) for nome in ("camada_fundo", "atalho_global")]
    assert set(app.LOGS_DE_DEPURACAO) == {"camada_fundo", "atalho_global"}
    raiz = logging.getLogger()
    niveis_antes, handlers_antes = [r.level for r in registros], list(raiz.handlers)
    try:
        for registro in registros:
            registro.setLevel(logging.NOTSET)
        app.configurar_log()
        assert [r.level for r in registros] == [nivel, nivel]
    finally:
        for handler in raiz.handlers[len(handlers_antes):]:
            handler.close()
        raiz.handlers[:] = handlers_antes
        for registro, antes in zip(registros, niveis_antes, strict=True):
            registro.setLevel(antes)


# ---------------------------------------------------------------------------
# Destaque do alarme (camada fundo)
# ---------------------------------------------------------------------------


def test_destacar_alarme_no_fundo_repassa_ao_controlador(camadas):
    api, fundo, _topo = camadas
    api.definir_camada("fundo")
    assert api.destacar_alarme(True) is True
    assert api.destacar_alarme(False) is True
    assert fundo.chamadas == ["entrar", "destacar:True", "destacar:False"]


@pytest.mark.parametrize("camada", ["normal", "topo"])
def test_destacar_alarme_fora_do_fundo_nao_faz_nada(camadas, camada):
    api, fundo, _topo = camadas
    api.definir_camada(camada)
    assert api.destacar_alarme(True) is False
    assert not any(c.startswith("destacar") for c in fundo.chamadas)


def test_destacar_alarme_converte_o_valor(camadas):
    api, fundo, _topo = camadas
    api.definir_camada("fundo")
    api.destacar_alarme(1)
    api.destacar_alarme("")
    assert fundo.chamadas[-2:] == ["destacar:True", "destacar:False"]


# ---------------------------------------------------------------------------
# Atalho global (atalho_global.py)
# ---------------------------------------------------------------------------


class OuvinteFalso:
    """Imita o OuvinteAtalho: registra a criação, o início e a parada."""

    criados: list = []

    def __init__(self, sistema, obter_janela, obter_camada) -> None:
        self.sistema, self.obter_janela, self.obter_camada = sistema, obter_janela, obter_camada
        self.chamadas: list[str] = []
        self.registrado = SimpleNamespace(nome="Ctrl+Alt+B")
        self.recusados: list = []
        self.explodir = getattr(sistema, "explodir", False)
        OuvinteFalso.criados.append(self)

    def iniciar(self):
        self.chamadas.append("iniciar")
        if self.explodir:
            raise OSError("falha simulada")
        return self.registrado

    def parar(self) -> None:
        self.chamadas.append("parar")


@pytest.fixture
def atalho(api, monkeypatch):
    OuvinteFalso.criados = []
    monkeypatch.setattr(app, "OuvinteAtalho", OuvinteFalso)
    api._criar_sistema_atalho = lambda: SimpleNamespace(explodir=False)
    return api


def test_atalho_e_ligado_quando_a_janela_aparece(atalho):
    janela = JanelaFalsa(100, 100)
    janela.events = SimpleNamespace(shown=EventoFalso())
    app.registrar_atalho_global(janela, atalho)
    assert OuvinteFalso.criados == []  # nada antes de a janela aparecer
    janela.events.shown.disparar()
    ouvinte = OuvinteFalso.criados[0]
    assert ouvinte.chamadas == ["iniciar"]
    # Usa o mesmo handle das outras funções e lê a camada a cada aperto.
    assert ouvinte.obter_janela == atalho._handle_janela
    atalho._camada = "fundo"
    assert ouvinte.obter_camada() == "fundo"
    handler = janela.events.shown.handlers[0]
    assert handler.__code__.co_argcount == 0
    janela.events.shown.disparar()  # um 2º shown não cria outro
    assert len(OuvinteFalso.criados) == 1


def test_fechar_desliga_o_atalho(monkeypatch, config, tmp_path):
    OuvinteFalso.criados = []
    monkeypatch.setattr(app, "OuvinteAtalho", OuvinteFalso)
    janela = JanelaFalsa(0, 0)
    janela.events = EventosFalsos()
    original = app.ExposedApi

    def criar_api(*args, **kwargs):
        api = original(*args, **kwargs)
        api._criar_sistema_atalho = lambda: SimpleNamespace()
        return api

    monkeypatch.setattr(app, "ExposedApi", criar_api)
    monkeypatch.setattr(app, "MEDICAO_ATIVA", False)
    monkeypatch.setattr(app, "webview", SimpleNamespace(
        screens=[MONITOR_COM_BARRA], create_window=lambda *_a, **_k: janela, start=lambda **_k: None))
    monkeypatch.setattr(app, "PASTA_WEBVIEW", tmp_path / "webview")
    app.abrir_janela()
    janela.events.shown.disparar()
    janela.events.closing.disparar()
    assert OuvinteFalso.criados[0].chamadas == ["iniciar", "parar"]


def test_falha_ao_ligar_o_atalho_nao_derruba_a_abertura(atalho):
    atalho._criar_sistema_atalho = lambda: SimpleNamespace(explodir=True)
    atalho._ligar_atalho()  # não levanta
    assert atalho._atalho_tentado.is_set()
    assert atalho.aviso_do_atalho() is None


def test_sem_windows_nao_liga_e_nao_avisa(api):
    api._criar_sistema_atalho = None
    api._ligar_atalho()
    assert api._atalho is None and api.aviso_do_atalho() is None


def test_aviso_do_atalho_sem_conflito(atalho):
    atalho._ligar_atalho()
    assert atalho.aviso_do_atalho() is None


def test_aviso_do_atalho_com_reserva_so_na_primeira_vez(atalho):
    atalho._ligar_atalho()
    ouvinte = OuvinteFalso.criados[0]
    ouvinte.registrado = SimpleNamespace(nome="Ctrl+Shift+Alt+B")
    ouvinte.recusados = [SimpleNamespace(nome="Ctrl+Alt+B")]
    assert atalho.aviso_do_atalho() == {"ativo": "Ctrl+Shift+Alt+B", "em_uso": ["Ctrl+Alt+B"]}
    assert atalho.aviso_do_atalho() is None  # o ↻ não repete


def test_aviso_do_atalho_sem_nenhum(atalho):
    atalho._ligar_atalho()
    ouvinte = OuvinteFalso.criados[0]
    ouvinte.registrado = None
    ouvinte.recusados = [SimpleNamespace(nome="Ctrl+Alt+B"), SimpleNamespace(nome="Ctrl+Shift+Alt+B")]
    assert atalho.aviso_do_atalho() == {"ativo": None, "em_uso": ["Ctrl+Alt+B", "Ctrl+Shift+Alt+B"]}


def test_aviso_do_atalho_espera_o_registro(atalho, monkeypatch):
    """A página pode perguntar antes de o shown ter registrado o atalho."""
    import threading

    monkeypatch.setattr(app, "ESPERA_AVISO_ATALHO_S", 2.0)
    resultados: list = []
    pergunta = threading.Thread(target=lambda: resultados.append(atalho.aviso_do_atalho()))
    pergunta.start()
    pergunta.join(0.05)
    assert pergunta.is_alive()  # esperando o registro
    atalho._ligar_atalho()
    pergunta.join(1)
    assert not pergunta.is_alive() and resultados == [None]  # sem conflito


def test_atalho_nao_e_exposto_ao_js(api):
    publicos = {nome for nome in dir(api) if not nome.startswith("_")}
    assert "aviso_do_atalho" in publicos
    assert not {"atalho", "ligar_atalho", "desligar_atalho", "criar_sistema_atalho"} & publicos


# --- Uma instância só (instancia_unica.py) ------------------------------------------------
def test_main_nao_abre_janela_se_ja_existe_outra_instancia(monkeypatch):
    aberturas = []
    monkeypatch.setattr(app, "configurar_log", lambda: None)
    monkeypatch.setattr(app, "deve_buscar_preco_pelo_python", lambda: False)  # sem rede no teste
    monkeypatch.setattr(app, "ja_existe_outra_instancia", lambda: True)
    monkeypatch.setattr(app, "abrir_janela", lambda: aberturas.append(1))
    app.main()
    assert aberturas == []


def test_main_abre_janela_quando_e_a_unica_instancia(monkeypatch):
    aberturas = []
    monkeypatch.setattr(app, "configurar_log", lambda: None)
    monkeypatch.setattr(app, "deve_buscar_preco_pelo_python", lambda: False)  # sem rede no teste
    monkeypatch.setattr(app, "ja_existe_outra_instancia", lambda: False)
    monkeypatch.setattr(app, "abrir_janela", lambda: aberturas.append(1))
    app.main()
    assert aberturas == [1]


def test_fora_do_windows_nunca_ha_outra_instancia(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "linux")
    assert app.ja_existe_outra_instancia() is False


def test_falha_ao_criar_o_sistema_da_instancia_deixa_abrir(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "win32")

    def falhar():
        raise OSError("sem kernel32")

    monkeypatch.setattr(app.instancia_unica, "SistemaWin32Instancia", falhar)
    assert app.ja_existe_outra_instancia() is False


# --- .ini robusto (I5) e posição ao fechar minimizada (I6) -------------------------------
@pytest.mark.parametrize("conteudo", [
    "[Position]\nx = 10\ny = 20\n[Janela]\ncompacto = 1\ncamada = fundo %\n",   # "%" escrito à mão
    "﻿[Position]\nx = 10\ny = 20\n[Janela]\ncompacto = 1\ncamada = fundo\n",  # BOM de editor
])
def test_ini_com_percentual_ou_bom_continua_legivel(config, conteudo):
    config.write_text(conteudo, encoding="utf-8")
    assert app.carregar_posicao([MONITOR]) == (10, 20)
    assert app.carregar_modo_compacto() is True
    assert app.carregar_camada() in ("normal", "fundo")


def test_ini_em_outra_codificacao_e_ignorado_sem_derrubar_a_abertura(config):
    config.write_bytes("[Janela]\ncompacto = 1\ncamada = açúcar\n".encode("cp1252"))
    assert app.carregar_modo_compacto() is False
    assert app.carregar_camada() == "normal"


def test_gravacao_do_ini_e_atomica_e_nao_deixa_temporario(config):
    app.salvar_configuracao(30, 40, True, "fundo")
    assert sorted(p.name for p in config.parent.iterdir()) == ["BTC Monitor.ini"]
    assert app.carregar_posicao([MONITOR]) == (30, 40)


def test_sem_posicao_o_ini_fica_sem_a_secao_e_a_abertura_centraliza(config):
    app.salvar_configuracao(None, None, False)
    assert "[Position]" not in config.read_text(encoding="utf-8")
    assert app.carregar_posicao([MONITOR]) is None
    assert app.carregar_modo_compacto() is False


def test_fechar_minimizada_mantem_a_posicao_que_estava_no_ini(monkeypatch, config, api):
    app.salvar_configuracao(30, 40, False)
    api._vincular(JanelaFalsa(-32000, -32000))
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(api, "_handle_janela", lambda: 7)
    monkeypatch.setattr(app.topo_janela, "esta_minimizada", lambda hwnd: True)
    assert api._posicao_para_salvar() == (30, 40)
    monkeypatch.setattr(app.topo_janela, "esta_minimizada", lambda hwnd: False)
    assert api._posicao_para_salvar() == (-32000, -32000)  # não minimizada: a real


def test_fechar_minimizada_sem_posicao_anterior_nao_grava_posicao(monkeypatch, config, api):
    api._vincular(JanelaFalsa(-32000, -32000))
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(api, "_handle_janela", lambda: 7)
    monkeypatch.setattr(app.topo_janela, "esta_minimizada", lambda hwnd: True)
    assert api._posicao_para_salvar() == (None, None)


# --- Exceções soltas vão ao log (O1) ------------------------------------------------------
def test_excecao_solta_numa_thread_vai_ao_log(monkeypatch, caplog):
    import logging
    import threading

    monkeypatch.setattr(app.sys, "excepthook", app.sys.excepthook)
    monkeypatch.setattr(app.threading, "excepthook", app.threading.excepthook)
    app.registrar_excecoes_soltas()

    def falhar():
        raise RuntimeError("erro solto de teste")

    with caplog.at_level(logging.ERROR, logger="btcstatus"):
        thread = threading.Thread(target=falhar, name="thread-de-teste")
        thread.start()
        thread.join()
        try:
            raise ValueError("erro solto no processo")
        except ValueError:
            app.sys.excepthook(*app.sys.exc_info())
    assert "thread-de-teste" in caplog.text and "erro solto de teste" in caplog.text
    assert "erro solto no processo" in caplog.text
