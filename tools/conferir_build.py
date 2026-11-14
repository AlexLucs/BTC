"""Confere a pasta do build: nada do que foi excluído pode ter voltado, e mostra o tamanho.

Uso (o criar_exe_btc.ps1 chama depois do PyInstaller):
    .venv\\Scripts\\python.exe tools\\conferir_build.py "dist\\BTC Monitor" --trabalho "build\\BTC Monitor"

Sai com código 1 se faltar o executável, se faltar algum arquivo de
exclusoes_build.ARQUIVOS_OBRIGATORIOS (sem eles o .exe não abre) ou se existir no build
algum arquivo de exclusoes_build.arquivos_proibidos_no_build() (uma atualização do
PyInstaller, do pywebview ou do pythonnet pode trazê-lo de volta).

Com --trabalho (a pasta de trabalho do PyInstaller, build\\BTC Monitor), confere também:
- o arquivo de avisos (warn-BTC Monitor.txt): falha se um módulo do build importar NO TOPO
  um módulo excluído (fora os de exclusoes_build.IMPORTS_NO_TOPO_CONHECIDOS); esse import
  falharia assim que o módulo fosse carregado no .exe. Imports dentro de funções ou de
  try/except não são acusados (são o caso normal das exclusões);
- os módulos do build (PYZ-00.toc e base_library.zip): falha se faltar algum de
  exclusoes_build.MODULOS_OBRIGATORIOS, que só o lado .NET do pythonnet importa.
Só biblioteca padrão.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exclusoes_build import (  # noqa: E402
    ARQUIVOS_OBRIGATORIOS,
    IMPORTS_NO_TOPO_CONHECIDOS,
    MODULOS_OBRIGATORIOS,
    arquivos_proibidos_no_build,
    normalizar_caminho,
)

NOME_EXE = "BTC Monitor.exe"
PASTA_INTERNA = "_internal"
MAIORES_NA_LISTA = 10


def tamanhos(pasta: Path) -> dict[str, int]:
    """Tamanho em bytes de cada arquivo da pasta, pelo caminho relativo com "/"."""
    return {
        arquivo.relative_to(pasta).as_posix(): arquivo.stat().st_size
        for arquivo in pasta.rglob("*") if arquivo.is_file()
    }


def proibidos_presentes(pasta: Path) -> list[str]:
    """Arquivos excluídos que existem no build (caminhos relativos à pasta do build)."""
    presentes = {normalizar_caminho(caminho): caminho for caminho in tamanhos(pasta)}
    achados = []
    for proibido in arquivos_proibidos_no_build():
        chave = normalizar_caminho(f"{PASTA_INTERNA}/{proibido}")
        if chave in presentes:
            achados.append(presentes[chave])
    return achados


def obrigatorios_ausentes(pasta: Path) -> list[str]:
    """Arquivos sem os quais o .exe não abre e que faltam no build."""
    presentes = {normalizar_caminho(caminho) for caminho in tamanhos(pasta)}
    return [f"{PASTA_INTERNA}/{arquivo}" for arquivo in ARQUIVOS_OBRIGATORIOS
            if normalizar_caminho(f"{PASTA_INTERNA}/{arquivo}") not in presentes]


# Linha do arquivo de avisos do PyInstaller:
#   excluded module named ssl - imported by http.client (optional), webview.http (top-level)
_LINHA_EXCLUIDO = re.compile(r"^excluded module named (\S+) - imported by (.*)$")
_IMPORTADOR = re.compile(r"(\S+) \(([^)]*)\)")


def imports_no_topo_de_excluidos(texto_dos_avisos: str) -> list[tuple[str, str]]:
    """Pares (módulo excluído, quem o importa no topo) fora dos casos conhecidos.

    "top-level" sozinho é um import incondicional no topo do módulo; com "optional"
    (try/except), "conditional" (dentro de if) ou "delayed" (dentro de função) não conta.
    """
    achados = []
    for linha in texto_dos_avisos.splitlines():
        encontrado = _LINHA_EXCLUIDO.match(linha.strip())
        if not encontrado:
            continue
        excluido = encontrado.group(1)
        for importador, tipo in _IMPORTADOR.findall(encontrado.group(2)):
            if tipo.strip() == "top-level" and (excluido, importador) not in IMPORTS_NO_TOPO_CONHECIDOS:
                achados.append((excluido, importador))
    return achados


def conferir_avisos(arquivo: Path) -> list[str]:
    """Problemas no arquivo de avisos do PyInstaller (lista vazia: está tudo certo)."""
    if not arquivo.is_file():
        return [f"arquivo de avisos nao encontrado: {arquivo}"]
    texto = arquivo.read_text(encoding="utf-8", errors="replace")
    return [f"{importador} importa no topo o modulo excluido {excluido}"
            for excluido, importador in imports_no_topo_de_excluidos(texto)]


NOME_AVISOS = "warn-BTC Monitor.txt"
NOME_LISTA_DO_PYZ = "PYZ-00.toc"
NOME_BASE_LIBRARY = "base_library.zip"


def modulos_do_pyz(arquivo: Path) -> set[str]:
    """Nomes dos módulos Python dentro do .exe, lidos do PYZ-00.toc do PyInstaller
    (uma tupla Python cujo último item é a lista de (nome, origem, tipo))."""
    conteudo = ast.literal_eval(arquivo.read_text(encoding="utf-8"))
    return {entrada[0] for entrada in conteudo[-1]}


def modulos_da_base_library(arquivo: Path) -> set[str]:
    """Nomes dos módulos dentro do base_library.zip (ex.: "collections/abc.pyc")."""
    nomes = set()
    with zipfile.ZipFile(arquivo) as pacote:
        for caminho in pacote.namelist():
            if caminho.endswith(".pyc"):
                modulo = caminho[:-4].replace("/", ".")
                nomes.add(modulo.removesuffix(".__init__"))
    return nomes


def obrigatorios_fora_do_build(modulos_no_build: set[str]) -> list[str]:
    return [nome for nome in MODULOS_OBRIGATORIOS if nome not in modulos_no_build]


def conferir_modulos(pasta_de_trabalho: Path, pasta_do_build: Path) -> list[str]:
    """Problemas com os módulos obrigatórios (lista vazia: estão todos no build)."""
    lista_do_pyz = pasta_de_trabalho / NOME_LISTA_DO_PYZ
    base_library = pasta_do_build / PASTA_INTERNA / NOME_BASE_LIBRARY
    for arquivo in (lista_do_pyz, base_library):
        if not arquivo.is_file():
            return [f"arquivo nao encontrado para conferir os modulos: {arquivo}"]
    try:
        no_build = modulos_do_pyz(lista_do_pyz) | modulos_da_base_library(base_library)
    except (ValueError, SyntaxError, IndexError, TypeError, zipfile.BadZipFile) as erro:
        return [f"nao foi possivel ler os modulos do build: {erro}"]
    return [f"modulo obrigatorio faltando no build: {nome} ({MODULOS_OBRIGATORIOS[nome]})"
            for nome in obrigatorios_fora_do_build(no_build)]


def conferir(pasta: Path) -> list[str]:
    """Problemas encontrados no build (lista vazia: está tudo certo)."""
    if not pasta.is_dir():
        return [f"pasta do build nao encontrada: {pasta}"]
    problemas = []
    if not (pasta / NOME_EXE).is_file():
        problemas.append(f"executavel nao encontrado: {pasta / NOME_EXE}")
    problemas += [f"arquivo obrigatorio faltando no build: {caminho}" for caminho in obrigatorios_ausentes(pasta)]
    problemas += [f"arquivo excluido voltou ao build: {caminho}" for caminho in proibidos_presentes(pasta)]
    return problemas


def resumo(pasta: Path, maiores: int = MAIORES_NA_LISTA) -> str:
    """Tamanho total e os maiores arquivos do build."""
    por_arquivo = tamanhos(pasta)
    total = sum(por_arquivo.values())
    linhas = [f"Tamanho do build: {total / 1024 / 1024:.1f} MB em {len(por_arquivo)} arquivos"]
    for caminho, tamanho in sorted(por_arquivo.items(), key=lambda item: item[1], reverse=True)[:maiores]:
        linhas.append(f"  {tamanho / 1024:8.0f} KB  {caminho}")
    return "\n".join(linhas)


def main(argumentos: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description="Confere a pasta do build do BTC Status.")
    analisador.add_argument("pasta", type=Path, help='pasta do build (ex.: "dist\\BTC Monitor")')
    analisador.add_argument("--trabalho", type=Path,
                            help='pasta de trabalho do PyInstaller (ex.: "build\\BTC Monitor"): confere os avisos e os modulos')
    opcoes = analisador.parse_args(argumentos)

    # Mensagens sem acentos: o criar_exe_btc.ps1 as mostra no console do PowerShell.
    problemas = conferir(opcoes.pasta)
    if opcoes.trabalho is not None:
        problemas += conferir_avisos(opcoes.trabalho / NOME_AVISOS)
        problemas += conferir_modulos(opcoes.trabalho, opcoes.pasta)
    if opcoes.pasta.is_dir():
        print(resumo(opcoes.pasta))
    for problema in problemas:
        print(f"ERRO: {problema}")
    if not problemas:
        print("Build conferido: arquivos obrigatorios presentes, nenhum arquivo excluido"
              + (", nenhum import no topo de modulo excluido e modulos obrigatorios presentes."
                 if opcoes.trabalho is not None else "."))
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
