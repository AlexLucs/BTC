"""Uso de banda: a página só busca o que é necessário (testes no navegador, rede simulada).

- janela do app oculta, sem alerta ativo: nenhuma rede; ao reaparecer, tudo volta;
- oculta com alerta ativo: só os preços (o alerta dispara); dólar, taxas e gráfico param;
- modo compacto: as taxas não são buscadas;
- stream <par>@miniTicker, com a variação calculada pela abertura;
- oculta com alerta ativo, o WebSocket assina só o BTC/BRL e sonda a conexão no silêncio;
- dólar comercial e taxas em intervalos que acompanham as mudanças.

A visibilidade é simulada trocando document.visibilityState e disparando o evento
"visibilitychange" (o que o WebView2 faz ao minimizar a janela). Os timers de 1 s ou mais
rodam 50x mais rápido: 60 s viram 1,2 s.
"""

from __future__ import annotations

import json

import pytest

from apoio_pagina import (
    INDEX_URL,
    RedeSimulada,
    esperar_carregamento,
    estabilizar_websocket,
    navegador,  # noqa: F401 - fixture
    nova_pagina,
)
from test_pagina_funcional import (
    com_estado_salvo,
    contador,
    com_grafico_ao_abrir,
    esmaecidos,
    esperar,
    manter_vivo,
    texto,
)

SIMULAR_VISIBILIDADE = """
window.__visibilidade = window.__visibilidade ?? 'visible';
Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => window.__visibilidade });
Object.defineProperty(document, 'hidden', { configurable: true, get: () => window.__visibilidade !== 'visible' });
window.__definirVisibilidade = estado => {
    window.__visibilidade = estado;
    document.dispatchEvent(new Event('visibilitychange'));
};
"""

ALERTA_ATIVO_DISTANTE = [{"id": "a", "valor": 1000, "tipo": "menor"}]
ALERTA_PERTO = [{"id": "a", "valor": 550_000, "tipo": "maior"}]  # o preço simulado fica perto de 500 mil
SO_DESATIVADO = [{"id": "a", "valor": 1000, "tipo": "desativado"}]
FONTES = "({ precos: precosLigados, taxas: fontes.taxas.ligada, dolar: fontes.dolar.ligada })"


def api_do_app(alertas: list) -> str:
    """A ponte do pywebview, com os alertas que o Python devolveria do disco."""
    return f"""
    window.__alertasSalvos = null;
    window.addEventListener('load', () => setTimeout(() => {{
        window.pywebview = {{ api: {{
            carregar_alerta: async () => {json.dumps(alertas)},
            salvar_alerta: async lista => {{ window.__alertasSalvos = lista; return true; }},
            esta_no_topo: async () => false,
            registrar_metricas: async () => true,
        }} }};
        window.dispatchEvent(new Event('pywebviewready'));
    }}, 50));
    """


def abrir(navegador, app: bool = True, alertas: list | None = None, acelerar: bool = True,
          antes_de_abrir=None, visibilidade: str = "visible"):
    """Abre a página (como app ou como navegador) e espera a abertura terminar."""
    rede = RedeSimulada()
    opcoes = {"user_agent": "Mozilla/5.0 pywebview"} if app else {}
    contexto, pagina, erros = nova_pagina(navegador, rede, acelerar=acelerar,
                                          com_alertas=False if app else (alertas or False), **opcoes)
    contexto.add_init_script(f"window.__visibilidade = '{visibilidade}';" + SIMULAR_VISIBILIDADE)
    if app:
        contexto.add_init_script(api_do_app(alertas or []))
    if antes_de_abrir:
        antes_de_abrir(contexto)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    if app:
        pagina.wait_for_function("sincronizacaoAlertasConcluida")
    return rede, contexto, pagina, erros


def definir_visibilidade(pagina, estado: str) -> None:
    pagina.evaluate("estado => window.__definirVisibilidade(estado)", estado)


def pedidos(rede: RedeSimulada) -> tuple[int, int, int, int]:
    return (rede.contagem["binance"], rede.contagem["ws"], rede.contagem["dolar"], rede.contagem["taxas"])


# ---------------------------------------------------------------------------
# Janela oculta
# ---------------------------------------------------------------------------

def test_app_oculto_sem_alerta_ativo_nao_usa_a_rede_e_volta_ao_reaparecer(navegador):
    rede, contexto, pagina, erros = abrir(navegador, alertas=SO_DESATIVADO)
    estabilizar_websocket(rede, pagina)
    assert pagina.evaluate(FONTES) == {"precos": True, "taxas": True, "dolar": True}

    definir_visibilidade(pagina, "hidden")
    assert pagina.evaluate(FONTES) == {"precos": False, "taxas": False, "dolar": False}
    assert pagina.evaluate("ws === null && !wsSaudavel")
    assert pagina.evaluate("Number.isNaN(ultimoPrecoBRL)"), "um preço parado não pode entrar nos alarmes"
    pagina.wait_for_timeout(200)  # respostas que já estavam a caminho
    antes = pedidos(rede)
    pagina.wait_for_timeout(3000)  # 150 s acelerados: dólar e taxas teriam consultado, e o REST, várias vezes
    assert pedidos(rede) == antes, "com a janela oculta e sem alerta ativo não pode haver nenhuma requisição"
    assert texto(pagina, "#info-price").startswith("R$"), "o último valor continua na tela"

    rede.segurar_binance = True  # segura o REST para ver a tela esmaecida antes de o dado novo chegar
    definir_visibilidade(pagina, "visible")
    assert pagina.evaluate(FONTES) == {"precos": True, "taxas": True, "dolar": True}
    assert esmaecidos(pagina)["#info-price"] is True, "o valor antigo fica esmaecido até a fonte responder"
    rede.liberar_binance()
    esperar(lambda: not esmaecidos(pagina)["#info-price"], pagina)
    esperar(lambda: rede.contagem["dolar"] > antes[2] and rede.contagem["taxas"] > antes[3], pagina)
    esperar(lambda: rede.contagem["ws"] > antes[1], pagina)
    esperar(lambda: not any(esmaecidos(pagina).values()), pagina)
    assert not erros, erros
    contexto.close()


def test_app_oculto_com_alerta_ativo_mantem_so_os_precos_e_o_alerta_dispara(navegador):
    rede, contexto, pagina, erros = abrir(navegador, alertas=ALERTA_PERTO)
    estabilizar_websocket(rede, pagina)
    manter_vivo(rede, pagina, 500_000, 6)  # passa o silêncio após carregar

    definir_visibilidade(pagina, "hidden")
    assert pagina.evaluate(FONTES) == {"precos": True, "taxas": False, "dolar": False}
    assert pagina.evaluate("wsComUsdt") is False, "oculta, a conexão fica só com o BTC/BRL"
    manter_vivo(rede, pagina, 500_000, 4)  # respostas que já estavam a caminho (sem deixar a conexão em silêncio)
    _, conexoes, dolar, taxas = pedidos(rede)
    for _ in range(4):  # ~2,4 s: dólar e taxas teriam consultado
        manter_vivo(rede, pagina, 500_100, 10)
    assert pagina.evaluate("wsSaudavel"), "os preços continuam chegando pelo WebSocket"
    assert (rede.contagem["ws"], rede.contagem["dolar"], rede.contagem["taxas"]) == (conexoes, dolar, taxas)
    assert texto(pagina, "#info-price") == "R$ 500.100,00"

    manter_vivo(rede, pagina, 560_000, 3)
    pagina.wait_for_function("document.getElementById('dialogo').open", timeout=3000)
    assert "R$ 550.000,00" in texto(pagina, "#dialogo-conteudo")

    # Fechado o aviso, o alerta fica desativado: sem alerta ativo e ainda oculta, os preços param.
    pagina.evaluate("document.getElementById('dialogo').close()")
    esperar(lambda: pagina.evaluate("window.__alertasSalvos?.[0]?.tipo") == "desativado", pagina)
    esperar(lambda: pagina.evaluate(FONTES) == {"precos": False, "taxas": False, "dolar": False}, pagina)
    assert not erros, erros
    contexto.close()


def test_criar_alerta_e_o_que_decide_com_a_janela_oculta(navegador):
    """Sem alerta, oculta desliga os preços; com um alerta ativo criado antes, não."""
    rede, contexto, pagina, erros = abrir(navegador)
    definir_visibilidade(pagina, "hidden")
    assert pagina.evaluate("precosLigados") is False
    definir_visibilidade(pagina, "visible")
    assert pagina.evaluate("precosLigados") is True
    pagina.evaluate("gravarAlertas([{ id: 'x', valor: 1000, tipo: 'menor' }])")
    definir_visibilidade(pagina, "hidden")
    assert pagina.evaluate(FONTES) == {"precos": True, "taxas": False, "dolar": False}
    pagina.evaluate("gravarAlertas([{ id: 'x', valor: 1000, tipo: 'desativado' }])")
    assert pagina.evaluate("precosLigados") is False
    assert not erros, erros
    contexto.close()


def test_navegador_em_segundo_plano_continua_atualizando_o_titulo(navegador):
    """No navegador a aba oculta mostra o preço no título: nada é desligado."""
    rede, contexto, pagina, erros = abrir(navegador, app=False)
    estabilizar_websocket(rede, pagina)
    definir_visibilidade(pagina, "hidden")
    assert pagina.evaluate(FONTES) == {"precos": True, "taxas": True, "dolar": True}
    manter_vivo(rede, pagina, 612_345, 3)
    assert "612.345,00" in pagina.title()
    assert not erros, erros
    contexto.close()


def test_app_aberto_ja_oculto_mostra_o_1o_preco_e_so_depois_desliga(navegador):
    """A abertura nunca espera a visibilidade: o 1º preço aparece de qualquer jeito."""
    rede, contexto, pagina, erros = abrir(navegador, visibilidade="hidden")
    assert texto(pagina, "#info-price").startswith("R$")
    assert rede.contagem["binance"] >= 1
    esperar(lambda: pagina.evaluate(FONTES) == {"precos": False, "taxas": False, "dolar": False}, pagina)
    definir_visibilidade(pagina, "visible")
    assert pagina.evaluate(FONTES) == {"precos": True, "taxas": True, "dolar": True}
    assert not erros, erros
    contexto.close()


def test_pausa_continua_valendo_sobre_a_visibilidade(navegador):
    rede, contexto, pagina, erros = abrir(navegador, alertas=ALERTA_ATIVO_DISTANTE)
    pagina.click("#pausar-btn")
    assert pagina.evaluate(FONTES) == {"precos": False, "taxas": False, "dolar": False}
    definir_visibilidade(pagina, "hidden")
    definir_visibilidade(pagina, "visible")
    assert pagina.evaluate(FONTES) == {"precos": False, "taxas": False, "dolar": False}, "pausado não religa sozinho"
    pagina.click("#pausar-btn")
    assert pagina.evaluate(FONTES) == {"precos": True, "taxas": True, "dolar": True}
    assert not erros, erros
    contexto.close()


def test_grafico_sai_com_a_janela_oculta_e_volta_ao_reaparecer(navegador):
    rede, contexto, pagina, erros = abrir(navegador, acelerar=False)
    pagina.click("#grafico-btn")
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)
    definir_visibilidade(pagina, "hidden")
    assert pagina.evaluate("document.getElementById('grafico').childElementCount") == 0
    definir_visibilidade(pagina, "visible")
    pagina.wait_for_function("document.querySelector('#grafico iframe') !== null", timeout=10000)
    assert not erros, erros
    contexto.close()


def test_grafico_configurado_para_abrir_ainda_espera_a_ponte(navegador):
    """Ligar as fontes na abertura não pode montar o gráfico antes do load e da ponte."""
    rede, contexto, pagina, erros = abrir(navegador, acelerar=False, antes_de_abrir=com_grafico_ao_abrir)
    pagina.wait_for_function("'grafico_carregado' in Metricas.marcos", timeout=10000)
    marcos = pagina.evaluate("Metricas.marcos")
    assert marcos["nav_load"] <= marcos["api_python_pronta"] <= marcos["grafico_carregado"]
    assert not erros, erros
    contexto.close()


# ---------------------------------------------------------------------------
# Modo compacto
# ---------------------------------------------------------------------------

def test_modo_compacto_nao_busca_taxas_e_expandir_busca_na_hora(navegador):
    def compacto_salvo(contexto):
        contexto.add_init_script("localStorage.setItem('modoCompacto', '1');")
        com_estado_salvo(contexto)

    rede, contexto, pagina, erros = abrir(navegador, app=False, antes_de_abrir=compacto_salvo)
    assert pagina.evaluate("document.documentElement.classList.contains('compacto')")
    esperar(lambda: rede.contagem["dolar"] >= 2, pagina, limite_s=10)  # o dólar aparece no compacto e segue
    assert rede.contagem["taxas"] == 0, "as taxas não aparecem no modo compacto: não são buscadas"
    assert pagina.evaluate(FONTES) == {"precos": True, "taxas": False, "dolar": True}

    pagina.click("#compacto-btn")  # expande
    esperar(lambda: rede.contagem["taxas"] == 1, pagina)
    esperar(lambda: texto(pagina, "#fastestFee") == "3,40 sat/vB", pagina)
    esperar(lambda: not esmaecidos(pagina)["#fastestFee"], pagina)

    pagina.click("#compacto-btn")  # volta ao compacto
    assert pagina.evaluate("fontes.taxas.ligada") is False
    pagina.wait_for_timeout(200)
    depois = rede.contagem["taxas"]
    pagina.wait_for_timeout(2500)  # mais de 120 s acelerados
    assert rede.contagem["taxas"] == depois
    assert not erros, erros
    contexto.close()


def test_taxas_salvas_ficam_esmaecidas_ao_expandir_ate_a_resposta(navegador):
    def preparar(contexto):
        contexto.add_init_script("localStorage.setItem('modoCompacto', '1');")
        com_estado_salvo(contexto)
        contexto.route("https://mempool.space/**", lambda rota: None)  # nunca responde

    rede, contexto, pagina, erros = abrir(navegador, app=False, antes_de_abrir=preparar)
    pagina.click("#compacto-btn")
    assert esmaecidos(pagina)["#fastestFee"] is True
    assert texto(pagina, "#fastestFee").endswith("sat/vB"), "o valor salvo continua na tela"
    assert not erros, erros
    contexto.close()


# ---------------------------------------------------------------------------
# miniTicker
# ---------------------------------------------------------------------------

def test_websocket_assina_o_miniticker_dos_dois_pares(navegador):
    rede, contexto, pagina, erros = abrir(navegador, app=False)
    esperar(lambda: rede.urls_ws, pagina)
    url = rede.urls_ws[0]
    assert url.endswith("/stream?streams=btcbrl@miniTicker/btcusdt@miniTicker"), url
    assert "@ticker" not in url
    assert not erros, erros
    contexto.close()


# ---------------------------------------------------------------------------
# Janela oculta com alerta ativo: só o BTC/BRL
# (timers acelerados: a sonda de 5 s vira 100 ms e a vigia de 10 s, 200 ms)
# ---------------------------------------------------------------------------

STREAM_USDT = ["btcusdt@miniTicker"]


def grupo_esmaecido(pagina, grupo: str) -> bool:
    return pagina.evaluate("g => ui.grupos[g].every(e => e.classList.contains('desatualizado'))", grupo)


def abrir_oculto_com_alerta(navegador):
    """App com alerta ativo, recebendo pelo WebSocket, e a janela acaba de ser ocultada."""
    rede, contexto, pagina, erros = abrir(navegador, alertas=ALERTA_ATIVO_DISTANTE)
    estabilizar_websocket(rede, pagina)
    manter_vivo(rede, pagina, 500_000, 6)
    definir_visibilidade(pagina, "hidden")
    esperar(lambda: rede.controles, pagina)
    return rede, contexto, pagina, erros


def test_oculta_com_alerta_cancela_o_usdt_e_ao_reaparecer_assina_de_novo(navegador):
    rede, contexto, pagina, erros = abrir_oculto_com_alerta(navegador)
    assert rede.controles[0]["method"] == "UNSUBSCRIBE" and rede.controles[0]["params"] == STREAM_USDT
    assert pagina.evaluate("wsComUsdt") is False
    assert rede.contagem["ws"] == 1, "a troca é feita na conexão aberta, sem reconectar"
    rede.enviar_ticker("BTCBRL", 500_500)
    esperar(lambda: texto(pagina, "#info-price") == "R$ 500.500,00", pagina)

    definir_visibilidade(pagina, "visible")
    esperar(lambda: "SUBSCRIBE" in rede.metodos(), pagina)
    assinatura = next(m for m in rede.controles if m["method"] == "SUBSCRIBE")
    assert assinatura["params"] == STREAM_USDT
    assert len({m["id"] for m in rede.controles}) == len(rede.controles), "cada mensagem de controle tem um id próprio"
    # O dólar da tela é de antes de ocultar: esmaecido até o BTC/USDT voltar a chegar.
    assert grupo_esmaecido(pagina, "usdt") and grupo_esmaecido(pagina, "dolarImplicito")
    assert not grupo_esmaecido(pagina, "brl"), "o BTC/BRL nunca parou de chegar"
    rede.enviar_ticker("BTCUSDT", 100_100)
    esperar(lambda: not grupo_esmaecido(pagina, "usdt") and not grupo_esmaecido(pagina, "dolarImplicito"), pagina)
    assert rede.contagem["ws"] == 1
    assert contador(pagina, "ws:mensagem_invalida") == 0, "respostas de controle não são mensagens inválidas"
    assert not erros, erros
    contexto.close()


def test_so_com_brl_o_silencio_e_sondado_e_a_conexao_continua(navegador):
    """O BTC/BRL passa de 5 a 16 s calado: a resposta à sonda é o sinal de vida."""
    rede, contexto, pagina, erros = abrir_oculto_com_alerta(navegador)
    rest = rede.contagem["binance"]
    pagina.wait_for_timeout(1500)  # 75 s acelerados sem nenhum preço
    sondas = rede.metodos().count("LIST_SUBSCRIPTIONS")
    assert sondas >= 5, f"esperava uma sonda a cada ~5 s de silêncio, houve {sondas}"
    assert sondas <= 16, f"a sonda não pode virar tráfego constante: {sondas} em 75 s"
    assert rede.contagem["ws"] == 1 and pagina.evaluate("wsSaudavel"), "a conexão não pode ser dada como perdida"
    assert rede.contagem["binance"] == rest, "o REST continua parado"
    assert contador(pagina, "ws:queda:silencio") == 0
    assert contador(pagina, "ws:mensagem_invalida") == 0

    # Uma mensagem de preço adia a sonda: com preços chegando, quase não há sondas.
    for _ in range(25):
        rede.enviar_ticker("BTCBRL", 500_000)
        pagina.wait_for_timeout(40)
    assert rede.metodos().count("LIST_SUBSCRIPTIONS") - sondas <= 2
    assert not erros, erros
    contexto.close()


def test_sonda_sem_resposta_derruba_a_conexao_e_a_nova_ja_nasce_so_com_brl(navegador):
    rede, contexto, pagina, erros = abrir_oculto_com_alerta(navegador)
    rest = rede.contagem["binance"]
    rede.resposta_controle = None  # a conexão morreu sem fechar
    esperar(lambda: rede.contagem["ws"] >= 2, pagina, limite_s=8)
    assert contador(pagina, "ws:queda:silencio") >= 1
    assert rede.contagem["binance"] > rest, "sem o WebSocket, o REST volta para o alerta não ficar cego"
    assert rede.urls_ws[-1].endswith("/stream?streams=btcbrl@miniTicker"), rede.urls_ws[-1]
    rede.resposta_controle = "resultado"

    # De volta à tela: a conexão seguinte (ou a atual, por SUBSCRIBE) traz o BTC/USDT.
    antes = len(rede.controles)
    estabilizar_websocket(rede, pagina)
    definir_visibilidade(pagina, "visible")
    esperar(lambda: "SUBSCRIBE" in [m["method"] for m in rede.controles[antes:]], pagina)
    assert pagina.evaluate("wsComUsdt") is True
    assert not erros, erros
    contexto.close()


def test_conexao_aberta_com_a_pagina_visivel_assina_os_dois_e_nao_sonda(navegador):
    rede, contexto, pagina, erros = abrir(navegador, alertas=ALERTA_ATIVO_DISTANTE)
    estabilizar_websocket(rede, pagina)
    for _ in range(4):
        manter_vivo(rede, pagina, 500_000, 10)
    assert pagina.evaluate("wsComUsdt") is True
    assert rede.controles == [], "visível, nenhuma mensagem de controle é enviada"
    assert not erros, erros
    contexto.close()


def test_controle_recusado_pela_binance_reconecta(navegador):
    rede, contexto, pagina, erros = abrir(navegador, alertas=ALERTA_ATIVO_DISTANTE)
    estabilizar_websocket(rede, pagina)
    manter_vivo(rede, pagina, 500_000, 6)
    rede.resposta_controle = "erro"
    definir_visibilidade(pagina, "hidden")
    esperar(lambda: contador(pagina, "ws:queda:controle") >= 1, pagina)
    rede.resposta_controle = "resultado"
    esperar(lambda: rede.contagem["ws"] >= 2, pagina, limite_s=8)
    assert rede.urls_ws[-1].endswith("/stream?streams=btcbrl@miniTicker"), rede.urls_ws[-1]
    assert contador(pagina, "ws:mensagem_invalida") == 0
    assert not erros, erros
    contexto.close()


def test_pausar_com_a_conexao_so_de_brl_cancela_a_sonda(navegador):
    rede, contexto, pagina, erros = abrir_oculto_com_alerta(navegador)
    pagina.evaluate("gravarAlertas([{ id: 'a', valor: 1000, tipo: 'desativado' }])")  # sem alerta: preços param
    assert pagina.evaluate("precosLigados") is False
    assert pagina.evaluate("timers.wsSonda === 0 && timers.wsVigia === 0")
    pagina.wait_for_timeout(300)
    enviadas = len(rede.controles)
    pagina.wait_for_timeout(600)
    assert len(rede.controles) == enviadas
    assert not erros, erros
    contexto.close()


def enviar_mini(rede: RedeSimulada, simbolo: str, **campos) -> None:
    dados = {"e": "24hrMiniTicker", "E": 1, "s": simbolo, **campos}
    rede.sockets[-1].send(json.dumps({"stream": f"{simbolo.lower()}@miniTicker", "data": dados}))


def test_variacao_e_calculada_pela_abertura_do_miniticker(navegador):
    rede, contexto, pagina, erros = abrir(navegador, app=False)
    estabilizar_websocket(rede, pagina)
    enviar_mini(rede, "BTCBRL", c="510000.00", o="500000.00", h="520000.00", l="490000.00")
    esperar(lambda: texto(pagina, "#info-percent") == "2.00%", pagina)
    assert texto(pagina, "#info-price") == "R$ 510.000,00"
    enviar_mini(rede, "BTCBRL", c="485000.00", o="500000.00", h="520000.00", l="480000.00")
    esperar(lambda: texto(pagina, "#info-percent") == "-3.00%", pagina)
    # O USDT só usa preço, máxima e mínima.
    enviar_mini(rede, "BTCUSDT", c="100000.00", o="99000.00", h="101000.00", l="98000.00")
    esperar(lambda: texto(pagina, "#info-usdt") == "US$ 100.000,00", pagina)
    assert not erros, erros
    contexto.close()


def test_mensagem_sem_abertura_e_recusada_sem_mexer_na_tela(navegador):
    rede, contexto, pagina, erros = abrir(navegador, app=False)
    estabilizar_websocket(rede, pagina, preco=600_000)
    manter_vivo(rede, pagina, 600_000, 2)
    enviar_mini(rede, "BTCBRL", c="700000.00", h="710000.00", l="690000.00")  # sem "o"
    esperar(lambda: pagina.evaluate("Metricas.resumo().contadores['ws:mensagem_invalida'] ?? 0") >= 1, pagina)
    assert texto(pagina, "#info-price") == "R$ 600.000,00"
    contexto.close()


@pytest.mark.parametrize("tickers,esperado", [
    # Com a abertura, a página faz a mesma conta do WebSocket (e ignora o percentual pronto).
    ({"openPrice": "500000.00", "priceChangePercent": "9.990"}, "2.00%"),
    # Sem a abertura, vale o percentual que a Binance mandou.
    ({"priceChangePercent": "-0.570"}, "-0.57%"),
])
def test_rest_usa_a_abertura_e_cai_no_percentual_pronto(navegador, tickers, esperado):
    def rest_fixo(contexto):
        corpo = json.dumps([
            {"symbol": "BTCBRL", "lastPrice": "510000.00", "highPrice": "520000.00", "lowPrice": "490000.00", **tickers},
            {"symbol": "BTCUSDT", "lastPrice": "100000.00", "highPrice": "101000.00", "lowPrice": "99000.00", **tickers},
        ])
        contexto.route("https://api.binance.com/**", lambda rota: rota.fulfill(
            body=corpo, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}))

    rede, contexto, pagina, erros = abrir(navegador, app=False, antes_de_abrir=rest_fixo)
    assert texto(pagina, "#info-percent") == esperado
    assert not erros, erros
    contexto.close()


# ---------------------------------------------------------------------------
# Intervalos que acompanham as mudanças
# ---------------------------------------------------------------------------

def test_dolar_parado_alonga_o_intervalo_e_a_1a_mudanca_volta_ao_minimo(navegador):
    rede, contexto, pagina, erros = abrir(navegador, app=False)
    # 1ª consulta conta como mudança; a 2ª e a 3ª iguais ainda no mínimo; a 4ª dobra.
    esperar(lambda: pagina.evaluate("ritmoDolar.intervalo") >= 120_000, pagina, limite_s=15)
    assert rede.contagem["dolar"] >= 4
    assert pagina.evaluate("ritmoDolar.semMudanca") >= 3

    rede.dolar = {"USDBRL": {"bid": "5.10", "ask": "5.12"}}
    esperar(lambda: texto(pagina, "#dolar-comercial") == "R$ 5,11", pagina, limite_s=15)
    assert pagina.evaluate("ritmoDolar") == {"intervalo": 60_000, "semMudanca": 0}
    assert pagina.evaluate("DOLAR_INTERVALO_MIN") >= 60_000, "a AwesomeAPI não aceita menos de 60 s"
    assert not erros, erros
    contexto.close()


def test_taxas_paradas_espacam_as_consultas_e_uma_mudanca_as_aproxima(navegador):
    rede, contexto, pagina, erros = abrir(navegador, app=False)
    intervalo = "intervaloPorAtividade(historicoTaxas, { minimo: TAXAS_INTERVALO_MIN, maximo: TAXAS_INTERVALO_MAX, janela: TAXAS_JANELA })"
    assert pagina.evaluate("[TAXAS_INTERVALO_MIN, TAXAS_INTERVALO_MAX]") == [60_000, 300_000]
    # 1ª leitura conta como mudança; depois as taxas ficam iguais e o intervalo cresce.
    esperar(lambda: pagina.evaluate("historicoTaxas.length") >= 3, pagina, limite_s=20)
    assert pagina.evaluate("historicoTaxas")[1:] == [False] * (pagina.evaluate("historicoTaxas.length") - 1)
    parado = pagina.evaluate(intervalo)
    assert parado >= 180_000

    # Variação pequena (menos de 5%) não conta; uma de 10% conta e aproxima a próxima consulta.
    rede.taxas = {"fastestFee": 3.45, "halfHourFee": 2.1, "hourFee": 1.5, "minimumFee": 1}
    consultas = rede.contagem["taxas"]
    esperar(lambda: rede.contagem["taxas"] > consultas and texto(pagina, "#fastestFee") == "3,45 sat/vB", pagina, limite_s=20)
    assert pagina.evaluate("historicoTaxas.at(-1)") is False
    rede.taxas = {"fastestFee": 3.8, "halfHourFee": 2.1, "hourFee": 1.5, "minimumFee": 1}
    esperar(lambda: texto(pagina, "#fastestFee") == "3,80 sat/vB", pagina, limite_s=20)
    assert pagina.evaluate("historicoTaxas.at(-1)") is True
    assert pagina.evaluate(intervalo) < pagina.evaluate("TAXAS_INTERVALO_MAX")
    assert not erros, erros
    contexto.close()


def test_falha_do_dolar_ou_das_taxas_tenta_de_novo_no_intervalo_minimo(navegador):
    def falhar(contexto):
        contexto.route("https://economia.awesomeapi.com.br/**", lambda rota: rota.abort())
        contexto.route("https://mempool.space/**", lambda rota: rota.abort())

    rede, contexto, pagina, erros = abrir(navegador, app=False, antes_de_abrir=falhar)
    esperar(lambda: pagina.evaluate("falhasDolar >= 2 && falhasTaxas >= 2"), pagina, limite_s=10)  # 2 falhas em ~1,5 s
    assert pagina.evaluate("ritmoDolar.intervalo") == 60_000
    assert pagina.evaluate("historicoTaxas") == []
    contexto.close()


# ---------------------------------------------------------------------------
# Pré-conexões
# ---------------------------------------------------------------------------

def test_pagina_nao_abre_conexao_com_o_tradingview_sem_o_grafico(navegador):
    rede, contexto, pagina, erros = abrir(navegador, app=False, acelerar=False)
    html = pagina.content()
    assert 'rel="preconnect" href="https://s3.tradingview.com"' not in html
    assert pagina.evaluate("[...document.querySelectorAll('link[rel=preconnect]')].map(l => l.href)") == [
        "https://api.binance.com/", "https://economia.awesomeapi.com.br/", "https://mempool.space/"]
    assert not erros, erros
    contexto.close()
