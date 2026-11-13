"""Analisa o metricas.jsonl gravado pelo BTC Status e imprime um relatório de desempenho.

Uso (na raiz do projeto):
    .venv\\Scripts\\python.exe tools\\analisar_metricas.py
    .venv\\Scripts\\python.exe tools\\analisar_metricas.py --ultimas 5
    .venv\\Scripts\\python.exe tools\\analisar_metricas.py --sessoes 3fa2 9b1c --json resumo.json

Seções do relatório:
1. Abertura: cada etapa em ms desde a criação do processo (mediana, mínimo e máximo entre as sessões).
2. Funções, rede e Python: duração das funções medidas (n, média, p50, p95, máximo).
3. Contadores, tarefas longas (> 50 ms) e memória do JS.
4. Janela minimizada: se a página percebe (visibilidade) e quanto os timers atrasam.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metricas import NOME_ARQUIVO, estatisticas  # noqa: E402

ARQUIVO_PADRAO = Path(os.getenv("APPDATA") or Path.home()) / "btcstatus" / NOME_ARQUIVO

# Etapas da abertura: (origem, marco, descrição). O relatório as ordena pelo tempo medido.
ETAPAS_ABERTURA = [
    ("py", "inicio_script", "Python começa o script (bootloader + interpretador)"),
    ("py", "imports_concluidos", "Imports concluídos (inclui pywebview)"),
    ("py", "preco_python_inicio", "Python começa a buscar o 1º preço (thread)"),
    ("py", "log_configurado", "Log configurado"),
    ("py", "posicao_calculada", "Posição calculada (1º webview.screens: inicia o .NET)"),
    ("py", "janela_criada", "create_window concluído"),
    ("py", "webview_start", "webview.start chamado"),
    ("py", "evento_initialized", "Evento initialized"),
    ("py", "evento_before_show", "Evento before_show"),
    ("py", "evento_shown", "Janela exibida (shown)"),
    ("py", "tamanho_ajustado", "Tamanho da janela corrigido (moldura do frameless)"),
    ("js", "navegacao", "Página começa a carregar (timeOrigin)"),
    ("js", "nav_resposta_fim", "index.html recebido"),
    ("js", "script_inicio", "metricas.js/script.js começam"),
    ("js", "primeiro_quadro", "1º quadro (requestAnimationFrame)"),
    ("js", "fontes_prontas", "Fonte Roboto carregada"),
    ("js", "estado_restaurado", "Último estado salvo na tela"),
    ("js", "conteudo_visivel", "Tela de carregamento some"),
    ("js", "first-paint", "Primeira pintura"),
    ("js", "first-contentful-paint", "Primeira pintura com conteúdo"),
    ("js", "dom_pronto", "DOMContentLoaded"),
    ("js", "nav_load", "Evento load da página (libera a ponte do pywebview)"),
    ("js", "inicializacao_js_concluida", "Inicialização do script.js concluída"),
    ("py", "evento_loaded", "Evento loaded (Python)"),
    ("js", "api_python_pronta", "Ponte JS→Python pronta"),
    ("js", "alertas_sincronizados", "Alertas lidos do disco"),
    ("js", "ws_conectado", "WebSocket da Binance conectado"),
    ("js", "ws_primeiro_preco", "1º preço pelo WebSocket"),
    ("py", "preco_python_resposta", "1º preço recebido pelo Python"),
    ("py", "preco_python_falha", "1º preço pelo Python falhou"),
    ("py", "servidor_preco_no_html", "Servidor põe o 1º preço no HTML"),
    ("js", "preco_no_html", "Página lê o 1º preço do HTML"),
    ("js", "preco_inicial_pedido", "Página pede /preco-inicial"),
    ("js", "preco_inicial_resposta", "Resposta de /preco-inicial chega"),
    ("js", "preco_inicial_dados", "Dados de /preco-inicial lidos (json)"),
    ("js", "precos_continuacao", "Código do preço volta a rodar com os dados"),
    ("js", "primeira_resposta_binance", "1ª resposta da Binance (Python ou REST)"),
    ("js", "primeiro_preco", "1º preço na tela (fim do carregamento)"),
    ("js", "grafico_carregado", "Gráfico do TradingView carregado"),
]

JANELA_VISIBILIDADE_S = 3.0  # tolerância (±) para casar "minimized" (Python) com "hidden" (JS)


def ler_registros(arquivo: Path) -> list[dict[str, Any]]:
    """Lê o arquivo e a cópia rotacionada (.1), ignorando linhas inválidas."""
    registros: list[dict[str, Any]] = []
    for caminho in (arquivo.with_name(arquivo.name + ".1"), arquivo):
        if not caminho.is_file():
            continue
        with open(caminho, encoding="utf-8") as entrada:
            for numero, linha in enumerate(entrada, 1):
                try:
                    registros.append(json.loads(linha))
                except json.JSONDecodeError:
                    print(f"Aviso: linha {numero} inválida em {caminho.name}", file=sys.stderr)
    return registros


def agrupar_sessoes(registros: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    sessoes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for registro in registros:
        sessoes[registro.get("sessao", "?")].append(registro)
    return dict(sessoes)


def selecionar(sessoes: dict[str, list], prefixos: list[str] | None, ultimas: int | None) -> dict[str, list]:
    ordenadas = sorted(sessoes.items(), key=lambda item: item[1][0].get("epoch", 0))
    if prefixos:
        ordenadas = [(s, r) for s, r in ordenadas if any(s.startswith(p) for p in prefixos)]
    if ultimas:
        ordenadas = ordenadas[-ultimas:]
    return dict(ordenadas)


def relatorios_js(registros: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r["relatorio"] for r in registros if r.get("tipo") == "js" and isinstance(r.get("relatorio"), dict)]


# ---------------------------------------------------------------------------
# 1. Abertura
# ---------------------------------------------------------------------------

def linha_do_tempo_abertura(registros: list[dict[str, Any]]) -> dict[str, float]:
    """Etapas da abertura em ms desde a criação do processo (ou do início do script)."""
    python = next((r for r in registros if r.get("tipo") == "abertura_python"), None)
    js = relatorios_js(registros)
    marcos_js = {}
    origem_js = None
    for relatorio in js:  # o 1º relatório tem quase tudo; os seguintes completam (ex.: gráfico)
        origem_js = origem_js or relatorio.get("timeOrigin")
        for nome, valor in (relatorio.get("marcos") or {}).items():
            marcos_js.setdefault(nome, valor)

    if python is None:
        return {}
    inicio_script = python["inicio_script_epoch"]
    base = python.get("inicio_processo_epoch") or inicio_script

    tempos: dict[str, float] = {"inicio_script": (inicio_script - base) * 1000}
    for nome, valor in (python.get("marcos_ms") or {}).items():
        tempos[nome] = (inicio_script - base) * 1000 + valor
    if origem_js:
        deslocamento = origem_js - base * 1000
        tempos["navegacao"] = deslocamento
        for nome, valor in marcos_js.items():
            tempos[nome] = deslocamento + valor
    return tempos


def etapas_dos_arquivos(por_etapa: dict[str, list[float]]) -> list[tuple[str, str, str]]:
    """Marcos dos arquivos da própria página: recurso_inicio:/recurso:<arquivo> (metricas.js) e
    servidor_pedido:/servidor_fim:<arquivo> (servidor_local.py, lado do Python)."""
    etapas = []
    for nome in sorted(por_etapa):
        if nome.startswith("recurso_inicio:"):
            etapas.append(("js", nome, f"{nome.split(':', 1)[1]}: pedido"))
        elif nome.startswith("recurso:"):
            etapas.append(("js", nome, f"{nome.split(':', 1)[1]}: recebido"))
        elif nome.startswith("servidor_pedido:"):
            etapas.append(("py", nome, f"{nome.split(':', 1)[1]}: servidor recebe o pedido"))
        elif nome.startswith("servidor_fim:"):
            etapas.append(("py", nome, f"{nome.split(':', 1)[1]}: servidor termina de enviar"))
    return etapas


def secao_abertura(sessoes: dict[str, list]) -> dict[str, Any]:
    por_etapa: dict[str, list[float]] = defaultdict(list)
    tipos = set()
    sem_inicio_processo = 0
    for registros in sessoes.values():
        tempos = linha_do_tempo_abertura(registros)
        python = next((r for r in registros if r.get("tipo") == "abertura_python"), {})
        tipos.add("exe" if python.get("congelado") else "python")
        if python and not python.get("inicio_processo_epoch"):
            sem_inicio_processo += 1
        for nome, valor in tempos.items():
            por_etapa[nome].append(valor)

    print("\n== 1. Abertura (ms desde a criação do processo) ==")
    if not por_etapa:
        print("Nenhuma sessão com dados de abertura.")
        return {}
    print(f"Sessões: {len(sessoes)} | modo: {', '.join(sorted(tipos))}")
    if sem_inicio_processo:
        print(f"Atenção: {sem_inicio_processo} sessão(ões) sem o início do processo; nelas o zero é o início do script.")
    print(f"{'Etapa':<55} {'mediana':>9} {'mín':>9} {'máx':>9} {'Δ etapa':>9}")
    # Ordena pela mediana: algumas etapas se sobrepõem (ex.: Python e página em paralelo).
    linhas = sorted(
        ((statistics.median(por_etapa[nome]), origem, nome, descricao)
         for origem, nome, descricao in ETAPAS_ABERTURA + etapas_dos_arquivos(por_etapa) if por_etapa.get(nome)),
    )
    resultado = {}
    anterior = 0.0
    for mediana, origem, nome, descricao in linhas:
        valores = por_etapa[nome]
        delta = mediana - anterior
        anterior = mediana
        resultado[nome] = {"mediana": round(mediana, 1), "min": round(min(valores), 1), "max": round(max(valores), 1), "n": len(valores)}
        print(f"[{origem}] {descricao:<50} {mediana:>9.0f} {min(valores):>9.0f} {max(valores):>9.0f} {delta:>+9.0f}")
    return resultado


def secao_bloqueios(sessoes: dict[str, list]) -> dict[str, Any]:
    """Momentos em que a thread da página ficou ocupada (> 15 ms) nos primeiros 2 s (metricas.js)."""
    resultado = {}
    linhas = []
    for sessao, registros in sessoes.items():
        python = next((r for r in registros if r.get("tipo") == "abertura_python"), None)
        js = relatorios_js(registros)
        if python is None or not js:
            continue
        base = python.get("inicio_processo_epoch") or python["inicio_script_epoch"]
        deslocamento = (js[0].get("timeOrigin") or 0) - base * 1000
        pontos = [(inicio + deslocamento, duracao) for relatorio in js for inicio, duracao in (relatorio.get("bloqueios") or [])]
        resultado[sessao] = pontos
        texto = ", ".join(f"{inicio:.0f} (+{duracao:.0f})" for inicio, duracao in sorted(pontos)) or "nenhum"
        linhas.append(f"  {sessao[:8]}: {texto}")
    if resultado:
        print("\n== 1b. Thread da página ocupada na abertura (> 15 ms): início em ms desde a criação do processo (+duração) ==")
        print("\n".join(linhas))
    return resultado


# ---------------------------------------------------------------------------
# 2. Funções, rede e Python
# ---------------------------------------------------------------------------

def secao_funcoes(sessoes: dict[str, list]) -> dict[str, Any]:
    amostras_js: dict[str, list[float]] = defaultdict(list)
    amostras_py: dict[str, list[float]] = defaultdict(list)
    for registros in sessoes.values():
        for relatorio in relatorios_js(registros):
            for nome, valores in (relatorio.get("amostras") or {}).items():
                if nome != "memoria_mb":
                    amostras_js[nome].extend(valores)
        for registro in registros:
            if registro.get("tipo") == "api_python":
                for nome, valores in (registro.get("amostras") or {}).items():
                    amostras_py[nome].extend(valores)

    resultado = {}
    print("\n== 2. Funções, rede e Python (ms) ==")
    print(f"{'Medida':<40} {'n':>6} {'média':>9} {'p50':>9} {'p95':>9} {'máx':>9}")
    for titulo, grupo in (("Página (JS)", amostras_js), ("Métodos da ExposedApi (Python)", amostras_py)):
        if not grupo:
            continue
        print(f"-- {titulo}")
        for nome in sorted(grupo):
            est = estatisticas(grupo[nome])
            resultado[f"{'js' if grupo is amostras_js else 'py'}:{nome}"] = est
            print(f"{nome:<40} {est['n']:>6} {est['media']:>9.2f} {est['p50']:>9.2f} {est['p95']:>9.2f} {est['max']:>9.2f}")
    if not resultado:
        print("Nenhuma amostra.")
    return resultado


# ---------------------------------------------------------------------------
# 3. Contadores, tarefas longas e memória
# ---------------------------------------------------------------------------

def secao_contadores(sessoes: dict[str, list]) -> dict[str, Any]:
    contadores: dict[str, int] = defaultdict(int)
    tarefas: list[float] = []
    memoria: dict[str, list[float]] = {}
    for sessao, registros in sessoes.items():
        pontos = []
        for relatorio in relatorios_js(registros):
            for nome, valor in (relatorio.get("contadores") or {}).items():
                contadores[nome] += valor
            tarefas.extend(duracao for _, duracao in relatorio.get("tarefasLongas") or [])
            pontos.extend(valor for _, valor in (relatorio.get("linhaTempo") or {}).get("memoria_mb", []))
            if relatorio.get("memoriaMb") is not None:
                pontos.append(relatorio["memoriaMb"])
        if pontos:
            memoria[sessao] = pontos

    print("\n== 3. Contadores, tarefas longas e memória ==")
    for nome in sorted(contadores):
        print(f"{nome:<40} {contadores[nome]:>8}")
    est_tarefas = estatisticas(tarefas)
    if tarefas:
        print(f"Tarefas longas (> 50 ms): {est_tarefas['n']} | p50 {est_tarefas['p50']:.0f} ms | máx {est_tarefas['max']:.0f} ms")
    else:
        print("Tarefas longas (> 50 ms): nenhuma")
    for sessao, pontos in memoria.items():
        print(f"Memória JS sessão {sessao[:8]}: início {pontos[0]:.1f} MB | máx {max(pontos):.1f} MB | fim {pontos[-1]:.1f} MB ({len(pontos)} leituras)")
    return {"contadores": dict(contadores), "tarefas_longas": est_tarefas,
            "memoria_mb": {s: {"inicio": p[0], "max": max(p), "fim": p[-1]} for s, p in memoria.items()}}


# ---------------------------------------------------------------------------
# 4. Janela minimizada
# ---------------------------------------------------------------------------

def intervalos_minimizada(registros: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Períodos (epoch s) entre "minimized" e "restored" registrados pelo Python."""
    eventos = sorted((r["epoch"], r["evento"]) for r in registros if r.get("tipo") == "janela")
    periodos, inicio = [], None
    for momento, evento in eventos:
        if evento == "minimized" and inicio is None:
            inicio = momento
        elif evento == "restored" and inicio is not None:
            periodos.append((inicio, momento))
            inicio = None
    return periodos


def secao_minimizada(sessoes: dict[str, list]) -> dict[str, Any]:
    print("\n== 4. Janela minimizada ==")
    casados = nao_casados = 0
    atraso_min: list[float] = []
    atraso_normal: list[float] = []
    for registros in sessoes.values():
        periodos = intervalos_minimizada(registros)
        ocultos = [e["t"] / 1000 for rel in relatorios_js(registros) for e in rel.get("eventos") or []
                   if e.get("tipo") == "visibilidade" and e.get("estado") == "hidden"]
        for inicio, _ in periodos:
            # Simétrico: o "hidden" da página pode chegar antes do "minimized" do Python.
            if any(abs(t - inicio) <= JANELA_VISIBILIDADE_S for t in ocultos):
                casados += 1
            else:
                nao_casados += 1
        for relatorio in relatorios_js(registros):
            for nome, pontos in (relatorio.get("linhaTempo") or {}).items():
                if not nome.startswith("atraso_timer:"):
                    continue
                for momento_ms, valor in pontos:
                    momento = momento_ms / 1000
                    minimizado = any(inicio <= momento <= fim for inicio, fim in periodos)
                    (atraso_min if minimizado else atraso_normal).append(valor)

    if casados + nao_casados == 0:
        print("Nenhum minimizar/restaurar registrado. Para este teste, minimize a janela por 1–2 min e restaure.")
    else:
        resposta = "sim" if nao_casados == 0 else ("não" if casados == 0 else "às vezes")
        print(f"A página recebe visibilityState='hidden' ao minimizar? {resposta} ({casados} de {casados + nao_casados})")
    normal, minimizada = estatisticas(atraso_normal), estatisticas(atraso_min)
    for rotulo, est in (("visível", normal), ("minimizada", minimizada)):
        if est["n"]:
            print(f"Atraso dos timers com a janela {rotulo:<10}: n {est['n']:>5} | p50 {est['p50']:>8.1f} ms | p95 {est['p95']:>8.1f} ms | máx {est['max']:>8.1f} ms")
    return {"hidden_ao_minimizar": {"casados": casados, "nao_casados": nao_casados},
            "atraso_timer_visivel": normal, "atraso_timer_minimizada": minimizada}


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Relatório de desempenho do BTC Status")
    parser.add_argument("--arquivo", type=Path, default=ARQUIVO_PADRAO, help="caminho do metricas.jsonl")
    parser.add_argument("--sessoes", nargs="*", help="prefixos dos ids das sessões a incluir")
    parser.add_argument("--ultimas", type=int, help="considera só as N sessões mais recentes")
    parser.add_argument("--json", type=Path, help="também grava o resumo neste arquivo JSON")
    opcoes = parser.parse_args(argumentos)

    registros = ler_registros(opcoes.arquivo)
    if not registros:
        print(f"Nenhum registro em {opcoes.arquivo}")
        return 1
    sessoes = selecionar(agrupar_sessoes(registros), opcoes.sessoes, opcoes.ultimas)
    if not sessoes:
        print("Nenhuma sessão corresponde ao filtro.")
        return 1

    print(f"Arquivo: {opcoes.arquivo} | sessões analisadas: {len(sessoes)}")
    for sessao, lista in sessoes.items():
        print(f"  {sessao[:8]}  {lista[0].get('quando', '?')}  ({len(lista)} registros)")

    resumo = {
        "sessoes": list(sessoes),
        "abertura": secao_abertura(sessoes),
        "bloqueios": secao_bloqueios(sessoes),
        "funcoes": secao_funcoes(sessoes),
        "contadores": secao_contadores(sessoes),
        "minimizada": secao_minimizada(sessoes),
    }
    if opcoes.json:
        opcoes.json.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nResumo gravado em {opcoes.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
