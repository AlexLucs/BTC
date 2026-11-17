"""Atalho global do teclado: traz o BTC Status para a frente ou o esconde, de qualquer programa.

Liga/desliga, nas três camadas:

- janela minimizada ou atrás de outras: restaura (se minimizada) e a ativa;
- já em primeiro plano, camada normal ou topo: minimiza;
- já em primeiro plano, camada fundo: devolve o foco à janela que estava ativa antes
  do atalho (ou à área de trabalho); a vigia da camada fundo a afunda sozinha.

Combinações tentadas em ordem (`ATALHOS_PADRAO`): se a 1ª já estiver registrada por
outro programa, vale a 2ª. As recusadas ficam em `recusados` para a página avisar.

O `RegisterHotKey` com janela nula associa o atalho à thread que o registrou: o
`WM_HOTKEY` chega na fila dela. Por isso o `OuvinteAtalho` tem thread própria
(`atalho-global`) com laço de mensagens, ligada enquanto a janela existe (a vigia da
camada fundo só existe no fundo). A ação roda **nessa mesma thread**, ao receber o
`WM_HOTKEY`: é ela que ganha do Windows a permissão de mudar o primeiro plano; repassada
a outra thread, a permissão se perderia e o Windows só piscaria o botão na barra.

Nada de .NET: tudo por ctypes, com `argtypes`/`restype` declarados (armadilhas 1 e 15).
No topo, só `logging`, `threading`, `typing` e `collections.abc` (como o `camada_fundo.py`): nada que o
build exclua.

Organização (mesmo padrão do `camada_fundo.py`):

- lógica pura: `ler_atalho`, `acao_do_atalho`;
- `OuvinteAtalho`: thread, registro (com reserva), laço e decisões, com o sistema
  injetado por parâmetro;
- `SistemaWin32Atalho`: chamadas ao Windows.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from typing import NamedTuple, Protocol

logger = logging.getLogger(__name__)

# Tentadas em ordem: a 2ª só se a 1ª estiver em uso por outro programa.
ATALHOS_PADRAO: tuple[str, ...] = ("ctrl+alt+b", "ctrl+shift+alt+b")

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000  # tecla segurada não repete o aviso
ID_ATALHO = 1
ERROR_HOTKEY_ALREADY_REGISTERED = 1409
ESPERA_REGISTRO_S = 2.0
ESPERA_ENCERRAR_S = 2.0

# Ordem e nomes de exibição dos modificadores.
_MODIFICADORES = (("ctrl", MOD_CONTROL, "Ctrl"), ("shift", MOD_SHIFT, "Shift"), ("alt", MOD_ALT, "Alt"))
VK_F1 = 0x70
VK_F12 = 0x7B  # reservada ao depurador pelo Windows: não pode ser atalho


# ---------------------------------------------------------------------------
# Lógica pura
# ---------------------------------------------------------------------------

class Atalho(NamedTuple):
    modificadores: int  # MOD_* (sem MOD_NOREPEAT)
    tecla: int          # código virtual (VK_*)
    nome: str           # para mensagens: "Ctrl+Alt+B"


def ler_atalho(texto: str) -> Atalho:
    """"ctrl+alt+b" → Atalho. Exige Ctrl ou Alt; teclas: A–Z, 0–9, F1–F24 (menos F12).

    A tecla Windows não é aceita (as combinações com ela são do sistema). Erro: ValueError.
    """
    partes = [parte.strip().lower() for parte in str(texto).split("+")]
    if len(partes) < 2 or any(not parte for parte in partes):
        raise ValueError(f"atalho inválido: {texto!r}")
    *mods, tecla = partes
    modificadores = 0
    for mod in mods:
        valor = next((v for nome, v, _ in _MODIFICADORES if nome == mod), None)
        if valor is None or modificadores & valor:
            raise ValueError(f"modificador inválido ou repetido em {texto!r}: {mod!r}")
        modificadores |= valor
    if not modificadores & (MOD_CONTROL | MOD_ALT):
        raise ValueError(f"o atalho precisa de Ctrl ou Alt: {texto!r}")
    if len(tecla) == 1 and (tecla.isascii() and tecla.isalnum()):
        vk, nome_tecla = ord(tecla.upper()), tecla.upper()
    elif tecla[0] == "f" and tecla[1:].isdigit() and 1 <= int(tecla[1:]) <= 24:
        vk, nome_tecla = VK_F1 + int(tecla[1:]) - 1, tecla.upper()
    else:
        raise ValueError(f"tecla inválida em {texto!r}: {tecla!r}")
    if vk == VK_F12:
        raise ValueError("F12 é reservada pelo Windows")
    nome = "+".join([exibir for _, valor, exibir in _MODIFICADORES if modificadores & valor] + [nome_tecla])
    return Atalho(modificadores, vk, nome)


def acao_do_atalho(camada: str, minimizada: bool, em_primeiro_plano: bool) -> str:
    """"trazer", "minimizar" ou "devolver_foco" (ver o topo do módulo)."""
    if minimizada or not em_primeiro_plano:
        return "trazer"
    return "devolver_foco" if camada == "fundo" else "minimizar"


# ---------------------------------------------------------------------------
# Ouvinte
# ---------------------------------------------------------------------------

class SistemaAtalho(Protocol):
    def preparar_fila(self) -> int: ...
    def registrar(self, id_atalho: int, modificadores: int, tecla: int) -> int: ...  # 0 = deu certo
    def cancelar_registro(self, id_atalho: int) -> None: ...
    def rodar_laco(self, ao_atalho: Callable[[int], None]) -> None: ...
    def encerrar_laco(self, id_thread: int) -> None: ...
    def janela_em_primeiro_plano(self) -> int | None: ...  # raiz (GA_ROOT)
    def minimizada(self, hwnd: int) -> bool: ...
    def pode_receber_foco(self, hwnd: int) -> bool: ...
    def restaurar(self, hwnd: int) -> None: ...
    def minimizar(self, hwnd: int) -> None: ...
    def ativar(self, hwnd: int) -> bool: ...
    def area_de_trabalho(self) -> int | None: ...
    def enviar_para_fundo(self, hwnd: int) -> None: ...


class OuvinteAtalho:
    """Thread `atalho-global`: registra o atalho, espera o `WM_HOTKEY` e age na janela.

    `iniciar` volta depois da tentativa de registro (`registrado`, `recusados`).
    `parar` encerra o laço e espera a thread; o registro é desfeito na própria thread
    (o `UnregisterHotKey` precisa ser feito pela thread que registrou).
    Os avisos nunca levantam exceção (o `.exe` não tem console): erros vão ao log.
    """

    def __init__(
        self,
        sistema: SistemaAtalho,
        obter_janela: Callable[[], int | None],
        obter_camada: Callable[[], str],
        atalhos: Sequence[str] = ATALHOS_PADRAO,
    ) -> None:
        self._sistema = sistema
        self._obter_janela = obter_janela
        self._obter_camada = obter_camada
        self._atalhos = [ler_atalho(texto) for texto in atalhos]
        self._thread: threading.Thread | None = None
        self._id_thread: int | None = None
        self._pronto = threading.Event()
        self._erro: BaseException | None = None
        self.registrado: Atalho | None = None
        self.recusados: list[Atalho] = []
        # Janela ativa antes de o atalho trazer o BTC Status (devolver_foco, camada fundo).
        self._anterior: int | None = None

    @property
    def ativo(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def iniciar(self) -> Atalho | None:
        """Inicia a thread e espera o registro. Retorna o atalho registrado (ou None)."""
        if self._thread is not None:
            return self.registrado
        self._thread = threading.Thread(target=self._rodar, name="atalho-global", daemon=True)
        self._thread.start()
        if not self._pronto.wait(ESPERA_REGISTRO_S):
            logger.error("Atalho global: o registro não terminou no prazo")
        elif self._erro is not None:
            logger.error("Atalho global: não iniciou: %s", self._erro)
        return self.registrado

    def parar(self) -> None:
        thread, id_thread = self._thread, self._id_thread
        if thread is None:
            return
        if id_thread is not None and thread.is_alive():
            try:
                self._sistema.encerrar_laco(id_thread)
            except Exception:
                logger.exception("Atalho global: falha ao encerrar o laço")
        thread.join(ESPERA_ENCERRAR_S)
        if thread.is_alive():
            logger.error("Atalho global: a thread não terminou no prazo")

    def _rodar(self) -> None:
        try:
            # A fila precisa existir antes de `encerrar_laco` poder postar nela.
            self._id_thread = self._sistema.preparar_fila()
            self._registrar()
        except BaseException as erro:  # noqa: BLE001 — repassado a `iniciar`
            self._erro = erro
            return
        finally:
            self._pronto.set()
        if self.registrado is None:
            return
        try:
            self._sistema.rodar_laco(self._ao_mensagem)
        except Exception:
            logger.exception("Atalho global: falha no laço")
        finally:
            try:
                self._sistema.cancelar_registro(ID_ATALHO)
            except Exception:
                logger.exception("Atalho global: falha ao desfazer o registro")

    def _registrar(self) -> None:
        for atalho in self._atalhos:
            codigo = self._sistema.registrar(ID_ATALHO, atalho.modificadores | MOD_NOREPEAT, atalho.tecla)
            if codigo == 0:
                self.registrado = atalho
                logger.info("Atalho global: %s", atalho.nome)
                return
            self.recusados.append(atalho)
            if codigo == ERROR_HOTKEY_ALREADY_REGISTERED:
                logger.warning("Atalho global: %s já está em uso por outro programa", atalho.nome)
            else:
                logger.warning("Atalho global: %s não pôde ser registrado (erro %s)", atalho.nome, codigo)
        logger.warning("Atalho global: nenhuma combinação disponível; o app segue sem atalho")

    def _ao_mensagem(self, id_atalho: int) -> None:
        if id_atalho != ID_ATALHO:
            return
        try:
            self.ao_apertar()
        except Exception:
            logger.exception("Atalho global: falha ao tratar o atalho")

    def ao_apertar(self) -> str | None:
        """Decide e executa a ação. Chamado na thread do atalho. Retorna a ação feita."""
        hwnd = self._obter_janela()
        if not hwnd:
            logger.warning("Atalho global: janela não encontrada")
            return None
        sistema = self._sistema
        camada = self._obter_camada()
        minimizada = sistema.minimizada(hwnd)
        frente = sistema.janela_em_primeiro_plano()
        acao = acao_do_atalho(camada, minimizada, frente == hwnd)
        logger.debug("Atalho global: %s (camada=%s, minimizada=%s, em primeiro plano=%s)",
                     acao, camada, minimizada, frente == hwnd)
        if acao == "trazer":
            if frente and frente != hwnd:
                self._anterior = frente
            if minimizada:
                sistema.restaurar(hwnd)
            if not sistema.ativar(hwnd):
                logger.warning("Atalho global: o Windows não trouxe a janela para a frente")
        elif acao == "minimizar":
            sistema.minimizar(hwnd)
        else:
            self._devolver_foco(hwnd)
        return acao

    def _devolver_foco(self, hwnd: int) -> None:
        """Camada fundo: o foco vai para outra janela e a vigia afunda o widget."""
        anterior, self._anterior = self._anterior, None
        for destino in (anterior, self._sistema.area_de_trabalho()):
            if destino and destino != hwnd and self._sistema.pode_receber_foco(destino) \
                    and self._sistema.ativar(destino):
                return
        # Sem para onde mandar o foco: ao menos sai da frente.
        self._sistema.enviar_para_fundo(hwnd)


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

class SistemaWin32Atalho:
    """Implementação por ctypes. Criada só no Windows."""

    WM_QUIT = 0x0012
    WM_HOTKEY = 0x0312
    PM_NOREMOVE = 0x0000
    SW_MINIMIZE = 6
    SW_RESTORE = 9
    GA_ROOT = 2
    HWND_BOTTOM = 1
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOACTIVATE = 0x0010

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        LONG_PTR = ctypes.c_ssize_t
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)

        u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        u.RegisterHotKey.restype = wintypes.BOOL
        u.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        u.UnregisterHotKey.restype = wintypes.BOOL
        u.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT,
        ]
        u.PeekMessageW.restype = wintypes.BOOL
        # GetMessageW devolve -1 em erro: restype inteiro, não BOOL.
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        u.GetMessageW.restype = ctypes.c_int
        u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.TranslateMessage.restype = wintypes.BOOL
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.DispatchMessageW.restype = LONG_PTR
        u.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.PostThreadMessageW.restype = wintypes.BOOL
        k.GetCurrentThreadId.argtypes = []
        k.GetCurrentThreadId.restype = wintypes.DWORD
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetAncestor.restype = wintypes.HWND
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsWindow.restype = wintypes.BOOL
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindowVisible.restype = wintypes.BOOL
        u.IsIconic.argtypes = [wintypes.HWND]
        u.IsIconic.restype = wintypes.BOOL
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.ShowWindow.restype = wintypes.BOOL
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.SetForegroundWindow.restype = wintypes.BOOL
        u.GetShellWindow.argtypes = []
        u.GetShellWindow.restype = wintypes.HWND
        u.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.UINT,
        ]
        u.SetWindowPos.restype = wintypes.BOOL
        self._u, self._k = u, k

    def _hwnd(self, valor: int):
        return self._wintypes.HWND(valor)

    # -- thread do atalho ---------------------------------------------------

    def preparar_fila(self) -> int:
        msg = self._wintypes.MSG()
        # A 1ª chamada a uma função de mensagens cria a fila da thread.
        self._u.PeekMessageW(self._ctypes.byref(msg), None, 0, 0, self.PM_NOREMOVE)
        return int(self._k.GetCurrentThreadId())

    def registrar(self, id_atalho: int, modificadores: int, tecla: int) -> int:
        """0 se registrou; senão o código do erro (1409: em uso por outro programa)."""
        if self._u.RegisterHotKey(None, id_atalho, modificadores, tecla):
            return 0
        return self._ctypes.get_last_error() or -1

    def cancelar_registro(self, id_atalho: int) -> None:
        self._u.UnregisterHotKey(None, id_atalho)

    def rodar_laco(self, ao_atalho: Callable[[int], None]) -> None:
        msg = self._wintypes.MSG()
        ref = self._ctypes.byref(msg)
        while True:
            resultado = self._u.GetMessageW(ref, None, 0, 0)
            if resultado == 0:  # WM_QUIT
                return
            if resultado == -1:
                codigo = self._ctypes.get_last_error()
                raise OSError(codigo, f"GetMessageW falhou (erro {codigo})")
            if msg.message == self.WM_HOTKEY:
                ao_atalho(int(msg.wParam))
            else:
                self._u.TranslateMessage(ref)
                self._u.DispatchMessageW(ref)

    def encerrar_laco(self, id_thread: int) -> None:
        if not self._u.PostThreadMessageW(id_thread, self.WM_QUIT, 0, 0):
            codigo = self._ctypes.get_last_error()
            raise OSError(codigo, f"PostThreadMessageW falhou (erro {codigo})")

    # -- janelas ------------------------------------------------------------

    def janela_em_primeiro_plano(self) -> int | None:
        hwnd = self._u.GetForegroundWindow()
        if not hwnd:
            return None
        return self._u.GetAncestor(hwnd, self.GA_ROOT) or None

    def minimizada(self, hwnd: int) -> bool:
        return bool(self._u.IsIconic(self._hwnd(hwnd)))

    def pode_receber_foco(self, hwnd: int) -> bool:
        h = self._hwnd(hwnd)
        return bool(self._u.IsWindow(h) and self._u.IsWindowVisible(h) and not self._u.IsIconic(h))

    def restaurar(self, hwnd: int) -> None:
        # O retorno diz se estava visível, não se deu certo.
        self._u.ShowWindow(self._hwnd(hwnd), self.SW_RESTORE)

    def minimizar(self, hwnd: int) -> None:
        self._u.ShowWindow(self._hwnd(hwnd), self.SW_MINIMIZE)

    def ativar(self, hwnd: int) -> bool:
        return bool(self._u.SetForegroundWindow(self._hwnd(hwnd)))

    def area_de_trabalho(self) -> int | None:
        return self._u.GetShellWindow() or None

    def enviar_para_fundo(self, hwnd: int) -> None:
        flags = self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE
        self._u.SetWindowPos(self._hwnd(hwnd), self._hwnd(self.HWND_BOTTOM), 0, 0, 0, 0, flags)
