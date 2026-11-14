"""tools/empacotar_build.py: o pacote de distribuição (.zip sempre; .7z com o 7-Zip)."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

import empacotar_build  # noqa: E402


def criar_build(pasta: Path) -> Path:
    build = pasta / "dist" / "BTC Monitor"
    conteudo = {
        "BTC Monitor.exe": b"MZ" + b"\x00" * 5000,
        "_internal/python314.dll": bytes(range(256)) * 40,
        "_internal/index.html": "<html lang=\"pt-BR\">ação</html>".encode(),
        "_internal/webview/lib/runtimes/win-x64/native/WebView2Loader.dll": b"x" * 3000,
        "_internal/webview/js/finish.js": b"",  # arquivo vazio também precisa ir
    }
    for caminho, dados in conteudo.items():
        arquivo = build / caminho
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(dados)
    return build


def test_zip_guarda_a_pasta_inteira_com_o_mesmo_conteudo(tmp_path):
    build = criar_build(tmp_path)
    destino = empacotar_build.compactar_zip(build, tmp_path / "dist" / "BTC Monitor.zip")
    with zipfile.ZipFile(destino) as pacote:
        nomes = pacote.namelist()
        assert all(nome.startswith("BTC Monitor/") for nome in nomes), "tudo dentro da pasta do build"
        assert len(nomes) == 5
        for arquivo in empacotar_build.arquivos_da_pasta(build):
            assert pacote.read(empacotar_build.nome_no_pacote(build, arquivo)) == arquivo.read_bytes()
        assert {item.compress_type for item in pacote.infolist()} == {zipfile.ZIP_DEFLATED}
    assert destino.stat().st_size < sum(a.stat().st_size for a in empacotar_build.arquivos_da_pasta(build))
    assert not list((tmp_path / "dist").glob("*.tmp"))


def test_zip_extraido_refaz_a_pasta_do_build(tmp_path):
    build = criar_build(tmp_path)
    destino = empacotar_build.compactar_zip(build, tmp_path / "dist" / "BTC Monitor.zip")
    with zipfile.ZipFile(destino) as pacote:
        pacote.extractall(tmp_path / "outro-lugar")
    extraido = tmp_path / "outro-lugar" / "BTC Monitor"
    originais = {a.relative_to(build).as_posix(): a.read_bytes() for a in empacotar_build.arquivos_da_pasta(build)}
    copiados = {a.relative_to(extraido).as_posix(): a.read_bytes() for a in empacotar_build.arquivos_da_pasta(extraido)}
    assert copiados == originais


def test_zip_substitui_o_pacote_anterior(tmp_path):
    build = criar_build(tmp_path)
    destino = tmp_path / "dist" / "BTC Monitor.zip"
    destino.write_bytes(b"pacote antigo")
    empacotar_build.compactar_zip(build, destino)
    (build / "_internal" / "index.html").write_bytes(b"novo")
    empacotar_build.compactar_zip(build, destino)
    with zipfile.ZipFile(destino) as pacote:
        assert pacote.read("BTC Monitor/_internal/index.html") == b"novo"


def test_ordem_dos_arquivos_e_fixa(tmp_path):
    build = criar_build(tmp_path)
    nomes = [empacotar_build.nome_no_pacote(build, a) for a in empacotar_build.arquivos_da_pasta(build)]
    assert nomes == sorted(nomes, key=str.lower)
    assert nomes[-1] == "BTC Monitor/BTC Monitor.exe" or "BTC Monitor/BTC Monitor.exe" in nomes


def test_comando_do_7zip_guarda_a_pasta_pelo_nome(tmp_path):
    build = criar_build(tmp_path)
    comando = empacotar_build.comando_7zip(Path("C:/Program Files/7-Zip/7z.exe"), build, tmp_path / "BTC Monitor.7z")
    assert comando[1:5] == ["a", "-t7z", "-mx=9", "-ms=on"]
    assert comando[-1] == "BTC Monitor"  # nome relativo: o comando roda na pasta de cima
    assert comando[-2].endswith("BTC Monitor.7z")
    assert "-y" in comando


def test_achar_7zip_no_path_e_na_pasta_padrao(tmp_path, monkeypatch):
    monkeypatch.setattr(empacotar_build.shutil, "which", lambda nome: None)
    for variavel in empacotar_build.PASTAS_DO_7ZIP:
        monkeypatch.delenv(variavel, raising=False)
    assert empacotar_build.achar_7zip() is None

    programa = tmp_path / "7-Zip" / "7z.exe"
    programa.parent.mkdir()
    programa.write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert empacotar_build.achar_7zip() == programa

    monkeypatch.setattr(empacotar_build.shutil, "which", lambda nome: "C:/outro/7z.exe" if nome == "7z" else None)
    assert empacotar_build.achar_7zip() == Path("C:/outro/7z.exe")


def test_main_sem_7zip_gera_so_o_zip_e_avisa(tmp_path, monkeypatch, capsys):
    build = criar_build(tmp_path)
    monkeypatch.setattr(empacotar_build, "achar_7zip", lambda: None)
    assert empacotar_build.main([str(build)]) == 0
    saida = capsys.readouterr().out
    assert (tmp_path / "dist" / "BTC Monitor.zip").is_file()
    assert not (tmp_path / "dist" / "BTC Monitor.7z").exists()
    assert "7-Zip nao encontrado" in saida
    assert saida.isascii(), "mensagens sem acentos (console do PowerShell)"


def test_main_com_7zip_que_falha_devolve_erro(tmp_path, monkeypatch, capsys):
    build = criar_build(tmp_path)
    falso = tmp_path / "7z-falso"
    monkeypatch.setattr(empacotar_build, "achar_7zip", lambda: falso)

    class Resultado:
        returncode, stderr = 2, "erro fatal"

    monkeypatch.setattr(empacotar_build.subprocess, "run", lambda *a, **k: Resultado())
    assert empacotar_build.main([str(build)]) == 1
    assert "o 7-Zip falhou (codigo 2)" in capsys.readouterr().out


def test_main_pasta_inexistente_ou_vazia(tmp_path, capsys):
    assert empacotar_build.main([str(tmp_path / "nao-existe")]) == 1
    (tmp_path / "vazia").mkdir()
    assert empacotar_build.main([str(tmp_path / "vazia")]) == 1
    assert capsys.readouterr().out.count("ERRO:") == 2


@pytest.mark.skipif(empacotar_build.achar_7zip() is None, reason="7-Zip não instalado")
def test_7zip_de_verdade_gera_o_pacote(tmp_path):
    build = criar_build(tmp_path)
    destino = empacotar_build.compactar_7z(empacotar_build.achar_7zip(), build, tmp_path / "dist" / "BTC Monitor.7z")
    assert destino.is_file() and destino.read_bytes()[:2] == b"7z"


def test_script_do_build_tem_a_opcao_compactar():
    script = (RAIZ / "criar_exe_btc.ps1").read_text(encoding="utf-8")
    assert "[switch]$Compactar" in script
    assert "tools\\empacotar_build.py" in script
