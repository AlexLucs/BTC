"""Mede quanto demora a requisição do 1º preço (rede real), comparando endereços da Binance.

Uso (só no Windows; precisa de internet):
    .venv\\Scripts\\python.exe tools\\medir_primeiro_preco.py --vezes 10

A requisição é a mesma do app: baixar_winhttp.baixar, uma conexão nova por chamada (DNS,
TCP, TLS e resposta), como numa abertura. Os candidatos são medidos em rodízio, para a
variação da rede ao longo do tempo pesar igual em todos. A 1ª rodada é mostrada à parte
(inclui o DNS ainda fora do cache).

Serve para decidir se vale trocar o endereço em primeiro_preco.py: o 1º preço só entra no
HTML se chegar antes de a página ser pedida (~600 ms depois da criação do processo).

Só biblioteca padrão. Não entra no executável.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baixar_winhttp import baixar  # noqa: E402
from primeiro_preco import TIMEOUT_S, URL_TICKERS  # noqa: E402

SIMBOLOS = quote('["BTCBRL","BTCUSDT"]', safe="")
CAMINHO = "/api/v3/ticker/24hr?symbols=" + SIMBOLOS
# Campos que o script.js lê de cada par (aplicar os tickers).
CAMPOS_DA_PAGINA = ("lastPrice", "priceChangePercent", "highPrice", "lowPrice")
PARES = ("BTCBRL", "BTCUSDT")


def candidatos() -> dict[str, str]:
    """Nome -> URL. O primeiro é o endereço que o app usa hoje."""
    return {
        "atual (api.binance.com)": URL_TICKERS,
        "api.binance.com, type=MINI": "https://api.binance.com" + CAMINHO + "&type=MINI",
        "data-api.binance.vision": "https://data-api.binance.vision" + CAMINHO,
        "api1.binance.com": "https://api1.binance.com" + CAMINHO,
    }


def campos_faltando(corpo: bytes) -> list[str]:
    """Campos que a página usa e que a resposta não traz (lista vazia: serve como está)."""
    try:
        dados = json.loads(corpo)
    except ValueError:
        return ["resposta que nao e JSON"]
    if not isinstance(dados, list):
        return ["resposta que nao e uma lista"]
    por_par = {item.get("symbol"): item for item in dados if isinstance(item, dict)}
    faltando = [par for par in PARES if par not in por_par]
    for par in PARES:
        if par in por_par:
            faltando += [f"{par}.{campo}" for campo in CAMPOS_DA_PAGINA if campo not in por_par[par]]
    return faltando


def resumo(tempos_ms: list[float]) -> str:
    """Mediana, mínimo e máximo, em ms."""
    if not tempos_ms:
        return "sem medidas"
    return f"mediana {statistics.median(tempos_ms):6.0f}   min {min(tempos_ms):6.0f}   max {max(tempos_ms):6.0f}"


def medir(url: str, timeout_s: float) -> tuple[float, bytes | None, str]:
    """Uma requisição: (duração em ms, corpo ou None, erro ou "")."""
    inicio = time.perf_counter()
    try:
        corpo = baixar(url, timeout_s)
        return (time.perf_counter() - inicio) * 1000, corpo, ""
    except (OSError, ValueError) as erro:
        return (time.perf_counter() - inicio) * 1000, None, str(erro)


def main(argumentos: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description="Mede a requisição do 1º preço em vários endereços.")
    analisador.add_argument("--vezes", type=int, default=10, help="rodadas depois da 1ª (padrão: 10)")
    analisador.add_argument("--inverter", action="store_true",
                            help="mede os endereços na ordem inversa (o 1º da 1ª rodada paga o custo de "
                                 "carregar o WinHTTP no processo)")
    opcoes = analisador.parse_args(argumentos)
    if sys.platform != "win32":
        print("Esta medicao usa o WinHTTP: so funciona no Windows.")
        return 1

    urls = candidatos()
    if opcoes.inverter:
        urls = dict(reversed(urls.items()))
    primeira: dict[str, float] = {}
    tempos: dict[str, list[float]] = {nome: [] for nome in urls}
    erros: dict[str, list[str]] = {nome: [] for nome in urls}
    observacoes: dict[str, str] = {}
    for rodada in range(opcoes.vezes + 1):
        for nome, url in urls.items():
            duracao, corpo, erro = medir(url, TIMEOUT_S)
            if erro:
                erros[nome].append(erro)
                continue
            if rodada == 0:
                primeira[nome] = duracao
                faltando = campos_faltando(corpo)
                observacoes[nome] = (f"{len(corpo)} bytes; "
                                     + ("tem todos os campos da pagina" if not faltando
                                        else "FALTAM campos da pagina: " + ", ".join(faltando)))
            else:
                tempos[nome].append(duracao)
        print(f"rodada {rodada}/{opcoes.vezes} concluida", flush=True)

    print("\nRequisicao do 1o preco (ms; conexao nova a cada chamada)")
    for nome in urls:
        print(f"\n{nome}")
        print(f"  {resumo(tempos[nome])}   ({len(tempos[nome])} medidas)")
        if nome in primeira:
            print(f"  1a rodada: {primeira[nome]:.0f} ms | {observacoes[nome]}")
        if erros[nome]:
            print(f"  {len(erros[nome])} falha(s); ultima: {erros[nome][-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
