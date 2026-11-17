"""instancia_unica.py: a 2ª cópia do app não abre janela e traz a que já está aberta."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import instancia_unica  # noqa: E402

TITULO = "BTC Status"


class SistemaFalso:
    def __init__(self, ja_existe: bool = False, janela: int | None = 42, trazida: bool = True,
                 falhar_em: str | None = None) -> None:
        self.ja_existe, self.janela, self.trazida, self.falhar_em = ja_existe, janela, trazida, falhar_em
        self.chamadas: list[tuple] = []

    def _talvez_falhar(self, nome: str) -> None:
        if self.falhar_em == nome:
            raise OSError(f"falha simulada em {nome}")

    def criar_marca(self, nome: str) -> bool:
        self.chamadas.append(("criar_marca", nome))
        self._talvez_falhar("criar_marca")
        return self.ja_existe

    def janela_de_outra_instancia(self, titulo: str) -> int | None:
        self.chamadas.append(("janela", titulo))
        self._talvez_falhar("janela")
        return self.janela

    def trazer_para_frente(self, hwnd: int) -> bool:
        self.chamadas.append(("trazer", hwnd))
        self._talvez_falhar("trazer")
        return self.trazida


def test_unica_instancia_segue_sem_procurar_janela():
    sistema = SistemaFalso(ja_existe=False)
    assert instancia_unica.garantir(sistema, TITULO) is True
    assert sistema.chamadas == [("criar_marca", instancia_unica.NOME_DO_MUTEX)]


def test_segunda_instancia_traz_a_outra_janela_e_nao_abre():
    sistema = SistemaFalso(ja_existe=True, janela=42)
    assert instancia_unica.garantir(sistema, TITULO) is False
    assert sistema.chamadas[1:] == [("janela", TITULO), ("trazer", 42)]


def test_segunda_instancia_sem_a_outra_janela_tambem_nao_abre(caplog):
    sistema = SistemaFalso(ja_existe=True, janela=None)
    with caplog.at_level(logging.WARNING, logger="instancia_unica"):
        assert instancia_unica.garantir(sistema, TITULO) is False
    assert ("trazer", 42) not in sistema.chamadas
    assert "não foi achada" in caplog.text


@pytest.mark.parametrize("falha", ["janela", "trazer"])
def test_falha_ao_trazer_a_outra_janela_so_vai_ao_log(caplog, falha):
    sistema = SistemaFalso(ja_existe=True, falhar_em=falha)
    with caplog.at_level(logging.ERROR, logger="instancia_unica"):
        assert instancia_unica.garantir(sistema, TITULO) is False
    assert "falha ao trazer" in caplog.text


def test_falha_ao_conferir_deixa_o_app_abrir(caplog):
    sistema = SistemaFalso(falhar_em="criar_marca")
    with caplog.at_level(logging.ERROR, logger="instancia_unica"):
        assert instancia_unica.garantir(sistema, TITULO) is True
    assert "abre assim mesmo" in caplog.text


def test_topo_do_modulo_so_importa_o_que_o_build_mantem():
    import ast  # noqa: PLC0415

    fonte = Path(instancia_unica.__file__).read_text(encoding="utf-8")
    no_topo = set()
    for no in ast.parse(fonte).body:
        if isinstance(no, ast.Import):
            no_topo |= {alias.name for alias in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            no_topo.add(no.module)
    assert no_topo <= {"__future__", "logging", "typing"}


# --- Windows real ------------------------------------------------------------------------
@pytest.mark.skipif(sys.platform != "win32", reason="mutex e janelas do Windows")
def test_mutex_real_marca_a_instancia():
    nome = f"Local\\BTCStatus.teste.{os.getpid()}"
    primeira, segunda = instancia_unica.SistemaWin32Instancia(), instancia_unica.SistemaWin32Instancia()
    assert primeira.criar_marca(nome) is False
    assert segunda.criar_marca(nome) is True


@pytest.mark.skipif(sys.platform != "win32", reason="janelas do Windows")
def test_janela_real_com_titulo_improvavel_nao_existe():
    sistema = instancia_unica.SistemaWin32Instancia()
    assert sistema.janela_de_outra_instancia("BTC Status (titulo improvavel de teste)") is None
