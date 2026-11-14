"""Argumentos extras do WebView2 (Chromium) usados pelo app.

O pywebview 6.2.1 passa ao WebView2 só "--disable-features=ElasticOverscroll" e não tem
opção para acrescentar outros. A variável de ambiente WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
é somada aos argumentos do aplicativo: aplicar() a preenche antes de a janela ser criada.

Grupos:
    rede      desliga a rede "de fundo" do navegador (atualização de componentes, sincronização,
              relatórios de confiabilidade, pings de auditoria de links, conexões antecipadas);
    recursos  desliga recursos de navegador que o app não usa e que podem consultar a rede
              (dicas de otimização, tradução, transmissão de mídia);
    todos     os dois: é o grupo ADOTADO pelo app.

Medido (tools/medir_trafego.py): sem eles, cada abertura gasta ~31 KB com config.edge.skype.com
(serviço de experimentos e configuração do Edge) e edge.microsoft.com, e abre conexões a mais
com os servidores da página; a abertura não muda. Custo conhecido: sem o serviço de
configuração, a Microsoft não consegue desligar remotamente um recurso com defeito neste app
(as atualizações do WebView2 em si não passam por ele).

Nenhum grupo mexe em segurança (SmartScreen, sandbox, integridade de código) nem na GPU.
Um "--disable-features" repetido substitui o anterior: por isso o grupo "recursos" repete o
ElasticOverscroll do pywebview.

Módulo leve de propósito (só "os"): é importado pelo app e pelas ferramentas de medição.
"""

from __future__ import annotations

import os

VARIAVEL = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"

REDE = [
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-sync",
    "--no-pings",
]
RECURSOS = ["--disable-features=ElasticOverscroll,OptimizationHints,Translate,MediaRouter"]
GRUPOS: dict[str, list[str]] = {
    "rede": REDE,
    "recursos": RECURSOS,
    "todos": REDE + RECURSOS,
}
ADOTADOS = GRUPOS["todos"]


def resolver(escolha: str) -> list[str]:
    """Nome de um grupo, ou os próprios argumentos separados por espaço ("--a --b=c")."""
    if escolha in GRUPOS:
        return list(GRUPOS[escolha])
    argumentos = escolha.split()
    invalidos = [a for a in argumentos if not a.startswith("--")]
    if not argumentos or invalidos:
        raise ValueError(f"use um grupo ({', '.join(GRUPOS)}) ou argumentos iniciados por '--': {escolha!r}")
    return argumentos


def valor_da_variavel(argumentos: list[str], existente: str | None = None) -> str:
    """Texto da variável de ambiente; o que já estava nela é mantido na frente."""
    partes = ([existente.strip()] if existente and existente.strip() else []) + list(argumentos)
    return " ".join(partes)


def aplicar(ambiente=None, argumentos: list[str] | None = None) -> str:
    """Põe os argumentos adotados na variável de ambiente deste processo e devolve o valor.

    Precisa rodar antes de o WebView2 ser criado (webview.start). O que já estava na variável
    fica na frente; chamar de novo não duplica.
    """
    ambiente = os.environ if ambiente is None else ambiente
    argumentos = ADOTADOS if argumentos is None else argumentos
    existente = ambiente.get(VARIAVEL, "")
    faltam = [a for a in argumentos if a not in existente.split()]
    valor = valor_da_variavel(faltam, existente)
    ambiente[VARIAVEL] = valor
    return valor
