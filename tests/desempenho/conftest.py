"""Infraestrutura dos testes de desempenho.

Rodar (na raiz do projeto):
    .venv\\Scripts\\python.exe -m pytest tests\\desempenho -m desempenho

Ao final, as medidas são gravadas em tests/desempenho/resultados/AAAAMMDD-HHMMSS.json
e comparadas com o arquivo anterior (coluna "Δ %").

Variáveis de ambiente:
    BTC_SEM_ORCAMENTO=1   só mede; não falha quando um orçamento é estourado
    BTC_NAVEGADOR=...     msedge (padrão no Windows), chrome ou chromium (testes de página)
    BTC_REDE_REAL=1       testes de página usam a rede de verdade em vez da simulada
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))  # apoio_pagina

from metricas import estatisticas  # noqa: E402

PASTA_RESULTADOS = Path(__file__).resolve().parent / "resultados"
SEM_ORCAMENTO = os.getenv("BTC_SEM_ORCAMENTO") == "1"


class Coletor:
    """Guarda as medidas da execução e confere orçamentos."""

    def __init__(self) -> None:
        self.medidas: dict[str, dict[str, Any]] = {}
        self.ambiente: dict[str, Any] = {
            "python": sys.version.split()[0],
            "sistema": platform.platform(),
            "processador": platform.processor() or platform.machine(),
        }
        self.estouros: list[str] = []

    def registrar(self, nome: str, valor: float, unidade: str = "ms") -> None:
        self.medidas[nome] = {"valor": round(float(valor), 4), "unidade": unidade}

    def orcamento(self, nome: str, valor: float, limite: float, unidade: str = "ms") -> None:
        """Registra a medida e falha o teste se passar do limite (exceto com BTC_SEM_ORCAMENTO=1)."""
        self.registrar(nome, valor, unidade)
        self.medidas[nome]["limite"] = limite
        if valor > limite:
            mensagem = f"{nome}: {valor:.4g} {unidade} > orçamento {limite:.4g} {unidade}"
            self.estouros.append(mensagem)
            if not SEM_ORCAMENTO:
                pytest.fail(mensagem)


def cronometrar(funcao: Callable[[], Any], repeticoes: int, aquecimento: int = 5) -> dict[str, float | int]:
    """Executa a função várias vezes e devolve as estatísticas da duração de cada chamada (ms)."""
    for _ in range(aquecimento):
        funcao()
    duracoes = []
    for _ in range(repeticoes):
        inicio = time.perf_counter()
        funcao()
        duracoes.append((time.perf_counter() - inicio) * 1000)
    return estatisticas(duracoes)


def pytest_configure(config: pytest.Config) -> None:
    config._coletor_desempenho = Coletor()  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def coletor(request: pytest.FixtureRequest) -> Coletor:
    return request.config._coletor_desempenho  # type: ignore[attr-defined]


def _resultado_anterior() -> dict[str, Any] | None:
    arquivos = sorted(PASTA_RESULTADOS.glob("*.json"))
    if not arquivos:
        return None
    try:
        return json.loads(arquivos[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def pytest_terminal_summary(terminalreporter, config: pytest.Config) -> None:
    coletor: Coletor = config._coletor_desempenho  # type: ignore[attr-defined]
    if not coletor.medidas:
        return
    anterior = _resultado_anterior()
    medidas_anteriores = (anterior or {}).get("medidas", {})

    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    destino = PASTA_RESULTADOS / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    destino.write_text(json.dumps({"ambiente": coletor.ambiente, "medidas": coletor.medidas},
                                  ensure_ascii=False, indent=2), encoding="utf-8")

    escrever = terminalreporter.write_line
    terminalreporter.section("Desempenho")
    escrever(f"{'Medida':<58} {'anterior':>11} {'atual':>11} {'Δ %':>8}  unidade / orçamento")
    for nome in sorted(coletor.medidas):
        atual = coletor.medidas[nome]
        medida_anterior = medidas_anteriores.get(nome, {})
        # Só compara medidas na mesma unidade.
        anterior_valor = medida_anterior.get("valor") if medida_anterior.get("unidade") == atual["unidade"] else None
        delta = ""
        if anterior_valor not in (None, 0):
            delta = f"{(atual['valor'] - anterior_valor) / abs(anterior_valor) * 100:+.1f}"
        anterior_txt = "" if anterior_valor is None else f"{anterior_valor:.4g}"
        limite = f" (≤ {atual['limite']:.4g})" if "limite" in atual else ""
        escrever(f"{nome:<58} {anterior_txt:>11} {atual['valor']:>11.4g} {delta:>8}  {atual['unidade']}{limite}")
    if coletor.estouros:
        escrever("Orçamentos estourados: " + "; ".join(coletor.estouros))
    escrever(f"Resultados gravados em {destino}")
