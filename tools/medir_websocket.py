"""Compara as portas 9443 e 443 do stream da Binance (rede real).

Abre o WebSocket várias vezes em cada porta, alternando as portas para que
variações da rede afetem as duas por igual, e mede:
- conexão: do new WebSocket até o "open" (DNS + TCP + TLS + upgrade);
- 1ª mensagem: do new WebSocket até o 1º ticker (BTC/BRL ou BTC/USDT).

Usa o Microsoft Edge pelo Playwright (mesmo motor do WebView2).

Uso (na raiz do projeto):
    .venv\\Scripts\\python.exe tools\\medir_websocket.py
    .venv\\Scripts\\python.exe tools\\medir_websocket.py --vezes 15

Se a 443 for claramente mais rápida, troque a porta em URL_WS_TICKERS (script.js)
e em connect-src (CSP do index.html).
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metricas import estatisticas  # noqa: E402

STREAMS = "btcbrl@ticker/btcusdt@ticker"
PORTAS = (9443, 443)

MEDIR = """async (url) => {
    const inicio = performance.now();
    return await new Promise(resolve => {
        const resultado = { conexao: null, primeira: null, erro: null };
        const ws = new WebSocket(url);
        const limite = setTimeout(() => { resultado.erro = 'tempo esgotado'; ws.close(); resolve(resultado); }, 15000);
        ws.onopen = () => { resultado.conexao = performance.now() - inicio; };
        ws.onmessage = () => {
            resultado.primeira = performance.now() - inicio;
            clearTimeout(limite); ws.close(); resolve(resultado);
        };
        ws.onerror = () => { resultado.erro = 'erro'; };
        ws.onclose = () => { clearTimeout(limite); resolve(resultado); };
    });
}"""


def abrir_navegador(playwright):
    for canal in ("msedge", "chrome", None):
        try:
            return playwright.chromium.launch(channel=canal) if canal else playwright.chromium.launch()
        except Exception:  # noqa: BLE001 - tenta o próximo
            continue
    raise SystemExit("Nenhum navegador encontrado (Edge, Chrome ou Chromium do Playwright).")


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compara as portas do WebSocket da Binance")
    parser.add_argument("--vezes", type=int, default=10, help="conexões por porta")
    opcoes = parser.parse_args(argumentos)

    from playwright.sync_api import sync_playwright

    resultados = {porta: {"conexao": [], "primeira": [], "erros": 0} for porta in PORTAS}
    with sync_playwright() as playwright:
        navegador = abrir_navegador(playwright)
        pagina = navegador.new_page()
        pagina.goto("about:blank")
        for rodada in range(opcoes.vezes):
            for porta in (PORTAS if rodada % 2 == 0 else PORTAS[::-1]):  # alterna a ordem
                url = f"wss://stream.binance.com:{porta}/stream?streams={STREAMS}"
                medida = pagina.evaluate(MEDIR, url)
                if medida["erro"] or medida["conexao"] is None:
                    resultados[porta]["erros"] += 1
                    print(f"  porta {porta}: falhou ({medida['erro']})")
                    continue
                resultados[porta]["conexao"].append(medida["conexao"])
                if medida["primeira"] is not None:
                    resultados[porta]["primeira"].append(medida["primeira"])
                pagina.wait_for_timeout(300)
        navegador.close()

    print(f"\n{'Porta':<6} {'n':>3} {'conexão p50':>12} {'p95':>8} {'1ª msg p50':>11} {'p95':>8} {'falhas':>7}")
    for porta, dados in resultados.items():
        conexao, primeira = estatisticas(dados["conexao"]), estatisticas(dados["primeira"])
        if not conexao["n"]:
            print(f"{porta:<6}   0 {'—':>12} {'—':>8} {'—':>11} {'—':>8} {dados['erros']:>7}")
            continue
        print(f"{porta:<6} {conexao['n']:>3} {conexao['p50']:>10.0f}ms {conexao['p95']:>6.0f}ms "
              f"{primeira.get('p50', float('nan')):>9.0f}ms {primeira.get('p95', float('nan')):>6.0f}ms {dados['erros']:>7}")

    a, b = (resultados[p]["conexao"] for p in PORTAS)
    if a and b:
        diferenca = statistics.median(b) - statistics.median(a)
        mais_rapida = PORTAS[1] if diferenca < 0 else PORTAS[0]
        print(f"\nDiferença das medianas de conexão: {abs(diferenca):.0f} ms a favor da porta {mais_rapida}.")
        print("Só vale trocar se a diferença for grande (> ~50 ms) e se repetir em outra execução.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
