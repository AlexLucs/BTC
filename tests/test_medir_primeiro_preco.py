"""tools/medir_primeiro_preco.py: as partes que não dependem da rede."""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tools"))

import medir_primeiro_preco as medicao  # noqa: E402
from baixar_winhttp import separar_url  # noqa: E402
from primeiro_preco import URL_TICKERS  # noqa: E402

COMPLETO = {"lastPrice": "1", "priceChangePercent": "2", "highPrice": "3", "lowPrice": "0"}


def test_candidatos_comecam_pelo_endereco_do_app_e_sao_https():
    urls = medicao.candidatos()
    assert next(iter(urls.values())) == URL_TICKERS
    assert len(set(urls.values())) == len(urls)
    for url in urls.values():
        seguro, servidor, porta, caminho = separar_url(url)
        assert seguro and porta == 443
        assert servidor.endswith(("binance.com", "binance.vision"))
        assert caminho.startswith("/api/v3/ticker/24hr?symbols=%5B%22BTCBRL%22%2C%22BTCUSDT%22%5D")


def test_resposta_completa_nao_tem_campos_faltando():
    corpo = json.dumps([{"symbol": "BTCBRL", **COMPLETO}, {"symbol": "BTCUSDT", **COMPLETO}]).encode()
    assert medicao.campos_faltando(corpo) == []


def test_resposta_mini_acusa_o_percentual_que_a_pagina_usa():
    mini = {k: v for k, v in COMPLETO.items() if k != "priceChangePercent"}
    corpo = json.dumps([{"symbol": "BTCBRL", **mini}, {"symbol": "BTCUSDT", **COMPLETO}]).encode()
    assert medicao.campos_faltando(corpo) == ["BTCBRL.priceChangePercent"]


def test_resposta_sem_um_par_ou_invalida():
    assert medicao.campos_faltando(json.dumps([{"symbol": "BTCBRL", **COMPLETO}]).encode()) == ["BTCUSDT"]
    assert medicao.campos_faltando(b"<html>") == ["resposta que nao e JSON"]
    assert medicao.campos_faltando(b'{"code": -1}') == ["resposta que nao e uma lista"]


def test_campos_da_pagina_sao_os_que_o_script_le():
    script = (RAIZ / "script.js").read_text(encoding="utf-8")
    for campo in medicao.CAMPOS_DA_PAGINA:
        assert f"dados.{campo}" in script, campo


def test_resumo_e_medir_com_falha(monkeypatch):
    assert medicao.resumo([]) == "sem medidas"
    assert "mediana    200" in medicao.resumo([100.0, 200.0, 900.0])

    def falha(url, timeout_s):
        raise OSError("sem rede")

    monkeypatch.setattr(medicao, "baixar", falha)
    duracao, corpo, erro = medicao.medir("https://exemplo.invalid/", 1)
    assert corpo is None and erro == "sem rede" and duracao >= 0
