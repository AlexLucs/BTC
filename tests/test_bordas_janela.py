"""Testes do arraste com bordas magnéticas (bordas_janela.py), sem abrir janela."""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bordas_janela as bj  # noqa: E402
from bordas_janela import Retangulo  # noqa: E402

AREA = Retangulo(0, 0, 1920, 1040)  # 1920×1080 com a barra de tarefas embaixo (40 px)


def janela_em(x: int, y: int, largura: int = 500, altura: int = 810) -> Retangulo:
    return Retangulo(x, y, x + largura, y + altura)


# ---------------------------------------------------------------- encaixar_eixo


@pytest.mark.parametrize(
    "inicio, esperado",
    [
        (10, 0),  # no limite do ímã
        (11, 11),  # um pixel além: não encaixa
        (-10, 0),  # passou um pouco da borda: volta
        (-11, -11),  # longe demais para fora: fica (como no Windows)
        (0, 0),
    ],
)
def test_encaixar_eixo_na_borda_do_inicio(inicio, esperado):
    assert bj.encaixar_eixo(inicio, 500, 0, 1920, 10) == esperado


@pytest.mark.parametrize(
    "inicio, esperado",
    [
        (1920 - 500 - 10, 1420),
        (1920 - 500 + 10, 1420),
        (1920 - 500 - 11, 1409),
    ],
)
def test_encaixar_eixo_na_borda_do_fim(inicio, esperado):
    assert bj.encaixar_eixo(inicio, 500, 0, 1920, 10) == esperado


def test_encaixar_eixo_vence_a_borda_mais_proxima():
    # Janela quase do tamanho da área: início a 3 px e fim (998) a 2 px → vence o fim.
    assert bj.encaixar_eixo(3, 995, 0, 1000, 10) == 5
    # Início a 1 px e fim (996) a 4 px → vence o início.
    assert bj.encaixar_eixo(1, 995, 0, 1000, 10) == 0


def test_encaixar_eixo_empate_prefere_o_inicio():
    # Janela maior que a área (810 de altura num monitor de 800 livres):
    # início a 5 px e fim a 5 px → fica no topo, com os botões visíveis.
    assert bj.encaixar_eixo(-5, 810, 0, 800, 10) == 0


# --------------------------------------------------------------------- encaixar


def test_encaixar_longe_das_bordas_nao_mexe():
    assert bj.encaixar(janela_em(700, 100), AREA) == (700, 100)


def test_encaixar_canto_superior_esquerdo():
    assert bj.encaixar(janela_em(7, -4), AREA) == (0, 0)


def test_encaixar_canto_inferior_direito_respeita_a_barra_de_tarefas():
    # Base da janela a 6 px do topo da barra de tarefas (1040).
    janela = janela_em(1425, 1040 - 810 + 6)
    assert bj.encaixar(janela, AREA) == (1420, 1040 - 810)


def test_encaixar_barra_de_tarefas_a_esquerda():
    area = Retangulo(60, 0, 1920, 1080)
    assert bj.encaixar(janela_em(55, 300), area) == (60, 300)


def test_encaixar_segundo_monitor_com_coordenadas_negativas():
    area = Retangulo(-1280, -200, 0, 824)  # monitor à esquerda e mais alto
    assert bj.encaixar(janela_em(-1275, -195, altura=388), area) == (-1280, -200)
    assert bj.encaixar(janela_em(-498, 430, altura=388), area) == (-500, 824 - 388)


@pytest.mark.parametrize(("esquerda", "esperado"), [(20, 0), (-20, 0), (21, 21), (-21, -21)])
def test_encaixar_usa_20_px_por_padrao(esquerda, esperado):
    assert bj.DISTANCIA_IMA == 20
    assert bj.encaixar(janela_em(esquerda, 300), AREA) == (esperado, 300)


def test_encaixar_respeita_a_distancia_pedida():
    assert bj.encaixar(janela_em(15, 300), AREA, distancia=20) == (0, 300)
    assert bj.encaixar(janela_em(15, 300), AREA, distancia=10) == (15, 300)


# -------------------------------------------------------------------- area_livre


def tela(x=0, y=0, width=1920, height=1080, frame=None):
    return SimpleNamespace(x=x, y=y, width=width, height=height, frame=frame)


def frame(x, y, w, h):
    # Imita o System.Drawing.Rectangle do WinForms (atributos X, Y, Width, Height).
    return SimpleNamespace(X=x, Y=y, Width=w, Height=h)


def test_area_livre_usa_o_working_area():
    assert bj.area_livre(tela(frame=frame(0, 0, 1920, 1040))) == AREA


def test_area_livre_monitor_secundario():
    t = tela(x=1920, y=0, width=1280, height=1024, frame=frame(1920, 0, 1280, 984))
    assert bj.area_livre(t) == Retangulo(1920, 0, 3200, 984)


def test_area_livre_sem_frame_usa_a_area_total():
    t = SimpleNamespace(x=0, y=0, width=1920, height=1080)  # objeto sem 'frame'
    assert bj.area_livre(t) == Retangulo(0, 0, 1920, 1080)
    assert bj.area_livre(tela(frame=None)) == Retangulo(0, 0, 1920, 1080)


@pytest.mark.parametrize(
    "invalido",
    [
        frame(0, 0, 0, 0),  # vazio
        frame(0, 0, 2000, 1040),  # maior que o monitor
        frame(1920, 0, 1280, 1024),  # de outro monitor
        SimpleNamespace(X=0),  # incompleto
        object(),
    ],
)
def test_area_livre_com_frame_incoerente_usa_a_area_total(invalido):
    assert bj.area_livre(tela(frame=invalido)) == Retangulo(0, 0, 1920, 1080)


# ----------------------------------------------------------- acompanhar_arraste


class SistemaFalso:
    """Cursor roteirizado: cada leitura com o botão pressionado avança um passo."""

    def __init__(self, janela, cursores, area=AREA, falhar_mover=False):
        self.janela = janela
        self.cursores = list(cursores)
        self.area = area
        self.falhar_mover = falhar_mover
        self.indice = 0
        self.movimentos: list[tuple[int, int]] = []

    def botao_pressionado(self):
        return self.indice < len(self.cursores)

    def cursor(self):
        posicao = self.cursores[self.indice]
        self.indice += 1
        return posicao

    def retangulo_janela(self, hwnd):
        return self.janela

    def area_de_trabalho(self, x, y):
        return self.area

    def mover(self, hwnd, x, y):
        if self.falhar_mover:
            return False
        self.movimentos.append((x, y))
        self.janela = janela_em(x, y, self.janela.largura, self.janela.altura)
        return True


def arrastar(sistema):
    return bj.acompanhar_arraste(123, sistema, dormir=lambda _s: None)


def test_arraste_segue_o_cursor_mantendo_o_ponto_pego():
    # Pega a janela em (100, 20) a partir do canto (600, 100) e arrasta.
    sistema = SistemaFalso(janela_em(600, 100), [(700, 120), (750, 170), (800, 220)])
    assert arrastar(sistema) == 2
    assert sistema.movimentos == [(650, 150), (700, 200)]


def test_arraste_gruda_na_borda_esquerda_e_solta_ao_afastar():
    sistema = SistemaFalso(
        janela_em(300, 100),
        [(400, 120), (118, 120), (100, 120), (79, 120)],  # 18, 0 e −21 px da borda
    )
    arrastar(sistema)
    assert sistema.movimentos == [(0, 100), (-21, 100)]


def test_arraste_gruda_acima_da_barra_de_tarefas():
    # Cursor em y=287 → topo 237 → base 1047, 7 px sobre a barra → encaixa em 230.
    sistema = SistemaFalso(janela_em(100, 100), [(150, 150), (150, 287)])
    arrastar(sistema)
    assert sistema.movimentos == [(100, 1040 - 810)]


def test_arraste_nao_move_sem_mudanca_de_posicao():
    sistema = SistemaFalso(janela_em(600, 100), [(700, 120)] * 5)
    assert arrastar(sistema) == 0
    assert sistema.movimentos == []


def test_arraste_com_botao_ja_solto_nao_faz_nada():
    sistema = SistemaFalso(janela_em(600, 100), [])
    assert arrastar(sistema) == 0


def test_arraste_sem_area_de_trabalho_nao_encaixa():
    sistema = SistemaFalso(janela_em(300, 100), [(400, 120), (105, 120)], area=None)
    arrastar(sistema)
    assert sistema.movimentos == [(5, 100)]


def test_arraste_sem_janela_nao_faz_nada():
    sistema = SistemaFalso(None, [(1, 1), (2, 2)])
    assert arrastar(sistema) == 0


def test_arraste_para_se_mover_falhar(caplog):
    sistema = SistemaFalso(janela_em(600, 100), [(700, 120), (750, 170), (800, 220)], falhar_mover=True)
    assert arrastar(sistema) == 0
    assert sistema.indice == 2  # parou na 1ª falha, sem ler o resto
    assert "Falha ao mover" in caplog.text


# --------------------------------------------------------------------- Arrastador


def test_arrastador_ignora_um_segundo_pedido_durante_o_arraste():
    liberar = threading.Event()
    comecou = threading.Event()

    def obter_hwnd():
        comecou.set()
        liberar.wait(2)
        return 123

    arrastador = bj.Arrastador(obter_hwnd, SistemaFalso(janela_em(0, 0), []))
    assert arrastador.iniciar() is True
    assert comecou.wait(2)
    assert arrastador.iniciar() is False
    liberar.set()
    # Depois do fim do 1º, um novo arraste é aceito.
    for _ in range(200):
        if arrastador.iniciar(esperar=True):
            break
        threading.Event().wait(0.01)
    else:
        pytest.fail("o arrastador não liberou a trava")


def test_arrastador_sem_janela_registra_no_log(caplog):
    arrastador = bj.Arrastador(lambda: None, SistemaFalso(janela_em(0, 0), [(1, 1)]))
    assert arrastador.iniciar(esperar=True) is True
    assert "janela não encontrada" in caplog.text
    assert arrastador.iniciar(esperar=True) is True  # trava liberada


def test_arrastador_com_erro_registra_e_libera_a_trava(caplog):
    def falhar():
        raise RuntimeError("boom")

    arrastador = bj.Arrastador(falhar, SistemaFalso(janela_em(0, 0), []))
    assert arrastador.iniciar(esperar=True) is True
    assert "Falha no arraste" in caplog.text
    assert arrastador.iniciar(esperar=True) is True


# --------------------------------------------------------------------- Win32


@pytest.mark.skipif(sys.platform == "win32", reason="confere só a recusa fora do Windows")
def test_sistema_win32_recusa_fora_do_windows():
    with pytest.raises(OSError):
        bj.SistemaWin32()


@pytest.mark.skipif(sys.platform != "win32", reason="só no Windows")
def test_sistema_win32_le_cursor_e_area_de_trabalho():
    sistema = bj.SistemaWin32()
    x, y = sistema.cursor()
    area = sistema.area_de_trabalho(x, y)
    assert area is not None and area.largura > 0 and area.altura > 0
    assert isinstance(sistema.botao_pressionado(), bool)
