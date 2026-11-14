"""Testes funcionais da página num navegador real (Playwright, rede simulada).

Rodam no "python -m pytest tests" padrão e são pulados se o Playwright ou um
navegador Chromium (Edge/Chrome) não estiver disponível.
"""

from __future__ import annotations

import pytest

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
RAIZ_PROJETO = Path(__file__).resolve().parent.parent

from apoio_pagina import (  # noqa: E402,F401 - navegador é fixture
    INDEX_URL,
    RedeSimulada,
    esperar_carregamento,
    estabilizar_websocket,
    navegador,
    nova_pagina,
)

ESTADO_SALVO = {
    "versao": 1,
    "salvoEm": 1_794_000_000_000,
    "brl": {"preco": 432_100.0, "variacao": -2.5, "maxima": 440_000.0, "minima": 430_000.0},
    "usdt": {"preco": 86_000.0, "variacao": -2.4, "maxima": 87_000.0, "minima": 85_500.0},
    "dolar": 5.02,
    "taxas": {"fastestFee": 9.87, "halfHourFee": 6.54, "hourFee": 3.21, "minimumFee": 1.0},
}
# Dispararia com o preço salvo (432.100 >= 100), mas não com nada (o preço novo é segurado).
ALERTA_QUE_DISPARARIA = [{"id": "a", "valor": 100, "tipo": "maior"}]
ALERTA_ATIVO_DISTANTE = [{"id": "a", "valor": 1000, "tipo": "menor"}]
SO_DESATIVADOS = [{"id": "a", "valor": 1000, "tipo": "desativado"}]

# Guarda os relatórios enviados: cada relatório zera os contadores do Metricas, e o de
# abertura (gráfico oculto) é montado logo depois da ponte. Ver contadores() e marcos_da_pagina().
PYWEBVIEW_TARDIO = """
window.__relatorios = [];
window.addEventListener('load', () => setTimeout(() => {
    window.pywebview = { api: {
        carregar_alerta: async () => [],
        salvar_alerta: async () => true,
        esta_no_topo: async () => false,
        registrar_metricas: async relatorio => { window.__relatorios.push(relatorio); return true; },
    } };
    window.dispatchEvent(new Event('pywebviewready'));
}, 300));
"""


# O gráfico começa oculto (atributo "hidden" de #grafico no index.html). Os testes da
# abertura COM o gráfico tiram o atributo antes de o script.js lê-lo: o listener do init
# script é registrado antes do script.js e roda primeiro no DOMContentLoaded.
MOSTRAR_GRAFICO_AO_ABRIR = """
document.addEventListener('DOMContentLoaded', () => {
    // O init script roda em todos os frames (inclusive no iframe do TradingView, sem #grafico).
    const grafico = document.getElementById('grafico');
    if (grafico) grafico.hidden = false;
});
"""


def com_grafico_ao_abrir(contexto) -> None:
    contexto.add_init_script(MOSTRAR_GRAFICO_AO_ABRIR)


def com_estado_salvo(contexto, estado: dict = ESTADO_SALVO) -> None:
    contexto.add_init_script(f"localStorage.setItem('ultimoEstado', {json.dumps(json.dumps(estado))});")


def texto(pagina, seletor: str) -> str:
    return pagina.locator(seletor).text_content().replace("\xa0", " ")


def test_estado_salvo_aparece_antes_da_rede_e_nao_dispara_alarme(navegador):
    rede = RedeSimulada()
    rede.segurar_binance = True
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=False, com_alertas=ALERTA_QUE_DISPARARIA)
    com_estado_salvo(contexto)
    # Taxas e dólar também ficam sem resposta: a tela mostra só o que foi salvo.
    # (A rota registrada por último tem precedência.)
    pendentes: list = []
    contexto.route("https://mempool.space/**", lambda rota: pendentes.append(rota))
    contexto.route("https://economia.awesomeapi.com.br/**", lambda rota: pendentes.append(rota))
    pagina.goto(INDEX_URL)

    # A tela sai do carregamento sem nenhuma resposta da rede.
    esperar_carregamento(pagina, timeout_ms=5000)
    assert texto(pagina, "#info-price") == "R$ 432.100,00"
    assert "desatualizado" in pagina.get_attribute("#info-price", "class")
    assert texto(pagina, "#info-time").startswith("atualizando… (salvo em")
    assert texto(pagina, "#highPrice") == "R$ 440.000,00"
    assert texto(pagina, "#info-usdt") == "US$ 86.000,00"
    assert texto(pagina, "#fastestFee") == "9,87 sat/vB"
    assert texto(pagina, "#info-dolar") == "R$ 5,02 | R$ 5,02"  # 432.100 / 86.000 ≈ 5,02
    assert pagina.evaluate("'estado_restaurado' in Metricas.marcos && !('primeiro_preco' in Metricas.marcos)")

    # O preço salvo nunca entra nos alarmes.
    assert pagina.evaluate("Number.isNaN(ultimoPrecoBRL)")
    pagina.evaluate("alarmesSilenciados = false; checarAlarmes()")
    assert pagina.evaluate("document.getElementById('dialogo').open") is False

    # Chega o preço novo: some o esmaecimento e o estado é regravado.
    rede.liberar_binance()
    pagina.wait_for_function("!document.getElementById('info-price').classList.contains('desatualizado')")
    assert texto(pagina, "#info-price") != "R$ 432.100,00"
    assert not texto(pagina, "#info-time").startswith("atualizando")
    salvo = json.loads(pagina.evaluate("localStorage.getItem('ultimoEstado')"))
    assert salvo["brl"]["preco"] != ESTADO_SALVO["brl"]["preco"] and salvo["salvoEm"] > ESTADO_SALVO["salvoEm"]
    assert not erros, erros
    contexto.close()


def test_estado_salvo_resiste_a_falhas_e_depois_vira_sem_dados(navegador):
    rede = RedeSimulada()
    rede.falhar_binance = True
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=True, com_alertas=False)
    com_estado_salvo(contexto)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("falhasBRL >= 1")
    assert texto(pagina, "#info-price") == "R$ 432.100,00"  # 1ª falha: mantém o salvo
    pagina.wait_for_function("falhasBRL >= 3")
    assert texto(pagina, "#info-price") == "▶Sem Dados◀"
    assert "desatualizado" not in (pagina.get_attribute("#info-price", "class") or "")
    assert not erros, erros
    contexto.close()


def test_sem_estado_salvo_continua_esperando_a_rede(navegador):
    rede = RedeSimulada()
    rede.segurar_binance = True
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=False, com_alertas=False)
    pagina.goto(INDEX_URL)
    pagina.wait_for_timeout(500)
    assert pagina.is_visible("#tela-carregamento")
    rede.liberar_binance()
    esperar_carregamento(pagina)
    assert not erros, erros
    contexto.close()


def _inatividade(navegador, alertas: list) -> bool:
    """Avança o relógio da página além do limite de inatividade e diz se o monitoramento continua ativo."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=alertas)
    pagina.clock.install()
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.clock.fast_forward(1_001_000)  # LIMITE_INATIVIDADE = 1.000 s
    pagina.clock.run_for(2000)            # deixa o verificador (a cada 1 s) rodar
    ativo = pagina.evaluate("ativo")
    assert not erros, erros
    contexto.close()
    return ativo


def test_inatividade_nao_pausa_com_alerta_ativo(navegador):
    assert _inatividade(navegador, ALERTA_ATIVO_DISTANTE) is True


def test_inatividade_pausa_sem_alerta_ativo(navegador):
    assert _inatividade(navegador, SO_DESATIVADOS) is False


@pytest.mark.parametrize("evento", ["new MouseEvent('mousemove')", "new PointerEvent('pointerdown')"])
def test_apos_um_alarme_a_inatividade_espera_nova_atividade(navegador, evento):
    """Disparou um alarme e o usuário não voltou: não pausa por inatividade, nem depois de
    o alarme fechar (o alerta vira desativado). Só conta ~17 min a partir da próxima atividade;
    um clique sem mover o mouse também conta."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False,
                                          com_alertas=ALERTA_QUE_DISPARARIA)
    pagina.clock.install()
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    for _ in range(20):  # silêncio inicial (5 s) + checagem (1 s)
        if pagina.evaluate("document.getElementById('dialogo').open"):
            break
        pagina.clock.run_for(1000)
    assert pagina.evaluate("alertaAberto"), "o alarme não disparou"
    # Fecha sem nenhum evento de usuário: o alerta vira desativado.
    pagina.evaluate("document.getElementById('dialogo').close()")
    for _ in range(50):  # o evento "close" do <dialog> chega numa tarefa à parte
        if pagina.evaluate("!existeAlertaAtivo(alertas)"):
            break
        pagina.clock.run_for(100)
        pagina.wait_for_timeout(20)
    assert pagina.evaluate("!existeAlertaAtivo(alertas)")

    pagina.clock.fast_forward(1_001_000)  # LIMITE_INATIVIDADE = 1.000 s
    pagina.clock.run_for(2000)
    assert pagina.evaluate("ativo") is True  # sem atividade depois do alarme: não pausa

    pagina.evaluate(f"document.dispatchEvent({evento})")
    pagina.clock.fast_forward(500_000)
    pagina.clock.run_for(2000)
    assert pagina.evaluate("ativo") is True  # ainda dentro dos ~17 min após a atividade
    pagina.clock.fast_forward(501_000)
    pagina.clock.run_for(2000)
    assert pagina.evaluate("ativo") is False  # ~17 min depois da atividade: pausa
    contexto.close()


@pytest.mark.parametrize(("alertas", "continua"), [(SO_DESATIVADOS, True), (ALERTA_ATIVO_DISTANTE, True), (False, False)])
def test_falhas_seguidas_so_pausam_sem_alertas_cadastrados(navegador, alertas, continua):
    """Com qualquer alerta cadastrado, MAX_FALHAS não pausa: o preço vira "Sem Dados" e o ciclo
    segue tentando, para os alertas voltarem a valer quando a internet voltar."""
    rede = RedeSimulada()
    rede.falhar_binance = True
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=True, com_alertas=alertas)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    if continua:
        pagina.wait_for_function("falhasBRL >= 13", timeout=20000)  # passou de MAX_FALHAS (10)
        assert pagina.evaluate("ativo") is True
        assert texto(pagina, "#info-price") == "▶Sem Dados◀"
        assert pagina.evaluate("getComputedStyle(document.getElementById('overlay')).display") == "none"
        rede.falhar_binance = False  # a internet volta: o preço volta sem nenhum clique
        pagina.wait_for_function("falhasBRL === 0 && Number.isFinite(ultimoPrecoBRL)", timeout=10000)
    else:
        pagina.wait_for_function("!ativo", timeout=20000)
        assert pagina.evaluate("falhasBRL") >= 10 and pagina.evaluate("pausaManual") is True
    contexto.close()


def test_grafico_espera_a_ponte_do_python(navegador):
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script(PYWEBVIEW_TARDIO)
    com_grafico_ao_abrir(contexto)
    pagina.goto(INDEX_URL)
    pagina.wait_for_function("'nav_load' in Metricas.marcos")
    assert pagina.evaluate("document.getElementById('grafico').childElementCount") == 0  # a ponte vem 300 ms depois
    pagina.wait_for_function("'grafico_carregado' in Metricas.marcos", timeout=10000)
    marcos = pagina.evaluate("Metricas.marcos")
    assert marcos["nav_load"] < marcos["api_python_pronta"] < marcos["grafico_carregado"], marcos
    assert not erros, erros
    contexto.close()


def test_grafico_aparece_mesmo_sem_ponte_do_python(navegador):
    # Sem a ponte, o gráfico é montado ao fim do prazo da API (5 s, acelerado aqui).
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=True, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    com_grafico_ao_abrir(contexto)
    pagina.goto(INDEX_URL)
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)
    assert not erros, erros
    contexto.close()


def test_grafico_comeca_oculto_e_nada_do_tradingview_e_carregado(navegador):
    """Padrão do index.html: o gráfico abre oculto e o TradingView só é pedido ao clicar em ⇄."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script(PYWEBVIEW_TARDIO)
    pedidos: list[str] = []
    pagina.on("request", lambda pedido: pedidos.append(pedido.url))
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("'api_python_pronta' in Metricas.marcos")  # quando o gráfico seria montado
    pagina.wait_for_timeout(1000)
    assert pagina.evaluate("document.getElementById('grafico').childElementCount") == 0
    assert pagina.evaluate("getComputedStyle(document.getElementById('grafico')).display") == "none"
    assert pagina.evaluate("document.getElementById('grafico').hidden") is True
    assert not any("tradingview" in url for url in pedidos), pedidos
    pagina.click("#grafico-btn")
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)
    assert pagina.evaluate("document.getElementById('grafico').hidden") is False
    assert not erros, erros
    contexto.close()


# ---------------------------------------------------------------------------
# WebSocket da Binance (timers acelerados 50x: vigia de silêncio de 10 s -> 200 ms)
# ---------------------------------------------------------------------------

def esperar(condicao, pagina, limite_s: float = 5.0) -> None:
    prazo = time.monotonic() + limite_s
    while not condicao():
        assert time.monotonic() < prazo, "tempo esgotado esperando a condição"
        pagina.wait_for_timeout(20)


def manter_vivo(rede: RedeSimulada, pagina, preco: float, vezes: int, intervalo_ms: int = 60) -> None:
    """Envia BTC/BRL e BTC/USDT várias vezes, mais rápido que a vigia de silêncio."""
    for _ in range(vezes):
        rede.enviar_ticker("BTCBRL", preco)
        rede.enviar_ticker("BTCUSDT", preco / 5)
        pagina.wait_for_timeout(intervalo_ms)


def contador(pagina, nome: str) -> int:
    return pagina.evaluate(f"Metricas.resumo().contadores['{nome}'] ?? 0")


def pagina_com_websocket(navegador, alertas=False):
    rede = RedeSimulada()
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=True, com_alertas=alertas)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    estabilizar_websocket(rede, pagina)
    return rede, contexto, pagina, erros


def test_websocket_atualiza_o_preco_e_para_o_polling(navegador):
    rede, contexto, pagina, erros = pagina_com_websocket(navegador)
    manter_vivo(rede, pagina, 600_000, 3)
    assert texto(pagina, "#info-price") == "R$ 600.000,00"
    assert pagina.evaluate("wsSaudavel")

    rest_antes = rede.contagem["binance"]
    manter_vivo(rede, pagina, 600_100, 15)  # ~0,9 s: o REST acelerado faria ~10 consultas
    assert rede.contagem["binance"] - rest_antes <= 1, "o polling REST deveria ter parado"
    assert texto(pagina, "#info-price") == "R$ 600.100,00"
    assert texto(pagina, "#info-usdt") == "US$ 120.020,00"
    # Preço repetido não muda a seta: continua mostrando a última mudança (subiu).
    assert pagina.locator("#info-seta").text_content().strip() == "↑"
    assert not erros, erros
    contexto.close()


def test_queda_do_websocket_volta_ao_rest_e_reconecta(navegador):
    rede, contexto, pagina, erros = pagina_com_websocket(navegador)
    manter_vivo(rede, pagina, 600_000, 3)
    rest_antes, conexoes_antes = rede.contagem["binance"], rede.contagem["ws"]

    rede.fechar_socket()
    esperar(lambda: rede.contagem["binance"] >= rest_antes + 2, pagina)  # REST de volta
    esperar(lambda: rede.contagem["ws"] > conexoes_antes, pagina)       # nova tentativa
    assert not pagina.evaluate("wsSaudavel")

    manter_vivo(rede, pagina, 610_000, 3)  # a nova conexão recebe: o REST para de novo
    assert pagina.evaluate("wsSaudavel")
    assert texto(pagina, "#info-price") == "R$ 610.000,00"
    assert not erros, erros
    contexto.close()


def test_websocket_em_silencio_e_trocado_pelo_rest(navegador):
    rede, contexto, pagina, erros = pagina_com_websocket(navegador)
    manter_vivo(rede, pagina, 600_000, 3)
    rest_antes = rede.contagem["binance"]
    pagina.wait_for_timeout(600)  # nenhuma mensagem: a vigia (200 ms acelerados) dispara
    assert not pagina.evaluate("wsSaudavel")
    assert contador(pagina, "ws:queda:silencio") >= 1, "o app deveria fechar a conexão muda"
    esperar(lambda: rede.contagem["binance"] > rest_antes, pagina)
    assert not erros, erros
    contexto.close()


def test_pausa_fecha_o_websocket_e_retomar_reabre(navegador):
    rede, contexto, pagina, erros = pagina_com_websocket(navegador)
    manter_vivo(rede, pagina, 600_000, 2)
    pagina.click("#pausar-btn")
    assert pagina.evaluate("ws === null"), "pausar deveria fechar a conexão"
    conexoes, rest = rede.contagem["ws"], rede.contagem["binance"]
    pagina.wait_for_timeout(500)
    assert (rede.contagem["ws"], rede.contagem["binance"]) == (conexoes, rest), "nada de rede durante a pausa"
    pagina.click("#overlay")
    esperar(lambda: rede.contagem["ws"] > conexoes, pagina)
    assert not erros, erros
    contexto.close()


def test_alarme_dispara_pelo_websocket(navegador):
    alerta = [{"id": "a", "valor": 550_000, "tipo": "maior"}]  # o REST simulado fica perto de 500 mil
    rede, contexto, pagina, erros = pagina_com_websocket(navegador, alertas=alerta)
    # Passa o silêncio após carregar (5 s acelerados) com a conexão viva e preço abaixo do alerta.
    manter_vivo(rede, pagina, 500_000, 6)
    assert pagina.evaluate("wsSaudavel")
    assert pagina.evaluate("document.getElementById('dialogo').open") is False
    manter_vivo(rede, pagina, 560_000, 3)
    pagina.wait_for_function("document.getElementById('dialogo').open", timeout=3000)
    assert "R$ 550.000,00" in texto(pagina, "#dialogo-conteudo")
    assert not erros, erros
    contexto.close()


def test_brl_em_silencio_com_usdt_vivo_nao_derruba_a_conexao(navegador):
    """O BTC/BRL pode ficar 5-16 s sem mudar (a Binance só envia o que muda); o USDT chega a cada ~1 s."""
    rede, contexto, pagina, erros = pagina_com_websocket(navegador)
    manter_vivo(rede, pagina, 600_000, 2)
    rest_antes, conexoes_antes = rede.contagem["binance"], rede.contagem["ws"]
    for _ in range(12):  # ~0,7 s só de USDT: mais de 3x a vigia acelerada (200 ms)
        rede.enviar_ticker("BTCUSDT", 120_000)
        pagina.wait_for_timeout(60)
    assert pagina.evaluate("wsSaudavel")
    assert contador(pagina, "ws:queda:silencio") == 0
    assert (rede.contagem["ws"], rede.contagem["binance"]) == (conexoes_antes, rest_antes)
    assert texto(pagina, "#info-price") == "R$ 600.000,00"  # o último BRL continua valendo
    assert not erros, erros
    contexto.close()


def test_preload_da_fonte_e_aproveitado(navegador):
    """Com file://, o preload só é aproveitado SEM "crossorigin"; senão o Chromium avisa e lê a fonte duas vezes."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False)
    avisos: list[str] = []
    pagina.on("console", lambda msg: avisos.append(msg.text) if "preload" in msg.text.lower() else None)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("[...document.fonts].some(f => f.family === 'Roboto' && f.status === 'loaded')")
    pagina.wait_for_timeout(300)
    assert avisos == [], avisos
    assert not erros, erros
    contexto.close()


@pytest.mark.parametrize("ajustar_preload,leituras", [(True, 1), (False, 2)])
def test_preload_da_fonte_pelo_servidor_local(navegador, ajustar_preload, leituras):
    """Por http (o app), o preload só é aproveitado COM "crossorigin", que o servidor local
    acrescenta. Sem o ajuste, a fonte é lida duas vezes (o caso de controle confirma que o
    teste enxerga o problema). As leituras vêm do metricas.js (recurso_n:<arquivo>)."""
    from apoio_pagina import ServidorDaPagina

    class SemPreco:
        def resultado(self, espera_s):
            return None

    servidor = ServidorDaPagina(SemPreco(), ajustar_preload=ajustar_preload)
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script(CAPTURAR_RELATORIOS)  # o relatório de abertura zera os contadores
    avisos: list[str] = []
    pagina.on("console", lambda msg: avisos.append(msg.text) if "preload" in msg.text.lower() else None)
    pagina.goto(servidor.url)
    esperar_carregamento(pagina)
    pagina.wait_for_function("[...document.fonts].some(f => f.family === 'Roboto' && f.status === 'loaded')")
    pagina.wait_for_timeout(500)
    resumo = pagina.evaluate("Metricas.resumo()")
    leituras_fonte = pagina.evaluate("""() => [...window.__relatorios.map(r => r.contadores), Metricas.resumo().contadores]
        .reduce((soma, c) => soma + (c['recurso_n:Roboto.woff2'] ?? 0), 0)""")
    assert leituras_fonte == leituras
    assert (avisos == []) == ajustar_preload, avisos
    # Marcos de cada arquivo da página (para ver o que segura o "load").
    for arquivo in ("style.css", "script.js", "Roboto.woff2"):
        assert resumo["marcos"][f"recurso_inicio:{arquivo}"] <= resumo["marcos"][f"recurso:{arquivo}"]
    assert not erros, erros
    contexto.close()
    servidor.fechar()


def test_pagina_de_producao_funciona_com_o_substituto_vazio(navegador, tmp_path):
    """Como no .exe de produção: metricas.js é o metricas_desligadas.js."""
    import shutil

    for arquivo in ("index.html", "regras.js", "script.js", "style.css", "Roboto.woff2", "btc-logo.svg", "alerta.mp3"):
        shutil.copy(RAIZ_PROJETO / arquivo, tmp_path / arquivo)
    shutil.copy(RAIZ_PROJETO / "metricas_desligadas.js", tmp_path / "metricas.js")

    rede = RedeSimulada()
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=True, com_alertas=ALERTA_ATIVO_DISTANTE,
                                          user_agent="Mozilla/5.0 pywebview")
    chamadas: list[str] = []
    contexto.expose_function("__chamada", lambda nome: chamadas.append(nome))
    contexto.add_init_script("""
        // "then" fica de fora: senão o objeto vira um "thenable" e as Promises nunca resolvem.
        window.pywebview = { api: new Proxy({}, { get: (_, nome) => nome === 'then' ? undefined : async () => {
            window.__chamada(String(nome));
            return nome === 'carregar_alerta' ? [] : (nome === 'esta_no_topo' ? false : true);
        } }) };
    """)
    com_grafico_ao_abrir(contexto)
    pagina.goto((tmp_path / "index.html").as_uri())
    esperar_carregamento(pagina)
    estabilizar_websocket(rede, pagina, 600_000)
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)
    pagina.evaluate("reiniciar = () => {}")  # evita recarregar a página no meio do teste
    assert pagina.evaluate("Metricas.ATIVAS") is False
    assert texto(pagina, "#info-price") == "R$ 600.000,00"
    pagina.evaluate("fecharJanela()")  # no app isso enviaria o relatório de encerramento
    pagina.wait_for_timeout(200)
    assert "registrar_metricas" not in chamadas, chamadas
    assert "fechar" in chamadas
    assert not erros, erros
    contexto.close()


def test_navegador_mostra_e_oculta_o_grafico(navegador):
    """No navegador aparecem Alertas, Gráfico (⇄), Modo compacto e Pausar, sem sobreposição; o
    gráfico abre oculto e ⇄ o mostra e o oculta."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    visiveis = pagina.evaluate("[...document.querySelectorAll('.btns')].filter(b => getComputedStyle(b).display !== 'none').map(b => b.id)")
    assert sorted(visiveis) == ["alerta-btn", "compacto-btn", "grafico-btn", "pausar-btn"]
    caixas = [pagina.locator(f"#{id_}").bounding_box() for id_ in ("alerta-btn", "grafico-btn", "compacto-btn", "pausar-btn")]
    for esquerda, direita in zip(caixas, caixas[1:]):
        assert esquerda["x"] + esquerda["width"] <= direita["x"], caixas  # lado a lado, sem sobrepor

    pagina.wait_for_function("'nav_load' in Metricas.marcos")
    pagina.wait_for_timeout(500)  # passa o momento em que o gráfico seria montado
    assert pagina.evaluate("document.getElementById('grafico').childElementCount") == 0
    assert pagina.evaluate("getComputedStyle(document.getElementById('grafico')).display") == "none"
    pagina.click("#grafico-btn")
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)
    pagina.click("#grafico-btn")
    assert pagina.evaluate("document.getElementById('grafico').childElementCount") == 0
    assert pagina.evaluate("getComputedStyle(document.getElementById('grafico')).display") == "none"
    pagina.click("#grafico-btn")
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)
    assert not erros, erros
    contexto.close()


GEOMETRIA = """() => {
    const caixa = s => document.querySelector(s).getBoundingClientRect();
    const t = caixa('.bottom-left-info table'), q = caixa('#grafico'), g = caixa('#grafico iframe'), d = caixa('#info-time'), s = caixa('.bottom-left-info .separator');
    return { tabela: [t.left, t.top, t.right, t.bottom], quadro: [q.left, q.top, q.right, q.bottom],
             grafico: [g.left, g.top, g.right, g.bottom], data: d.bottom, separador: s.top, fundo: getComputedStyle(document.getElementById('grafico')).backgroundColor };
}"""


def conferir_cobertura(medida, altura_janela):
    """O quadro opaco e o widget cobrem a tabela inteira, sem tapar a data/hora nem passar do fim da janela."""
    (tl, tt, tr, tb) = medida["tabela"]
    for nome in ("quadro", "grafico"):
        (gl, gt, gr, gb) = medida[nome]
        assert gl <= tl and gr >= tr, (nome, medida)            # nenhuma borda lateral à mostra
        # Nem em cima nem embaixo (a parte da tabela abaixo do fim da janela já não aparece).
        assert abs(gt - medida["separador"]) <= 1, (nome, medida)  # borda de cima sobre a linha separadora
        assert gb >= min(tb, altura_janela), (nome, medida)
        assert tl - gl <= 4 and gr - tr <= 4, (nome, medida)    # sobra pequena nas laterais
        assert gt >= medida["data"] and gb <= altura_janela, (nome, medida)  # data e hora à mostra
    assert medida["fundo"] == "rgb(0, 0, 0)", medida


def test_grafico_na_janela_do_app_fica_como_sempre(navegador):
    """Aberto pelo ⇄ (o padrão é oculto), o gráfico fica na mesma posição de sempre."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.click("#grafico-btn")
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)
    medida = pagina.evaluate(GEOMETRIA)
    assert medida["quadro"] == [24, 449, 476, 767], medida  # 500x810: sobre a linha separadora
    conferir_cobertura(medida, 810)
    assert not erros, erros
    contexto.close()


@pytest.mark.parametrize("largura,altura", [(617, 931), (1280, 720), (900, 1000), (420, 700), (1600, 900)])
def test_grafico_cobre_a_tabela_em_varios_tamanhos(navegador, largura, altura):
    """No navegador o gráfico cobre a tabela de máx./mín./taxas por inteiro, em qualquer proporção.

    O gráfico é montado antes do 1º preço (a tabela ainda está mais acima) e precisa se
    reposicionar quando os textos são preenchidos.
    """
    rede = RedeSimulada()
    rede.segurar_binance = True
    contexto = navegador.new_context(viewport={"width": largura, "height": altura})
    rede.instalar(contexto)
    com_grafico_ao_abrir(contexto)
    pagina = contexto.new_page()
    erros: list[str] = []
    pagina.on("pageerror", lambda erro: erros.append(str(erro)))
    pagina.goto(INDEX_URL)
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)
    rede.liberar_binance()
    esperar_carregamento(pagina)
    pagina.wait_for_timeout(300)
    conferir_cobertura(pagina.evaluate(GEOMETRIA), altura)
    # Redimensionar a janela com o gráfico aberto também mantém a cobertura.
    pagina.set_viewport_size({"width": largura + 150, "height": altura - 60})
    pagina.wait_for_timeout(300)
    conferir_cobertura(pagina.evaluate(GEOMETRIA), altura - 60)
    assert not erros, erros
    contexto.close()


CAPTURAR_RELATORIOS = """
window.__relatorios = [];
window.addEventListener('load', () => setTimeout(() => {
    window.pywebview = { api: {
        carregar_alerta: async () => [],
        salvar_alerta: async () => true,
        esta_no_topo: async () => false,
        registrar_metricas: async relatorio => { window.__relatorios.push(relatorio); return true; },
    } };
    window.dispatchEvent(new Event('pywebviewready'));
}, 50));
"""


def test_relatorio_de_abertura_traz_a_1a_requisicao_a_cada_servidor(navegador):
    """O relatório sai no 1º preço; a entrada da requisição à Binance ainda não foi entregue
    ao PerformanceObserver nesse momento e precisa ser recolhida (takeRecords)."""
    rede = RedeSimulada()
    rede.segurar_binance = True  # como no app real: o gráfico carrega antes do 1º preço
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script(CAPTURAR_RELATORIOS)
    com_grafico_ao_abrir(contexto)
    pagina.goto(INDEX_URL)
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)
    pagina.wait_for_timeout(300)
    rede.liberar_binance()  # o relatório sai junto com o 1º preço
    esperar_carregamento(pagina)
    pagina.wait_for_function("window.__relatorios.some(r => r.motivo === 'abertura')", timeout=20000)
    abertura = pagina.evaluate("window.__relatorios.find(r => r.motivo === 'abertura')")
    amostras = abertura["amostras"]
    assert "primeiro_preco" in abertura["marcos"], abertura["marcos"]
    assert "rede1:api.binance.com" in amostras, sorted(amostras)
    assert len(amostras["rede1:api.binance.com"]) == 1
    assert not erros, erros
    contexto.close()


def test_relatorio_de_abertura_nao_espera_o_grafico_oculto(navegador):
    """Com o gráfico oculto (padrão), o relatório sai ao fim da abertura (alertas lidos, logo
    depois da ponte), sem esperar os 15 s. Ele precisa trazer o "load" e a ponte: montado já
    no 1º preço, perderia todos os marcos posteriores (e o medir_abertura.py fecha o app
    assim que o relatório de abertura chega)."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script(CAPTURAR_RELATORIOS)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("window.__relatorios.some(r => r.motivo === 'abertura')", timeout=5000)
    abertura = pagina.evaluate("window.__relatorios.find(r => r.motivo === 'abertura')")
    for marco in ("primeiro_preco", "nav_load", "api_python_pronta", "alertas_sincronizados"):
        assert marco in abertura["marcos"], (marco, abertura["marcos"])
    assert "grafico_carregado" not in abertura["marcos"], abertura["marcos"]
    assert not erros, erros
    contexto.close()


# ---------------------------------------------------------------------------
# 1º preço buscado pelo Python (primeiro_preco.py), entregue pelo servidor local
# (servidor_local.py, /preco-inicial) e correndo contra o REST. A página é servida pelo
# servidor_local de verdade, em http://, como no app.
# ---------------------------------------------------------------------------

TICKERS_DO_PYTHON = [
    {"symbol": "BTCBRL", "lastPrice": "123456.00", "priceChangePercent": "0.50", "highPrice": "124000.00", "lowPrice": "122000.00"},
    {"symbol": "BTCUSDT", "lastPrice": "24000.00", "priceChangePercent": "0.40", "highPrice": "24100.00", "lowPrice": "23900.00"},
]


class BuscaSimulada:
    """Faz o papel da BuscaPrimeiroPreco: modo "dados", "nada" ou "lento" (nunca termina a tempo)."""

    def __init__(self, modo: str) -> None:
        self.modo, self.pedidos, self._entregue = modo, 0, False

    def resultado(self, espera_s: float):
        self.pedidos += 1
        if self.modo == "lento":
            time.sleep(espera_s)
            return None
        if self.modo == "nada" or self._entregue:
            return None
        self._entregue = True
        return TICKERS_DO_PYTHON


def abrir_pelo_servidor(navegador, busca, segurar_binance: bool = False, falhar_binance: bool = False,
                        preco_no_html: bool = True, pedidos: list | None = None):
    from apoio_pagina import ServidorDaPagina

    servidor = ServidorDaPagina(busca, preco_no_html=preco_no_html)
    rede = RedeSimulada()
    rede.segurar_binance = segurar_binance
    rede.falhar_binance = falhar_binance
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script(PYWEBVIEW_TARDIO)
    if pedidos is not None:
        pagina.on("request", lambda pedido: pedidos.append(pedido.url))
    pagina.goto(servidor.url)
    return servidor, rede, contexto, pagina, erros


def _esperar_relatorio_de_abertura(pagina) -> None:
    """O relatório de abertura zera os contadores ao ser montado, e a entrega ao registrar_metricas
    passa pela ponte. Entre uma coisa e outra, os contadores não estão em lugar nenhum."""
    pagina.wait_for_function(
        "typeof window.__relatorios === 'undefined' || !carregado"
        " || window.__relatorios.some(r => r.motivo === 'abertura')",
        timeout=10000,
    )


def contadores(pagina) -> dict:
    """Contadores da página somados aos dos relatórios já enviados (cada relatório os zera)."""
    _esperar_relatorio_de_abertura(pagina)
    return pagina.evaluate("""() => {
        const soma = {};
        for (const c of [...(window.__relatorios ?? []).map(r => r.contadores ?? {}), Metricas.resumo().contadores]) {
            for (const [nome, valor] of Object.entries(c)) soma[nome] = (soma[nome] ?? 0) + valor;
        }
        return soma;
    }""")


def marcos_da_pagina(pagina) -> dict:
    """Marcos da página junto com os dos relatórios já enviados (caso um relatório os tenha zerado)."""
    _esperar_relatorio_de_abertura(pagina)
    return pagina.evaluate("""() => Object.assign({},
        ...(window.__relatorios ?? []).map(r => r.marcos ?? {}), Metricas.marcos)""")


def test_primeiro_preco_vem_no_html_antes_do_load(navegador):
    """O Python já tem o preço quando a página é pedida: ele vem no HTML, sem nenhum pedido de rede."""
    busca = BuscaSimulada("dados")
    pedidos: list[str] = []
    servidor, rede, contexto, pagina, erros = abrir_pelo_servidor(navegador, busca, segurar_binance=True,
                                                                  pedidos=pedidos)
    esperar_carregamento(pagina)  # sem nenhuma resposta da Binance
    assert texto(pagina, "#info-price") == "R$ 123.456,00"
    assert contadores(pagina).get("primeiro_preco:html") == 1
    marcos = marcos_da_pagina(pagina)
    assert marcos["preco_no_html"] <= marcos["primeiro_preco"] <= marcos["nav_load"], marcos
    assert not any("preco-inicial" in url for url in pedidos), pedidos
    assert rede.contagem["binance"] == 0 and len(rede._segurados) == 0  # nem o REST foi preciso
    assert pagina.evaluate("document.getElementById('preco-inicial')") is None  # o bloco sai da página
    # Os ciclos seguintes são normais e só usam o REST.
    rede.liberar_binance()
    pagina.wait_for_function("document.getElementById('info-price').textContent !== 'R$\\u00a0123.456,00'", timeout=15000)
    assert busca.pedidos == 1
    assert not erros, erros
    contexto.close()
    servidor.fechar()


def test_primeiro_preco_do_python_aparece_sem_esperar_o_rest_nem_a_ponte(navegador):
    """Sem o preço no HTML (o Python ainda não o tinha): ele vem de /preco-inicial."""
    busca = BuscaSimulada("dados")
    servidor, rede, contexto, pagina, erros = abrir_pelo_servidor(navegador, busca, segurar_binance=True,
                                                                  preco_no_html=False)
    esperar_carregamento(pagina)  # sem nenhuma resposta da Binance
    assert texto(pagina, "#info-price") == "R$ 123.456,00"
    assert contadores(pagina).get("primeiro_preco:python") == 1
    marcos = marcos_da_pagina(pagina)
    assert "api_python_pronta" not in marcos or marcos["primeiro_preco"] < marcos["api_python_pronta"], marcos
    assert marcos["preco_inicial_pedido"] <= marcos["preco_inicial_resposta"] <= marcos["preco_inicial_dados"] \
        <= marcos["precos_continuacao"] <= marcos["primeiro_preco"], marcos
    assert rede.contagem["binance"] == 0 and len(rede._segurados) == 1  # o REST saiu em paralelo
    # Os ciclos seguintes são normais e só usam o REST.
    rede.liberar_binance()
    pagina.wait_for_function("document.getElementById('info-price').textContent !== 'R$\\u00a0123.456,00'", timeout=15000)
    assert busca.pedidos == 1
    assert not erros, erros
    contexto.close()
    servidor.fechar()


@pytest.mark.parametrize("modo", ["nada", "lento"])
def test_sem_preco_do_python_o_rest_assume(navegador, modo):
    servidor, rede, contexto, pagina, erros = abrir_pelo_servidor(navegador, BuscaSimulada(modo))
    esperar_carregamento(pagina)
    assert texto(pagina, "#info-price") != "R$ 123.456,00"
    assert contadores(pagina).get("primeiro_preco:rest") == 1
    assert contadores(pagina).get("primeiro_preco:python") is None
    assert not erros, erros
    contexto.close()
    servidor.fechar()


def test_python_e_rest_falhando_contam_como_falha_da_binance(navegador):
    servidor, rede, contexto, pagina, erros = abrir_pelo_servidor(navegador, BuscaSimulada("nada"), falhar_binance=True)
    pagina.wait_for_function("(Metricas.resumo().contadores['falha:binance'] ?? 0) >= 1", timeout=10000)
    assert not erros, erros
    contexto.close()
    servidor.fechar()


def test_pagina_aberta_do_disco_nao_pede_o_preco_inicial(navegador):
    """Fora do servidor local (file://, navegador comum) não existe /preco-inicial."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script(PYWEBVIEW_TARDIO)
    pedidos: list[str] = []
    pagina.on("request", lambda pedido: pedidos.append(pedido.url))
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    assert not any("preco-inicial" in url for url in pedidos), pedidos
    assert contadores(pagina).get("primeiro_preco:python") is None
    assert not erros, erros
    contexto.close()


def test_vigia_registra_a_thread_da_pagina_ocupada_na_abertura(navegador):
    """Uma tarefa de ~60 ms aos 400 ms aparece nos bloqueios do relatório; o ritmo normal não."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False)
    contexto.add_init_script("setTimeout(() => { const fim = performance.now() + 60; while (performance.now() < fim); }, 400);")
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("performance.now() > 2100", timeout=10000)
    bloqueios = pagina.evaluate("Metricas.relatorio('teste').bloqueios")
    assert any(380 <= inicio <= 470 and duracao >= 55 for inicio, duracao in bloqueios), bloqueios
    assert pagina.evaluate("Metricas.relatorio('teste').bloqueios") == []  # zera a cada relatório
    assert not erros, erros
    contexto.close()


# ---------------------------------------------------------------------------
# Modo compacto
# ---------------------------------------------------------------------------

MODO_COMPACTO = """() => {
    const visivel = s => getComputedStyle(document.querySelector(s)).display !== 'none';
    return {
        classe: document.documentElement.classList.contains('compacto'),
        botao: document.getElementById('compacto-btn').textContent,
        dica: document.getElementById('compacto-btn').title,
        logo: visivel('#info-logo'), tabela: visivel('.bottom-left-info'),
        faixa: visivel('#info-faixa'), botaoGrafico: visivel('#grafico-btn'),
        faixaMaxima: document.getElementById('faixaMaxima').textContent,
        faixaMinima: document.getElementById('faixaMinima').textContent,
        maxima: document.getElementById('highPrice').textContent,
        minima: document.getElementById('lowPrice').textContent,
        iframes: document.querySelectorAll('#grafico iframe').length,
    };
}"""

# Registra as chamadas a definir_compacto; a 1ª demora mais que as seguintes, para que, sem
# a fila do script.js, as respostas chegassem fora de ordem.
API_DEFINIR_COMPACTO = """
window.__compacto = [];
window.addEventListener('pywebviewready', () => {
    let n = 0;
    window.pywebview.api.definir_compacto = ativo => new Promise(resolver => {
        const atraso = n++ === 0 ? 300 : 10;
        setTimeout(() => { window.__compacto.push(ativo); resolver(true); }, atraso);
    });
});
"""


def test_navegador_modo_compacto_troca_o_layout_e_guarda_o_grafico(navegador):
    """No navegador, ⊟ só muda o layout: sem logo, tabela e ⇄, com máxima e mínima no rodapé;
    o gráfico aberto sai e volta com ⊞."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    inicial = pagina.evaluate(MODO_COMPACTO)
    assert (inicial["classe"], inicial["botao"], inicial["faixa"], inicial["tabela"], inicial["logo"]) == (
        False, "⊟", False, True, True)
    pagina.click("#grafico-btn")
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)

    pagina.click("#compacto-btn")
    compacto = pagina.evaluate(MODO_COMPACTO)
    assert compacto["classe"] and compacto["botao"] == "⊞" and compacto["dica"] == "Modo completo"
    assert not compacto["logo"] and not compacto["tabela"] and not compacto["botaoGrafico"]
    assert compacto["faixa"] and compacto["iframes"] == 0
    assert compacto["faixaMaxima"] == compacto["maxima"] != ""
    assert compacto["faixaMinima"] == compacto["minima"] != ""
    assert pagina.viewport_size == {"width": 500, "height": 810}  # no navegador a janela não muda

    pagina.click("#compacto-btn")
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)
    completo = pagina.evaluate(MODO_COMPACTO)
    assert not completo["classe"] and completo["botao"] == "⊟" and completo["tabela"] and not completo["faixa"]
    assert not erros, erros
    contexto.close()


def test_rodape_do_modo_compacto_acompanha_estado_salvo_e_sem_dados(navegador):
    rede = RedeSimulada()
    rede.falhar_binance = True
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=True, com_alertas=False)
    contexto.add_init_script(f"localStorage.setItem('ultimoEstado', {json.dumps(json.dumps(ESTADO_SALVO))})")
    pagina.goto(INDEX_URL)
    pagina.click("#compacto-btn")
    salvo = pagina.evaluate(MODO_COMPACTO)
    assert salvo["faixaMaxima"] == salvo["maxima"] and "440.000" in salvo["faixaMaxima"]
    assert salvo["faixaMinima"] == salvo["minima"] and "430.000" in salvo["faixaMinima"]
    pagina.wait_for_function("document.getElementById('faixaMaxima').textContent === '—'", timeout=15000)
    assert pagina.evaluate("document.getElementById('faixaMinima').textContent") == "—"
    contexto.close()


def test_app_pede_o_redimensionamento_ao_python_na_ordem_dos_cliques(navegador):
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script(PYWEBVIEW_TARDIO)
    contexto.add_init_script(API_DEFINIR_COMPACTO)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("typeof window.pywebview?.api?.definir_compacto === 'function'")
    for _ in range(3):
        pagina.click("#compacto-btn")
    pagina.wait_for_function("window.__compacto.length === 3", timeout=5000)
    assert pagina.evaluate("window.__compacto") == [True, False, True]
    assert pagina.evaluate(MODO_COMPACTO)["classe"] is True
    # No app, o botão fica à esquerda do minimizar, sem sobrepor.
    compacto, minimizar = (pagina.locator(f"#{i}").bounding_box() for i in ("compacto-btn", "minimize-btn"))
    assert compacto["x"] + compacto["width"] <= minimizar["x"]
    assert not erros, erros
    contexto.close()


def test_app_abre_no_modo_compacto_salvo_e_tudo_cabe_na_janela(navegador):
    """O servidor local entrega o HTML com a classe: a página já abre no layout compacto, sem
    montar o gráfico (nem com ele configurado como visível) e sem nada cortado em 500x388."""
    from apoio_pagina import ServidorDaPagina

    servidor = ServidorDaPagina(BuscaSimulada("dados"), modo_compacto=lambda: True)
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    pagina.set_viewport_size({"width": 500, "height": 388})
    contexto.add_init_script(PYWEBVIEW_TARDIO)
    com_grafico_ao_abrir(contexto)
    try:
        pagina.goto(servidor.url)
        esperar_carregamento(pagina)
        estado = pagina.evaluate(MODO_COMPACTO)
        assert estado["classe"] and estado["botao"] == "⊞" and estado["faixa"] and not estado["tabela"]
        fim = pagina.evaluate("document.getElementById('info-faixa').getBoundingClientRect().bottom")
        assert fim <= 388 - 8, fim
        assert pagina.evaluate("document.documentElement.scrollHeight") <= 388
        pagina.wait_for_function("'nav_load' in Metricas.marcos")
        pagina.wait_for_timeout(800)  # passa o momento em que o gráfico seria montado
        assert pagina.evaluate(MODO_COMPACTO)["iframes"] == 0
        # O relatório de abertura não espera o gráfico que não é montado.
        pagina.wait_for_function("window.__relatorios.some(r => r.motivo === 'abertura')", timeout=5000)
        assert not erros, erros
    finally:
        contexto.close()
        servidor.fechar()


# ---------------------------------------------------------------------------
# Seta de direção
# ---------------------------------------------------------------------------

POSICAO_DA_SETA = """() => {
    const p = document.getElementById('info-percent').getBoundingClientRect();
    const linha = document.querySelector('.percentual').getBoundingClientRect();
    const s = document.getElementById('info-seta');
    const caixaSeta = s.getBoundingClientRect();
    return {
        esquerda: p.left, texto: s.textContent, neutra: s.classList.contains('seta-neutra'),
        centroPercentual: p.left + p.width / 2, centroLinha: linha.left + linha.width / 2,
        setaAposPercentual: caixaSeta.left >= p.right,
    };
}"""


@pytest.mark.parametrize("compacto", [False, True])
def test_seta_comeca_neutra_e_nao_desloca_o_percentual(navegador, compacto):
    """O estado salvo já aparece com ↔, e trocar a seta (↔, ↑, ↓ ou nenhuma) não move o %."""
    rede = RedeSimulada()
    rede.segurar_binance = True  # só o estado salvo e as chamadas abaixo mexem na tela
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=False, com_alertas=False)
    contexto.add_init_script(f"localStorage.setItem('ultimoEstado', {json.dumps(json.dumps(ESTADO_SALVO))})")
    pagina.goto(INDEX_URL)
    pagina.wait_for_function("document.getElementById('tela-carregamento').style.display === 'none'")
    if compacto:
        pagina.click("#compacto-btn")
    pagina.evaluate("document.fonts.ready")
    inicial = pagina.evaluate(POSICAO_DA_SETA)
    assert (inicial["texto"], inicial["neutra"]) == ("↔", True)

    posicoes = []
    # A variação fica igual (-2.50%): só a seta muda.
    for preco in (432_100, 432_100, 433_000, 431_000):
        pagina.evaluate(f"exibirBRL({{ preco: {preco}, variacao: -2.5, maxima: 440000, minima: 430000 }})")
        posicoes.append(pagina.evaluate(POSICAO_DA_SETA))
    assert [p["texto"] for p in posicoes] == ["↔", "↔", "↑", "↓"]
    pagina.evaluate("ui.seta.textContent = ''")  # como no "Sem Dados"
    posicoes.append(pagina.evaluate(POSICAO_DA_SETA))
    assert {p["esquerda"] for p in posicoes} == {inicial["esquerda"]}, posicoes
    # Só o número é centralizado: a seta fica à direita dele, fora do centro.
    for posicao in [inicial, *posicoes]:
        assert abs(posicao["centroPercentual"] - posicao["centroLinha"]) <= 1, posicao
        assert posicao["setaAposPercentual"], posicao
    assert not erros, erros
    contexto.close()


# ---------------------------------------------------------------------------
# Valores salvos e falhas: a mesma regra para todos os campos
# ---------------------------------------------------------------------------

CAMPOS_POR_FONTE = {
    "binance": ["#info-price", "#info-usdt", "#highPriceDol", "#faixaMaxima", "#dolar-implicito"],
    "awesomeapi": ["#dolar-comercial"],
    "mempool": ["#fastestFee", "#minimumFee"],
}


def esmaecidos(pagina) -> dict:
    return pagina.evaluate("""seletores => Object.fromEntries(seletores.map(s => {
        const e = document.querySelector(s);
        return [s, !!e.closest('.desatualizado')];
    }))""", [s for lista in CAMPOS_POR_FONTE.values() for s in lista])


def falhar_tudo(contexto) -> None:
    """AwesomeAPI e mempool.space falham (a rota registrada por último tem precedência)."""
    contexto.route("https://economia.awesomeapi.com.br/**", lambda rota: rota.abort())
    contexto.route("https://mempool.space/**", lambda rota: rota.abort())


def test_dolar_e_taxas_mantem_o_valor_salvo_ate_3_falhas(navegador):
    """Dólar comercial e taxas mantêm o valor salvo (esmaecido) até 3 falhas seguidas e só então
    viram "Sem Dados"/"—", já sem o esmaecimento. A Binance fica retida: com ela falhando, o
    monitoramento pausaria (MAX_FALHAS) antes; o preço tem o próprio teste (resiste_a_falhas)."""
    rede = RedeSimulada()
    rede.segurar_binance = True
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=True, com_alertas=False)
    com_estado_salvo(contexto)
    falhar_tudo(contexto)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("falhasDolar >= 1 && falhasTaxas >= 1", timeout=15000)
    if pagina.evaluate("falhasDolar < 3 && falhasTaxas < 3"):
        assert texto(pagina, "#info-dolar") == "R$ 5,02 | R$ 5,02"
        assert texto(pagina, "#fastestFee") == "9,87 sat/vB"
        assert all(esmaecidos(pagina).values()), esmaecidos(pagina)

    pagina.wait_for_function("falhasDolar >= 3 && falhasTaxas >= 3", timeout=30000)
    assert texto(pagina, "#dolar-comercial") == "Sem Dados"
    assert texto(pagina, "#fastestFee") == "—" and texto(pagina, "#minimumFee") == "—"
    estado = esmaecidos(pagina)
    assert not estado["#dolar-comercial"] and not estado["#fastestFee"], estado
    # A Binance ainda não respondeu: preço, USDT e dólar implícito continuam os salvos.
    assert texto(pagina, "#info-price") == "R$ 432.100,00" and texto(pagina, "#dolar-implicito") == "R$ 5,02"
    assert all(estado[s] for s in CAMPOS_POR_FONTE["binance"]), estado
    assert not erros, erros
    contexto.close()


def test_usdt_salvo_resiste_a_falha_depois_que_o_brl_chega(navegador):
    """O BRL novo tira o BRL do estado salvo, mas não o USDT: uma falha só do USDT mantém o salvo."""
    rede = RedeSimulada()
    rede.segurar_binance = True
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=False, com_alertas=False)
    com_estado_salvo(contexto)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.evaluate("aplicarBRL({ preco: 433000, variacao: -2.5, maxima: 440000, minima: 430000 });"
                    "registrarFalhaUSD(new Error('teste'))")
    assert texto(pagina, "#info-usdt") == "US$ 86.000,00"
    assert esmaecidos(pagina)["#info-usdt"] is True
    assert esmaecidos(pagina)["#info-price"] is False
    contexto.close()


def test_cada_fonte_tira_o_esmaecimento_dos_seus_campos(navegador):
    """Com a Binance demorando, o dólar implícito continua com os preços salvos (não vira
    "Sem Dados"); o comercial e as taxas se atualizam quando as fontes deles respondem."""
    rede = RedeSimulada()
    rede.segurar_binance = True
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=False, com_alertas=False)
    com_estado_salvo(contexto)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("document.getElementById('fastestFee').textContent === '3,40 sat/vB'")
    pagina.wait_for_function("document.getElementById('dolar-comercial').textContent.includes('5,01')")
    assert texto(pagina, "#dolar-implicito") == "R$ 5,02"  # 432.100 / 86.000 (salvos)
    estado = esmaecidos(pagina)
    assert estado["#dolar-implicito"] and estado["#info-price"] and estado["#info-usdt"]
    assert not estado["#dolar-comercial"] and not estado["#fastestFee"]

    rede.liberar_binance()
    pagina.wait_for_function("!document.getElementById('info-price').classList.contains('desatualizado')")
    assert not any(esmaecidos(pagina).values()), esmaecidos(pagina)
    assert texto(pagina, "#dolar-implicito") != "Sem Dados"
    assert not erros, erros
    contexto.close()


def test_sem_estado_salvo_a_1a_falha_ja_mostra_sem_dados(navegador):
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False)
    falhar_tudo(contexto)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("falhasDolar >= 1 && falhasTaxas >= 1", timeout=10000)
    assert texto(pagina, "#dolar-comercial") == "Sem Dados"
    assert texto(pagina, "#fastestFee") == "—"
    contexto.close()


# ---------------------------------------------------------------------------
# Modo compacto no navegador: salvo no localStorage; pausa e alertas presos ao bloco
# ---------------------------------------------------------------------------

def test_navegador_lembra_o_modo_compacto_ao_recarregar(navegador):
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.click("#compacto-btn")
    pagina.reload()
    esperar_carregamento(pagina)
    estado = pagina.evaluate(MODO_COMPACTO)
    assert estado["classe"] and estado["botao"] == "⊞"
    pagina.click("#compacto-btn")
    pagina.reload()
    esperar_carregamento(pagina)
    assert pagina.evaluate(MODO_COMPACTO)["classe"] is False
    assert not erros, erros
    contexto.close()


def test_app_ignora_o_modo_do_navegador(navegador):
    """No app, o modo vem do Python (classe no HTML), nunca do localStorage."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script("localStorage.setItem('modoCompacto', '1');")
    contexto.add_init_script(PYWEBVIEW_TARDIO)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    assert pagina.evaluate(MODO_COMPACTO)["classe"] is False
    contexto.close()


CAIXAS_DO_BLOCO = """() => {
    const caixa = s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
    return { bloco: caixa('#conteudo'), pausa: caixa('#overlay'), fundo: caixa('#darkback'), alertas: caixa('#modalAlerta'),
             fimConteudo: caixa('#conteudoMenosBotoes')[3], altura: innerHeight };
}"""


@pytest.mark.parametrize(("largura", "altura"), [(500, 388), (1100, 650), (800, 900)])
def test_pausa_e_alertas_ficam_no_bloco_compacto(navegador, largura, altura):
    alertas = [{"id": str(i), "valor": 400_000 + i * 1000, "tipo": "maior"} for i in range(6)]
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=alertas)
    pagina.set_viewport_size({"width": largura, "height": altura})
    contexto.add_init_script("localStorage.setItem('modoCompacto', '1');")
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.click("#pausar-btn")
    pagina.click("#overlay")
    pagina.click("#pausar-btn")
    medida = pagina.evaluate(CAIXAS_DO_BLOCO)
    (bl, bt, br, bb) = medida["bloco"]
    # O bloco acaba 10 px abaixo do conteúdo (no navegador, bem antes do fim da janela).
    assert abs(bb - (medida["fimConteudo"] + 10)) <= 1 and bb <= altura + 1, medida
    (pl, pt, pr, pb) = medida["pausa"]
    assert pt == bt + 40 and abs(pb - bb) <= 1, medida  # da barra até o fim do bloco
    pagina.click("#overlay")
    pagina.click("#alerta-btn")
    medida = pagina.evaluate(CAIXAS_DO_BLOCO)
    (al, at, ar, ab) = medida["alertas"]
    assert at >= bt + 40 and ab <= bb, medida  # a tela de alertas não passa do bloco
    (fl, ft, fr, fb) = medida["fundo"]
    assert abs(fb - bb) <= 1, medida
    # Só a lista rola: os botões continuam dentro da tela de alertas.
    botao = pagina.locator("#voltarBotao").bounding_box()
    assert botao["y"] + botao["height"] <= ab, (botao, medida)
    assert not erros, erros
    contexto.close()


# Conta os pedidos de arraste ao Python (bordas_janela.py move a janela até o botão ser solto).
API_INICIAR_ARRASTE = """
window.__arrastes = 0;
window.addEventListener('pywebviewready', () => {
    window.pywebview.api.iniciar_arraste = async () => { window.__arrastes++; return true; };
});
"""

PRESSIONAR = """([seletor, botao]) => {
    const alvo = document.querySelector(seletor);
    const caixa = alvo.getBoundingClientRect();
    alvo.dispatchEvent(new MouseEvent('mousedown', {
        bubbles: true, button: botao, clientX: caixa.left + 2, clientY: caixa.top + 2,
    }));
}"""


def arrastes(pagina) -> int:
    pagina.wait_for_timeout(100)  # chamarApi é assíncrona
    return pagina.evaluate("window.__arrastes")


def test_app_pede_o_arraste_ao_python_so_fora_dos_controles(navegador):
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script(PYWEBVIEW_TARDIO)
    contexto.add_init_script(API_INICIAR_ARRASTE)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("typeof window.pywebview?.api?.iniciar_arraste === 'function'")

    # Mouse de verdade sobre o preço: um pedido por pressionamento.
    caixa = pagina.locator("#info-price").bounding_box()
    pagina.mouse.move(caixa["x"] + caixa["width"] / 2, caixa["y"] + caixa["height"] / 2)
    pagina.mouse.down()
    pagina.mouse.up()
    assert arrastes(pagina) == 1

    # Botão direito ou do meio: não arrasta.
    for botao in (1, 2):
        pagina.evaluate(PRESSIONAR, ["#info-price", botao])
    assert arrastes(pagina) == 1

    # Controles têm ação própria: não arrastam.
    pagina.evaluate("alternarTelaAlerta()")
    for seletor in ("#compacto-btn", "#close-btn", "#valorAlerta", "#salvarBotao"):
        pagina.evaluate(PRESSIONAR, [seletor, 0])
    assert arrastes(pagina) == 1

    # O fundo da tela de alertas arrasta.
    pagina.evaluate(PRESSIONAR, [".modal-content p", 0])
    assert arrastes(pagina) == 2

    # O diálogo fica fora da região de arrasto.
    pagina.evaluate("aviso('Teste', 'mensagem')")
    pagina.evaluate(PRESSIONAR, ["#dialogo-titulo", 0])
    assert arrastes(pagina) == 2
    assert not erros, erros
    contexto.close()


def test_clique_na_barra_de_rolagem_da_lista_nao_arrasta(navegador):
    muitos = [{"id": f"a{i}", "valor": 1000 + i, "tipo": "desativado"} for i in range(40)]
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script(PYWEBVIEW_TARDIO.replace("carregar_alerta: async () => []",
                                                      f"carregar_alerta: async () => {json.dumps(muitos)}"))
    contexto.add_init_script(API_INICIAR_ARRASTE)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("typeof window.pywebview?.api?.iniciar_arraste === 'function'")
    pagina.wait_for_function("alertas.length === 40")
    # O Chromium sem janela do Playwright esconde as barras de rolagem (a largura delas é 0).
    # O pressionamento vai logo à direita da área interna da lista, onde fica a barra no Edge.
    pagina.evaluate("alternarTelaAlerta()")
    lista = pagina.evaluate("""() => {
        const lista = document.getElementById('listaAlertas');
        const caixa = lista.getBoundingClientRect();
        return { rola: lista.scrollHeight > lista.clientHeight, x: caixa.left, y: caixa.top, interna: lista.clientWidth };
    }""")
    assert lista["rola"], lista
    pagina.evaluate("""([x, y]) => document.getElementById('listaAlertas').dispatchEvent(
        new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: x, clientY: y }))""",
                    [lista["x"] + lista["interna"] + 2, lista["y"] + 10])
    assert arrastes(pagina) == 0
    # Controle: o mesmo pressionamento dentro da área da lista arrasta.
    pagina.evaluate("""([x, y]) => document.getElementById('listaAlertas').dispatchEvent(
        new MouseEvent('mousedown', { bubbles: true, button: 0, clientX: x, clientY: y }))""",
                    [lista["x"] + lista["interna"] - 20, lista["y"] + 10])
    assert arrastes(pagina) == 1
    assert not erros, erros
    contexto.close()


def test_navegador_nao_pede_arraste(navegador):
    """Fora do app (sem "pywebview" no user agent), nada de arraste, mesmo com uma API presente."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False)
    contexto.add_init_script("""
        window.__arrastes = 0;
        window.pywebview = { api: { iniciar_arraste: async () => { window.__arrastes++; } } };
    """)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.evaluate(PRESSIONAR, ["#info-price", 0])
    assert arrastes(pagina) == 0
    assert not erros, erros
    contexto.close()


# ---------------------------------------------------------------------------
# Edição do valor do alerta (clique no valor da tabela)
# ---------------------------------------------------------------------------

ALERTAS_PARA_EDITAR = [
    {"id": "a", "valor": 30000, "tipo": "menor"},
    {"id": "b", "valor": 20000, "tipo": "desativado"},
    {"id": "c", "valor": 10000, "tipo": "maior"},
]

LINHAS_DA_TABELA = """() => [...document.querySelectorAll('#alertasTabela tr')].map(tr => ({
    id: tr.dataset.id,
    valor: tr.querySelector('.botaoValor')?.textContent ?? null,
    tipo: tr.querySelector('.botaoTipo').textContent,
}))"""


def abrir_alertas_para_editar(navegador):
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False,
                                          com_alertas=ALERTAS_PARA_EDITAR)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.evaluate("alternarTelaAlerta()")
    return contexto, pagina, erros


def editar(pagina, id_alerta: str, valor: str):
    pagina.click(f'#alertasTabela tr[data-id="{id_alerta}"] .botaoValor')
    campo = pagina.locator(f'#alertasTabela tr[data-id="{id_alerta}"] .campoEdicaoValor')
    assert campo.evaluate("c => c === document.activeElement")
    campo.fill(valor)
    return campo


def salvos(pagina) -> list:
    return json.loads(pagina.evaluate("localStorage.getItem('alertasjson')"))


def test_editar_valor_do_alerta_com_enter_grava_e_reordena(navegador):
    contexto, pagina, erros = abrir_alertas_para_editar(navegador)
    campo = editar(pagina, "c", "40000")
    campo.press("Enter")
    linhas = pagina.evaluate(LINHAS_DA_TABELA)
    assert [linha["id"] for linha in linhas] == ["c", "a", "b"]
    assert salvos(pagina)[0] == {"id": "c", "valor": 40000, "tipo": "maior"}
    assert pagina.evaluate("alarmesSilenciados") is True  # 15 s, como ao criar ou alterar

    assert not erros, erros
    contexto.close()


def tipo_na_tabela(pagina, id_alerta: str) -> str:
    return pagina.locator(f'#alertasTabela tr[data-id="{id_alerta}"] .botaoTipo').text_content()


@pytest.mark.parametrize("valor, tipo, rotulo", [
    ("25000", "menor", "Menor ▽"),     # preço (~500 mil) acima do valor: "maior" dispararia
    ("900000", "maior", "Maior △"),    # preço abaixo do valor: "menor" dispararia
])
def test_editar_desativado_reativa_pelo_lado_que_nao_dispara(navegador, valor, tipo, rotulo):
    contexto, pagina, erros = abrir_alertas_para_editar(navegador)
    pagina.wait_for_function("Number.isFinite(ultimoPrecoBRL)")
    editar(pagina, "b", valor).press("Enter")
    assert {"id": "b", "valor": float(valor), "tipo": tipo} in salvos(pagina)
    assert tipo_na_tabela(pagina, "b") == rotulo
    assert not erros, erros
    contexto.close()


@pytest.mark.parametrize("valor, rotulo", [(400_000, "Menor ▽"), (900_000, "Maior △")])
def test_botao_de_tipo_reativa_pelo_lado_que_nao_dispara(navegador, valor, rotulo):
    """O ciclo Maior → Menor → Desativado → (lado que não dispara com o preço atual)."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False,
                                          com_alertas=[{"id": "a", "valor": valor, "tipo": "desativado"}])
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("Number.isFinite(ultimoPrecoBRL)")  # ~500 mil
    pagina.evaluate("alternarTelaAlerta()")
    pagina.click('#alertasTabela tr[data-id="a"] .botaoTipo')
    assert tipo_na_tabela(pagina, "a") == rotulo
    assert pagina.evaluate("alarmesSilenciados") is True
    assert not erros, erros
    contexto.close()


@pytest.mark.parametrize("estado_salvo, rotulo", [(True, "Menor ▽"), (False, "Maior △")])
def test_reativar_sem_preco_novo_usa_o_da_tela_ou_maior(navegador, estado_salvo, rotulo):
    """Sem preço novo (Binance retida): vale o preço salvo na tela (432.100); sem nenhum, "maior"."""
    rede = RedeSimulada()
    rede.segurar_binance = True
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=False,
                                          com_alertas=[{"id": "a", "valor": 400_000, "tipo": "desativado"}])
    if estado_salvo:
        com_estado_salvo(contexto)
    pagina.goto(INDEX_URL)
    pagina.wait_for_function("alertas.length === 1")
    assert pagina.evaluate("Number.isFinite(ultimoPrecoBRL)") is False
    pagina.evaluate("alternarTipoAlerta('a')")  # sem estado salvo, a tela de carregamento cobre a página
    assert pagina.evaluate("alertas[0].tipo") == ("menor" if estado_salvo else "maior")
    pagina.evaluate("alternarTelaAlerta()")
    assert tipo_na_tabela(pagina, "a") == rotulo
    assert not erros, erros
    contexto.close()


def test_esc_e_sair_do_campo_cancelam_a_edicao(navegador):
    contexto, pagina, erros = abrir_alertas_para_editar(navegador)
    antes = pagina.evaluate(LINHAS_DA_TABELA)

    editar(pagina, "a", "1").press("Escape")
    assert pagina.evaluate(LINHAS_DA_TABELA) == antes
    # O botão volta no lugar, com o foco; a tela de alertas continua aberta.
    assert pagina.evaluate("document.activeElement.classList.contains('botaoValor')")
    assert pagina.evaluate("modalAlertaAberto()")

    editar(pagina, "b", "5")
    pagina.click(".modal-content p")  # clicar fora do campo
    assert pagina.evaluate(LINHAS_DA_TABELA) == antes
    assert pagina.locator(".campoEdicaoValor").count() == 0
    assert salvos(pagina) == ALERTAS_PARA_EDITAR
    assert not erros, erros
    contexto.close()


@pytest.mark.parametrize("valor, mensagem", [
    ("20000", "Existe um alerta com esse mesmo valor."),  # "d" já é maior com 20.000
    ("0", "Digite um número válido maior que zero."),
])
def test_edicao_recusada_avisa_e_mantem_o_valor(navegador, valor, mensagem):
    alertas = [*ALERTAS_PARA_EDITAR, {"id": "d", "valor": 20000, "tipo": "maior"}]
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=alertas)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.evaluate("alternarTelaAlerta()")
    antes = pagina.evaluate(LINHAS_DA_TABELA)
    salvos_antes = salvos(pagina)
    editar(pagina, "c", valor).press("Enter")
    pagina.wait_for_function("document.getElementById('dialogo').open")
    assert pagina.locator("#dialogo-conteudo").text_content() == mensagem
    assert pagina.evaluate(LINHAS_DA_TABELA) == antes
    assert salvos(pagina) == salvos_antes
    assert not erros, erros
    contexto.close()


def test_valor_do_alerta_e_o_campo_de_edicao_nao_arrastam_a_janela(navegador):
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False,
                                          user_agent="Mozilla/5.0 pywebview")
    contexto.add_init_script(PYWEBVIEW_TARDIO.replace(
        "carregar_alerta: async () => []",
        f"carregar_alerta: async () => {json.dumps(ALERTAS_PARA_EDITAR)}"))
    contexto.add_init_script(API_INICIAR_ARRASTE)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    pagina.wait_for_function("typeof window.pywebview?.api?.iniciar_arraste === 'function'")
    pagina.wait_for_function("alertas.length === 3")
    pagina.evaluate("alternarTelaAlerta()")
    pagina.evaluate(PRESSIONAR, ['#alertasTabela tr[data-id="a"] .botaoValor', 0])
    pagina.click('#alertasTabela tr[data-id="a"] .botaoValor')
    pagina.evaluate(PRESSIONAR, ['#alertasTabela .campoEdicaoValor', 0])
    assert arrastes(pagina) == 0
    # Controle: o fundo da tela de alertas arrasta.
    pagina.evaluate(PRESSIONAR, [".modal-content p", 0])
    assert arrastes(pagina) == 1
    assert not erros, erros
    contexto.close()
