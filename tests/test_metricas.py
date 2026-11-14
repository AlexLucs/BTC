"""Testes do registro de métricas e da ferramenta de análise (python -m pytest tests)."""

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tools"))

import analisar_metricas  # noqa: E402
from metricas import (  # noqa: E402
    NOME_ARQUIVO,
    MetricasInvalidasError,
    RegistroMetricas,
    estatisticas,
    filetime_para_epoch,
    inicio_do_processo_epoch,
    validar_relatorio_js,
)


def test_estatisticas_com_interpolacao():
    # Mesmo vetor e mesmos valores esperados de tests/metricas.test.js.
    assert estatisticas([4, 1, 3, 2, 10]) == {"n": 5, "media": 4.0, "p50": 3.0, "p95": 8.8, "max": 10}
    assert estatisticas([7]) == {"n": 1, "media": 7.0, "p50": 7.0, "p95": 7.0, "max": 7}
    assert estatisticas([]) == {"n": 0}


def test_filetime_para_epoch():
    assert filetime_para_epoch(116_444_736_000_000_000) == 0          # 01/01/1970
    assert filetime_para_epoch(116_444_736_000_000_000 + 10_000_000) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="GetProcessTimes só existe no Windows")
def test_inicio_do_processo_no_windows():
    import time

    inicio = inicio_do_processo_epoch()
    assert inicio is not None, "GetProcessTimes falhou (ver btcstatus.log)"
    assert 0 < time.time() - inicio < 3600  # o pytest começou há pouco


@pytest.mark.parametrize(
    "relatorio",
    [
        [],                                   # não é objeto
        {"x": float("nan")},                  # número não finito
        {"x": {1, 2}},                        # tipo não suportado
        {"x": "a" * 600_000},                 # grande demais
        {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}},  # aninhado demais
    ],
)
def test_relatorio_js_invalido(relatorio):
    with pytest.raises(MetricasInvalidasError):
        validar_relatorio_js(relatorio)


def test_relatorio_js_valido():
    dados = {"motivo": "abertura", "marcos": {"dom_pronto": 12.5}, "amostras": {"render:brl": [0.1, 0.2]}}
    assert validar_relatorio_js(dados) is dados


def test_marco_com_instante_proprio_entra_com_o_tempo_em_que_ocorreu(tmp_path):
    """A busca do 1º preço começa antes de o registro existir e entrega os marcos depois."""
    registro = RegistroMetricas(tmp_path, inicio_perf=100.0, inicio_epoch=1000.0, sessao="s1")
    registro.marcar("preco_python_inicio", 100.045)
    registro.marcar("preco_python_inicio", 100.9)  # só o 1º instante conta
    registro.marcar("agora")
    assert registro._marcos["preco_python_inicio"] == 45.0
    assert registro._marcos["agora"] > 1000  # sem instante: o de agora (perf_counter atual - 100)


def test_registro_grava_jsonl_com_marcos_e_amostras(tmp_path):
    registro = RegistroMetricas(tmp_path, inicio_perf=0.0, inicio_epoch=1000.0, sessao="s1")
    registro.marcar("imports_concluidos")
    registro.marcar("imports_concluidos")  # só o 1º instante conta
    with registro.medir("salvar_alerta"):
        pass
    assert registro.gravar_abertura_python()
    assert registro.gravar_api_python("periodico")
    assert registro.gravar_api_python("periodico")  # sem amostras novas: não grava nada

    linhas = [json.loads(linha) for linha in (tmp_path / NOME_ARQUIVO).read_text(encoding="utf-8").splitlines()]
    assert [linha["tipo"] for linha in linhas] == ["abertura_python", "api_python"]
    assert all(linha["sessao"] == "s1" and "epoch" in linha for linha in linhas)
    assert list(linhas[0]["marcos_ms"]) == ["imports_concluidos"]
    assert len(linhas[1]["amostras"]["salvar_alerta"]) == 1


def test_sessao_pode_vir_da_variavel_de_ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("BTC_SESSAO_METRICAS", "da-variavel")
    assert RegistroMetricas(tmp_path, 0.0, 0.0).sessao == "da-variavel"


def test_rotacao_do_arquivo(tmp_path, monkeypatch):
    # Linhas de ~360 bytes e limite de 1000: uma única rotação (3 linhas no .1, 2 no atual).
    monkeypatch.setattr("metricas.TAMANHO_MAXIMO_ARQUIVO", 1000)
    registro = RegistroMetricas(tmp_path, 0.0, 0.0, sessao="s")
    for _ in range(5):
        registro.gravar("janela", {"evento": "x" * 250})
    assert (tmp_path / (NOME_ARQUIVO + ".1")).is_file()
    assert len(analisar_metricas.ler_registros(tmp_path / NOME_ARQUIVO)) == 5


def _escrever(arquivo: Path, registros: list[dict]) -> None:
    arquivo.write_text("".join(json.dumps(r) + "\n" for r in registros), encoding="utf-8")


def test_analise_alinha_python_e_js_e_detecta_minimizar(tmp_path, capsys):
    base = 1_700_000_000.0  # criação do processo (epoch s)
    registros = [
        {"sessao": "abc", "tipo": "abertura_python", "epoch": base + 1, "quando": "x",
         "inicio_processo_epoch": base, "inicio_script_epoch": base + 0.2,
         "marcos_ms": {"imports_concluidos": 300, "evento_shown": 800}, "congelado": True},
        {"sessao": "abc", "tipo": "janela", "epoch": base + 100, "evento": "minimized"},
        {"sessao": "abc", "tipo": "janela", "epoch": base + 160, "evento": "restored"},
        {"sessao": "abc", "tipo": "js", "epoch": base + 200, "relatorio": {
            "motivo": "abertura", "timeOrigin": (base + 0.9) * 1000,
            "marcos": {"dom_pronto": 100, "primeiro_preco": 600},
            "amostras": {"render:brl": [1, 2, 3]},
            "linhaTempo": {"atraso_timer:preco": [[(base + 50) * 1000, 2], [(base + 130) * 1000, 900]]},
            "contadores": {"falha:binance": 2},
            # "hidden" 1 ms ANTES do "minimized" do Python (caso real observado no Windows).
            "eventos": [{"t": (base + 100 - 0.001) * 1000, "tipo": "visibilidade", "estado": "hidden"}],
            "tarefasLongas": [[0, 80]],
        }},
    ]
    arquivo = tmp_path / NOME_ARQUIVO
    _escrever(arquivo, registros)
    resumo_json = tmp_path / "resumo.json"
    assert analisar_metricas.main(["--arquivo", str(arquivo), "--json", str(resumo_json)]) == 0

    resumo = json.loads(resumo_json.read_text(encoding="utf-8"))
    abertura = resumo["abertura"]
    assert abertura["inicio_script"]["mediana"] == pytest.approx(200)
    assert abertura["imports_concluidos"]["mediana"] == pytest.approx(500)
    assert abertura["dom_pronto"]["mediana"] == pytest.approx(1000)       # 900 + 100
    assert abertura["primeiro_preco"]["mediana"] == pytest.approx(1500)
    assert resumo["funcoes"]["js:render:brl"]["p50"] == 2
    assert resumo["contadores"]["contadores"]["falha:binance"] == 2
    assert resumo["minimizada"]["hidden_ao_minimizar"] == {"casados": 1, "nao_casados": 0}
    assert resumo["minimizada"]["atraso_timer_minimizada"]["max"] == 900
    assert resumo["minimizada"]["atraso_timer_visivel"]["max"] == 2
    assert "A página recebe visibilityState='hidden' ao minimizar? sim" in capsys.readouterr().out
