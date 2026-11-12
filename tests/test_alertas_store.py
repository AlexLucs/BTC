"""Testes da validação e persistência de alertas (python -m pytest tests)."""

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alertas_store import (  # noqa: E402
    MAX_ALERTAS,
    AlertasInvalidosError,
    RepositorioAlertas,
    validar_alertas,
)


def test_valida_e_normaliza():
    entrada = [{"id": "a1", "valor": "500000", "tipo": "maior", "vazio": 0}]
    assert validar_alertas(entrada) == [{"id": "a1", "valor": 500000.0, "tipo": "maior"}]


def test_aceita_formato_antigo_sem_id():
    assert validar_alertas([{"valor": 1.239, "tipo": "menor"}]) == [{"valor": 1.24, "tipo": "menor"}]


@pytest.mark.parametrize(
    "entrada",
    [
        {"valor": 1, "tipo": "maior"},                 # não é lista
        [{"valor": 0, "tipo": "maior"}],               # valor zero
        [{"valor": -5, "tipo": "maior"}],              # negativo
        [{"valor": "abc", "tipo": "maior"}],           # não numérico
        [{"valor": True, "tipo": "maior"}],            # bool não é número
        [{"valor": float("inf"), "tipo": "maior"}],    # infinito
        [{"valor": 10, "tipo": "outro"}],              # tipo desconhecido
        [{"valor": 10, "tipo": "maior", "id": 123}],   # id não-string
        [{"valor": 10, "tipo": "maior", "id": "x" * 65}],
        ["texto"],
        [{"valor": 1, "tipo": "maior"}] * (MAX_ALERTAS + 1),
    ],
)
def test_rejeita_invalidos(entrada):
    with pytest.raises(AlertasInvalidosError):
        validar_alertas(entrada)


def test_salvar_e_carregar(tmp_path):
    repo = RepositorioAlertas(tmp_path)
    alertas = [{"id": "x", "valor": 10.5, "tipo": "desativado"}]
    repo.salvar(alertas)
    assert repo.carregar() == alertas
    assert not list(tmp_path.glob("*.tmp"))


def test_arquivo_inexistente_retorna_lista_vazia(tmp_path):
    assert RepositorioAlertas(tmp_path).carregar() == []


def test_salvar_invalido_nao_altera_arquivo(tmp_path):
    repo = RepositorioAlertas(tmp_path)
    repo.salvar([{"valor": 1, "tipo": "maior"}])
    with pytest.raises(AlertasInvalidosError):
        repo.salvar([{"valor": -1, "tipo": "maior"}])
    assert repo.carregar() == [{"valor": 1.0, "tipo": "maior"}]


@pytest.mark.parametrize("conteudo", ["{corrompido", json.dumps({"nao": "lista"})])
def test_arquivo_corrompido_gera_backup_e_retorna_none(tmp_path, conteudo):
    repo = RepositorioAlertas(tmp_path)
    repo.arquivo.write_text(conteudo, encoding="utf-8")
    assert repo.carregar() is None
    assert not repo.arquivo.exists()
    backups = list(tmp_path.glob("Alertas.*.bak"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == conteudo


def test_gravacoes_concorrentes_nao_falham(tmp_path):
    """O pywebview executa cada chamada da js_api numa thread própria."""
    repo = RepositorioAlertas(tmp_path)
    total = 16
    barreira = threading.Barrier(total)
    erros: list[BaseException] = []

    def gravar(indice: int) -> None:
        barreira.wait()
        try:
            for _ in range(20):
                repo.salvar([{"id": f"a{indice}", "valor": indice + 1, "tipo": "maior"}])
        except BaseException as erro:  # noqa: BLE001 - o teste precisa capturar qualquer falha
            erros.append(erro)

    threads = [threading.Thread(target=gravar, args=(i,)) for i in range(total)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert erros == []
    carregados = repo.carregar()
    assert carregados is not None and len(carregados) == 1
    assert not list(tmp_path.glob("*.tmp"))
