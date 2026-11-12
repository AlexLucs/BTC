"""Desempenho do lado Python: validação, disco, métricas e custo dos imports da abertura."""

from __future__ import annotations

import importlib.util
import json
import statistics
import subprocess
import sys
import time

import pytest
from conftest import RAIZ, cronometrar

from alertas_store import RepositorioAlertas, validar_alertas
from metricas import RegistroMetricas, validar_relatorio_js

pytestmark = pytest.mark.desempenho

ALERTAS_100 = [{"id": f"id-{i:03d}", "valor": 100_000 + i * 1000.5, "tipo": ("maior", "menor", "desativado")[i % 3]}
               for i in range(100)]


def relatorio_js_tipico() -> dict:
    """Relatório de 5 min com o volume real aproximado (cerca de 70 ciclos de preço)."""
    nomes = ["espera:precos", "processamento:precos", "render:brl", "alarmes:checar",
             "rede:api.binance.com", "atraso_timer:preco", "python:registrar_metricas"]
    return {
        "motivo": "periodico", "timeOrigin": 1.7e12, "marcos": {f"m{i}": i * 10.5 for i in range(20)},
        "amostras": {nome: [i * 0.123 for i in range(70)] for nome in nomes},
        "linhaTempo": {"atraso_timer:preco": [[1.7e12 + i, i * 0.5] for i in range(70)]},
        "contadores": {"falha:binance": 1}, "eventos": [], "tarefasLongas": [],
    }


def test_validar_alertas_100(coletor):
    est = cronometrar(lambda: validar_alertas(ALERTAS_100), repeticoes=2000)
    coletor.registrar("py/validar_alertas(100) p50", est["p50"])
    coletor.orcamento("py/validar_alertas(100) p95", est["p95"], limite=5)


def test_salvar_e_carregar_100(coletor, tmp_path):
    repositorio = RepositorioAlertas(tmp_path)
    est_salvar = cronometrar(lambda: repositorio.salvar(ALERTAS_100), repeticoes=50)
    est_carregar = cronometrar(repositorio.carregar, repeticoes=200)
    # salvar inclui fsync: depende muito do disco (SSD x HD) e do antivírus.
    coletor.registrar("py/salvar_alerta(100) p50", est_salvar["p50"])
    coletor.orcamento("py/salvar_alerta(100) p95", est_salvar["p95"], limite=200)
    coletor.registrar("py/carregar_alerta(100) p50", est_carregar["p50"])
    coletor.orcamento("py/carregar_alerta(100) p95", est_carregar["p95"], limite=20)


def test_relatorio_de_metricas(coletor, tmp_path):
    relatorio = relatorio_js_tipico()
    registro = RegistroMetricas(tmp_path, 0.0, 0.0, sessao="bench")
    est_validar = cronometrar(lambda: validar_relatorio_js(relatorio), repeticoes=200)
    est_gravar = cronometrar(lambda: registro.gravar("js", {"relatorio": relatorio}), repeticoes=200)
    coletor.registrar("py/métricas: tamanho do relatório típico", len(json.dumps(relatorio)) / 1024, "KB")
    coletor.orcamento("py/métricas: validar relatório p95", est_validar["p95"], limite=20)
    coletor.orcamento("py/métricas: gravar relatório p95", est_gravar["p95"], limite=50)


def _tempo_subprocesso(codigo: str, vezes: int = 5) -> float:
    """Mediana (ms) de um Python novo executando o código: aproxima o custo da abertura."""
    duracoes = []
    for _ in range(vezes):
        inicio = time.perf_counter()
        subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, check=True, capture_output=True)
        duracoes.append((time.perf_counter() - inicio) * 1000)
    return statistics.median(duracoes)


def test_custo_dos_imports_da_abertura(coletor):
    """Quanto da abertura é só Python: interpretador vazio, pywebview e o módulo do app."""
    vazio = _tempo_subprocesso("pass")
    coletor.registrar("abertura/python vazio (mediana)", vazio)
    if importlib.util.find_spec("webview") is None:
        pytest.skip("pywebview não instalado neste Python")
    webview = _tempo_subprocesso("import webview")
    app = _tempo_subprocesso("import BTC_Monitor")
    coletor.registrar("abertura/import webview - vazio", webview - vazio)
    coletor.orcamento("abertura/import BTC_Monitor - vazio", app - vazio, limite=3000)
