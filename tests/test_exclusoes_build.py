"""exclusoes_build.py: o que fica fora do executável, e o app funcionando sem isso.

O teste principal não precisa de build: um Python novo bloqueia cada módulo excluído
(sys.modules[nome] = None, o import falha como no .exe) e percorre o que o app faz na
abertura. Se uma dependência passar a precisar de um módulo excluído, ele falha aqui,
antes de o .exe quebrar.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tools"))

import conferir_build  # noqa: E402
import exclusoes_build  # noqa: E402

precisa_do_pywebview = pytest.mark.skipif(importlib.util.find_spec("webview") is None,
                                          reason="pywebview não instalado")

# Roda num Python novo. sys.argv[1]: JSON com os módulos a bloquear; sys.argv[2]: "1"
# para carregar também a plataforma do pywebview no Windows (.NET e WebView2). Com
# "python -OO" o roteiro roda sem docstrings, como o bytecode do .exe (optimize=2).
CODIGO = r"""
import json, sys
bloqueados = json.loads(sys.argv[1])
for nome in bloqueados:
    sys.modules[nome] = None  # como no .exe: o import falha (ImportError)

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from wsgiref.util import setup_testing_defaults

import BTC_Monitor as app
import servidor_local
from primeiro_preco import BuscaPrimeiroPreco

# Log em arquivo e configuração da janela (.ini)
app.configurar_log()
app.logger.info("teste das exclusões do build")
app.salvar_configuracao(10, 20, True)

# Alertas em disco, pela API exposta ao JS
api = app.ExposedApi(app.RepositorioAlertas(app.PASTA_DADOS), app.METRICAS)
salvou = api.salvar_alerta([{"valor": 10, "tipo": "maior"}])

# 1º preço pelo Python, com um servidor HTTP local no lugar da Binance
TICKERS = [{"symbol": "BTCBRL", "lastPrice": "1"}]

class Tratador(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(TICKERS).encode())

    def log_message(self, *args):
        pass

http = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
threading.Thread(target=http.serve_forever, daemon=True).start()
def baixar_de_apoio(url, timeout_s):  # fora do Windows não há WinHTTP: só a lógica é conferida
    from http.client import HTTPConnection  # o urllib.request é um dos módulos excluídos
    conexao = HTTPConnection("127.0.0.1", http.server_address[1], timeout=timeout_s)
    conexao.request("GET", "/tickers")
    return conexao.getresponse().read()

busca = BuscaPrimeiroPreco(app.METRICAS, url=f"http://127.0.0.1:{http.server_address[1]}/tickers",
                           baixar=None if sys.platform == "win32" else baixar_de_apoio)
busca.iniciar()

# Servidor local da página (bottle), chamado direto pela interface WSGI
aplicativo = servidor_local.criar_aplicativo(app.PASTA_RECURSOS, app.html_da_pagina, busca)

def pedir(caminho):
    ambiente = {}
    setup_testing_defaults(ambiente)
    ambiente["PATH_INFO"] = caminho
    resposta = {}

    def iniciar(status, cabecalhos, exc_info=None):
        resposta["status"] = int(status.split()[0])

    corpo = aplicativo(ambiente, iniciar)
    try:
        resposta["corpo"] = b"".join(corpo)
    finally:
        if hasattr(corpo, "close"):
            corpo.close()
    return resposta

preco = pedir("/preco-inicial")  # espera a busca do Python (até 1,5 s)
pagina = pedir("/")
arquivos = {nome: pedir("/" + nome)["status"] for nome in servidor_local.ARQUIVOS_DA_PAGINA}
http.shutdown()

# Erros registrados no log: a formatação do traceback não pode depender de módulo excluído
for codigo in ("app.nao_existe", "compile('x = = 1', 'a', 'exec')", "import modulo_que_nao_existe"):
    try:
        exec(codigo)
    except Exception:
        app.logger.exception("erro de teste")
for manipulador in app.logging.getLogger().handlers:
    manipulador.flush()

# No Windows: a plataforma do pywebview (pythonnet, clr_loader, cffi, .NET e WebView2),
# como na 1ª leitura de webview.screens. Não abre janela.
plataforma = None
if sys.argv[2] == "1" and sys.platform == "win32":
    import webview
    plataforma = len(webview.screens) > 0

print(json.dumps({
    "salvou": salvou,
    "carregou": api.carregar_alerta(),
    "compacto": app.carregar_modo_compacto(),
    "log_existe": app.ARQUIVO_LOG.is_file(),
    "erros_no_log": app.ARQUIVO_LOG.read_text(encoding="utf-8").count("Traceback (most recent call last)"),
    "otimizacao": sys.flags.optimize,
    "sem_docstrings": app.main.__doc__ is None and servidor_local.criar_aplicativo.__doc__ is None,
    "pagina": pagina["status"],
    "preco_inicial": preco["status"],
    "preco": json.loads(preco["corpo"] or b"null"),
    "arquivos": arquivos,
    "plataforma": plataforma,
    # O ssl bloqueado é trocado pelo módulo vazio do ssl_ausente.py (o pywebview o importa).
    "ssl_substituto": app.ssl_ausente.e_substituto(sys.modules.get("ssl")),
    "importados": sorted(nome for nome in bloqueados
                         if sys.modules.get(nome) is not None
                         and not app.ssl_ausente.e_substituto(sys.modules[nome])),
}))
"""


def rodar_app_sem(modulos, tmp_path, com_plataforma: bool = False,
                  sem_docstrings: bool = False) -> subprocess.CompletedProcess:
    """Roda CODIGO num Python novo com os módulos bloqueados e a pasta de dados em tmp_path.

    sem_docstrings: usa "python -OO" (sem docstrings nem asserts), como o bytecode do .exe.
    O PYTHONDONTWRITEBYTECODE evita gravar .pyc desse nível no venv.
    """
    ambiente = {**os.environ, "APPDATA": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    opcoes = ["-OO"] if sem_docstrings else []
    return subprocess.run(
        [sys.executable, *opcoes, "-c", CODIGO, json.dumps(list(modulos)), "1" if com_plataforma else "0"],
        cwd=RAIZ, env=ambiente, capture_output=True, text=True, timeout=240)


def resultado_de(saida: subprocess.CompletedProcess) -> dict:
    assert saida.returncode == 0, saida.stderr
    return json.loads(saida.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# O app sem os módulos excluídos
# ---------------------------------------------------------------------------

@precisa_do_pywebview
@pytest.mark.parametrize("sem_docstrings", [False, True], ids=["normal", "sem-docstrings"])
def test_app_funciona_sem_os_modulos_excluidos(tmp_path, sem_docstrings):
    resultado = resultado_de(rodar_app_sem(exclusoes_build.MODULOS_SEM_USO, tmp_path,
                                           sem_docstrings=sem_docstrings))
    assert resultado["otimizacao"] == (2 if sem_docstrings else 0)
    assert resultado["sem_docstrings"] is sem_docstrings
    assert resultado["erros_no_log"] == 3, "os três erros de teste precisam chegar ao log com o traceback"
    assert resultado["salvou"] is True
    assert resultado["carregou"] == [{"valor": 10.0, "tipo": "maior"}]
    assert resultado["compacto"] is True
    assert resultado["log_existe"] is True
    assert resultado["pagina"] == 200
    assert resultado["preco_inicial"] == 200, "o 1º preço pelo Python precisa funcionar sem os módulos"
    assert resultado["preco"] == [{"symbol": "BTCBRL", "lastPrice": "1"}]
    assert set(resultado["arquivos"].values()) == {200}, resultado["arquivos"]
    assert resultado["importados"] == []
    assert resultado["ssl_substituto"] is True


@precisa_do_pywebview
@pytest.mark.skipif(sys.platform != "win32", reason="a plataforma do pywebview (.NET/WebView2) só existe no Windows")
def test_plataforma_do_pywebview_carrega_sem_os_modulos_excluidos(tmp_path):
    """pythonnet, clr_loader, cffi e os módulos do pywebview para Windows, como na abertura
    do .exe: sem os módulos excluídos e sem docstrings (o cffi interpreta as declarações C do
    clr_loader com o pycparser a cada abertura)."""
    resultado = resultado_de(rodar_app_sem(exclusoes_build.MODULOS_SEM_USO, tmp_path, com_plataforma=True,
                                           sem_docstrings=True))
    assert resultado["plataforma"] is True
    assert resultado["otimizacao"] == 2


@precisa_do_pywebview
def test_cffi_interpreta_as_declaracoes_do_clr_loader_sem_docstrings_e_sem_a_parte_de_compilar():
    """Em qualquer sistema: o que o clr_loader faz com o cffi na abertura (FFI().cdef),
    com "python -OO" e sem os módulos do cffi que só servem para compilar extensões."""
    pytest.importorskip("clr_loader")
    codigo = (
        "import json, sys\n"
        "for nome in json.loads(sys.argv[1]): sys.modules[nome] = None\n"
        "import clr_loader.ffi as f\n"
        "print(hasattr(f.ffi, 'dlopen'), sys.flags.optimize)\n"
    )
    saida = subprocess.run([sys.executable, "-OO", "-c", codigo, json.dumps(list(exclusoes_build.MODULOS_SEM_USO))],
                           cwd=RAIZ, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                           capture_output=True, text=True, timeout=120)
    assert saida.returncode == 0, saida.stderr
    assert saida.stdout.split() == ["True", "2"]


@precisa_do_pywebview
def test_controle_modulo_necessario_bloqueado_e_detectado(tmp_path):
    """Caso de controle: o bloqueio de um módulo que o app usa (o bottle importa o
    unicodedata no topo) faz o mesmo roteiro falhar. Sem isso, o teste acima passaria
    mesmo que o bloqueio não tivesse efeito."""
    saida = rodar_app_sem(["unicodedata"], tmp_path)
    assert saida.returncode != 0
    assert "unicodedata" in saida.stderr


# ---------------------------------------------------------------------------
# As listas
# ---------------------------------------------------------------------------

def test_modulos_que_ficam_nao_estao_na_lista_de_exclusao():
    excluidos = set(exclusoes_build.MODULOS_SEM_USO)
    for nome in exclusoes_build.MODULOS_QUE_FICAM:
        assert nome not in excluidos, f"{nome} não pode ser excluído (ver exclusoes_build.py)"
        assert not any(e.startswith(nome + ".") for e in excluidos)


def test_lista_de_exclusao_tem_pacotes_e_extensoes_sem_repeticao():
    modulos = exclusoes_build.MODULOS_SEM_USO
    assert len(modulos) == len(set(modulos))
    assert set(exclusoes_build.EXTENSOES_SEM_USO) <= set(modulos)
    assert set(exclusoes_build.PACOTES_SEM_USO) <= set(modulos)


def test_modulos_do_app_nao_importam_os_excluidos():
    """Nenhum arquivo .py da raiz (o app) importa um módulo excluído, nem dentro de função."""
    import ast  # noqa: PLC0415

    excluidos = set(exclusoes_build.MODULOS_SEM_USO)

    def excluido(nome: str) -> bool:
        return any(nome == e or nome.startswith(e + ".") for e in excluidos)

    # O ssl_ausente.py tenta o "import ssl" de propósito, dentro de try/except ImportError.
    permitidos = {"ssl_ausente.py: ssl"}
    achados = []
    for arquivo in sorted(RAIZ.glob("*.py")):
        if arquivo.name == "exclusoes_build.py":
            continue
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            nomes = []
            if isinstance(no, ast.Import):
                nomes = [alias.name for alias in no.names]
            elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
                nomes = [no.module] + [f"{no.module}.{alias.name}" for alias in no.names]
            achados += [f"{arquivo.name}: {nome}" for nome in nomes if excluido(nome)]
    assert sorted(set(achados) - permitidos) == []
    assert set(achados) >= permitidos, "o ssl_ausente.py deixou de conferir o ssl de verdade"


# ---------------------------------------------------------------------------
# ssl_ausente.py: o "import ssl" do pywebview sem o OpenSSL no executável
# ---------------------------------------------------------------------------

def test_ssl_ausente_instala_o_substituto_so_quando_o_ssl_nao_existe(monkeypatch):
    import ssl_ausente  # noqa: PLC0415

    monkeypatch.setitem(sys.modules, "ssl", None)  # como no .exe: o import falha
    assert ssl_ausente.garantir() is True
    import ssl  # noqa: PLC0415

    assert ssl_ausente.e_substituto(ssl)
    assert not hasattr(ssl, "SSLContext")
    with pytest.raises(AttributeError, match="exclusoes_build.py"):
        ssl.create_default_context()
    assert ssl_ausente.garantir() is False  # já há um módulo ssl importável: nada a fazer


def test_ssl_ausente_nao_mexe_no_ssl_de_verdade():
    pytest.importorskip("ssl")
    import ssl  # noqa: PLC0415

    import ssl_ausente  # noqa: PLC0415

    assert ssl_ausente.garantir() is False
    assert sys.modules["ssl"] is ssl
    assert not ssl_ausente.e_substituto(ssl)


def test_app_garante_o_ssl_antes_de_importar_o_pywebview():
    fonte = (RAIZ / "BTC_Monitor.py").read_text(encoding="utf-8")
    assert fonte.index("\nssl_ausente.garantir()\n") < fonte.index("\nimport webview")


@precisa_do_pywebview
def test_controle_sem_o_substituto_o_pywebview_nao_importa(tmp_path):
    """Caso de controle: com o ssl bloqueado e sem o ssl_ausente, "import webview" falha
    (o pywebview importa o ssl no topo de webview/http.py). Se um dia passar a importar,
    o substituto deixou de ser necessário."""
    codigo = 'import sys; sys.modules["ssl"] = None; import webview'
    saida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=120)
    assert saida.returncode != 0
    assert "ssl" in saida.stderr


@precisa_do_pywebview
def test_pywebview_so_usa_o_ssl_com_ssl_ligado():
    """O substituto só serve enquanto o pywebview usar o ssl apenas dentro de "if ssl:"."""
    import re  # noqa: PLC0415

    import webview  # noqa: PLC0415

    fonte = (Path(webview.__file__).parent / "http.py").read_text(encoding="utf-8")
    usos = [linha.strip() for linha in fonte.splitlines() if re.search(r"\bssl\.\w", linha)]
    assert usos == ["ssl_context = ssl.SSLContext()"], usos
    assert "ssl=" not in (RAIZ / "BTC_Monitor.py").read_text(encoding="utf-8"), "o app não pode ligar o ssl do pywebview"


def test_openssl_esta_na_lista_do_que_nao_pode_estar_no_build():
    proibidos = exclusoes_build.arquivos_proibidos_no_build()
    for arquivo in ("libcrypto-3.dll", "libssl-3.dll", "_ssl.pyd", "_hashlib.pyd"):
        assert arquivo in proibidos
    assert {"ssl", "_ssl", "_hashlib"} <= set(exclusoes_build.MODULOS_SEM_USO)


def test_spec_usa_as_listas_do_exclusoes_build():
    spec = (RAIZ / "BTC Monitor.spec").read_text(encoding="utf-8")
    assert ("from exclusoes_build import MODULOS_OBRIGATORIOS, MODULOS_SEM_USO, OTIMIZACAO_DO_BYTECODE, "
            "sem_arquivos_sem_uso") in spec
    assert "hiddenimports=list(MODULOS_OBRIGATORIOS)," in spec
    # O bytecode e o interpretador do .exe no mesmo nível de otimização.
    assert "optimize=OTIMIZACAO_DO_BYTECODE," in spec
    assert "[('O', None, 'OPTION')] * OTIMIZACAO_DO_BYTECODE," in spec
    assert exclusoes_build.OTIMIZACAO_DO_BYTECODE == 2
    assert "EXCLUIR += MODULOS_SEM_USO" in spec
    assert "a.datas = sem_arquivos_sem_uso(a.datas)" in spec
    assert "a.binaries = sem_arquivos_sem_uso(a.binaries)" in spec
    # O filtro vem depois de tudo o que acrescenta arquivos e antes do COLLECT.
    assert spec.index("a.datas +=") < spec.index("sem_arquivos_sem_uso(a.datas)") < spec.index("COLLECT(")


def test_script_do_build_confere_a_pasta_dist():
    script = (RAIZ / "criar_exe_btc.ps1").read_text(encoding="utf-8")
    assert "tools\\conferir_build.py" in script
    assert '--trabalho (Join-Path $raiz "build\\BTC Monitor")' in script


def test_cada_modulo_python_sem_uso_tem_o_motivo():
    for nome, motivo in exclusoes_build.MODULOS_PYTHON_SEM_USO.items():
        assert motivo.strip(), nome
        assert nome in exclusoes_build.MODULOS_SEM_USO


# ---------------------------------------------------------------------------
# tools/conferir_build.py --avisos: import no topo de módulo excluído
# ---------------------------------------------------------------------------

AVISOS = """
This file lists modules PyInstaller was not able to find.

missing module named pwd - imported by posixpath (delayed, conditional, optional), shutil (delayed, optional)
excluded module named bz2 - imported by encodings.bz2_codec (top-level), shutil (optional), zipfile (optional)
excluded module named ssl - imported by http.client (optional), ssl_ausente (delayed, optional), webview.http (top-level)
excluded module named argparse - imported by uuid (delayed), http.server (conditional), bottle (delayed)
excluded module named tarfile - imported by shutil (delayed)
"""


def test_avisos_sem_import_no_topo_fora_dos_conhecidos():
    assert conferir_build.imports_no_topo_de_excluidos(AVISOS) == []


def test_avisos_acusam_import_no_topo_de_modulo_excluido(tmp_path):
    """O caso que quebraria o .exe: um módulo do build importa no topo um módulo excluído
    (foi assim que o zipfile, importado pelo runtime hook do PyInstaller, ficou de fora da lista)."""
    texto = AVISOS + "excluded module named zipfile - imported by importlib.resources.readers (top-level), shutil (delayed)\n"
    assert conferir_build.imports_no_topo_de_excluidos(texto) == [("zipfile", "importlib.resources.readers")]
    arquivo = tmp_path / "warn.txt"
    arquivo.write_text(texto, encoding="utf-8")
    assert conferir_build.conferir_avisos(arquivo) == [
        "importlib.resources.readers importa no topo o modulo excluido zipfile"]
    build = criar_build(tmp_path)
    trabalho = criar_pasta_de_trabalho(tmp_path, build, avisos=texto)
    assert conferir_build.main([str(build), "--trabalho", str(trabalho)]) == 1
    assert conferir_build.main([str(build)]) == 0


def test_avisos_arquivo_ausente_e_erro(tmp_path):
    assert conferir_build.conferir_avisos(tmp_path / "nao-existe.txt") != []


# ---------------------------------------------------------------------------
# Módulos que só o lado .NET do pythonnet importa (MODULOS_OBRIGATORIOS)
# ---------------------------------------------------------------------------

def criar_pasta_de_trabalho(pasta: Path, build: Path, avisos: str = AVISOS,
                            no_pyz=("importlib.abc", "importlib.machinery", "inspect", "threading"),
                            na_base=("collections/__init__.pyc", "_collections_abc.pyc", "traceback.pyc",
                                     "warnings.pyc")) -> Path:
    """Pasta de trabalho do PyInstaller de mentira: avisos, PYZ-00.toc e o base_library.zip do build."""
    import zipfile  # noqa: PLC0415

    trabalho = pasta / "trabalho"
    trabalho.mkdir(exist_ok=True)
    (trabalho / conferir_build.NOME_AVISOS).write_text(avisos, encoding="utf-8")
    entradas = [(nome, f"C:\\Python314\\Lib\\{nome}.py", "PYMODULE") for nome in no_pyz]
    (trabalho / conferir_build.NOME_LISTA_DO_PYZ).write_text(
        repr(("C:\\build\\PYZ-00.pyz", entradas)), encoding="utf-8")
    with zipfile.ZipFile(build / "_internal" / conferir_build.NOME_BASE_LIBRARY, "w") as pacote:
        for caminho in na_base:
            pacote.writestr(caminho, b"")
    return trabalho


def test_conferir_build_aceita_o_build_com_os_modulos_obrigatorios(tmp_path, capsys):
    build = criar_build(tmp_path)
    trabalho = criar_pasta_de_trabalho(tmp_path, build)
    assert conferir_build.conferir_modulos(trabalho, build) == []
    assert conferir_build.main([str(build), "--trabalho", str(trabalho)]) == 0
    assert "modulos obrigatorios presentes" in capsys.readouterr().out


def test_conferir_build_acusa_modulo_obrigatorio_faltando(tmp_path, capsys):
    """O defeito da 1ª versão da leva 3: o importlib.abc saiu do build junto com o
    importlib.metadata, e o .exe fechava sem mensagem ao iniciar o pythonnet."""
    build = criar_build(tmp_path)
    trabalho = criar_pasta_de_trabalho(tmp_path, build, no_pyz=("importlib.machinery", "inspect", "threading"))
    problemas = conferir_build.conferir_modulos(trabalho, build)
    assert len(problemas) == 1 and "importlib.abc" in problemas[0]
    assert conferir_build.main([str(build), "--trabalho", str(trabalho)]) == 1
    assert "modulo obrigatorio faltando no build: importlib.abc" in capsys.readouterr().out


def test_conferir_build_sem_a_lista_do_pyz_e_erro(tmp_path):
    build = criar_build(tmp_path)
    trabalho = criar_pasta_de_trabalho(tmp_path, build)
    (trabalho / conferir_build.NOME_LISTA_DO_PYZ).unlink()
    assert conferir_build.conferir_modulos(trabalho, build) != []


def test_modulos_obrigatorios_existem_como_arquivo():
    """Cada módulo obrigatório precisa ser um módulo de verdade (com arquivo), senão o
    conferir_build.py nunca o acharia no build (ex.: collections.abc é só um apelido)."""
    for nome in exclusoes_build.MODULOS_OBRIGATORIOS:
        especificacao = importlib.util.find_spec(nome)
        assert especificacao is not None and especificacao.origin not in (None, "built-in"), nome


def test_modulos_obrigatorios_nao_sao_excluidos():
    excluidos = exclusoes_build.MODULOS_SEM_USO
    for nome in exclusoes_build.MODULOS_OBRIGATORIOS:
        assert not any(nome == e or nome.startswith(e + ".") for e in excluidos), nome


def test_modulos_que_a_dll_do_pythonnet_importa_sao_obrigatorios():
    """Lê da Python.Runtime.dll instalada o código Python embutido (texto em UTF-16) e
    confere que todo "import x" dele está em MODULOS_OBRIGATORIOS. Ao atualizar o pythonnet,
    um import novo aparece aqui antes de quebrar o .exe."""
    import re  # noqa: PLC0415

    if importlib.util.find_spec("pythonnet") is None:
        pytest.skip("pythonnet não instalado")
    import pythonnet  # noqa: PLC0415

    dll = Path(pythonnet.__file__).parent / "runtime" / "Python.Runtime.dll"
    texto = dll.read_bytes().decode("utf-16-le", errors="ignore")
    importados = set(re.findall(r"^[ \t]*import ([a-z_][\w.]*)", texto, re.M))
    importados |= {nome for nome in re.findall(r"\b((?:importlib|collections)\.[a-z_]+)\.", texto)}
    assert "importlib.abc" in importados, "o código do import hook não foi achado na DLL: rever este teste"
    # collections.abc não tem arquivo: é o _collections_abc, registrado pelo collections.
    if "collections.abc" in importados:
        importados = (importados - {"collections.abc"}) | {"collections", "_collections_abc"}
    # sys é embutido no interpretador; clr é o módulo que a própria DLL cria.
    faltando = importados - set(exclusoes_build.MODULOS_OBRIGATORIOS) - {"sys", "clr"}
    assert faltando == set(), f"a Python.Runtime.dll importa módulos fora de MODULOS_OBRIGATORIOS: {faltando}"


def test_imports_no_topo_conhecidos_sao_de_modulos_excluidos():
    for (excluido, importador), motivo in exclusoes_build.IMPORTS_NO_TOPO_CONHECIDOS.items():
        assert excluido in exclusoes_build.MODULOS_SEM_USO, excluido
        assert importador and motivo.strip()


# ---------------------------------------------------------------------------
# Filtro das listas do PyInstaller
# ---------------------------------------------------------------------------

def test_filtro_tira_so_os_arquivos_sem_uso():
    entradas = [
        ("webview\\lib\\runtimes\\win-x64\\native\\WebView2Loader.dll", "C:\\a", "BINARY"),
        ("webview\\lib\\runtimes\\win-arm64\\native\\WebView2Loader.dll", "C:\\b", "BINARY"),
        ("webview\\lib\\runtimes\\win-x86\\native\\WebView2Loader.dll", "C:\\c", "DATA"),
        ("webview/lib/pywebview-android.jar", "/d", "DATA"),
        ("PYTHONNET\\Runtime\\python.runtime.XML", "C:\\e", "DATA"),
        ("pythonnet\\runtime\\Python.Runtime.dll", "C:\\f", "DATA"),
        ("index.html", "C:\\g", "DATA"),
    ]
    assert [e[0] for e in exclusoes_build.sem_arquivos_sem_uso(entradas)] == [
        "webview\\lib\\runtimes\\win-x64\\native\\WebView2Loader.dll",
        "webview\\lib\\runtimes\\win-arm64\\native\\WebView2Loader.dll",
        "webview\\lib\\runtimes\\win-x86\\native\\WebView2Loader.dll",
        "pythonnet\\runtime\\Python.Runtime.dll",
        "index.html",
    ]


def test_arquivos_obrigatorios_nunca_sao_sem_uso():
    for arquivo in exclusoes_build.ARQUIVOS_OBRIGATORIOS:
        assert not exclusoes_build.arquivo_sem_uso(arquivo), arquivo
        assert arquivo not in exclusoes_build.arquivos_proibidos_no_build()


# ---------------------------------------------------------------------------
# Os arquivos que o pywebview procura no .exe
#
# No .exe o pywebview localiza as DLLs e as PASTAS de webview/lib com
# webview.util.interop_dll_path, e levanta FileNotFoundError se faltar alguma. Os testes
# com o Python do venv não pegam isso (lá os arquivos existem todos): aqui a pasta lib é
# refeita só com o que sobra depois do filtro, como o PyInstaller faz (pasta sem arquivo
# não é criada), e a função real do pywebview procura nela.
# ---------------------------------------------------------------------------

def nomes_que_o_pywebview_procura() -> list[str]:
    """Argumentos de interop_dll_path em platforms/edgechromium.py (lidos do código-fonte)."""
    import re  # noqa: PLC0415

    import webview  # noqa: PLC0415

    fonte = (Path(webview.__file__).parent / "platforms" / "edgechromium.py").read_text(encoding="utf-8")
    nomes = re.findall(r"interop_dll_path\('([^']+)'\)", fonte)
    laco = re.search(r"for platform in \(([^)]*)\):\s*\n\s*os\.environ\['Path'\] \+= ';' \+ interop_dll_path\(platform\)", fonte)
    assert laco, "o edgechromium.py do pywebview mudou: rever ARQUIVOS_SEM_USO e este teste"
    return nomes + re.findall(r"'([^']+)'", laco.group(1))


def refazer_lib_do_pywebview(destino: Path, sem_uso) -> Path:
    """Copia a árvore webview/lib (arquivos vazios) sem os arquivos que o filtro tira."""
    import webview  # noqa: PLC0415

    origem = Path(webview.__file__).parent
    for arquivo in (origem / "lib").rglob("*"):
        relativo = arquivo.relative_to(origem.parent).as_posix()  # webview/lib/...
        if arquivo.is_file() and not sem_uso(relativo):
            copia = destino / relativo
            copia.parent.mkdir(parents=True, exist_ok=True)
            copia.touch()
    return destino / "webview"


def procurar_como_o_pywebview(pasta_webview: Path, monkeypatch) -> None:
    import webview.util  # noqa: PLC0415

    monkeypatch.setattr(webview.util, "__file__", str(pasta_webview / "util.py"))
    monkeypatch.setattr(sys, "argv", [str(pasta_webview.parent.parent / "BTC Monitor.exe")])
    for nome in nomes_que_o_pywebview_procura():
        webview.util.interop_dll_path(nome)  # FileNotFoundError se faltar


@precisa_do_pywebview
def test_pywebview_acha_no_build_tudo_o_que_procura(tmp_path, monkeypatch):
    nomes = nomes_que_o_pywebview_procura()
    assert {"win-arm64", "win-x64", "win-x86", "Microsoft.Web.WebView2.Core.dll"} <= set(nomes)
    pasta = refazer_lib_do_pywebview(tmp_path, exclusoes_build.arquivo_sem_uso)
    procurar_como_o_pywebview(pasta, monkeypatch)


@precisa_do_pywebview
def test_controle_tirar_um_webview2loader_impede_a_abertura(tmp_path, monkeypatch):
    """Caso de controle (o defeito que este teste pegaria): sem a DLL, a pasta
    runtimes/win-arm64/native não existe no build e o pywebview não abre."""
    def sem_uso(relativo: str) -> bool:
        return exclusoes_build.arquivo_sem_uso(relativo) or "win-arm64" in relativo

    pasta = refazer_lib_do_pywebview(tmp_path, sem_uso)
    with pytest.raises(FileNotFoundError, match="win-arm64"):
        procurar_como_o_pywebview(pasta, monkeypatch)


# ---------------------------------------------------------------------------
# tools/conferir_build.py
# ---------------------------------------------------------------------------

def criar_build(pasta: Path, extras: tuple[str, ...] = ()) -> Path:
    build = pasta / "BTC Monitor"
    obrigatorios = tuple(f"_internal/{arquivo}" for arquivo in exclusoes_build.ARQUIVOS_OBRIGATORIOS)
    for caminho in ("BTC Monitor.exe", *obrigatorios, *extras):
        arquivo = build / caminho
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(b"x" * 1024)
    return build


def test_conferir_build_aceita_o_build_limpo(tmp_path, capsys):
    build = criar_build(tmp_path)
    assert conferir_build.conferir(build) == []
    assert conferir_build.main([str(build)]) == 0
    saida = capsys.readouterr().out
    assert f"Tamanho do build: 0.0 MB em {len(exclusoes_build.ARQUIVOS_OBRIGATORIOS) + 1} arquivos" in saida
    assert "ERRO" not in saida


def test_conferir_build_acusa_arquivo_excluido_que_voltou(tmp_path, capsys):
    build = criar_build(tmp_path, extras=(
        "_internal/_decimal.pyd",
        "_internal/libcrypto-3.dll",
        "_internal/webview/lib/pywebview-android.jar",
        "_internal/Pythonnet/runtime/Python.Runtime.xml",  # maiúsculas diferentes: o Windows não diferencia
    ))
    problemas = conferir_build.conferir(build)
    assert len(problemas) == 4
    assert any("_decimal.pyd" in p for p in problemas)
    assert any("libcrypto-3.dll" in p for p in problemas)
    assert any("pywebview-android.jar" in p for p in problemas)
    assert any("Python.Runtime.xml" in p for p in problemas)
    assert conferir_build.main([str(build)]) == 1
    assert capsys.readouterr().out.count("ERRO:") == 4


def test_conferir_build_acusa_arquivo_obrigatorio_faltando(tmp_path, capsys):
    """O defeito da 1ª versão: o build saía sem a pasta runtimes/win-arm64 e o .exe não abria."""
    build = criar_build(tmp_path)
    (build / "_internal/webview/lib/runtimes/win-arm64/native/WebView2Loader.dll").unlink()
    problemas = conferir_build.conferir(build)
    assert len(problemas) == 1
    assert "obrigatorio" in problemas[0] and "win-arm64" in problemas[0]
    assert conferir_build.main([str(build)]) == 1


def test_conferir_build_acusa_falta_do_executavel_e_da_pasta(tmp_path):
    build = criar_build(tmp_path)
    (build / "BTC Monitor.exe").unlink()
    assert any("executavel" in p for p in conferir_build.conferir(build))
    assert conferir_build.main([str(tmp_path / "nao-existe")]) == 1


def test_todo_proibido_fica_na_pasta_interna():
    for caminho in exclusoes_build.arquivos_proibidos_no_build():
        assert not caminho.startswith(("/", "\\", "_internal")), caminho
        assert "\\" not in caminho
