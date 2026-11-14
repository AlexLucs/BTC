"""Abre o BTC Status várias vezes seguidas e mede a abertura de cada uma.

Cada execução recebe um id de sessão (variável BTC_SESSAO_METRICAS). O script
espera o relatório "abertura" da página chegar ao metricas.jsonl, fecha o app
e, no fim, imprime o relatório só dessas sessões (tools/analisar_metricas.py).

Uso (na raiz do projeto, com o app fechado):
    .venv\\Scripts\\python.exe tools\\medir_abertura.py                 # 5 vezes, pelo Python do venv
    .venv\\Scripts\\python.exe tools\\medir_abertura.py --vezes 10
    .venv\\Scripts\\python.exe tools\\medir_abertura.py --exe "dist\\BTC Monitor\\BTC Monitor.exe"
    (o --exe exige o build com medição:  .\\criar_exe_btc.ps1 -ComMedicao)
    .venv\\Scripts\\python.exe tools\\medir_abertura.py --comparar preconnect --vezes 20
    .venv\\Scripts\\python.exe tools\\medir_abertura.py --comparar preco-python --vezes 20
    (metade das aberturas sem o recurso, alternadas; no fim, uma tabela compara as duas
     metades. --comparar-preconnect é o mesmo que --comparar preconnect)
    .venv\\Scripts\\python.exe tools\\medir_abertura.py --comparar-argumentos rede --vezes 20
    (o mesmo, com e sem OUTROS argumentos do WebView2, além dos adotados pelo app em
     argumentos_webview2.py: um grupo de lá ou os próprios argumentos entre aspas)

Observações:
- O app é encerrado à força (sem o evento de fechamento), então a posição da
  janela não é salva nessas execuções.
- A 1ª execução após ligar o PC (ou após um build) costuma ser mais lenta:
  é a abertura "fria". Compare a 1ª com as demais.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tools"))

import analisar_metricas  # noqa: E402
import argumentos_webview2  # noqa: E402
from metricas import VARIAVEL_SESSAO  # noqa: E402


def encerrar(processo: subprocess.Popen) -> None:
    """Fecha o app e os processos filhos (WebView2)."""
    if processo.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(processo.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        processo.kill()
    try:
        processo.wait(timeout=10)
    except subprocess.TimeoutExpired:
        processo.kill()


def esperar_abertura(arquivo: Path, inicio_leitura: int, sessao: str, limite_s: float) -> bool:
    """Espera um registro "js" com motivo "abertura" desta sessão a partir da posição inicial do arquivo."""
    prazo = time.monotonic() + limite_s
    posicao = inicio_leitura
    while time.monotonic() < prazo:
        if arquivo.is_file():
            with open(arquivo, encoding="utf-8") as entrada:
                entrada.seek(posicao)
                for linha in entrada:
                    if sessao not in linha:
                        continue
                    try:
                        registro = json.loads(linha)
                    except json.JSONDecodeError:
                        continue
                    if registro.get("tipo") == "js" and registro.get("relatorio", {}).get("motivo") == "abertura":
                        return True
        time.sleep(0.25)
    return False


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mede a abertura do BTC Status N vezes")
    parser.add_argument("--vezes", type=int, default=5)
    parser.add_argument("--exe", type=Path, help="executável gerado pelo PyInstaller (padrão: BTC_Monitor.py com este Python)")
    parser.add_argument("--limite", type=float, default=60.0, help="segundos máximos de espera por execução")
    parser.add_argument("--pausa", type=float, default=3.0, help="segundos entre uma execução e outra")
    parser.add_argument("--arquivo", type=Path, default=analisar_metricas.ARQUIVO_PADRAO)
    parser.add_argument("--comparar", choices=sorted(COMPARACOES),
                        help="alterna aberturas com e sem o recurso e compara as duas metades")
    parser.add_argument("--comparar-preconnect", action="store_const", dest="comparar", const="preconnect",
                        help="o mesmo que --comparar preconnect")
    parser.add_argument("--comparar-argumentos", metavar="GRUPO_OU_ARGUMENTOS",
                        help=f"alterna aberturas com e sem argumentos extras do WebView2 "
                             f"(grupo: {', '.join(argumentos_webview2.GRUPOS)}; ou os argumentos entre aspas)")
    opcoes = parser.parse_args(argumentos)
    if opcoes.comparar and opcoes.comparar_argumentos:
        parser.error("use --comparar ou --comparar-argumentos, um de cada vez")
    if opcoes.comparar_argumentos:
        try:
            extras = argumentos_webview2.resolver(opcoes.comparar_argumentos)
        except ValueError as erro:
            parser.error(str(erro))
        return comparar(opcoes, "Outros argumentos do WebView2", ambiente_dos_argumentos(extras))
    if opcoes.comparar:
        variavel, titulo = COMPARACOES[opcoes.comparar]
        return comparar(opcoes, titulo, lambda sem: {variavel: "1" if sem else "0"})

    sessoes: list[str] = []
    for indice in range(1, opcoes.vezes + 1):
        sessao = abrir_e_medir(opcoes, indice, ambiente_extra={})
        if sessao:
            sessoes.append(sessao)

    if not sessoes:
        avisar_sem_relatorio(opcoes)
        return 1
    print()
    return analisar_metricas.main(["--arquivo", str(opcoes.arquivo), "--sessoes", *sessoes])


# Com o perfil persistente (private_mode=False), o pywebview serve a página por um servidor
# HTTP local sempre na mesma porta (settings["DEFAULT_HTTP_PORT"] = 42001 no pywebview 6.2.1).
# No Windows o servidor dele aceita abrir a porta mesmo ocupada (SO_REUSEADDR) e a página pode
# vir de OUTRA instância aberta (ex.: o .exe de produção): sem medição e sem os arquivos novos.
PORTA_PYWEBVIEW = 42001


def porta_ocupada(porta: int = PORTA_PYWEBVIEW) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conexao:
        conexao.settimeout(0.3)
        return conexao.connect_ex(("127.0.0.1", porta)) == 0


def garantir_porta_livre(espera_s: float = 10.0) -> None:
    """Espera a instância anterior terminar de fechar; se outra continuar aberta, para a medição."""
    prazo = time.monotonic() + espera_s
    while porta_ocupada():
        if time.monotonic() > prazo:
            raise SystemExit(
                f"\nA porta {PORTA_PYWEBVIEW} está em uso: há um BTC Status (ou outro app pywebview) aberto.\n"
                "Feche-o (inclusive o .exe de produção) e rode a medição de novo."
            )
        time.sleep(0.25)


def abrir_e_medir(opcoes: argparse.Namespace, indice: int, ambiente_extra: dict[str, str], rotulo: str = "") -> str | None:
    """Abre o app uma vez, espera o relatório de abertura e fecha. Devolve o id da sessão (ou None)."""
    garantir_porta_livre()
    comando = [str(opcoes.exe)] if opcoes.exe else [sys.executable, str(RAIZ / "BTC_Monitor.py")]
    sessao = uuid.uuid4().hex
    inicio_leitura = opcoes.arquivo.stat().st_size if opcoes.arquivo.is_file() else 0
    ambiente = {**os.environ, VARIAVEL_SESSAO: sessao, **ambiente_extra}
    print(f"Execução {indice}/{opcoes.vezes}{rotulo} (sessão {sessao[:8]})...", end=" ", flush=True)
    inicio = time.perf_counter()
    processo = subprocess.Popen(comando, cwd=RAIZ, env=ambiente)
    try:
        ok = esperar_abertura(opcoes.arquivo, inicio_leitura, sessao, opcoes.limite)
    finally:
        encerrar(processo)
    print(f"{'ok' if ok else 'SEM RELATÓRIO'} em {time.perf_counter() - inicio:.1f} s")
    time.sleep(opcoes.pausa)
    return sessao if ok else None


def avisar_sem_relatorio(opcoes: argparse.Namespace) -> None:
    print("Nenhuma execução gerou relatório. Veja o btcstatus.log.")
    if opcoes.exe:
        print("O .exe de produção não tem medição: gere o build de teste com  .\\criar_exe_btc.ps1 -ComMedicao")


# ---------------------------------------------------------------------------
# Comparação com e sem um recurso da abertura (aberturas alternadas)
# ---------------------------------------------------------------------------

# Recurso -> (variável que o desliga no app com medição, nome na tabela). Os nomes das
# variáveis são os mesmos usados em BTC_Monitor.py.
COMPARACOES = {
    "preconnect": ("BTC_SEM_PRECONNECT", "Pré-conexão"),
    "preco-python": ("BTC_SEM_PRECO_PYTHON", "1º preço pelo Python"),
    "preload-fonte": ("BTC_SEM_AJUSTE_PRELOAD", "Preload da fonte por http"),
    "tipos-fixos": ("BTC_SEM_TIPOS_FIXOS", "Tipos fixos no servidor local"),
    "preco-no-html": ("BTC_SEM_PRECO_NO_HTML", "1º preço dentro do HTML"),
    "preco-cedo": ("BTC_SEM_PRECO_CEDO", "Busca do 1º preço antes dos imports"),
    "net-cedo": ("BTC_SEM_NET_CEDO", ".NET em paralelo com os imports"),
    "argumentos-webview2": ("BTC_SEM_ARGUMENTOS_WEBVIEW2", "Argumentos extras do WebView2 (adotados)"),
}
# Etapas da abertura comparadas (nomes de analisar_metricas.ETAPAS_ABERTURA).
ETAPAS_COMPARADAS = ["net_cedo_inicio", "net_cedo_clr", "net_cedo_imports", "imports_concluidos",
                     "posicao_calculada", "evento_before_show", "evento_shown", "navegacao",
                     "preco_python_inicio", "preco_python_enviado", "preco_python_cabecalhos",
                     "preco_python_resposta", "servidor_pedido:index.html", "servidor_fim:index.html", "servidor_pedido:script.js", "servidor_fim:script.js",
                     "recurso:script.js", "recurso:style.css", "dom_pronto", "fontes_prontas",
                     "recurso:Roboto.woff2", "servidor_preco_no_html", "preco_no_html", "nav_load", "preco_inicial_pedido", "preco_inicial_resposta",
                     "precos_continuacao", "api_python_pronta", "primeira_resposta_binance",
                     "primeiro_preco", "ws_conectado", "ws_primeiro_preco", "grafico_carregado"]


def sem_recurso_na_execucao(indice: int) -> bool:
    """Ordem com, sem, sem, com, com, sem...: nenhuma das metades fica sempre em 1º lugar."""
    return indice % 4 in (2, 3)


def ambiente_dos_argumentos(extras: list[str], base: dict[str, str] | None = None):
    """Função sem -> variáveis da execução: com os argumentos extras, ou como o app roda hoje."""
    base = os.environ if base is None else base
    com = argumentos_webview2.valor_da_variavel(extras, base.get(argumentos_webview2.VARIAVEL))
    return lambda sem: {} if sem else {argumentos_webview2.VARIAVEL: com}


def comparar(opcoes: argparse.Namespace, titulo: str, ambiente_da_execucao) -> int:
    """ambiente_da_execucao(sem) devolve as variáveis de ambiente de uma execução sem/com o recurso."""
    grupos: dict[str, list[str]] = {"com": [], "sem": []}
    for indice in range(1, opcoes.vezes + 1):
        sem = sem_recurso_na_execucao(indice)
        extra = ambiente_da_execucao(sem)
        rotulo = f" [{'sem' if sem else 'com'}: {titulo.lower()}]"
        sessao = abrir_e_medir(opcoes, indice, extra, rotulo=rotulo)
        if sessao:
            grupos["sem" if sem else "com"].append(sessao)

    if not grupos["com"] or not grupos["sem"]:
        avisar_sem_relatorio(opcoes)
        return 1
    registros = analisar_metricas.agrupar_sessoes(analisar_metricas.ler_registros(opcoes.arquivo))
    por_grupo = {nome: {s: registros[s] for s in ids if s in registros} for nome, ids in grupos.items()}
    medianas = {nome: medianas_do_grupo(sessoes) for nome, sessoes in por_grupo.items()}
    imprimir_comparacao(medianas, {nome: len(ids) for nome, ids in grupos.items()}, titulo)
    imprimir_origens({nome: origens_do_1o_preco(sessoes) for nome, sessoes in por_grupo.items()})
    return 0


def origens_do_1o_preco(sessoes: dict[str, list]) -> dict[str, int]:
    """De onde veio o 1º preço (contadores primeiro_preco:python / primeiro_preco:rest)."""
    origens: dict[str, int] = {}
    for registros in sessoes.values():
        for relatorio in analisar_metricas.relatorios_js(registros):
            for nome, valor in (relatorio.get("contadores") or {}).items():
                if nome.startswith("primeiro_preco:"):
                    origem = nome.split(":", 1)[1]
                    origens[origem] = origens.get(origem, 0) + valor
    return origens


def imprimir_origens(origens: dict[str, dict[str, int]]) -> None:
    if not any(origens.values()):
        return
    for grupo in ("com", "sem"):
        contagem = origens.get(grupo) or {}
        texto = ", ".join(f"{origem}: {n}" for origem, n in sorted(contagem.items())) or "-"
        print(f"Origem do 1º preço ({grupo}): {texto}")


def medianas_do_grupo(sessoes: dict[str, list]) -> dict[str, float]:
    """Mediana, entre as sessões, das etapas comparadas e da 1ª requisição a cada servidor."""
    valores: dict[str, list[float]] = {}
    for registros in sessoes.values():
        tempos = analisar_metricas.linha_do_tempo_abertura(registros)
        for nome in ETAPAS_COMPARADAS:
            if nome in tempos:
                valores.setdefault(nome, []).append(tempos[nome])
        leituras: dict[str, int] = {}
        for relatorio in analisar_metricas.relatorios_js(registros):
            for nome, amostras in (relatorio.get("amostras") or {}).items():
                if nome.startswith("rede1:"):
                    valores.setdefault(nome, []).extend(amostras)
            for nome, quantidade in (relatorio.get("contadores") or {}).items():
                if nome.startswith("recurso_n:"):
                    leituras[nome] = leituras.get(nome, 0) + quantidade
        for nome, quantidade in leituras.items():  # leituras de cada arquivo nesta abertura
            valores.setdefault(nome, []).append(quantidade)
    return {nome: statistics.median(lista) for nome, lista in valores.items() if lista}


def imprimir_comparacao(medianas: dict[str, dict[str, float]], quantidades: dict[str, int],
                        titulo: str = "Pré-conexão") -> None:
    descricoes = {nome: descricao for _, nome, descricao in analisar_metricas.ETAPAS_ABERTURA}
    print(f"\n== {titulo}: com ({quantidades['com']} aberturas) x sem ({quantidades['sem']} aberturas), medianas em ms ==")
    print(f"{'Medida':<50} {'com':>8} {'sem':>8} {'ganho':>8}")
    nomes = [n for n in ETAPAS_COMPARADAS if n in medianas["com"] or n in medianas["sem"]]
    nomes += sorted(n for n in set(medianas["com"]) | set(medianas["sem"]) if n.startswith("rede1:"))
    nomes += sorted(n for n in set(medianas["com"]) | set(medianas["sem"]) if n.startswith("recurso_n:"))
    for nome in nomes:
        com, sem = medianas["com"].get(nome), medianas["sem"].get(nome)
        rotulo = descricoes.get(nome) or rotulo_de(nome)
        ganho = f"{sem - com:>+8.0f}" if com is not None and sem is not None else f"{'-':>8}"
        print(f"{rotulo[:50]:<50} {formatar(com):>8} {formatar(sem):>8} {ganho}")
    print("Etapas: ms desde a criação do processo. \"1ª requisição\": duração do 1º fetch a cada servidor.")
    print("\"Leituras\": quantas vezes o arquivo foi lido na abertura (mediana; o ideal é 1).")
    print("Ganho = sem - com (positivo: o recurso adiantou).")


def rotulo_de(nome: str) -> str:
    for prefixo, texto in (("rede1:", "1ª requisição a "), ("recurso:", "Arquivo recebido: "),
                           ("servidor_pedido:", "Servidor recebe o pedido: "),
                           ("servidor_fim:", "Servidor termina de enviar: "),
                           ("recurso_n:", "Leituras (vezes) de ")):
        if nome.startswith(prefixo):
            return texto + nome[len(prefixo):]
    return nome


def formatar(valor: float | None) -> str:
    return "-" if valor is None else f"{valor:.0f}"


if __name__ == "__main__":
    sys.exit(main())
