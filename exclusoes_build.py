"""O que fica fora do executável por não ser usado pelo app (redução do tamanho do build).

Fonte única das listas: o "BTC Monitor.spec" as aplica no build, o
tools/conferir_build.py confere a pasta dist depois do build e o
tests/test_exclusoes_build.py confere, sem build, que o app funciona sem esses módulos.

Este módulo não é importado pelo app e não entra no executável. Só biblioteca padrão.

Antes de acrescentar um módulo à lista, conferir que nada o importa na abertura
(python -X importtime BTC_Monitor.py) e que os usos nas dependências ficam dentro de
try/except ImportError ou de funções que o app não chama.
"""

from __future__ import annotations

from collections.abc import Iterable

# Extensões (.pyd) que o PyInstaller empacotava sem o app usar. O valor diz por que a
# exclusão é segura.
EXTENSOES_SEM_USO: dict[str, str] = {
    # tempfile -> shutil tenta os três dentro de try/except ImportError (só servem para
    # criar e extrair arquivos compactados, o que o app não faz).
    "_bz2": "shutil: try/except ImportError",
    "_lzma": "shutil: try/except ImportError",
    "_zstd": "shutil: try/except ImportError",
    # Nunca importados na abertura; nas dependências só aparecem em funções que o app não
    # chama (bottle: adaptadores de servidor com asyncio; clr_loader: xml no caminho do
    # CoreCLR, e o app usa o .NET Framework).
    "_asyncio": "asyncio não é usado",
    "_overlapped": "asyncio não é usado",
    "_multiprocessing": "multiprocessing não é usado",
    "_decimal": "decimal não é usado",
    "pyexpat": "xml não é usado",
    "_elementtree": "xml não é usado",
    # OpenSSL. O app não usa TLS pelo Python: o 1º preço vai pelo WinHTTP (baixar_winhttp.py)
    # e o "import ssl" do pywebview recebe um módulo vazio (ssl_ausente.py). hashlib e hmac
    # têm implementação embutida para quando o _hashlib falta (try/except ImportError).
    "_ssl": "TLS pelo WinHTTP; ssl_ausente.py cobre o import do pywebview",
    "_hashlib": "hashlib e hmac usam as implementações embutidas",
}

# Pacotes e módulos Python donos dessas extensões: saem junto (ficam no .exe, dentro do PYZ).
PACOTES_SEM_USO: tuple[str, ...] = (
    "bz2",
    "lzma",
    "compression.zstd",
    "asyncio",
    "multiprocessing",
    "decimal",
    "_pydecimal",
    "xml",
    "ssl",
)

# DLLs que só entram no build por causa das extensões acima (_ssl e _hashlib). Não são
# filtradas: saem sozinhas quando nada mais depende delas, e o conferir_build.py acusa se
# voltarem.
DLLS_DAS_EXTENSOES_SEM_USO: tuple[str, ...] = ("libcrypto-3.dll", "libssl-3.dll")

# Módulos só em Python (ficam no .exe, dentro do PYZ) que a análise do PyInstaller traz e
# o app nunca importa: só aparecem dentro de funções que o app não chama. Basta listar a
# raiz de cada grupo; o que só ela usava sai junto (ex.: http.cookiejar, ftplib, gzip, csv
# e gettext saem com urllib.request, tarfile e argparse). O valor diz quem os cita.
MODULOS_PYTHON_SEM_USO: dict[str, str] = {
    # Plataformas do pywebview de outros sistemas (webview/guilib.py só as importa neles).
    "webview.platforms.android": "pywebview: só no Android",
    "webview.platforms.cocoa": "pywebview: só no macOS",
    "webview.platforms.gtk": "pywebview: só no Linux",
    "webview.platforms.qt": "pywebview: só com Qt",
    # Parte do cffi que COMPILA extensões (o clr_loader só usa FFI().cdef e FFI().dlopen).
    "cffi.recompiler": "cffi.api: só em set_source/compile/emit",
    "cffi.verifier": "cffi.api: só em verify",
    "cffi.vengine_cpy": "cffi.verifier",
    "cffi.vengine_gen": "cffi.verifier",
    "cffi.ffiplatform": "cffi.verifier e cffi.recompiler",
    "cffi.setuptools_ext": "só no build de extensões",
    "cffi.backend_ctypes": "só com FFI(backend=...)",
    "cffi.pkgconfig": "cffi.api: só em set_source_pkgconfig",
    "cffi.cffi_opcode": "cffi.recompiler",
    "cffi._shimmed_dist_utils": "cffi.api: só ao compilar",
    "cffi._imp_emulation": "cffi.verifier",
    # Biblioteca padrão.
    "tarfile": "shutil: só em make_archive/unpack_archive",
    "argparse": "só nos main() de linha de comando (bottle, uuid, platform, ...)",
    "urllib.request": "pathlib: só em as_uri/from_uri; o 1º preço usa o WinHTTP",
    "statistics": "random: só no teste interno",
    "importlib.metadata": "importlib: só em find_distributions",
    "smtplib": "logging.handlers: só no SMTPHandler",
    "_pydatetime": "datetime: reserva para quando falta o _datetime, que é embutido",
}

# Lista passada ao "excludes" do Analysis no .spec.
MODULOS_SEM_USO: tuple[str, ...] = (PACOTES_SEM_USO + tuple(EXTENSOES_SEM_USO)
                                    + tuple(MODULOS_PYTHON_SEM_USO))

# Nunca excluir (o teste confere que não entram na lista):
# - distutils: o hook do PyInstaller o redireciona e a exclusão quebra o build;
# - unicodedata: o bottle o importa no topo (from unicodedata import normalize);
# - _wmi: sem ele o platform, que o pywebview usa na abertura, perde a consulta WMI;
# - zipfile: o runtime hook pyi_rth_inspect do PyInstaller o importa em TODA abertura do
#   .exe (dentro de uma função, por isso a análise o mostra como import "delayed");
# - difflib: o traceback o importa ao formatar certos erros; sem ele, registrar o erro no
#   log falharia.
MODULOS_QUE_FICAM: tuple[str, ...] = ("distutils", "unicodedata", "_wmi", "zipfile", "difflib")

# Módulos que precisam estar no .exe embora nenhum módulo Python do build os importe: quem
# os importa é o lado .NET do pythonnet (Python.Runtime.dll), que a análise do PyInstaller
# não enxerga. Entram como "hiddenimports" no .spec, e o tools/conferir_build.py confere a
# presença deles no build.
#
# O importlib.abc só estava no build por acaso (o importlib.metadata o importava); com o
# importlib.metadata excluído ele sumiu, o "import importlib.abc" do código que a
# Python.Runtime.dll executa ao iniciar falhou e o .exe fechava sem mensagem (violação de
# acesso em ImportHook.SetupImportHook). Os testes pelo Python do venv não pegam isso.
MODULOS_OBRIGATORIOS: dict[str, str] = {
    "importlib.abc": "Python.Runtime.dll: código do import hook (DotNetLoader/DotNetFinder)",
    "importlib.machinery": "Python.Runtime.dll: código do import hook (ModuleSpec)",
    # "import collections.abc" não tem arquivo próprio: o collections o cria a partir do
    # _collections_abc (sys.modules["collections.abc"] = _collections_abc).
    "_collections_abc": "Python.Runtime.dll: código embutido dos conversores (collections.abc)",
    "collections": "Python.Runtime.dll: importado pelo nome; cria o collections.abc",
    "inspect": "Python.Runtime.dll: importado pelo nome",
    "traceback": "Python.Runtime.dll: importado pelo nome",
    "warnings": "Python.Runtime.dll: importado pelo nome",
    "threading": "Python.Runtime.dll: importado pelo nome",
}

# Nível de otimização do bytecode no build (Analysis(optimize=...) e as opções "O" do EXE):
# 2 tira também as docstrings. Nenhuma dependência lê __doc__ (o pycparser 3.x não usa mais
# o PLY, que montava a gramática a partir das docstrings).
OTIMIZACAO_DO_BYTECODE = 2

# Módulo excluído que um módulo do build importa NO TOPO, e por quê isso não quebra. Fora
# desta lista, o tools/conferir_build.py trata um import assim como erro (ver --avisos).
IMPORTS_NO_TOPO_CONHECIDOS: dict[tuple[str, str], str] = {
    ("ssl", "webview.http"): "o app instala um módulo ssl vazio antes (ssl_ausente.py)",
    ("bz2", "encodings.bz2_codec"): "codec só carregado se alguém pedir a codificação 'bz2'",
}

# Arquivos que os hooks do pywebview e do pythonnet copiam e o app nunca carrega. Caminhos
# relativos à pasta "_internal" do build, com "/" (a comparação ignora maiúsculas e "\").
#
# Os WebView2Loader.dll de win-arm64 e win-x86 NÃO entram aqui, embora o processo x64 só
# carregue o de win-x64: o pywebview 6.2.1 (platforms/edgechromium.py) acrescenta ao PATH as
# três pastas webview/lib/runtimes/<plataforma>/native e levanta FileNotFoundError
# ("Cannot find win-arm64") se alguma não existir. O PyInstaller só cria uma pasta que
# tenha arquivo, então tirar a DLL tira a pasta e o .exe não abre.
ARQUIVOS_SEM_USO: tuple[str, ...] = (
    # Só para o Android.
    "webview/lib/pywebview-android.jar",
    # Documentação da Python.Runtime.dll (IntelliSense); não é lida em execução.
    "pythonnet/runtime/Python.Runtime.xml",
)


# Arquivos sem os quais o .exe não abre: o tools/conferir_build.py falha se faltar algum,
# e o filtro nunca pode tirá-los (o teste confere). Caminhos relativos a "_internal".
ARQUIVOS_OBRIGATORIOS: tuple[str, ...] = (
    "base_library.zip",
    "index.html",
    "webview/lib/Microsoft.Web.WebView2.Core.dll",
    "webview/lib/Microsoft.Web.WebView2.WinForms.dll",
    # Uma por plataforma: o pywebview exige as três pastas (ver ARQUIVOS_SEM_USO).
    "webview/lib/runtimes/win-arm64/native/WebView2Loader.dll",
    "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
    "webview/lib/runtimes/win-x86/native/WebView2Loader.dll",
    "webview/js/api.js",
    "pythonnet/runtime/Python.Runtime.dll",
    "clr_loader/ffi/dlls/amd64/ClrLoader.dll",
)


def normalizar_caminho(caminho: str) -> str:
    """Caminho comparável: barras "/" e minúsculas (o Windows não diferencia)."""
    return caminho.replace("\\", "/").lower()


_ARQUIVOS_SEM_USO_NORMALIZADOS = frozenset(normalizar_caminho(a) for a in ARQUIVOS_SEM_USO)


def arquivo_sem_uso(destino: str) -> bool:
    """True se o destino (caminho dentro de "_internal") é um dos ARQUIVOS_SEM_USO."""
    return normalizar_caminho(destino) in _ARQUIVOS_SEM_USO_NORMALIZADOS


def sem_arquivos_sem_uso(entradas: Iterable[tuple]) -> list[tuple]:
    """Tira os ARQUIVOS_SEM_USO de uma lista TOC do PyInstaller.

    Cada entrada é (destino, origem, tipo); as demais ficam na mesma ordem.
    """
    return [entrada for entrada in entradas if not arquivo_sem_uso(entrada[0])]


def arquivos_proibidos_no_build() -> tuple[str, ...]:
    """Caminhos (relativos a "_internal") que não podem existir no build: os arquivos
    sem uso, o .pyd de cada extensão excluída e as DLLs que só elas usavam."""
    return (ARQUIVOS_SEM_USO + tuple(f"{nome}.pyd" for nome in EXTENSOES_SEM_USO)
            + DLLS_DAS_EXTENSOES_SEM_USO)
