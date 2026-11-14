"""Registro de métricas de desempenho do BTC Status.

Grava uma linha JSON por registro em %APPDATA%\\btcstatus\\metricas.jsonl.
Cada execução do app é uma "sessão" (uuid). A análise é feita por
tools/analisar_metricas.py.

Tipos de registro ("tipo"):
- "abertura_python": marcos da abertura no Python (ms desde o início do script)
  e os instantes absolutos (epoch) do início do processo e do script;
- "janela": eventos nativos da janela (minimized, restored, ...);
- "js": relatório enviado pela página (metricas.js);
- "api_python": duração dos métodos da ExposedApi no Python;
- "encerramento": fim da sessão.

Módulo sem dependências de interface gráfica, para poder ser testado isoladamente.
"""

from __future__ import annotations

import ctypes
import json
import logging
import math
import os
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

NOME_ARQUIVO = "metricas.jsonl"
TAMANHO_MAXIMO_ARQUIVO = 5_000_000      # ao passar disso, o arquivo vira metricas.jsonl.1
TAMANHO_MAXIMO_RELATORIO_JS = 512_000   # bytes do JSON vindo da página
PROFUNDIDADE_MAXIMA_JS = 6
MAX_AMOSTRAS_API = 2000
VARIAVEL_SESSAO = "BTC_SESSAO_METRICAS" # permite a tools/medir_abertura.py identificar a sessão


class MetricasInvalidasError(ValueError):
    """O relatório recebido da página não tem o formato esperado."""


def estatisticas(valores: list[float]) -> dict[str, float | int]:
    """Resumo de uma lista de durações: n, média, p50, p95 e máximo (ms)."""
    if not valores:
        return {"n": 0}
    ordenados = sorted(valores)

    def percentil(p: float) -> float:
        # Interpolação linear entre as posições vizinhas (mesmo método do metricas.js).
        posicao = (len(ordenados) - 1) * p
        abaixo = math.floor(posicao)
        acima = math.ceil(posicao)
        return ordenados[abaixo] + (ordenados[acima] - ordenados[abaixo]) * (posicao - abaixo)

    return {
        "n": len(ordenados),
        "media": round(sum(ordenados) / len(ordenados), 3),
        "p50": round(percentil(0.50), 3),
        "p95": round(percentil(0.95), 3),
        "max": round(ordenados[-1], 3),
    }


def filetime_para_epoch(intervalos_100ns: int) -> float:
    """Converte um FILETIME (intervalos de 100 ns desde 01/01/1601) em epoch (s)."""
    return intervalos_100ns / 10_000_000 - 11_644_473_600


def inicio_do_processo_epoch() -> float | None:
    """Instante (epoch, s) em que o Windows criou este processo.

    Inclui o tempo do bootloader do PyInstaller e da inicialização do Python,
    que acontecem antes da primeira linha do script. Pelo .venv, o python.exe do
    venv é um lançador que cria o interpretador real como processo filho: a medida
    começa no filho.
    """
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Os tipos precisam ser declarados: sem restype, o handle (64 bits) volta
        # truncado como int de 32 bits e a chamada falha.
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        ponteiro = ctypes.POINTER(wintypes.FILETIME)
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, ponteiro, ponteiro, ponteiro, ponteiro]
        kernel32.GetProcessTimes.restype = wintypes.BOOL

        criacao, saida, kernel, usuario = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(
            kernel32.GetCurrentProcess(),
            ctypes.byref(criacao), ctypes.byref(saida),
            ctypes.byref(kernel), ctypes.byref(usuario),
        ):
            logger.warning("GetProcessTimes falhou (erro %s)", ctypes.get_last_error())
            return None
        return filetime_para_epoch((criacao.dwHighDateTime << 32) | criacao.dwLowDateTime)
    except (OSError, AttributeError):
        logger.exception("Falha ao obter o início do processo")
        return None


def _validar_valor(valor: Any, profundidade: int) -> None:
    if profundidade > PROFUNDIDADE_MAXIMA_JS:
        raise MetricasInvalidasError("estrutura aninhada demais")
    if valor is None or isinstance(valor, (bool, str)):
        return
    if isinstance(valor, (int, float)):
        if isinstance(valor, float) and not math.isfinite(valor):
            raise MetricasInvalidasError("número não finito")
        return
    if isinstance(valor, list):
        for item in valor:
            _validar_valor(item, profundidade + 1)
        return
    if isinstance(valor, dict):
        for chave, item in valor.items():
            if not isinstance(chave, str):
                raise MetricasInvalidasError("chave não textual")
            _validar_valor(item, profundidade + 1)
        return
    raise MetricasInvalidasError(f"tipo não suportado: {type(valor).__name__}")


def validar_relatorio_js(dados: Any) -> dict[str, Any]:
    """Confere o relatório vindo da página: objeto JSON simples e de tamanho limitado.

    Raises:
        MetricasInvalidasError: se o relatório for inválido.
    """
    if not isinstance(dados, dict):
        raise MetricasInvalidasError("o relatório deve ser um objeto")
    _validar_valor(dados, 0)
    if len(json.dumps(dados, ensure_ascii=False)) > TAMANHO_MAXIMO_RELATORIO_JS:
        raise MetricasInvalidasError("relatório grande demais")
    return dados


class RegistroMetricas:
    """Acumula marcos e durações e grava os registros no arquivo JSONL."""

    def __init__(self, pasta: Path, inicio_perf: float, inicio_epoch: float, sessao: str | None = None) -> None:
        """
        Args:
            pasta: pasta de dados do usuário.
            inicio_perf: time.perf_counter() na primeira linha do script.
            inicio_epoch: time.time() no mesmo instante.
            sessao: identificador da execução (padrão: variável BTC_SESSAO_METRICAS ou uuid novo).
        """
        self.arquivo = pasta / NOME_ARQUIVO
        self.sessao = sessao or os.getenv(VARIAVEL_SESSAO) or uuid.uuid4().hex
        self._inicio_perf = inicio_perf
        self._inicio_epoch = inicio_epoch
        self._marcos: dict[str, float] = {}
        self._duracoes_api: dict[str, list[float]] = {}
        self._trava = threading.Lock()

    def agora_ms(self) -> float:
        """Milissegundos desde a primeira linha do script."""
        return round((time.perf_counter() - self._inicio_perf) * 1000, 3)

    def marcar(self, nome: str, instante_perf: float | None = None) -> None:
        """Registra o primeiro instante em que um marco da abertura ocorreu.

        instante_perf: valor de time.perf_counter() de quando o marco ocorreu, para um
        marco anotado antes de este registro existir (None: agora).
        """
        if instante_perf is None:
            instante_ms = self.agora_ms()
        else:
            instante_ms = round((instante_perf - self._inicio_perf) * 1000, 3)
        with self._trava:
            self._marcos.setdefault(nome, instante_ms)

    @contextmanager
    def medir(self, nome: str) -> Iterator[None]:
        """Mede a duração do bloco e guarda a amostra em nome."""
        inicio = time.perf_counter()
        try:
            yield
        finally:
            duracao = (time.perf_counter() - inicio) * 1000
            with self._trava:
                amostras = self._duracoes_api.setdefault(nome, [])
                if len(amostras) < MAX_AMOSTRAS_API:
                    amostras.append(round(duracao, 3))

    def gravar(self, tipo: str, dados: dict[str, Any]) -> bool:
        """Acrescenta um registro ao arquivo. Nunca lança exceção (medição não pode derrubar o app)."""
        registro = {
            "sessao": self.sessao,
            "tipo": tipo,
            "quando": datetime.now().isoformat(timespec="milliseconds"),
            "epoch": round(time.time(), 3),  # alinha com os instantes da página (epoch em ms / 1000)
            "t_ms": self.agora_ms(),
            **dados,
        }
        linha = json.dumps(registro, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            with self._trava:
                self.arquivo.parent.mkdir(parents=True, exist_ok=True)
                self._rotacionar_se_preciso()
                with open(self.arquivo, "a", encoding="utf-8") as arquivo:
                    arquivo.write(linha)
            return True
        except OSError:
            logger.exception("Falha ao gravar métricas")
            return False

    def gravar_abertura_python(self) -> bool:
        with self._trava:
            marcos = dict(self._marcos)
        return self.gravar("abertura_python", {
            "inicio_processo_epoch": inicio_do_processo_epoch(),
            "inicio_script_epoch": self._inicio_epoch,
            "marcos_ms": marcos,
            "congelado": bool(getattr(sys, "frozen", False)),
            "python": sys.version.split()[0],
        })

    def gravar_api_python(self, motivo: str) -> bool:
        """Grava as amostras acumuladas da ExposedApi e começa um novo período."""
        with self._trava:
            duracoes, self._duracoes_api = self._duracoes_api, {}
        if not duracoes:
            return True
        return self.gravar("api_python", {"motivo": motivo, "amostras": duracoes})

    def _rotacionar_se_preciso(self) -> None:
        try:
            if self.arquivo.stat().st_size > TAMANHO_MAXIMO_ARQUIVO:
                os.replace(self.arquivo, self.arquivo.with_name(NOME_ARQUIVO + ".1"))
        except FileNotFoundError:
            pass
