"""inicio_paralelo.py: duas tarefas de inicialização ao mesmo tempo, sem derrubar a abertura."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import inicio_paralelo  # noqa: E402


def test_as_duas_tarefas_rodam_ao_mesmo_tempo_em_threads_diferentes():
    principal_comecou, auxiliar_comecou = threading.Event(), threading.Event()
    threads = {}

    def principal():
        threads["principal"] = threading.current_thread()
        principal_comecou.set()
        assert auxiliar_comecou.wait(5), "a auxiliar precisa rodar enquanto a principal ainda está rodando"

    def auxiliar():
        threads["auxiliar"] = threading.current_thread()
        auxiliar_comecou.set()
        assert principal_comecou.wait(5)

    resultado = inicio_paralelo.rodar(principal, auxiliar)
    assert resultado.esperar_auxiliar(5)
    assert resultado.erros() == []
    assert threads["principal"] is threading.current_thread(), "a principal roda na thread de quem chamou"
    assert threads["auxiliar"] is not threading.current_thread()
    assert resultado.inicio <= resultado.fim_principal and resultado.inicio <= resultado.fim_auxiliar


def test_volta_quando_a_principal_termina_sem_esperar_a_auxiliar():
    liberar = threading.Event()
    resultado = inicio_paralelo.rodar(lambda: None, lambda: liberar.wait(5))
    assert resultado.fim_principal is not None and resultado.fim_auxiliar is None
    assert resultado.esperar_auxiliar(0.01) is False
    liberar.set()
    assert resultado.esperar_auxiliar(5) is True
    assert resultado.fim_auxiliar is not None


def test_erro_em_qualquer_das_tarefas_fica_guardado_e_nao_sobe():
    def falha_principal():
        raise RuntimeError("sem .NET")

    def falha_auxiliar():
        raise ImportError("sem pywebview")

    resultado = inicio_paralelo.rodar(falha_principal, falha_auxiliar)
    assert resultado.esperar_auxiliar(5)
    assert resultado.erros() == ["tarefa principal: RuntimeError('sem .NET')",
                                 "tarefa auxiliar: ImportError('sem pywebview')"]
    assert resultado.fim_principal is not None and resultado.fim_auxiliar is not None


def test_importar_o_modulo_e_leve():
    codigo = ("import sys; antes = set(sys.modules); import inicio_paralelo; "
              "print(sorted(m for m in ('json', 'logging', 'ctypes', 'webview', 're') "
              "if m in sys.modules and m not in antes))")
    saida = subprocess.run([sys.executable, "-S", "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, saida.stderr
    assert saida.stdout.strip() == "[]"


def test_imports_iguais_em_duas_threads_terminam_sem_travar():
    """O uso real: a auxiliar importa módulos que a principal importa logo depois."""
    codigo = (
        "import inicio_paralelo, sys\n"
        "def auxiliar():\n"
        "    import logging, configparser, json, http.server, email.parser\n"
        "def principal():\n"
        "    import inspect, traceback, collections, warnings, importlib.abc\n"
        "r = inicio_paralelo.rodar(principal, auxiliar)\n"
        "import logging, configparser, json, http.server\n"
        "print(r.esperar_auxiliar(20), r.erros())\n"
    )
    for _ in range(5):
        saida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=60)
        assert saida.returncode == 0, saida.stderr
        assert saida.stdout.strip() == "True []"
