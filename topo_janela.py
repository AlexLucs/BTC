"""Fixar a janela do app no topo usando a API Win32 via ctypes.

Por que não usar window.on_top do pywebview: no pywebview 6.2.1 (Windows), o setter
altera a propriedade TopMost do formulário WinForms direto da thread que atende a
js_api, sem passar pela thread da interface. A chamada .NET (pythonnet) mantém o
GIL do Python enquanto o Windows aguarda a thread da interface processar a mudança,
e essa thread precisa do GIL para executar os handlers Python de Move/Resize do
pywebview. Resultado: as duas threads esperam uma pela outra e o app trava.

O ctypes libera o GIL durante a chamada Win32 (é assim que o próprio pywebview
implementa window.move), então o problema não ocorre.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL

    # GetWindowLongPtrW só existe no Windows 64 bits; no 32 bits o equivalente é GetWindowLongW.
    _get_window_long = getattr(_user32, "GetWindowLongPtrW", None) or _user32.GetWindowLongW
    _get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
    _get_window_long.restype = ctypes.c_ssize_t
else:
    _user32 = None


def _exigir_windows() -> None:
    if _user32 is None:
        raise OSError("Fixar no topo só é suportado no Windows")


def _titulo(hwnd: int) -> str:
    tamanho = _user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(tamanho + 1)
    _user32.GetWindowTextW(hwnd, buffer, tamanho + 1)
    return buffer.value


def encontrar_janela(titulo: str) -> int | None:
    """Retorna o handle da janela deste processo com o título exato, ou None.

    Filtrar pelo processo evita pegar outra janela que tenha o mesmo título.
    """
    _exigir_windows()
    pid_atual = os.getpid()
    encontradas: list[int] = []

    @_WNDENUMPROC
    def verificar(hwnd, _parametro):
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == pid_atual and _titulo(hwnd) == titulo:
            encontradas.append(hwnd)
            return False  # interrompe a enumeração
        return True

    _user32.EnumWindows(verificar, 0)
    return encontradas[0] if encontradas else None


def esta_no_topo(hwnd: int) -> bool:
    _exigir_windows()
    return bool(_get_window_long(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def definir_topo(hwnd: int, fixar: bool) -> bool:
    """Fixa ou desafixa a janela no topo e retorna o estado real depois da mudança.

    Raises:
        OSError: se o Windows recusar a operação.
    """
    _exigir_windows()
    posicao_z = HWND_TOPMOST if fixar else HWND_NOTOPMOST
    sucesso = _user32.SetWindowPos(
        hwnd, posicao_z, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    )
    if not sucesso:
        raise ctypes.WinError(ctypes.get_last_error())
    return esta_no_topo(hwnd)
