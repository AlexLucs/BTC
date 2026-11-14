"""O app sem o módulo de medição, como no build de produção (python -m pytest tests).

O build de produção exclui o módulo metricas (ver "BTC Monitor.spec"). Aqui um Python
novo importa o BTC_Monitor com "metricas" bloqueado e confere que nada é medido nem
gravado e que a API exposta ao JS não tem registrar_metricas.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(importlib.util.find_spec("webview") is None, reason="pywebview não instalado")

CODIGO = r"""
import json, sys
sys.modules["metricas"] = None  # como no build de produção: o import falha
import BTC_Monitor as app
api = app.ExposedApi(app.RepositorioAlertas(app.PASTA_DADOS), app.METRICAS)
salvou = api.salvar_alerta([{"valor": 10, "tipo": "maior"}])
print(json.dumps({
    "medicao_ativa": app.MEDICAO_ATIVA,
    "api_tem_registrar_metricas": hasattr(api, "registrar_metricas"),
    "salvou": salvou,
    "carregou": api.carregar_alerta(),
    # BTC_SEM_PRECONNECT=1 e BTC_SEM_PRECO_PYTHON=1 são ignoradas sem a medição
    "html_com_preconnect": 'rel="preconnect"' in app.html_da_pagina(),
    "busca_preco_python": app.deve_buscar_preco_pelo_python(),
    "inicio_do_preco_desligado": app._desligado_antes_dos_imports("BTC_SEM_PRECO_PYTHON", "BTC_SEM_PRECO_CEDO"),
    "net_cedo_desligado": app._desligado_antes_dos_imports("BTC_SEM_NET_CEDO"),
}))
"""


def test_app_funciona_sem_o_modulo_de_medicao(tmp_path):
    ambiente = {**os.environ, "APPDATA": str(tmp_path), "BTC_SEM_PRECONNECT": "1", "BTC_SEM_PRECO_PYTHON": "1",
                "BTC_SEM_PRECO_CEDO": "1", "BTC_SEM_NET_CEDO": "1"}
    saida = subprocess.run([sys.executable, "-c", CODIGO], cwd=RAIZ, env=ambiente,
                           capture_output=True, text=True, timeout=120)
    assert saida.returncode == 0, saida.stderr
    resultado = json.loads(saida.stdout.strip().splitlines()[-1])
    assert resultado == {
        "medicao_ativa": False,
        "api_tem_registrar_metricas": False,
        "salvou": True,
        "carregou": [{"valor": 10.0, "tipo": "maior"}],
        "html_com_preconnect": True,
        "busca_preco_python": True,
        "inicio_do_preco_desligado": False,
        "net_cedo_desligado": False,
    }
    assert not (tmp_path / "btcstatus" / "metricas.jsonl").exists(), "produção não pode gravar métricas"
