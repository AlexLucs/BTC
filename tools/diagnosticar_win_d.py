"""Diagnóstico do Win+D com o widget na camada fundo (fora do .exe).

Abra o app (btc) com o widget em ▼ e rode este script. Durante a coleta, use o Win+D
como indicado na tela. A cada mudança de estado sai uma linha com o instante (ms) e:

- primeiro plano: classe da janela ativa;
- area: o hospedeiro dos ícones (pai do SHELLDLL_DefView), se é TOPMOST e se está
  acima da janela de referência (o critério que o app usa para "Win+D em andamento");
- widget: a janela "BTC Status" (de qualquer processo): visível, minimizada, cloaked
  (valor do DWMWA_CLOAKED: 1 = pelo app, 2 = pelo shell, 4 = herdado), TOPMOST, se
  está acima da área de trabalho e se conta como coberta pelo critério da fase 3.

- ref_app: a janela de referência do PRÓPRIO app (oculta, classe "Static", sem título,
  do processo do widget) e se a área de trabalho está acima dela. Era da detecção do
  Win+D, REMOVIDA do app (armadilha 70): com o app atual ela não existe e a linha mostra
  "ref_app=NÃO ENCONTRADA". A coluna só volta a valer se a técnica voltar;
- faixa: a "z-order band" de cada janela (GetWindowBand, função NÃO documentada do
  user32, só para diagnóstico; "n/d" se não existir). Janelas de faixas diferentes
  não se misturam: uma de faixa mais alta fica acima mesmo sem TOPMOST;
- pilha: a ordem das janelas visíveis (de cima para baixo), com as duas referências,
  o widget e a área de trabalho marcados, sempre que a linha principal muda.

A janela de referência "ref_diag" é criada por este script (como a do app).

    .venv\\Scripts\\python.exe tools\\diagnosticar_win_d.py --segundos 25
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TITULO = "BTC Status"
WS_EX_TOPMOST = 0x00000008
GWL_EXSTYLE = -20
DWMWA_CLOAKED = 14

ROTEIRO = (
    "Roteiro (siga no seu ritmo, a coleta continua até o fim do prazo):\n"
    "  1. espere 3 s sem mexer;\n"
    "  2. Win+D e espere 3 s;\n"
    "  3. Win+D de novo e espere 3 s;\n"
    "  4. Win+D, espere 3 s e clique num programa na barra de tarefas."
)


GW_HWNDNEXT = 2
WS_EX_TOOLWINDOW = 0x00000080


def _user32():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetTopWindow.argtypes = [wintypes.HWND]
    u.GetTopWindow.restype = wintypes.HWND
    u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    u.GetWindow.restype = wintypes.HWND
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.restype = ctypes.c_int
    try:  # não documentada (Windows 8 ou depois); só para diagnóstico
        u.GetWindowBand.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowBand.restype = wintypes.BOOL
    except AttributeError:
        pass
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.FindWindowW.restype = wintypes.HWND
    u.GetForegroundWindow.argtypes = []
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    u.GetAncestor.restype = wintypes.HWND
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetClassNameW.restype = ctypes.c_int
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsWindowVisible.restype = wintypes.BOOL
    u.IsIconic.argtypes = [wintypes.HWND]
    u.IsIconic.restype = wintypes.BOOL
    u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    return u


def _dwmapi():
    d = ctypes.WinDLL("dwmapi")
    d.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    d.DwmGetWindowAttribute.restype = ctypes.c_long
    return d


def classe(u, hwnd) -> str:
    if not hwnd:
        return "-"
    buffer = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(hwnd, buffer, 128)
    return buffer.value or "?"


def faixa(u, hwnd) -> str:
    funcao = getattr(u, "GetWindowBand", None)
    if funcao is None or not hwnd:
        return "n/d"
    valor = wintypes.DWORD()
    return str(valor.value) if funcao(hwnd, ctypes.byref(valor)) else "erro"


def topmost(u, hwnd) -> bool:
    return bool(int(u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)) & WS_EX_TOPMOST)


def cloaked(d, hwnd) -> int:
    valor = wintypes.DWORD()
    if d.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(valor), ctypes.sizeof(valor)) != 0:
        return -1
    return valor.value


def pid(u, hwnd) -> int:
    valor = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(valor))
    return valor.value


def pilha(u):
    """Todas as janelas de nível superior, de cima para baixo."""
    janela = u.GetTopWindow(None)
    for _ in range(20_000):
        if not janela:
            return
        yield janela
        janela = u.GetWindow(janela, GW_HWNDNEXT)


def referencia_do_app(u, widget) -> list[int]:
    """Janelas ocultas "Static" sem título do processo do widget: a referência do app."""
    if not widget:
        return []
    alvo = pid(u, widget)
    return [
        h for h in pilha(u)
        if pid(u, h) == alvo and classe(u, h) == "Static"
        and not u.IsWindowVisible(h) and u.GetWindowTextLengthW(h) == 0
    ]


def resumo_da_pilha(u, d, marcas: dict[int, str], limite: int = 45) -> str:
    itens = []
    for h in pilha(u):
        if h in marcas:
            itens.append(f"[{marcas[h]}]")
        elif u.IsWindowVisible(h) and cloaked(d, h) == 0:
            sufixo = "*" if topmost(u, h) else ""
            itens.append(f"{classe(u, h)[:24]}{sufixo}#{faixa(u, h)}")
        if len(itens) >= limite:
            itens.append("…")
            break
    return " > ".join(itens)


def amostra(sistema, u, d, referencia) -> tuple[str, dict[int, str]]:
    from camada_fundo import esta_coberta

    primeiro = u.GetForegroundWindow()
    primeiro = u.GetAncestor(primeiro, 2) if primeiro else None  # GA_ROOT
    host = sistema.hospedeiro_dos_icones()
    if host:
        area = (f"area={classe(u, host)} faixa={faixa(u, host)} topmost={topmost(u, host)} "
                f"acima_da_ref={sistema.esta_acima(host, referencia)}")
    else:
        area = "area=NENHUMA"
    widget = u.FindWindowW(None, TITULO)
    marcas = {referencia: "REF_DIAG"}
    if host:
        marcas[host] = "AREA"
    refs_app = referencia_do_app(u, widget)
    for h in refs_app:
        marcas[h] = "REF_APP"
    if host and refs_app:
        area += f" acima_da_ref_app={[sistema.esta_acima(host, h) for h in refs_app]}"
    elif widget:
        area += " ref_app=NÃO ENCONTRADA"
    if widget:
        marcas[widget] = "WIDGET"
        proprio, cobertores = sistema.estado_de_cobertura(widget)
        partes = [
            f"fundo={bool(int(u.GetWindowLongPtrW(widget, GWL_EXSTYLE)) & WS_EX_TOOLWINDOW)}",
            f"vis={bool(u.IsWindowVisible(widget))}",
            f"min={bool(u.IsIconic(widget))}",
            f"cloak={cloaked(d, widget)}",
            f"topmost={topmost(u, widget)}",
            f"faixa={faixa(u, widget)}",
            f"acima_da_area={sistema.esta_acima(widget, host) if host else '-'}",
            f"coberto={esta_coberta(proprio, cobertores)}({len(cobertores)} por cima)",
        ]
        janela = "widget: " + " ".join(partes)
    else:
        janela = "widget=NÃO ENCONTRADO (abra o app)"
    return f"primeiro_plano={classe(u, primeiro)} | {area} | {janela}", marcas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--segundos", type=float, default=25.0, help="duração da coleta (padrão: 25)")
    parser.add_argument("--intervalo-ms", type=int, default=50, help="intervalo entre amostras (padrão: 50)")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("Só no Windows.")
        return 1

    from camada_fundo import SistemaWin32Fundo, VigiaPrimeiroPlano

    sistema = SistemaWin32Fundo()
    u, d = _user32(), _dwmapi()
    vigia = VigiaPrimeiroPlano(sistema, lambda _h: None, lambda: None, 1000)
    if not vigia.iniciar() or not vigia.auxiliar:
        print("Não foi possível criar a janela de referência.")
        return 1
    print(f"Windows {sys.getwindowsversion().build} | coleta de {args.segundos:.0f} s")
    print(ROTEIRO)
    print("-" * 100)
    inicio = time.perf_counter()
    anterior = None
    try:
        while (agora := time.perf_counter() - inicio) < args.segundos:
            atual, marcas = amostra(sistema, u, d, vigia.auxiliar)
            if atual != anterior:
                print(f"{agora * 1000:8.0f} ms  {atual}", flush=True)
                print(f"           pilha: {resumo_da_pilha(u, d, marcas)}", flush=True)
                for h, nome in marcas.items():
                    if nome in ("AREA", "WIDGET"):
                        print(f"           {nome}: faixa={faixa(u, h)} topmost={topmost(u, h)}", flush=True)
                anterior = atual
            time.sleep(args.intervalo_ms / 1000)
    except KeyboardInterrupt:
        pass
    finally:
        vigia.parar()
    print("-" * 100)
    print("Fim. Envie toda a saída acima e as linhas novas do %APPDATA%\\btcstatus\\btcstatus.log.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
