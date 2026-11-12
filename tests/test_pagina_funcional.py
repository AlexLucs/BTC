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
    """No navegador aparecem Alertas, Gráfico (⇄) e Pausar, sem sobreposição; o gráfico abre
    oculto e ⇄ o mostra e o oculta."""
    contexto, pagina, erros = nova_pagina(navegador, RedeSimulada(), acelerar=False, com_alertas=False)
    pagina.goto(INDEX_URL)
    esperar_carregamento(pagina)
    visiveis = pagina.evaluate("[...document.querySelectorAll('.btns')].filter(b => getComputedStyle(b).display !== 'none').map(b => b.id)")
    assert sorted(visiveis) == ["alerta-btn", "grafico-btn", "pausar-btn"]
    caixas = [pagina.locator(f"#{id_}").bounding_box() for id_ in ("alerta-btn", "grafico-btn", "pausar-btn")]
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
