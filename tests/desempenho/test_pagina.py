"""Desempenho da página num navegador real (Playwright), com rede simulada por padrão.

Usa o Microsoft Edge instalado (mesmo motor Chromium do WebView2). Mede:
- abertura: marcos da página em contexto novo (sem cache), várias vezes;
- ciclos: custo de cada atualização de preço com 100 alertas cadastrados, via
  métricas do DevTools (layouts, recálculos de estilo, tempo de script, heap) e
  pelas amostras do metricas.js;
- gráfico e tela de alertas: montar/desmontar o widget e abrir a tabela.

O gráfico abre oculto (atributo "hidden" de #grafico no index.html): a abertura e os
ciclos são medidos sem ele, como no uso padrão; o teste do gráfico o abre pelo ⇄.

Para acelerar, um script injetado divide por ACELERACAO toda espera de setTimeout
de 1 s ou mais. A lógica é a mesma; só as pausas entre ciclos ficam curtas.
Com BTC_REDE_REAL=1 a rede não é simulada (os tempos passam a incluir a internet).
"""

from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime

import pytest
from apoio_pagina import (  # noqa: F401 - navegador é fixture
    ACELERACAO,
    INDEX_URL,
    REDE_REAL,
    RedeSimulada,
    esperar_carregamento,
    estabilizar_websocket,
    metricas_devtools,
    navegador,
    nova_pagina,
    sync_api,
)
from conftest import PASTA_RESULTADOS, RAIZ

from metricas import estatisticas

pytestmark = pytest.mark.desempenho
ABERTURAS = int(os.getenv("BTC_DESEMPENHO_ABERTURAS", "5"))
CICLOS = int(os.getenv("BTC_DESEMPENHO_CICLOS", "200"))


def test_abertura(navegador, coletor):
    marcos_por_nome: dict[str, list[float]] = {}
    for _ in range(ABERTURAS):
        contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=True)
        pagina.goto(INDEX_URL)
        esperar_carregamento(pagina)
        # O gráfico abre oculto: a abertura termina no "load" (não há gráfico para esperar).
        pagina.wait_for_function("'nav_load' in Metricas.marcos", timeout=15000)
        marcos = pagina.evaluate("Metricas.marcos")
        assert not erros, erros
        contexto.close()
        assert "grafico_carregado" not in marcos, marcos  # nada do TradingView na abertura padrão
        for nome, valor in marcos.items():
            marcos_por_nome.setdefault(nome, []).append(valor)

    sufixo = " [rede real]" if REDE_REAL else ""
    for nome in ("nav_resposta_fim", "script_inicio", "primeiro_quadro", "first-contentful-paint", "dom_pronto", "nav_load", "conteudo_visivel",
                 "inicializacao_js_concluida", "primeira_resposta_binance", "primeiro_preco"):
        if nome in marcos_por_nome:
            coletor.registrar(f"página/abertura{sufixo}: {nome} (mediana)", statistics.median(marcos_por_nome[nome]))
    if not REDE_REAL:
        coletor.orcamento("página/abertura: primeiro_preco (mediana)", statistics.median(marcos_por_nome["primeiro_preco"]), 1500)


def test_ciclos_de_preco(navegador, coletor):
    rede = RedeSimulada()
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=True, com_alertas=True)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_timeout(1000)  # deixa a 1ª rodada assentar (o gráfico abre oculto)

    cdp = contexto.new_cdp_session(pagina)
    cdp.send("Performance.enable")
    antes = metricas_devtools(cdp)
    pagina.evaluate("Metricas.relatorio('descartar')")
    inicial = rede.contagem["binance"]
    prazo = time.monotonic() + max(120, CICLOS)
    while rede.contagem["binance"] < inicial + CICLOS and time.monotonic() < prazo:
        pagina.wait_for_timeout(100)
    ciclos = rede.contagem["binance"] - inicial
    relatorio = pagina.evaluate("Metricas.relatorio('teste')")
    depois = metricas_devtools(cdp)
    assert not erros, erros
    assert ciclos >= CICLOS * 0.9, f"só {ciclos} ciclos"
    contexto.close()

    def por_ciclo(nome: str, escala: float = 1.0) -> float:
        return (depois[nome] - antes[nome]) * escala / ciclos

    coletor.registrar("página/ciclo: quantidade medida", ciclos, "ciclos")
    coletor.orcamento("página/ciclo: layouts por ciclo", por_ciclo("LayoutCount"), 3, "layouts")
    # Sem orçamento: inclui quadros da animação da seta, distorcidos pela aceleração
    # (ver test_animacao_da_seta para a medida em tempo real).
    coletor.registrar("página/ciclo: recálculos de estilo por ciclo (acelerado)", por_ciclo("RecalcStyleCount"), "recálculos")
    coletor.registrar("página/ciclo: tempo de layout por ciclo", por_ciclo("LayoutDuration", 1000))
    coletor.registrar("página/ciclo: tempo de estilo por ciclo", por_ciclo("RecalcStyleDuration", 1000))
    coletor.registrar("página/ciclo: tempo de script por ciclo", por_ciclo("ScriptDuration", 1000))
    coletor.orcamento("página/ciclo: tempo total de tarefas por ciclo", por_ciclo("TaskDuration", 1000), 10)
    coletor.orcamento("página/ciclo: crescimento do heap (após GC)", (depois["JSHeapUsedSize"] - antes["JSHeapUsedSize"]) / 1048576, 5, "MB")
    coletor.orcamento("página/ciclo: nós DOM criados e mantidos", depois["Nodes"] - antes["Nodes"], 200, "nós")
    coletor.orcamento("página/ciclo: tarefas longas (> 50 ms)", len(relatorio["tarefasLongas"]), 2, "tarefas")

    amostras = relatorio["amostras"]
    for nome, limite in (("render:brl", 5), ("processamento:precos", 10), ("alarmes:checar", 1)):
        est = estatisticas(amostras.get(nome, []))
        if est["n"]:
            coletor.registrar(f"página/ciclo: {nome} p50 (100 alertas)", est["p50"])
            coletor.orcamento(f"página/ciclo: {nome} p95 (100 alertas)", est["p95"], limite)


def test_mensagens_do_websocket(navegador, coletor):
    """Custo de cada atualização pelo WebSocket (o caminho principal desde o B4), com 100 alertas.

    O preço muda a cada mensagem (pior caso: a seta anima sempre).
    """
    rede = RedeSimulada()
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=True, com_alertas=True)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    estabilizar_websocket(rede, pagina)  # conexão saudável antes de medir

    cdp = contexto.new_cdp_session(pagina)
    cdp.send("Performance.enable")
    antes = metricas_devtools(cdp)
    pagina.evaluate("Metricas.relatorio('descartar')")
    rest_antes = rede.contagem["binance"]
    mensagens = 200
    for indice in range(mensagens):
        preco = 500_000 + (indice % 2) * 100  # sobe e desce: a seta muda sempre
        rede.enviar_ticker("BTCBRL", preco)
        rede.enviar_ticker("BTCUSDT", preco / 5)
        pagina.wait_for_timeout(30)  # bem abaixo da vigia de silêncio acelerada (200 ms)
    assert pagina.evaluate("wsSaudavel"), "a conexão caiu durante a medição"
    pagina.wait_for_timeout(100)  # termina o último quadro (abaixo da vigia)
    relatorio = pagina.evaluate("Metricas.relatorio('teste')")
    depois = metricas_devtools(cdp)
    assert not erros, erros
    contexto.close()

    def por_par(nome: str, escala: float = 1.0) -> float:
        return (depois[nome] - antes[nome]) * escala / mensagens

    coletor.registrar("página/ws: consultas REST durante as mensagens", rede.contagem["binance"] - rest_antes, "consultas")
    coletor.orcamento("página/ws: layouts por par BRL+USDT", por_par("LayoutCount"), 3, "layouts")
    coletor.registrar("página/ws: tempo de script por par", por_par("ScriptDuration", 1000))
    coletor.orcamento("página/ws: tempo total de tarefas por par", por_par("TaskDuration", 1000), 10)
    coletor.orcamento("página/ws: crescimento do heap (após GC)", (depois["JSHeapUsedSize"] - antes["JSHeapUsedSize"]) / 1048576, 5, "MB")
    coletor.orcamento("página/ws: nós DOM criados e mantidos", depois["Nodes"] - antes["Nodes"], 200, "nós")
    coletor.orcamento("página/ws: tarefas longas (> 50 ms)", len(relatorio["tarefasLongas"]), 2, "tarefas")
    est = estatisticas(relatorio["amostras"].get("processamento:ws", []))
    coletor.registrar("página/ws: processamento por mensagem p50", est["p50"])
    coletor.orcamento("página/ws: processamento por mensagem p95", est["p95"], 5)


def test_animacao_da_seta(navegador, coletor):
    """Custo de UMA atualização de preço em tempo real, incluindo 1 s de animação da seta.

    Com o monitoramento pausado (sem ciclos nem gráfico), compara 1,5 s ocioso com
    1,5 s após uma chamada a exibirBRL.
    """
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.click("#pausar-btn")
    pagina.wait_for_timeout(1500)
    cdp = contexto.new_cdp_session(pagina)
    cdp.send("Performance.enable")

    def janela(acao: str | None) -> dict[str, float]:
        antes = metricas_devtools(cdp)
        if acao:
            pagina.evaluate(acao)
        pagina.wait_for_timeout(1500)
        depois = metricas_devtools(cdp)
        return {nome: depois[nome] - antes[nome] for nome in ("RecalcStyleCount", "LayoutCount", "TaskDuration")}

    ocioso = janela(None)
    atualizacao = janela("exibirBRL({ preco: 512345.67, variacao: 1.5, maxima: 520000, minima: 500000 })")
    assert not erros, erros
    contexto.close()

    coletor.registrar("página/seta: recálculos de estilo por atualização", atualizacao["RecalcStyleCount"] - ocioso["RecalcStyleCount"], "recálculos")
    coletor.registrar("página/seta: layouts por atualização", atualizacao["LayoutCount"] - ocioso["LayoutCount"], "layouts")
    coletor.registrar("página/seta: tempo de tarefas por atualização", (atualizacao["TaskDuration"] - ocioso["TaskDuration"]) * 1000)


def clicar_e_confirmar_fechamento(pagina) -> None:
    """Clica em Voltar e confirma que a tela fechou; se não fechar, registra o porquê.

    Uma execução falhou aqui sem causa aparente. Em vez de repetir o clique (o que
    esconderia um bug real), a falha guarda qual elemento estava sob o ponto do
    clique e uma captura de tela.
    """
    caixa = pagina.locator("#voltarBotao").bounding_box()
    pagina.click("#voltarBotao")
    try:
        pagina.wait_for_function("document.getElementById('modalAlerta').style.display === 'none'", timeout=2000)
    except sync_api.TimeoutError:
        x, y = caixa["x"] + caixa["width"] / 2, caixa["y"] + caixa["height"] / 2
        alvo = pagina.evaluate("([x, y]) => document.elementFromPoint(x, y)?.outerHTML.slice(0, 200) ?? null", [x, y])
        PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
        captura = PASTA_RESULTADOS / f"falha-voltar-{datetime.now():%Y%m%d-%H%M%S}.png"
        pagina.screenshot(path=str(captura))
        pytest.fail(f"Voltar não fechou a tela de alertas. Elemento em ({x:.0f}, {y:.0f}): {alvo}. Captura: {captura}")


def test_grafico_e_tela_de_alertas(navegador, coletor):
    rede = RedeSimulada()
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=True, com_alertas=True)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.click("#grafico-btn")  # o gráfico abre oculto: mostra antes de medir
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null")
    pagina.wait_for_timeout(500)
    cdp = contexto.new_cdp_session(pagina)
    cdp.send("Performance.enable")
    antes = metricas_devtools(cdp)
    pagina.evaluate("Metricas.relatorio('descartar')")

    for _ in range(10):  # pausar desmonta o gráfico; retomar monta de novo
        pagina.click("#pausar-btn")
        assert pagina.evaluate("document.getElementById('grafico').childElementCount") == 0
        pagina.click("#overlay")
        pagina.wait_for_function("document.querySelector('#grafico iframe') !== null")
    for _ in range(10):  # tabela com 100 alertas: campo e botões precisam caber na janela
        pagina.click("#alerta-btn")
        for seletor in ("#valorAlerta", "#salvarBotao", "#voltarBotao"):
            caixa = pagina.locator(seletor).bounding_box()
            assert caixa and caixa["y"] >= 0 and caixa["y"] + caixa["height"] <= 810, (seletor, caixa)
        assert pagina.evaluate("(() => { const l = document.getElementById('listaAlertas');"
                               " return l.scrollHeight > l.clientHeight; })()"), "a lista deveria rolar"
        clicar_e_confirmar_fechamento(pagina)

    pagina.wait_for_timeout(500)
    relatorio = pagina.evaluate("Metricas.relatorio('teste')")
    depois = metricas_devtools(cdp)
    assert not erros, erros
    contexto.close()

    amostras = relatorio["amostras"]
    for nome, limite in (("grafico:montar", 20), ("render:tabela_alertas", 30)):
        est = estatisticas(amostras.get(nome, []))
        coletor.registrar(f"página/{nome} p50", est["p50"])
        coletor.orcamento(f"página/{nome} p95", est["p95"], limite)
    carga = estatisticas(amostras.get("grafico:montagem_ate_carga", []))
    if carga["n"]:
        coletor.registrar("página/grafico: montagem até carga p50 (widget simulado)", carga["p50"])
    coletor.orcamento("página/10 pausas + 10 aberturas da tabela: crescimento do heap",
                      (depois["JSHeapUsedSize"] - antes["JSHeapUsedSize"]) / 1048576, 3, "MB")


def test_relatorio_da_pagina_chega_ao_python(navegador, tmp_path):
    """Integração: o relatório real do metricas.js passa pela validação do Python e pela análise.

    Simula a ponte do pywebview (window.pywebview.api) com funções Python expostas.
    """
    import sys

    sys.path.insert(0, str(RAIZ / "tools"))
    import analisar_metricas
    from metricas import NOME_ARQUIVO, RegistroMetricas, validar_relatorio_js

    registro = RegistroMetricas(tmp_path, time.perf_counter(), time.time(), sessao="integracao")
    registro.marcar("imports_concluidos")
    registro.gravar_abertura_python()
    recebidos: list[dict] = []

    def registrar(relatorio: dict) -> bool:
        validar_relatorio_js(relatorio)
        recebidos.append(relatorio)
        return registro.gravar("js", {"relatorio": relatorio})

    rede = RedeSimulada()
    contexto = navegador.new_context(user_agent="Mozilla/5.0 pywebview", viewport={"width": 500, "height": 810})
    rede.instalar(contexto)
    contexto.expose_function("__registrarMetricas", registrar)
    contexto.add_init_script("""
        window.pywebview = { api: {
            carregar_alerta: async () => [],
            salvar_alerta: async () => true,
            esta_no_topo: async () => false,
            registrar_metricas: relatorio => window.__registrarMetricas(relatorio),
        } };
    """)
    pagina = contexto.new_page()
    erros: list[str] = []
    pagina.on("pageerror", lambda erro: erros.append(str(erro)))
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    prazo = time.monotonic() + 20
    while not recebidos and time.monotonic() < prazo:
        pagina.wait_for_timeout(100)
    contexto.close()

    assert not erros, erros
    assert recebidos and recebidos[0]["motivo"] == "abertura"
    marcos = recebidos[0]["marcos"]
    # O gráfico abre oculto: a abertura termina com os alertas lidos (sem grafico_carregado).
    for nome in ("script_inicio", "dom_pronto", "api_python_pronta", "alertas_sincronizados", "primeiro_preco"):
        assert nome in marcos, nome
    assert "python:carregar_alerta" in recebidos[0]["amostras"]

    resumo_json = tmp_path / "resumo.json"
    assert analisar_metricas.main(["--arquivo", str(tmp_path / NOME_ARQUIVO), "--json", str(resumo_json)]) == 0
    abertura = json.loads(resumo_json.read_text(encoding="utf-8"))["abertura"]
    assert "primeiro_preco" in abertura and "imports_concluidos" in abertura
