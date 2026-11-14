"""O início do BTC_Monitor.py, antes dos imports do topo: a requisição do 1º preço sai
primeiro e, em seguida, o .NET sobe em paralelo com os imports pesados.

Os testes executam só esse começo do arquivo num Python novo, com uma BuscaPrimeiroPreco
falsa e um inicio_paralelo.rodar falso: nenhuma janela é aberta, nenhuma requisição é
feita e o .NET não é carregado.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
FONTE = (RAIZ / "BTC_Monitor.py").read_text(encoding="utf-8")
# O começo termina onde ficam os imports do topo; o bloco do 1º preço, onde começa o do .NET.
FIM_DO_COMECO = "\nimport configparser"
FIM_DO_BLOCO_DO_PRECO = "\nimport inicio_paralelo"

# sys.argv[1]: nome com que o começo roda ("__main__" ao executar o app);
# sys.argv[2]: JSON com os módulos a bloquear (["metricas"] = build de produção).
CODIGO = r"""
import json, sys
for nome in json.loads(sys.argv[2]):
    sys.modules[nome] = None
antes = set(sys.modules)
import primeiro_preco

class BuscaFalsa:
    iniciada = False
    def __init__(self, *args, **kwargs): pass
    def iniciar(self): BuscaFalsa.iniciada = True

primeiro_preco.BuscaPrimeiroPreco = BuscaFalsa

import inicio_paralelo
paralelo = {"chamadas": 0, "busca_ja_iniciada": None, "pesados_antes": None}
pesados = ("logging", "configparser", "json.decoder", "webview", "bottle", "ctypes", "urllib.parse", "pathlib", "clr")

def importados():
    return sorted(m for m in pesados if m in sys.modules and m not in antes)

def rodar_falso(principal, auxiliar, nome_da_thread="x"):
    paralelo["chamadas"] += 1
    paralelo["busca_ja_iniciada"] = BuscaFalsa.iniciada
    paralelo["pesados_antes"] = importados()
    paralelo["tarefas"] = [principal.__name__, auxiliar.__name__]
    return inicio_paralelo.ResultadoParalelo()

inicio_paralelo.rodar = rodar_falso
if sys.argv[3]:
    sys.platform = sys.argv[3]
fonte = open("BTC_Monitor.py", encoding="utf-8").read()
comeco = fonte[:fonte.index("\nimport configparser")]
exec(compile(comeco, "BTC_Monitor.py", "exec"), {"__name__": sys.argv[1], "__file__": "BTC_Monitor.py"})
print(json.dumps({"iniciada": BuscaFalsa.iniciada, "pesados_importados": importados(), "paralelo": paralelo}))
"""


def rodar_o_comeco(nome: str = "__main__", bloqueados: tuple[str, ...] = (), plataforma: str = "win32",
                   **variaveis: str) -> dict:
    """Executa o começo do BTC_Monitor.py como se fosse no Windows (plataforma), sem o .NET."""
    ambiente = {k: v for k, v in os.environ.items() if not k.startswith("BTC_SEM_")}
    saida = subprocess.run([sys.executable, "-c", CODIGO, nome, json.dumps(list(bloqueados)), plataforma],
                           cwd=RAIZ, env={**ambiente, **variaveis}, capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, saida.stderr
    return json.loads(saida.stdout.strip().splitlines()[-1])


def test_o_comeco_do_arquivo_existe_e_vem_antes_dos_imports_pesados():
    assert FIM_DO_COMECO in FONTE, "os testes deste arquivo dependem de onde o bloco do 1º preço termina"
    assert FIM_DO_BLOCO_DO_PRECO in FONTE
    assert FONTE.index(FIM_DO_BLOCO_DO_PRECO) < FONTE.index(FIM_DO_COMECO)
    bloco_do_preco = "\n".join(linha for linha in FONTE[:FONTE.index(FIM_DO_BLOCO_DO_PRECO)].splitlines()
                               if not linha.lstrip().startswith("#"))  # só o código, sem os comentários
    assert "BUSCA_PRIMEIRO_PRECO.iniciar()" in bloco_do_preco
    for pesado in ("import logging", "import webview", "import configparser", "from logging.handlers", "import clr"):
        assert pesado not in bloco_do_preco, pesado


def test_ao_executar_o_app_a_busca_comeca_sem_nenhum_import_pesado():
    resultado = rodar_o_comeco()
    assert resultado["iniciada"] is True
    assert resultado["pesados_importados"] == [], "nada pesado pode ser importado antes de a requisição sair"


def test_importar_o_modulo_nao_inicia_a_busca():
    """Os testes importam o BTC_Monitor: isso não pode fazer uma requisição."""
    assert rodar_o_comeco(nome="BTC_Monitor")["iniciada"] is False


@pytest.mark.parametrize("variavel", ["BTC_SEM_PRECO_CEDO", "BTC_SEM_PRECO_PYTHON"])
def test_na_medicao_a_variavel_desliga_o_inicio_antes_dos_imports(variavel):
    """tools/medir_abertura.py --comparar preco-cedo / preco-python (com o módulo metricas)."""
    assert rodar_o_comeco(**{variavel: "1"})["iniciada"] is False
    assert rodar_o_comeco(**{variavel: "0"})["iniciada"] is True


@pytest.mark.parametrize("variavel", ["BTC_SEM_PRECO_CEDO", "BTC_SEM_PRECO_PYTHON"])
def test_na_producao_as_variaveis_sao_ignoradas(variavel):
    """Sem o módulo metricas (build de produção) as variáveis BTC_SEM_* não valem."""
    assert rodar_o_comeco(bloqueados=("metricas",), **{variavel: "1"})["iniciada"] is True


def test_main_ainda_inicia_a_busca_quando_o_comeco_foi_desligado():
    """Com preco-cedo desligado na medição, a busca sai no main(), como antes (iniciar() vale uma vez)."""
    main = FONTE[FONTE.index("def main()"):]
    assert "if deve_buscar_preco_pelo_python():\n        BUSCA_PRIMEIRO_PRECO.iniciar()" in main


def test_app_libera_o_log_da_busca_depois_de_configurar_o_log():
    assert "BuscaPrimeiroPreco(adiar_log=True)" in FONTE
    main = FONTE[FONTE.index("def main()"):]
    assert main.index("configurar_log()") < main.index("BUSCA_PRIMEIRO_PRECO.liberar_log()")


# ---------------------------------------------------------------------------
# .NET em paralelo com os imports
# ---------------------------------------------------------------------------

def test_no_windows_o_net_e_os_imports_rodam_em_paralelo_depois_de_a_busca_sair():
    paralelo = rodar_o_comeco()["paralelo"]
    assert paralelo["chamadas"] == 1
    assert paralelo["tarefas"] == ["_importar_clr", "_importar_o_resto"]
    assert paralelo["busca_ja_iniciada"] is True, "a requisição do preço sai antes de tudo"
    assert paralelo["pesados_antes"] == [], "nada pesado antes de o .NET começar a subir"


def test_fora_do_windows_ou_ao_importar_o_modulo_nao_ha_inicio_em_paralelo():
    assert rodar_o_comeco(plataforma="linux")["paralelo"]["chamadas"] == 0
    assert rodar_o_comeco(nome="BTC_Monitor")["paralelo"]["chamadas"] == 0


def test_na_medicao_a_variavel_desliga_o_net_em_paralelo_e_a_producao_a_ignora():
    assert rodar_o_comeco(BTC_SEM_NET_CEDO="1")["paralelo"]["chamadas"] == 0
    assert rodar_o_comeco(BTC_SEM_NET_CEDO="1")["iniciada"] is True, "a busca do preço não depende disso"
    assert rodar_o_comeco(bloqueados=("metricas",), BTC_SEM_NET_CEDO="1")["paralelo"]["chamadas"] == 1


def test_a_thread_auxiliar_importa_os_mesmos_modulos_do_topo_e_garante_o_ssl_antes_do_pywebview():
    """Se um import pesado novo entrar no topo do arquivo e não aqui, ele volta a rodar
    depois do .NET, em vez de junto."""
    import ast  # noqa: PLC0415

    arvore = ast.parse(FONTE)
    funcao = next(no for no in arvore.body if isinstance(no, ast.FunctionDef) and no.name == "_importar_o_resto")
    na_thread = {alias.name.split(".")[0] for no in ast.walk(funcao) if isinstance(no, ast.Import) for alias in no.names}

    depois = ast.parse(FONTE[FONTE.index(FIM_DO_COMECO):])
    no_topo = set()
    for no in depois.body:
        if isinstance(no, ast.Import):
            no_topo |= {alias.name.split(".")[0] for alias in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            no_topo.add(no.module.split(".")[0])
    assert no_topo - {"metricas"} <= na_thread, f"faltam na thread auxiliar: {no_topo - na_thread}"

    corpo = ast.get_source_segment(FONTE, funcao)
    assert corpo.index("ssl_ausente.garantir()") < corpo.index("import webview")


def test_erros_do_inicio_em_paralelo_vao_para_o_log():
    main = FONTE[FONTE.index("def main()"):]
    assert main.index("configurar_log()") < main.index("INICIO_PARALELO.erros()")


def test_as_metricas_sao_ligadas_a_busca_depois_de_criadas():
    assert FONTE.index('METRICAS.marcar("imports_concluidos")') < FONTE.index("BUSCA_PRIMEIRO_PRECO.ligar_metricas(METRICAS)")


def test_variaveis_novas_estao_no_medir_abertura_e_no_guia():
    sys.path.insert(0, str(RAIZ / "tools"))
    import medir_abertura  # noqa: PLC0415

    guia = (RAIZ / "MEDICAO.md").read_text(encoding="utf-8")
    for recurso, variavel in (("preco-cedo", "BTC_SEM_PRECO_CEDO"), ("net-cedo", "BTC_SEM_NET_CEDO")):
        assert medir_abertura.COMPARACOES[recurso][0] == variavel
        assert f'"{variavel}"' in FONTE
        assert f"`{recurso}`" in guia and variavel in guia
