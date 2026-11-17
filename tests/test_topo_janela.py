"""topo_janela.py: localizar a janela, fixar/desafixar no topo e saber se está minimizada.

A parte real usa uma janela "Static" criada pelo próprio teste (do mesmo processo, como a
do app), mostrada sem ativar (10x10 px no canto da tela, sem roubar o foco) e destruída no
fim. Visível como a do app: oculta, o Windows aceitou o HWND_TOPMOST sem marcá-la como
fixada (o teste falhou assim no Windows 11). Só no Windows.

Fixar no topo exige o terminal em primeiro plano (armadilha 87): com outro programa na frente,
o Windows aceita o HWND_TOPMOST sem aplicá-lo. Nesse caso o teste é pulado; com o terminal na
frente (ou outro processo da cadeia de pais do pytest), uma fixação que não pega é falha.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import topo_janela  # noqa: E402

TITULO = f"BTC Status teste topo {os.getpid()}"
MOTIVO_SEM_PRIMEIRO_PLANO = ("terminal fora do primeiro plano: o Windows não aplica o HWND_TOPMOST "
                             "(armadilha 87)")
LIMITE_DA_CADEIA = 64  # proteção contra PIDs reaproveitados que formem um ciclo


def cadeia_de_pais(pid: int, pais: dict[int, int]) -> list[int]:
    """O próprio `pid` e seus ancestrais, do mais próximo ao mais distante.

    Para no PID 0, num pai desconhecido, num PID já visto (reaproveitado pelo Windows) ou
    após LIMITE_DA_CADEIA processos.
    """
    cadeia: list[int] = []
    atual = pid
    while atual and atual not in cadeia and len(cadeia) < LIMITE_DA_CADEIA:
        cadeia.append(atual)
        atual = pais.get(atual, 0)
    return cadeia


def _pais_dos_processos() -> dict[int, int]:
    """PID → PID do pai de cada processo em execução (CreateToolhelp32Snapshot). Só Windows."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k.Process32FirstW.restype = wintypes.BOOL
    k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k.Process32NextW.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    th32cs_snapprocess = 0x2
    invalido = ctypes.c_void_p(-1).value
    instantaneo = k.CreateToolhelp32Snapshot(th32cs_snapprocess, 0)
    if not instantaneo or instantaneo == invalido:
        raise ctypes.WinError(ctypes.get_last_error())
    pais: dict[int, int] = {}
    try:
        entrada = PROCESSENTRY32W()
        entrada.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        continua = k.Process32FirstW(instantaneo, ctypes.byref(entrada))
        while continua:
            pais[entrada.th32ProcessID] = entrada.th32ParentProcessID
            continua = k.Process32NextW(instantaneo, ctypes.byref(entrada))
    finally:
        k.CloseHandle(instantaneo)
    return pais


def terminal_em_primeiro_plano() -> bool:
    """A janela em primeiro plano é do pytest ou de um ancestral dele (terminal, editor). Só Windows."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetForegroundWindow.argtypes = []
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    janela = u.GetForegroundWindow()
    if not janela:
        return False  # nenhuma (ex.: troca de janela em andamento, sessão bloqueada)
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(janela, ctypes.byref(pid))
    return pid.value in cadeia_de_pais(os.getpid(), _pais_dos_processos())


@pytest.mark.skipif(sys.platform == "win32", reason="confere a recusa fora do Windows")
@pytest.mark.parametrize("funcao", [
    lambda: topo_janela.encontrar_janela(TITULO),
    lambda: topo_janela.esta_no_topo(1),
    lambda: topo_janela.definir_topo(1, True),
    lambda: topo_janela.esta_minimizada(1),
])
def test_fora_do_windows_recusa_com_oserror(funcao):
    with pytest.raises(OSError):
        funcao()


@pytest.fixture
def janela_de_teste():
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    u = ctypes.WinDLL("user32", use_last_error=True)
    u.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    u.CreateWindowExW.restype = wintypes.HWND
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.DestroyWindow.restype = wintypes.BOOL
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.ShowWindow.restype = wintypes.BOOL
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsWindowVisible.restype = wintypes.BOOL
    ws_popup = 0x80000000
    sw_shownoactivate = 4
    hwnd = u.CreateWindowExW(0, "Static", TITULO, ws_popup, 0, 0, 10, 10, None, None, None, None)
    assert hwnd, f"CreateWindowExW falhou (erro {ctypes.get_last_error()})"
    u.ShowWindow(hwnd, sw_shownoactivate)  # visível como a janela do app, sem ativar
    assert u.IsWindowVisible(hwnd)
    try:
        yield hwnd, u
    finally:
        u.DestroyWindow(hwnd)


@pytest.mark.skipif(sys.platform != "win32", reason="janela real do Windows")
def test_encontra_a_janela_do_proprio_processo_pelo_titulo(janela_de_teste):
    hwnd, _u = janela_de_teste
    assert topo_janela.encontrar_janela(TITULO) == hwnd
    assert topo_janela.encontrar_janela(TITULO + " (outra)") is None


@pytest.mark.skipif(sys.platform != "win32", reason="janela real do Windows")
def test_fixa_e_desafixa_no_topo(janela_de_teste):
    hwnd, _u = janela_de_teste
    assert topo_janela.esta_no_topo(hwnd) is False
    fixada = topo_janela.definir_topo(hwnd, True)
    if not fixada and not terminal_em_primeiro_plano():
        pytest.skip(MOTIVO_SEM_PRIMEIRO_PLANO)
    assert fixada is True
    assert topo_janela.esta_no_topo(hwnd) is True
    assert topo_janela.definir_topo(hwnd, False) is False
    assert topo_janela.esta_no_topo(hwnd) is False


@pytest.mark.skipif(sys.platform != "win32", reason="janela real do Windows")
def test_sabe_quando_a_janela_esta_minimizada(janela_de_teste):
    hwnd, u = janela_de_teste
    assert topo_janela.esta_minimizada(hwnd) is False
    u.ShowWindow(hwnd, 7)  # SW_SHOWMINNOACTIVE: minimiza sem roubar o foco
    assert topo_janela.esta_minimizada(hwnd) is True


def test_cadeia_de_pais_sobe_ate_o_fim_e_para_em_ciclos():
    pais = {50: 40, 40: 30, 30: 0, 7: 8, 8: 7}
    assert cadeia_de_pais(50, pais) == [50, 40, 30]
    assert cadeia_de_pais(40, pais) == [40, 30]
    assert cadeia_de_pais(99, pais) == [99]  # pai desconhecido
    assert cadeia_de_pais(7, pais) == [7, 8]  # PID reaproveitado formando ciclo
    assert cadeia_de_pais(0, pais) == []
    longa = {n: n + 1 for n in range(1, 1000)}
    assert len(cadeia_de_pais(1, longa)) == LIMITE_DA_CADEIA


@pytest.mark.skipif(sys.platform != "win32", reason="processos reais do Windows")
def test_cadeia_real_do_pytest_inclui_o_pai():
    """Controle da verificação de primeiro plano: a cadeia real chega ao processo que abriu o pytest."""
    cadeia = cadeia_de_pais(os.getpid(), _pais_dos_processos())
    assert cadeia[:2] == [os.getpid(), os.getppid()]
