"""Arraste da janela com bordas magnéticas e área livre dos monitores.

O ``easy_drag`` do pywebview move a janela pelo JavaScript, com um
``SetWindowPos`` a cada movimento do mouse, sem nenhuma noção das bordas da
tela. Este módulo substitui esse arraste: o JS só avisa que o botão foi
pressionado (``ExposedApi.iniciar_arraste``) e uma thread do Python acompanha
o cursor até o botão ser solto, encaixando a janela nas bordas da área livre
(sem a barra de tarefas) do monitor sob o cursor.

Coordenadas:
- o laço de arraste usa só coordenadas do próprio Win32 (``GetCursorPos``,
  ``GetWindowRect``, ``GetMonitorInfo``, ``SetWindowPos``), sem converter para
  os pixels lógicos do pywebview (armadilha 3);
- ``area_livre`` trabalha nas coordenadas de ``webview.screens``, as mesmas que
  o resto do ``BTC_Monitor.py`` já usa.

As funções do Win32 ficam atrás de ``SistemaJanela`` para que o laço seja
testado sem abrir janela. Nenhuma propriedade .NET é alterada (armadilha 1).
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

logger = logging.getLogger(__name__)

DISTANCIA_IMA = 20
"""Distância (px) a partir da qual uma borda da janela gruda na da área livre."""

INTERVALO_ARRASTE_S = 1 / 120
"""Intervalo entre duas leituras do cursor durante o arraste."""


@dataclass(frozen=True)
class Retangulo:
    """Retângulo com bordas exclusivas à direita e embaixo (como o ``RECT``)."""

    esquerda: int
    topo: int
    direita: int
    base: int

    @property
    def largura(self) -> int:
        return self.direita - self.esquerda

    @property
    def altura(self) -> int:
        return self.base - self.topo

    def contem(self, outro: Retangulo) -> bool:
        return (
            self.esquerda <= outro.esquerda
            and self.topo <= outro.topo
            and outro.direita <= self.direita
            and outro.base <= self.base
        )

    def contem_ponto(self, x: int, y: int) -> bool:
        return self.esquerda <= x < self.direita and self.topo <= y < self.base


# ---------------------------------------------------------------------------
# Lógica pura
# ---------------------------------------------------------------------------


def encaixar_eixo(
    inicio: int, tamanho: int, area_inicio: int, area_fim: int, distancia: int
) -> int:
    """Devolve o novo início da janela num eixo, encaixado se estiver perto.

    Vale dos dois lados da borda: a janela que passou um pouco da borda também
    volta para ela. Se as duas bordas estiverem ao alcance (janela maior ou
    quase do tamanho da área), vence a mais próxima; no empate, a do início
    (topo ou esquerda), para os botões da barra ficarem visíveis.
    """
    distancia_inicio = abs(inicio - area_inicio)
    distancia_fim = abs(inicio + tamanho - area_fim)
    candidatos = []
    if distancia_inicio <= distancia:
        candidatos.append((distancia_inicio, area_inicio))
    if distancia_fim <= distancia:
        candidatos.append((distancia_fim, area_fim - tamanho))
    if not candidatos:
        return inicio
    # min() devolve o primeiro em caso de empate: a borda do início.
    return min(candidatos, key=lambda candidato: candidato[0])[1]


def encaixar(
    janela: Retangulo, area: Retangulo, distancia: int = DISTANCIA_IMA
) -> tuple[int, int]:
    """Posição (x, y) da janela depois de encaixar nas bordas de ``area``."""
    x = encaixar_eixo(janela.esquerda, janela.largura, area.esquerda, area.direita, distancia)
    y = encaixar_eixo(janela.topo, janela.altura, area.topo, area.base, distancia)
    return x, y


def area_total(tela: object) -> Retangulo:
    """Área total de um item de ``webview.screens``."""
    x, y = int(tela.x), int(tela.y)  # type: ignore[attr-defined]
    return Retangulo(x, y, x + int(tela.width), y + int(tela.height))  # type: ignore[attr-defined]


def area_livre(tela: object) -> Retangulo:
    """Área livre (sem a barra de tarefas) de um item de ``webview.screens``.

    No Windows, o pywebview 6.2.1 guarda em ``Screen.frame`` o
    ``Screen.WorkingArea`` do WinForms, nas mesmas coordenadas de
    ``x``/``y``/``width``/``height`` (``Screen.Bounds``). Se ``frame`` faltar
    ou for incoerente (vazio ou fora do monitor), vale a área total.
    """
    total = area_total(tela)
    frame = getattr(tela, "frame", None)
    if frame is None:
        return total
    try:
        x, y = int(frame.X), int(frame.Y)
        livre = Retangulo(x, y, x + int(frame.Width), y + int(frame.Height))
    except Exception:  # objeto .NET inesperado ou atributo ausente
        return total
    if livre.largura <= 0 or livre.altura <= 0 or not total.contem(livre):
        return total
    return livre


# ---------------------------------------------------------------------------
# Laço de arraste
# ---------------------------------------------------------------------------


class SistemaJanela(Protocol):
    """Operações do sistema usadas pelo arraste (Win32 no app, falsas nos testes)."""

    def botao_pressionado(self) -> bool: ...

    def cursor(self) -> tuple[int, int]: ...

    def retangulo_janela(self, hwnd: int) -> Retangulo | None: ...

    def area_de_trabalho(self, x: int, y: int) -> Retangulo | None: ...

    def mover(self, hwnd: int, x: int, y: int) -> bool: ...


def acompanhar_arraste(
    hwnd: int,
    sistema: SistemaJanela,
    distancia: int = DISTANCIA_IMA,
    intervalo_s: float = INTERVALO_ARRASTE_S,
    dormir: Callable[[float], None] = time.sleep,
) -> int:
    """Move a janela com o cursor enquanto o botão estiver pressionado.

    O deslocamento entre o cursor e o canto da janela é lido na 1ª volta, e não
    no clique: se o mouse andar um pouco antes de a thread começar, a janela
    não pula. Só chama ``mover`` quando a posição muda. Devolve quantas vezes
    a janela foi movida.
    """
    if not sistema.botao_pressionado():
        return 0
    retangulo = sistema.retangulo_janela(hwnd)
    if retangulo is None:
        return 0
    cursor_x, cursor_y = sistema.cursor()
    desloc_x = cursor_x - retangulo.esquerda
    desloc_y = cursor_y - retangulo.topo
    largura, altura = retangulo.largura, retangulo.altura
    posicao_atual = (retangulo.esquerda, retangulo.topo)
    movimentos = 0

    while sistema.botao_pressionado():
        cursor_x, cursor_y = sistema.cursor()
        x, y = cursor_x - desloc_x, cursor_y - desloc_y
        area = sistema.area_de_trabalho(cursor_x, cursor_y)
        if area is not None:
            x, y = encaixar(Retangulo(x, y, x + largura, y + altura), area, distancia)
        if (x, y) != posicao_atual:
            if not sistema.mover(hwnd, x, y):
                logger.warning("Falha ao mover a janela durante o arraste")
                break
            posicao_atual = (x, y)
            movimentos += 1
        dormir(intervalo_s)
    return movimentos


class Arrastador:
    """Inicia o arraste numa thread própria; ignora pedidos durante um arraste.

    As chamadas da js_api rodam em threads paralelas (armadilha 12): um duplo
    clique pode pedir dois arrastes ao mesmo tempo, e só o primeiro vale.
    """

    def __init__(
        self,
        obter_hwnd: Callable[[], int | None],
        sistema: SistemaJanela | None = None,
        distancia: int = DISTANCIA_IMA,
    ) -> None:
        self._obter_hwnd = obter_hwnd
        self._sistema = sistema
        self._distancia = distancia
        self._trava = threading.Lock()

    def iniciar(self, esperar: bool = False) -> bool:
        """Começa o arraste. Devolve ``False`` se já houver um em andamento."""
        if not self._trava.acquire(blocking=False):
            return False
        thread = threading.Thread(target=self._executar, name="arraste-janela", daemon=True)
        try:
            thread.start()
        except Exception:
            self._trava.release()
            raise
        if esperar:
            thread.join()
        return True

    def _executar(self) -> None:
        try:
            hwnd = self._obter_hwnd()
            if not hwnd:
                logger.warning("Arraste: janela não encontrada")
                return
            if self._sistema is None:  # criado uma vez, no 1º arraste (só no Windows)
                self._sistema = SistemaWin32()
            acompanhar_arraste(hwnd, self._sistema, self._distancia)
        except Exception:
            logger.exception("Falha no arraste da janela")
        finally:
            self._trava.release()


# ---------------------------------------------------------------------------
# Win32 (ctypes)
# ---------------------------------------------------------------------------


class SistemaWin32:
    """``SistemaJanela`` real, via ctypes. Só existe no Windows.

    ``argtypes``/``restype`` declarados em todas as funções com handles
    (armadilha 15). As chamadas ctypes liberam o GIL.
    """

    _VK_LBUTTON = 0x01
    _VK_RBUTTON = 0x02
    _SM_SWAPBUTTON = 23
    _MONITOR_DEFAULTTONEAREST = 2
    _SWP_NOSIZE = 0x0001
    _SWP_NOZORDER = 0x0004
    _SWP_NOACTIVATE = 0x0010

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("SistemaWin32 só funciona no Windows")
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._MONITORINFO = MONITORINFO
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        self._user32 = user32

    def botao_pressionado(self) -> bool:
        # GetAsyncKeyState lê o botão FÍSICO: com os botões trocados (canhotos),
        # o clique principal é o VK_RBUTTON.
        trocados = bool(self._user32.GetSystemMetrics(self._SM_SWAPBUTTON))
        tecla = self._VK_RBUTTON if trocados else self._VK_LBUTTON
        return bool(self._user32.GetAsyncKeyState(tecla) & 0x8000)

    def cursor(self) -> tuple[int, int]:
        ponto = self._wintypes.POINT()
        if not self._user32.GetCursorPos(self._ctypes.byref(ponto)):
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        return ponto.x, ponto.y

    def retangulo_janela(self, hwnd: int) -> Retangulo | None:
        rect = self._wintypes.RECT()
        if not self._user32.GetWindowRect(hwnd, self._ctypes.byref(rect)):
            return None
        return Retangulo(rect.left, rect.top, rect.right, rect.bottom)

    def area_de_trabalho(self, x: int, y: int) -> Retangulo | None:
        monitor = self._user32.MonitorFromPoint(
            self._wintypes.POINT(x, y), self._MONITOR_DEFAULTTONEAREST
        )
        if not monitor:
            return None
        info = self._MONITORINFO()
        info.cbSize = self._ctypes.sizeof(self._MONITORINFO)
        if not self._user32.GetMonitorInfoW(monitor, self._ctypes.byref(info)):
            return None
        r = info.rcWork
        return Retangulo(r.left, r.top, r.right, r.bottom)

    def mover(self, hwnd: int, x: int, y: int) -> bool:
        flags = self._SWP_NOSIZE | self._SWP_NOZORDER | self._SWP_NOACTIVATE
        return bool(self._user32.SetWindowPos(hwnd, None, x, y, 0, 0, flags))
