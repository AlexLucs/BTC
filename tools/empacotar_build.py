"""Compacta a pasta do build num arquivo só, para distribuir (download ou envio).

Uso (o criar_exe_btc.ps1 -Compactar chama depois de conferir o build):
    .venv\\Scripts\\python.exe tools\\empacotar_build.py "dist\\BTC Monitor"

Gera, ao lado da pasta do build:
- "BTC Monitor.zip": sempre. O Explorer de qualquer Windows abre, sem instalar nada.
- "BTC Monitor.7z": só se o 7-Zip estiver instalado (bem menor que o .zip). O Explorer do
  Windows 11 recente abre; nos demais é preciso o 7-Zip.

Os dois guardam a pasta inteira ("BTC Monitor\\..."): quem recebe extrai e abre o
"BTC Monitor.exe" de dentro dela. O app instalado não muda: a pasta dist continua sendo o
build de sempre, e a abertura não fica mais lenta (nada é descompactado ao abrir).

Só biblioteca padrão. Roda com o Python do venv, não entra no executável.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

NIVEL_ZIP = 9
# Onde o instalador do 7-Zip costuma pôr o 7z.exe, se não estiver no PATH.
PASTAS_DO_7ZIP = ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")
PRAZO_7ZIP_S = 300


def arquivos_da_pasta(pasta: Path) -> list[Path]:
    """Todos os arquivos da pasta, em ordem fixa (o mesmo build gera o mesmo pacote)."""
    return sorted((arquivo for arquivo in pasta.rglob("*") if arquivo.is_file()),
                  key=lambda arquivo: arquivo.relative_to(pasta).as_posix().lower())


def nome_no_pacote(pasta: Path, arquivo: Path) -> str:
    """Caminho do arquivo dentro do pacote: começa pelo nome da pasta do build."""
    return f"{pasta.name}/{arquivo.relative_to(pasta).as_posix()}"


def compactar_zip(pasta: Path, destino: Path) -> Path:
    """Cria o .zip (Deflate, nível máximo) e confere o conteúdo.

    Raises:
        OSError: se a conferência do arquivo gerado falhar.
    """
    arquivos = arquivos_da_pasta(pasta)
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        with zipfile.ZipFile(temporario, "w", zipfile.ZIP_DEFLATED, compresslevel=NIVEL_ZIP) as pacote:
            for arquivo in arquivos:
                pacote.write(arquivo, nome_no_pacote(pasta, arquivo))
        with zipfile.ZipFile(temporario) as pacote:
            danificado = pacote.testzip()
            esperado = {nome_no_pacote(pasta, arquivo): arquivo.stat().st_size for arquivo in arquivos}
            gravado = {item.filename: item.file_size for item in pacote.infolist()}
        if danificado is not None or gravado != esperado:
            raise OSError(f"o pacote gerado nao confere com a pasta do build: {destino}")
        os.replace(temporario, destino)
    finally:
        temporario.unlink(missing_ok=True)
    return destino


def achar_7zip() -> Path | None:
    """Caminho do 7z.exe (PATH ou pasta padrão do instalador); None se não houver."""
    for nome in ("7z", "7za", "7zr"):
        achado = shutil.which(nome)
        if achado:
            return Path(achado)
    for variavel in PASTAS_DO_7ZIP:
        base = os.environ.get(variavel)
        if base and (Path(base) / "7-Zip" / "7z.exe").is_file():
            return Path(base) / "7-Zip" / "7z.exe"
    return None


def comando_7zip(programa: Path, pasta: Path, destino: Path) -> list[str]:
    """Linha de comando do 7-Zip: LZMA2 no nível máximo, arquivo sólido, sem perguntas.
    A pasta entra pelo nome (o comando roda na pasta de cima), para ficar inteira no pacote."""
    return [str(programa), "a", "-t7z", "-mx=9", "-ms=on", "-bd", "-y", str(destino), pasta.name]


def compactar_7z(programa: Path, pasta: Path, destino: Path) -> Path:
    """Cria o .7z com o 7-Zip.

    Raises:
        OSError: se o 7-Zip falhar.
    """
    destino.unlink(missing_ok=True)  # o "a" do 7-Zip acrescentaria a um arquivo que já existisse
    resultado = subprocess.run(comando_7zip(programa, pasta, destino), cwd=pasta.parent,
                               capture_output=True, text=True, timeout=PRAZO_7ZIP_S, check=False)
    if resultado.returncode != 0 or not destino.is_file():
        destino.unlink(missing_ok=True)
        raise OSError(f"o 7-Zip falhou (codigo {resultado.returncode}): {resultado.stderr.strip()[-300:]}")
    return destino


def megabytes(tamanho: int) -> str:
    return f"{tamanho / 1024 / 1024:.1f} MB"


def main(argumentos: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description="Compacta a pasta do build do BTC Status.")
    analisador.add_argument("pasta", type=Path, help='pasta do build (ex.: "dist\\BTC Monitor")')
    analisador.add_argument("--sem-7zip", action="store_true", help="gera só o .zip, mesmo com o 7-Zip instalado")
    opcoes = analisador.parse_args(argumentos)

    # Mensagens sem acentos: o criar_exe_btc.ps1 as mostra no console do PowerShell.
    pasta = opcoes.pasta.resolve()
    if not pasta.is_dir() or not arquivos_da_pasta(pasta):
        print(f"ERRO: pasta do build nao encontrada ou vazia: {opcoes.pasta}")
        return 1
    original = sum(arquivo.stat().st_size for arquivo in arquivos_da_pasta(pasta))
    print(f"Pasta do build: {megabytes(original)}")
    try:
        pacote = compactar_zip(pasta, pasta.parent / f"{pasta.name}.zip")
        print(f"  {megabytes(pacote.stat().st_size):>8}  {pacote}")
        programa = None if opcoes.sem_7zip else achar_7zip()
        if programa is not None:
            pacote = compactar_7z(programa, pasta, pasta.parent / f"{pasta.name}.7z")
            print(f"  {megabytes(pacote.stat().st_size):>8}  {pacote}")
        elif not opcoes.sem_7zip:
            print("  7-Zip nao encontrado: o .7z (menor que o .zip) nao foi gerado.")
    except (OSError, subprocess.SubprocessError) as erro:
        print(f"ERRO: {erro}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
