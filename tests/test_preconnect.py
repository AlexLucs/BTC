"""Dicas de pré-conexão do index.html e a comparação com/sem do tools/medir_abertura.py."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

import medir_abertura  # noqa: E402

HTML = (RAIZ / "index.html").read_text(encoding="utf-8")
DICA = re.compile(r'<link rel="(preconnect|dns-prefetch)" href="([^"]+)"( crossorigin)?>')


def dicas() -> list[tuple[str, str, bool]]:
    return [(m[1], m[2], bool(m[3])) for m in DICA.finditer(HTML)]


def diretivas_csp() -> dict[str, list[str]]:
    conteudo = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', HTML)[1]
    regras = {}
    for parte in conteudo.split(";"):
        nome, *valores = parte.split()
        regras[nome] = valores
    return regras


def permitido(origem: str, fonte: str) -> bool:
    if fonte.startswith("https://*."):
        return urlsplit(origem).hostname.endswith(fonte[len("https://*"):])
    return fonte.startswith("https://") and urlsplit(fonte)._replace(path="").geturl() == origem


def test_dicas_esperadas_e_antes_dos_recursos():
    assert dicas() == [
        ("preconnect", "https://api.binance.com", True),
        ("preconnect", "https://economia.awesomeapi.com.br", True),
        ("preconnect", "https://mempool.space", True),
        ("preconnect", "https://s3.tradingview.com", False),
        ("dns-prefetch", "https://stream.binance.com", False),
    ]
    # Depois da CSP (que só vale para o que vem depois dela) e antes da fonte e dos scripts.
    assert HTML.index("Content-Security-Policy") < HTML.index('rel="preconnect"') < HTML.index('rel="preload"')


def test_cada_dica_e_permitida_por_alguma_diretiva_da_csp():
    """O Chromium só segue a dica se alguma diretiva da CSP permitir o endereço."""
    fontes = [f for valores in diretivas_csp().values() for f in valores]
    for _, origem, _ in dicas():
        host = urlsplit(origem).hostname
        assert any(permitido(origem, f) or (f.startswith("wss://") and urlsplit(f).hostname == host)
                   for f in fontes), origem


def test_app_remove_so_as_dicas_na_variante_de_medicao():
    """BTC_Monitor.remover_preconnect (importado com pywebview simulado)."""
    codigo = (
        "import sys, types; sys.modules['webview'] = types.ModuleType('webview')\n"
        "import BTC_Monitor as app\n"
        "html = open('index.html', encoding='utf-8').read()\n"
        "sys.stdout.write(app.remover_preconnect(html))\n"
    )
    ambiente = {**os.environ, "APPDATA": str(RAIZ / ".pytest_cache" / "appdata")}
    saida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, env=ambiente,
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert saida.returncode == 0, saida.stderr
    variante = saida.stdout
    assert not DICA.search(variante)
    linhas_removidas = [l for l in HTML.splitlines() if l not in variante.splitlines()]
    assert len(linhas_removidas) == len(dicas()) and all(DICA.search(l) for l in linhas_removidas)


def test_ordem_alternada_equilibra_as_metades():
    sem = [medir_abertura.sem_recurso_na_execucao(i) for i in range(1, 21)]
    assert sum(sem) == 10
    assert sem[:4] == [False, True, True, False]


def test_comparacao_calcula_medianas_e_ganho(capsys):
    def sessao(origem_ms: float, preco: float, rede1: float) -> list[dict]:
        return [
            {"tipo": "abertura_python", "inicio_script_epoch": 1000.0, "inicio_processo_epoch": 1000.0, "marcos_ms": {}},
            {"tipo": "js", "relatorio": {"timeOrigin": 1000.0 * 1000 + origem_ms, "marcos": {"primeiro_preco": preco},
                                         "amostras": {"rede1:api.binance.com": [rede1]}}},
        ]
    com = medir_abertura.medianas_do_grupo({"a": sessao(500, 400, 120), "b": sessao(500, 420, 140)})
    sem = medir_abertura.medianas_do_grupo({"c": sessao(500, 600, 330)})
    assert com == {"primeiro_preco": 910, "rede1:api.binance.com": 130}
    medir_abertura.imprimir_comparacao({"com": com, "sem": sem}, {"com": 2, "sem": 1})
    saida = capsys.readouterr().out
    assert "+190" in saida and "+200" in saida and "Pré-conexão" in saida


def test_medicao_para_se_outra_instancia_ocupa_a_porta(monkeypatch):
    import socket as _socket
    servidor = _socket.socket()
    servidor.bind(("127.0.0.1", 0))
    servidor.listen()
    porta = servidor.getsockname()[1]
    monkeypatch.setattr(medir_abertura, "PORTA_PYWEBVIEW", porta)
    verificar = medir_abertura.porta_ocupada
    try:
        assert verificar(porta)
        monkeypatch.setattr(medir_abertura, "porta_ocupada", lambda porta=porta: True)
        try:
            medir_abertura.garantir_porta_livre(espera_s=0.3)
        except SystemExit as erro:
            assert str(porta) in str(erro)
        else:
            raise AssertionError("deveria parar a medição")
    finally:
        servidor.close()
    assert not verificar(porta)


def test_tabela_mostra_arquivos_e_leituras(capsys):
    import analisar_metricas
    sessao = [
        {"tipo": "abertura_python", "inicio_script_epoch": 1000.0, "inicio_processo_epoch": 1000.0, "marcos_ms": {}},
        {"tipo": "js", "relatorio": {"timeOrigin": 1000.0 * 1000 + 600, "marcos": {"recurso:Roboto.woff2": 50},
                                     "contadores": {"recurso_n:Roboto.woff2": 1}}},
    ]
    com = medir_abertura.medianas_do_grupo({"a": sessao})
    assert com == {"recurso:Roboto.woff2": 650, "recurso_n:Roboto.woff2": 1}
    medir_abertura.imprimir_comparacao({"com": com, "sem": {"recurso_n:Roboto.woff2": 2}}, {"com": 1, "sem": 1}, "X")
    saida = capsys.readouterr().out
    assert "Arquivo recebido: Roboto.woff2" in saida and "Leituras (vezes) de Roboto.woff2" in saida
    assert analisar_metricas.etapas_dos_arquivos({"recurso_inicio:a.css": [1], "recurso:a.css": [2], "nav_load": [3]}) == [
        ("js", "recurso:a.css", "a.css: recebido"), ("js", "recurso_inicio:a.css", "a.css: pedido")]


def test_secao_bloqueios_converte_para_o_tempo_do_processo(capsys):
    import analisar_metricas
    sessao = [
        {"tipo": "abertura_python", "inicio_script_epoch": 1000.0, "inicio_processo_epoch": 1000.0, "marcos_ms": {}},
        {"tipo": "js", "relatorio": {"timeOrigin": 1000.0 * 1000 + 600, "bloqueios": [[74.0, 48.5]]}},
    ]
    assert analisar_metricas.secao_bloqueios({"abcdef123": sessao}) == {"abcdef123": [(674.0, 48.5)]}
    assert "abcdef12: 674 (+48)" in capsys.readouterr().out
