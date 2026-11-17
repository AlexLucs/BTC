"""Uma instância só do BTC Status: abrir o app de novo traz a janela que já está aberta.

Duas cópias abertas ao mesmo tempo dividem a porta 42001 (a página de uma pode vir do
servidor da outra, com o modo compacto e o 1º preço da outra; armadilha 23), gravam cada
uma a sua lista no Alertas.json (a última apaga os alertas criados na outra), reescrevem o
.ini e disputam o log. Por isso a 2ª cópia não abre janela: ativa a que já existe e sai.

A marca da instância é um mutex nomeado do Windows ("Local\\...": por sessão de usuário),
criado no início do main() e mantido até o processo terminar (o Windows o libera sozinho,
inclusive se o app cair). A janela da outra instância é achada pelo título e por um PID
diferente do nosso (armadilha 2).

Organização (mesmo padrão do camada_fundo.py): `garantir` decide, com o sistema injetado
por parâmetro; `SistemaWin32Instancia` faz as chamadas ao Windows (ctypes, argtypes e
restype declarados; carregado só ao criar). No topo, só logging e typing.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

NOME_DO_MUTEX = "Local\\BTCStatus.instancia"
ERROR_ALREADY_EXISTS = 183


class SistemaInstancia(Protocol):
    def criar_marca(self, nome: str) -> bool: ...  # True se outra instância já a criou
    def janela_de_outra_instancia(self, titulo: str) -> int | None: ...
    def trazer_para_frente(self, hwnd: int) -> bool: ...


def garantir(sistema: SistemaInstancia, titulo: str, nome: str = NOME_DO_MUTEX) -> bool:
    """True se esta é a única instância (o app segue). False: já havia outra, cuja janela
    foi trazida para a frente (se achada); o app deve sair sem abrir janela.

    Qualquer falha ao conferir conta como "única": nunca impedir o app de abrir.
    """
    try:
        ja_existe = sistema.criar_marca(nome)
    except Exception:
        logger.exception("Instância única: falha ao conferir; o app abre assim mesmo")
        return True
    if not ja_existe:
        return True
    logger.info("Instância única: o BTC Status já está aberto; trazendo a janela dele")
    try:
        hwnd = sistema.janela_de_outra_instancia(titulo)
        if hwnd is None:
            logger.warning("Instância única: a janela da outra instância não foi achada")
        elif not sistema.trazer_para_frente(hwnd):
            logger.warning("Instância única: o Windows não trouxe a outra janela para a frente")
    except Exception:
        logger.exception("Instância única: falha ao trazer a outra janela")
    return False


class SistemaWin32Instancia:
    """Implementação por ctypes. Criada só no Windows."""

    SW_RESTORE = 9

    def __init__(self) -> None:
        import ctypes
        import os
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._pid = os.getpid()
        self._marca = None  # handle do mutex: guardado até o processo terminar
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        u = ctypes.WinDLL("user32", use_last_error=True)

        k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateMutexW.restype = wintypes.HANDLE
        self._enumerar_tipo = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = [self._enumerar_tipo, wintypes.LPARAM]
        u.EnumWindows.restype = wintypes.BOOL
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextLengthW.restype = ctypes.c_int
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.restype = ctypes.c_int
        u.IsIconic.argtypes = [wintypes.HWND]
        u.IsIconic.restype = wintypes.BOOL
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.ShowWindow.restype = wintypes.BOOL
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.SetForegroundWindow.restype = wintypes.BOOL
        self._k, self._u = k, u

    def criar_marca(self, nome: str) -> bool:
        ctypes = self._ctypes
        ctypes.set_last_error(0)
        marca = self._k.CreateMutexW(None, False, nome)
        if not marca:
            raise OSError(ctypes.get_last_error(), "CreateMutexW falhou")
        self._marca = marca  # o handle fica aberto: é ele que marca a instância
        return ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def janela_de_outra_instancia(self, titulo: str) -> int | None:
        ctypes, wintypes, u = self._ctypes, self._wintypes, self._u
        achadas: list[int] = []

        def verificar(hwnd, _parametro):
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self._pid:
                return True
            tamanho = u.GetWindowTextLengthW(hwnd)
            if tamanho != len(titulo):
                return True
            buffer = ctypes.create_unicode_buffer(tamanho + 1)
            u.GetWindowTextW(hwnd, buffer, tamanho + 1)
            if buffer.value == titulo:
                achadas.append(hwnd)
                return False  # interrompe a enumeração
            return True

        u.EnumWindows(self._enumerar_tipo(verificar), 0)
        return achadas[0] if achadas else None

    def trazer_para_frente(self, hwnd: int) -> bool:
        # Quem o usuário acabou de abrir pode mudar o primeiro plano; a outra instância,
        # na camada fundo, não afunda a própria janela quando ela é a do primeiro plano.
        if self._u.IsIconic(hwnd):
            self._u.ShowWindow(hwnd, self.SW_RESTORE)
        return bool(self._u.SetForegroundWindow(hwnd))
