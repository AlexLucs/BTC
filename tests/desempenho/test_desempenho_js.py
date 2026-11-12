"""Desempenho das funções puras do JS (regras.js e metricas.js), medido no Node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.desempenho

BENCH = Path(__file__).resolve().parent / "bench_js.js"

# Orçamentos por chamada (µs). Hoje essas funções rodam a cada ciclo de preço ou por ação do usuário.
ORCAMENTOS = {
    "alertaParaDisparar(100, nenhum dispara)": 50,
    "normalizarLista(100, formato antigo)": 1000,
    "Metricas.registrar": 5,
    "Metricas.medir(função vazia)": 10,
    "Metricas.relatorio(período típico) + JSON": 5000,
}


def test_funcoes_puras_js(coletor):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js não encontrado")
    saida = subprocess.run([node, str(BENCH)], check=True, capture_output=True, text=True, timeout=300)
    resultados = json.loads(saida.stdout)
    for nome, est in resultados.items():
        coletor.registrar(f"js/{nome} p50", est["p50"], "µs")
        if nome in ORCAMENTOS:
            coletor.orcamento(f"js/{nome} p95", est["p95"], ORCAMENTOS[nome], "µs")
