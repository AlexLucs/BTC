"""Substituto do módulo ssl para o executável, que não leva o OpenSSL.

O build exclui ssl, _ssl e _hashlib (ver exclusoes_build.py): o app não usa TLS pelo
Python (o 1º preço vai pelo WinHTTP, ver baixar_winhttp.py; o resto da rede é da página,
no WebView2). Mas o pywebview 6.2.1 faz "import ssl" no topo de webview/http.py, mesmo só
usando o módulo com ssl=True no webview.start (que o app não liga); sem o módulo, o
"import webview" falharia.

garantir() precisa ser chamado ANTES do "import webview". Se o ssl de verdade existir
(execução pelo código-fonte, testes), nada muda. Se não existir (no .exe), entra em
sys.modules um módulo vazio: o "import ssl" funciona e qualquer uso de um atributo dele
levanta AttributeError com a explicação.

Ao atualizar o pywebview, conferir que webview/http.py continua usando o ssl só dentro
de "if ssl:" (BottleServer.start_server).
"""

from __future__ import annotations

import sys
import types


class ModuloSslAusente(types.ModuleType):
    """Módulo ssl vazio: importável, sem nenhum atributo do ssl de verdade."""

    substituto_do_btc_status = True

    def __getattr__(self, nome: str):
        raise AttributeError(
            f"ssl.{nome}: o módulo ssl não está neste executável (ver exclusoes_build.py e ssl_ausente.py)")


def garantir() -> bool:
    """Garante que "import ssl" funcione. Retorna True se o substituto foi instalado."""
    try:
        import ssl  # noqa: F401, PLC0415 - só para saber se o módulo de verdade existe
    except ImportError:
        sys.modules["ssl"] = ModuloSslAusente("ssl", "Substituto vazio do ssl (BTC Status).")
        return True
    return False


def e_substituto(modulo: object) -> bool:
    """True se o módulo é o substituto instalado por garantir()."""
    return isinstance(modulo, ModuloSslAusente)
