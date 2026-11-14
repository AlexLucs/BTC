"""Requisição HTTP(S) GET pelo WinHTTP do Windows, via ctypes (sem o módulo ssl do Python).

Usado por primeiro_preco.py para buscar o 1º preço na Binance. O TLS e os certificados
ficam com o Windows (SChannel), e assim o executável não precisa levar o OpenSSL
(libcrypto-3.dll, libssl-3.dll, _ssl.pyd e _hashlib.pyd, ~7,4 MB): ver exclusoes_build.py.

- Uma requisição por chamada, síncrona; pensada para rodar numa thread.
- Conexão direta, sem proxy (WINHTTP_ACCESS_TYPE_NO_PROXY): não há espera de detecção
  automática de proxy. Numa rede que exige proxy a requisição falha, e a página busca o
  preço pelo REST dela (o WebView2 usa o proxy do sistema).
- O prazo vale para cada etapa (resolver o nome, conectar, enviar e receber), como o
  timeout de socket do urllib.

Só biblioteca padrão. O ctypes e a winhttp.dll são carregados na 1ª chamada, não no import.
"""

from __future__ import annotations

import sys
import threading
from urllib.parse import urlsplit

AGENTE = "BTC Status"
CABECALHOS = "Accept: application/json\r\n"
# Limite do corpo da resposta (a dos tickers tem ~1,2 KB).
TAMANHO_MAXIMO = 1024 * 1024
TAMANHO_BLOCO = 16 * 1024

# Constantes do winhttp.h
WINHTTP_ACCESS_TYPE_NO_PROXY = 1
WINHTTP_FLAG_SECURE = 0x00800000
WINHTTP_QUERY_STATUS_CODE = 19
WINHTTP_QUERY_FLAG_NUMBER = 0x20000000
COMPRIMENTO_ATE_O_ZERO = 0xFFFFFFFF  # -1L: os cabeçalhos terminam em zero

# Erros mais comuns (winhttp.h), para a mensagem do log.
NOMES_DE_ERRO = {
    12002: "tempo esgotado",
    12007: "nome do servidor nao resolvido",
    12029: "nao foi possivel conectar",
    12030: "conexao encerrada pelo servidor",
    12152: "resposta invalida do servidor",
    12175: "falha de seguranca (TLS/certificado)",
}


class ErroDeRequisicao(OSError):
    """A requisição falhou (rede, TLS ou status HTTP diferente de 200)."""


def separar_url(url: str) -> tuple[bool, str, int, str]:
    """Divide a URL em (https?, servidor, porta, caminho com a consulta).

    Raises:
        ValueError: se não for http(s) ou não tiver servidor.
    """
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise ValueError(f"URL sem suporte: {url}")
    seguro = partes.scheme == "https"
    porta = partes.port or (443 if seguro else 80)
    caminho = partes.path or "/"
    if partes.query:
        caminho += "?" + partes.query
    return seguro, partes.hostname, porta, caminho


_trava = threading.Lock()
_winhttp = None  # winhttp.dll com as funções declaradas (criado na 1ª chamada)
_ctypes = None


def _carregar():
    """Carrega a winhttp.dll e declara argtypes/restype (handles são ponteiros: sem a
    declaração, voltariam truncados em 32 bits)."""
    global _winhttp, _ctypes
    with _trava:
        if _winhttp is not None:
            return _winhttp, _ctypes
        import ctypes  # noqa: PLC0415 - aqui, e não no topo: não pesa na abertura
        from ctypes import wintypes  # noqa: PLC0415

        dll = ctypes.WinDLL("winhttp", use_last_error=True)
        handle = ctypes.c_void_p
        texto = wintypes.LPCWSTR
        dword = wintypes.DWORD
        ponteiro_dword = ctypes.POINTER(wintypes.DWORD)

        dll.WinHttpOpen.argtypes = [texto, dword, texto, texto, dword]
        dll.WinHttpOpen.restype = handle
        dll.WinHttpSetTimeouts.argtypes = [handle, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        dll.WinHttpSetTimeouts.restype = wintypes.BOOL
        dll.WinHttpConnect.argtypes = [handle, texto, wintypes.WORD, dword]
        dll.WinHttpConnect.restype = handle
        dll.WinHttpOpenRequest.argtypes = [handle, texto, texto, texto, texto, ctypes.c_void_p, dword]
        dll.WinHttpOpenRequest.restype = handle
        dll.WinHttpSendRequest.argtypes = [handle, texto, dword, ctypes.c_void_p, dword, dword, ctypes.c_size_t]
        dll.WinHttpSendRequest.restype = wintypes.BOOL
        dll.WinHttpReceiveResponse.argtypes = [handle, ctypes.c_void_p]
        dll.WinHttpReceiveResponse.restype = wintypes.BOOL
        dll.WinHttpQueryHeaders.argtypes = [handle, dword, texto, ctypes.c_void_p, ponteiro_dword, ponteiro_dword]
        dll.WinHttpQueryHeaders.restype = wintypes.BOOL
        dll.WinHttpReadData.argtypes = [handle, ctypes.c_void_p, dword, ponteiro_dword]
        dll.WinHttpReadData.restype = wintypes.BOOL
        dll.WinHttpCloseHandle.argtypes = [handle]
        dll.WinHttpCloseHandle.restype = wintypes.BOOL

        _winhttp, _ctypes = dll, ctypes
        return _winhttp, _ctypes


def _erro(funcao: str, ctypes) -> ErroDeRequisicao:
    codigo = ctypes.get_last_error()
    nome = NOMES_DE_ERRO.get(codigo)
    return ErroDeRequisicao(f"{funcao} falhou: erro {codigo}" + (f" ({nome})" if nome else ""))


def baixar(url: str, timeout_s: float, marcar=None) -> bytes:
    """Faz um GET e devolve o corpo da resposta.

    Args:
        url: endereço http ou https.
        timeout_s: prazo de cada etapa da requisição, em segundos.
        marcar: só na medição; função chamada com o nome de cada etapa concluída:
            "preco_python_enviado" (nome resolvido, conexão, TLS e pedido enviado) e
            "preco_python_cabecalhos" (o servidor começou a responder).

    Raises:
        ErroDeRequisicao: falha de rede ou de TLS, status diferente de 200, resposta maior
            que TAMANHO_MAXIMO, ou sistema que não é o Windows.
        ValueError: URL sem suporte.
    """
    seguro, servidor, porta, caminho = separar_url(url)
    if sys.platform != "win32":
        raise ErroDeRequisicao("o WinHTTP so existe no Windows")
    dll, ctypes = _carregar()
    prazo_ms = max(1, int(timeout_s * 1000))
    abertos: list[int] = []  # handles a fechar, na ordem em que foram abertos

    def aberto(handle: int | None, funcao: str) -> int:
        if not handle:
            raise _erro(funcao, ctypes)
        abertos.append(handle)
        return handle

    try:
        sessao = aberto(dll.WinHttpOpen(AGENTE, WINHTTP_ACCESS_TYPE_NO_PROXY, None, None, 0), "WinHttpOpen")
        if not dll.WinHttpSetTimeouts(sessao, prazo_ms, prazo_ms, prazo_ms, prazo_ms):
            raise _erro("WinHttpSetTimeouts", ctypes)
        conexao = aberto(dll.WinHttpConnect(sessao, servidor, porta, 0), "WinHttpConnect")
        pedido = aberto(
            dll.WinHttpOpenRequest(conexao, "GET", caminho, None, None, None,
                                   WINHTTP_FLAG_SECURE if seguro else 0),
            "WinHttpOpenRequest")
        if not dll.WinHttpSendRequest(pedido, CABECALHOS, COMPRIMENTO_ATE_O_ZERO, None, 0, 0, 0):
            raise _erro("WinHttpSendRequest", ctypes)
        if marcar is not None:
            marcar("preco_python_enviado")
        if not dll.WinHttpReceiveResponse(pedido, None):
            raise _erro("WinHttpReceiveResponse", ctypes)
        if marcar is not None:
            marcar("preco_python_cabecalhos")

        status = ctypes.c_ulong(0)
        tamanho = ctypes.c_ulong(ctypes.sizeof(status))
        if not dll.WinHttpQueryHeaders(pedido, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                                       None, ctypes.byref(status), ctypes.byref(tamanho), None):
            raise _erro("WinHttpQueryHeaders", ctypes)
        if status.value != 200:
            raise ErroDeRequisicao(f"HTTP {status.value} em {url}")

        partes: list[bytes] = []
        total = 0
        bloco = ctypes.create_string_buffer(TAMANHO_BLOCO)
        lidos = ctypes.c_ulong(0)
        while True:
            if not dll.WinHttpReadData(pedido, bloco, TAMANHO_BLOCO, ctypes.byref(lidos)):
                raise _erro("WinHttpReadData", ctypes)
            if lidos.value == 0:  # fim da resposta
                break
            total += lidos.value
            if total > TAMANHO_MAXIMO:
                raise ErroDeRequisicao(f"resposta maior que {TAMANHO_MAXIMO} bytes em {url}")
            partes.append(bloco.raw[:lidos.value])
        return b"".join(partes)
    finally:
        for handle in reversed(abertos):
            dll.WinHttpCloseHandle(handle)
