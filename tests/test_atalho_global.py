"""atalho_global.py: leitura das combinações, decisões, ouvinte (sistema falso) e Win32 real."""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import atalho_global as ag  # noqa: E402

PROPRIA = 0x1000
OUTRA = 0x2000
AREA_DE_TRABALHO = 0x10


# ---------------------------------------------------------------------------
# Lógica pura
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("texto", "modificadores", "tecla", "nome"), [
    ("ctrl+alt+b", ag.MOD_CONTROL | ag.MOD_ALT, ord("B"), "Ctrl+Alt+B"),
    ("ctrl+shift+alt+b", ag.MOD_CONTROL | ag.MOD_SHIFT | ag.MOD_ALT, ord("B"), "Ctrl+Shift+Alt+B"),
    (" Alt + Shift + 7 ", ag.MOD_ALT | ag.MOD_SHIFT, ord("7"), "Shift+Alt+7"),  # nome em ordem fixa
    ("ctrl+f24", ag.MOD_CONTROL, 0x87, "Ctrl+F24"),
    ("alt+f1", ag.MOD_ALT, 0x70, "Alt+F1"),
])
def test_ler_atalho(texto, modificadores, tecla, nome):
    assert ag.ler_atalho(texto) == ag.Atalho(modificadores, tecla, nome)


@pytest.mark.parametrize("texto", [
    "b", "shift+b", "ctrl+", "+b", "ctrl+ctrl+b", "win+b", "ctrl+alt+f12", "ctrl+f25",
    "ctrl+alt+ç", "ctrl+alt+bb", "ctrl+alt+f0", "",
])
def test_ler_atalho_recusa(texto):
    with pytest.raises(ValueError):
        ag.ler_atalho(texto)


def test_padroes_sao_validos_e_em_ordem():
    assert [ag.ler_atalho(t).nome for t in ag.ATALHOS_PADRAO] == ["Ctrl+Alt+B", "Ctrl+Shift+Alt+B"]


@pytest.mark.parametrize(("camada", "minimizada", "frente", "acao"), [
    ("normal", True, False, "trazer"),
    ("normal", False, False, "trazer"),
    ("normal", False, True, "minimizar"),
    ("topo", False, False, "trazer"),
    ("topo", False, True, "minimizar"),
    ("fundo", False, False, "trazer"),
    ("fundo", False, True, "devolver_foco"),
    ("fundo", True, True, "trazer"),  # minimizada nunca conta como "na frente"
])
def test_acao_do_atalho(camada, minimizada, frente, acao):
    assert ag.acao_do_atalho(camada, minimizada, frente) == acao


# ---------------------------------------------------------------------------
# Ouvinte com sistema falso
# ---------------------------------------------------------------------------


class SistemaFalso:
    """Fila de mensagens de verdade (queue) e um Windows de mentira para as janelas."""

    def __init__(self, ocupados: dict[tuple[int, int], int] | None = None) -> None:
        self.ocupados = ocupados or {}  # (modificadores sem NOREPEAT, tecla) -> código de erro
        self.fila: queue.Queue = queue.Queue()
        self.registrados: dict[int, tuple[int, int]] = {}
        self.cancelados: list[int] = []
        self.chamadas: list[tuple] = []
        self.frente: int | None = OUTRA
        self.minimizadas: set[int] = set()
        self.visiveis: set[int] = {PROPRIA, OUTRA, AREA_DE_TRABALHO}
        self.recusar_ativar: set[int] = set()
        self.thread_do_laco: threading.Thread | None = None

    # thread
    def preparar_fila(self) -> int:
        return 42

    def registrar(self, id_atalho: int, modificadores: int, tecla: int) -> int:
        codigo = self.ocupados.get((modificadores & ~ag.MOD_NOREPEAT, tecla), 0)
        if codigo == 0:
            self.registrados[id_atalho] = (modificadores, tecla)
        return codigo

    def cancelar_registro(self, id_atalho: int) -> None:
        self.cancelados.append(id_atalho)
        self.registrados.pop(id_atalho, None)

    def rodar_laco(self, ao_atalho) -> None:
        self.thread_do_laco = threading.current_thread()
        while True:
            mensagem = self.fila.get()
            if mensagem is None:
                return
            ao_atalho(mensagem)

    def encerrar_laco(self, id_thread: int) -> None:
        assert id_thread == 42
        self.fila.put(None)

    def apertar(self, id_atalho: int = ag.ID_ATALHO) -> None:
        self.fila.put(id_atalho)

    # janelas
    def janela_em_primeiro_plano(self) -> int | None:
        return self.frente

    def minimizada(self, hwnd: int) -> bool:
        return hwnd in self.minimizadas

    def pode_receber_foco(self, hwnd: int) -> bool:
        return hwnd in self.visiveis and hwnd not in self.minimizadas

    def restaurar(self, hwnd: int) -> None:
        self.chamadas.append(("restaurar", hwnd))
        self.minimizadas.discard(hwnd)

    def minimizar(self, hwnd: int) -> None:
        self.chamadas.append(("minimizar", hwnd))
        self.minimizadas.add(hwnd)
        self.frente = OUTRA

    def ativar(self, hwnd: int) -> bool:
        self.chamadas.append(("ativar", hwnd))
        if hwnd in self.recusar_ativar:
            return False
        self.frente = hwnd
        return True

    def area_de_trabalho(self) -> int | None:
        return AREA_DE_TRABALHO

    def enviar_para_fundo(self, hwnd: int) -> None:
        self.chamadas.append(("fundo", hwnd))


def criar(sistema: SistemaFalso, camada: str = "normal", janela: int | None = PROPRIA) -> ag.OuvinteAtalho:
    estado = {"camada": camada}
    ouvinte = ag.OuvinteAtalho(sistema, lambda: janela, lambda: estado["camada"])
    ouvinte.estado = estado  # type: ignore[attr-defined]
    return ouvinte


@pytest.fixture
def ouvinte_ativo():
    criados: list[ag.OuvinteAtalho] = []

    def fabricar(sistema: SistemaFalso, **kwargs) -> ag.OuvinteAtalho:
        ouvinte = criar(sistema, **kwargs)
        criados.append(ouvinte)
        ouvinte.iniciar()
        return ouvinte

    yield fabricar
    for ouvinte in criados:
        ouvinte.parar()


def esperar(condicao, prazo_s: float = 2.0) -> None:
    fim = time.monotonic() + prazo_s
    while not condicao():
        assert time.monotonic() < fim, "condição não ocorreu no prazo"
        time.sleep(0.005)


def test_registra_o_primeiro_com_norepeat(ouvinte_ativo):
    sistema = SistemaFalso()
    ouvinte = ouvinte_ativo(sistema)
    assert ouvinte.registrado.nome == "Ctrl+Alt+B" and ouvinte.recusados == []
    assert sistema.registrados == {ag.ID_ATALHO: (ag.MOD_CONTROL | ag.MOD_ALT | ag.MOD_NOREPEAT, ord("B"))}
    assert ouvinte.ativo


def test_primeiro_em_uso_registra_o_segundo(ouvinte_ativo, caplog):
    sistema = SistemaFalso({(ag.MOD_CONTROL | ag.MOD_ALT, ord("B")): ag.ERROR_HOTKEY_ALREADY_REGISTERED})
    with caplog.at_level(logging.WARNING, logger="atalho_global"):
        ouvinte = ouvinte_ativo(sistema)
    assert ouvinte.registrado.nome == "Ctrl+Shift+Alt+B"
    assert [a.nome for a in ouvinte.recusados] == ["Ctrl+Alt+B"]
    assert "Ctrl+Alt+B já está em uso por outro programa" in caplog.text


def test_todos_em_uso_segue_sem_atalho_e_sem_thread(ouvinte_ativo, caplog):
    em_uso = ag.ERROR_HOTKEY_ALREADY_REGISTERED
    sistema = SistemaFalso({
        (ag.MOD_CONTROL | ag.MOD_ALT, ord("B")): em_uso,
        (ag.MOD_CONTROL | ag.MOD_SHIFT | ag.MOD_ALT, ord("B")): 5,  # outro erro qualquer
    })
    with caplog.at_level(logging.WARNING, logger="atalho_global"):
        ouvinte = ouvinte_ativo(sistema)
    assert ouvinte.registrado is None and len(ouvinte.recusados) == 2
    assert "não pôde ser registrado (erro 5)" in caplog.text
    assert "nenhuma combinação disponível" in caplog.text
    esperar(lambda: not ouvinte.ativo)
    ouvinte.parar()  # sem thread viva: não faz nada nem levanta


def test_parar_encerra_o_laco_e_desfaz_o_registro_na_thread_do_atalho(ouvinte_ativo):
    sistema = SistemaFalso()
    ouvinte = ouvinte_ativo(sistema)
    ouvinte.parar()
    assert not ouvinte.ativo
    assert sistema.cancelados == [ag.ID_ATALHO] and sistema.registrados == {}
    assert sistema.thread_do_laco.name == "atalho-global"


def test_falha_na_preparacao_e_avisada(caplog):
    class Quebrado(SistemaFalso):
        def preparar_fila(self) -> int:
            raise OSError("sem fila")

    ouvinte = criar(Quebrado())
    with caplog.at_level(logging.ERROR, logger="atalho_global"):
        assert ouvinte.iniciar() is None
    assert "não iniciou" in caplog.text
    ouvinte.parar()


def test_aviso_roda_na_thread_do_atalho_e_ignora_outros_ids(ouvinte_ativo):
    sistema = SistemaFalso()
    ouvinte = ouvinte_ativo(sistema)
    threads: list[str] = []
    original = ouvinte.ao_apertar

    def registrar_thread():
        threads.append(threading.current_thread().name)
        return original()

    ouvinte.ao_apertar = registrar_thread  # type: ignore[method-assign]
    sistema.apertar(99)  # id de outro atalho: ignorado
    sistema.apertar()
    esperar(lambda: threads)
    assert threads == ["atalho-global"]
    esperar(lambda: sistema.frente == PROPRIA)  # trouxe a janela


def test_erro_ao_tratar_nao_derruba_o_laco(ouvinte_ativo, caplog):
    sistema = SistemaFalso()
    ouvinte = ouvinte_ativo(sistema)
    vezes: list[int] = []

    def explode():
        vezes.append(1)
        raise RuntimeError("falha simulada")

    ouvinte.ao_apertar = explode  # type: ignore[method-assign]
    with caplog.at_level(logging.ERROR, logger="atalho_global"):
        sistema.apertar()
        sistema.apertar()
        esperar(lambda: len(vezes) == 2)
    assert "falha ao tratar o atalho" in caplog.text
    assert ouvinte.ativo


# -- decisões (ao_apertar direto, sem thread) ---------------------------------


@pytest.mark.parametrize("camada", ["normal", "topo", "fundo"])
def test_atras_de_outras_traz_e_ativa(camada):
    sistema = SistemaFalso()
    ouvinte = criar(sistema, camada=camada)
    assert ouvinte.ao_apertar() == "trazer"
    assert sistema.chamadas == [("ativar", PROPRIA)]


@pytest.mark.parametrize("camada", ["normal", "topo"])
def test_minimizada_restaura_e_ativa(camada):
    sistema = SistemaFalso()
    sistema.minimizadas.add(PROPRIA)
    ouvinte = criar(sistema, camada=camada)
    assert ouvinte.ao_apertar() == "trazer"
    assert sistema.chamadas == [("restaurar", PROPRIA), ("ativar", PROPRIA)]


@pytest.mark.parametrize("camada", ["normal", "topo"])
def test_na_frente_minimiza(camada):
    sistema = SistemaFalso()
    sistema.frente = PROPRIA
    assert criar(sistema, camada=camada).ao_apertar() == "minimizar"
    assert sistema.chamadas == [("minimizar", PROPRIA)]


def test_liga_desliga_na_camada_normal():
    sistema = SistemaFalso()
    ouvinte = criar(sistema)
    assert [ouvinte.ao_apertar() for _ in range(3)] == ["trazer", "minimizar", "trazer"]


def test_fundo_devolve_o_foco_a_janela_de_antes():
    sistema = SistemaFalso()
    ouvinte = criar(sistema, camada="fundo")
    assert ouvinte.ao_apertar() == "trazer"
    assert ouvinte.ao_apertar() == "devolver_foco"
    assert sistema.chamadas == [("ativar", PROPRIA), ("ativar", OUTRA)]
    assert sistema.frente == OUTRA


def test_fundo_sem_janela_de_antes_devolve_a_area_de_trabalho():
    sistema = SistemaFalso()
    ouvinte = criar(sistema, camada="fundo")
    ouvinte.ao_apertar()
    sistema.visiveis.discard(OUTRA)  # a janela de antes foi fechada
    assert ouvinte.ao_apertar() == "devolver_foco"
    assert sistema.chamadas[-1] == ("ativar", AREA_DE_TRABALHO)


def test_fundo_ja_na_frente_por_clique_devolve_a_area_de_trabalho():
    """Clicada (sem o atalho), não há janela de antes guardada."""
    sistema = SistemaFalso()
    sistema.frente = PROPRIA
    assert criar(sistema, camada="fundo").ao_apertar() == "devolver_foco"
    assert sistema.chamadas == [("ativar", AREA_DE_TRABALHO)]


def test_fundo_sem_para_onde_mandar_o_foco_ao_menos_afunda():
    sistema = SistemaFalso()
    sistema.frente = PROPRIA
    sistema.recusar_ativar.add(AREA_DE_TRABALHO)
    criar(sistema, camada="fundo").ao_apertar()
    assert sistema.chamadas == [("ativar", AREA_DE_TRABALHO), ("fundo", PROPRIA)]


def test_janela_de_antes_so_vale_uma_vez():
    sistema = SistemaFalso()
    ouvinte = criar(sistema, camada="fundo")
    ouvinte.ao_apertar()            # traz (guarda OUTRA)
    ouvinte.ao_apertar()            # devolve a OUTRA
    sistema.frente = PROPRIA        # clicada
    ouvinte.ao_apertar()            # nada guardado: área de trabalho
    assert sistema.chamadas[-1] == ("ativar", AREA_DE_TRABALHO)


def test_ativar_recusado_e_avisado(caplog):
    sistema = SistemaFalso()
    sistema.recusar_ativar.add(PROPRIA)
    with caplog.at_level(logging.WARNING, logger="atalho_global"):
        criar(sistema).ao_apertar()
    assert "não trouxe a janela para a frente" in caplog.text


def test_sem_janela_nao_faz_nada(caplog):
    sistema = SistemaFalso()
    with caplog.at_level(logging.WARNING, logger="atalho_global"):
        assert criar(sistema, janela=None).ao_apertar() is None
    assert sistema.chamadas == [] and "janela não encontrada" in caplog.text


def test_camada_lida_a_cada_aperto():
    sistema = SistemaFalso()
    sistema.frente = PROPRIA
    ouvinte = criar(sistema, camada="normal")
    ouvinte.estado["camada"] = "fundo"  # mudou depois de o ouvinte existir
    assert ouvinte.ao_apertar() == "devolver_foco"


# ---------------------------------------------------------------------------
# Windows real
# ---------------------------------------------------------------------------

windows = pytest.mark.skipif(sys.platform != "win32", reason="só no Windows")
# Improvável de estar em uso: F24 não existe na maioria dos teclados.
IMPROVAVEL = ("ctrl+shift+alt+f24",)


@windows
def test_registro_real_recusa_duplicata_e_libera_ao_parar():
    primeiro = ag.OuvinteAtalho(ag.SistemaWin32Atalho(), lambda: None, lambda: "normal", IMPROVAVEL)
    segundo = ag.OuvinteAtalho(ag.SistemaWin32Atalho(), lambda: None, lambda: "normal", IMPROVAVEL)
    terceiro = ag.OuvinteAtalho(ag.SistemaWin32Atalho(), lambda: None, lambda: "normal", IMPROVAVEL)
    try:
        assert primeiro.iniciar() is not None, "Ctrl+Shift+Alt+F24 já em uso nesta máquina?"
        assert segundo.iniciar() is None
        assert [a.nome for a in segundo.recusados] == ["Ctrl+Shift+Alt+F24"]
        primeiro.parar()
        assert not primeiro.ativo
        assert terceiro.iniciar() is not None  # o registro foi desfeito
    finally:
        for ouvinte in (primeiro, segundo, terceiro):
            ouvinte.parar()


@windows
def test_wm_hotkey_real_chega_na_thread_do_atalho():
    sistema = ag.SistemaWin32Atalho()
    ouvinte = ag.OuvinteAtalho(sistema, lambda: None, lambda: "normal", IMPROVAVEL)
    recebidos: list[str] = []
    ouvinte.ao_apertar = lambda: recebidos.append(threading.current_thread().name)  # type: ignore[method-assign]
    try:
        assert ouvinte.iniciar() is not None
        # Simula o Windows: WM_HOTKEY na fila da thread que registrou.
        assert sistema._u.PostThreadMessageW(ouvinte._id_thread, sistema.WM_HOTKEY, ag.ID_ATALHO, 0)
        esperar(lambda: recebidos)
        assert recebidos == ["atalho-global"]
    finally:
        ouvinte.parar()
    assert not ouvinte.ativo


@windows
def test_consultas_reais_de_janela_nao_falham():
    sistema = ag.SistemaWin32Atalho()
    frente = sistema.janela_em_primeiro_plano()
    if frente:
        assert isinstance(sistema.minimizada(frente), bool)
        assert isinstance(sistema.pode_receber_foco(frente), bool)
    assert sistema.area_de_trabalho()  # Progman
