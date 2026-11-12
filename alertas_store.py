"""Persistência e validação dos alertas de preço.

Módulo sem dependências de interface gráfica, para poder ser testado isoladamente.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TIPOS_VALIDOS = frozenset({"maior", "menor", "desativado"})
MAX_ALERTAS = 100
MAX_TAMANHO_ID = 64
NOME_ARQUIVO = "Alertas.json"


class AlertasInvalidosError(ValueError):
    """Os dados recebidos não estão no formato esperado para a lista de alertas."""


def _normalizar_valor(valor: Any, posicao: int) -> float:
    """Converte o valor do alerta para float positivo com 2 casas decimais.

    Aceita string numérica para manter compatibilidade com arquivos antigos,
    que gravavam o valor exatamente como digitado no campo.
    """
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        raise AlertasInvalidosError(f"alerta {posicao}: valor com tipo inválido")
    try:
        numero = float(valor)
    except ValueError as erro:
        raise AlertasInvalidosError(f"alerta {posicao}: valor não numérico") from erro
    if not math.isfinite(numero) or numero <= 0:
        raise AlertasInvalidosError(f"alerta {posicao}: valor deve ser maior que zero")
    return round(numero, 2)


def validar_alertas(dados: Any) -> list[dict[str, Any]]:
    """Valida e normaliza a lista de alertas.

    Formato de cada alerta: {"id": str (opcional), "valor": número > 0, "tipo": str}.
    Campos desconhecidos são descartados.

    Raises:
        AlertasInvalidosError: se a estrutura ou algum alerta for inválido.
    """
    if not isinstance(dados, list):
        raise AlertasInvalidosError("a lista de alertas deve ser um array")
    if len(dados) > MAX_ALERTAS:
        raise AlertasInvalidosError(f"máximo de {MAX_ALERTAS} alertas")

    alertas: list[dict[str, Any]] = []
    for posicao, item in enumerate(dados):
        if not isinstance(item, dict):
            raise AlertasInvalidosError(f"alerta {posicao}: deve ser um objeto")

        tipo = item.get("tipo")
        if tipo not in TIPOS_VALIDOS:
            raise AlertasInvalidosError(f"alerta {posicao}: tipo desconhecido")

        alerta: dict[str, Any] = {}
        id_alerta = item.get("id")
        if id_alerta is not None:
            if not isinstance(id_alerta, str) or not 0 < len(id_alerta) <= MAX_TAMANHO_ID:
                raise AlertasInvalidosError(f"alerta {posicao}: id inválido")
            alerta["id"] = id_alerta
        alerta["valor"] = _normalizar_valor(item.get("valor"), posicao)
        alerta["tipo"] = tipo
        alertas.append(alerta)

    return alertas


class RepositorioAlertas:
    """Lê e grava a lista de alertas em disco de forma segura.

    O pywebview executa cada chamada da js_api numa thread nova, então duas
    gravações podem chegar ao mesmo tempo. A trava serializa o acesso ao arquivo.
    """

    def __init__(self, pasta: Path) -> None:
        self.arquivo = pasta / NOME_ARQUIVO
        self._trava = threading.Lock()

    def salvar(self, dados: Any) -> None:
        """Valida e grava os alertas de forma atômica.

        A gravação vai primeiro para um arquivo temporário, que depois substitui
        o original. Uma queda no meio da escrita nunca deixa o arquivo pela metade.

        Raises:
            AlertasInvalidosError: se os dados forem inválidos (nada é gravado).
            OSError: em falhas de disco.
        """
        alertas = validar_alertas(dados)
        temporario = self.arquivo.with_suffix(self.arquivo.suffix + ".tmp")
        with self._trava:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            with open(temporario, "w", encoding="utf-8") as arquivo:
                json.dump(alertas, arquivo, indent=4, ensure_ascii=False)
                arquivo.flush()
                os.fsync(arquivo.fileno())
            os.replace(temporario, self.arquivo)

    def carregar(self) -> list[dict[str, Any]] | None:
        """Carrega os alertas do disco.

        Returns:
            A lista de alertas ([] se o arquivo ainda não existe), ou None se o
            arquivo existe mas não pôde ser lido. Quando o conteúdo está corrompido,
            o arquivo é preservado como cópia .bak antes de retornar None.
        """
        with self._trava:
            if not self.arquivo.is_file():
                return []

            try:
                conteudo = self.arquivo.read_text(encoding="utf-8")
            except OSError:
                logger.exception("Falha ao ler %s", self.arquivo)
                return None

            try:
                return validar_alertas(json.loads(conteudo))
            except (json.JSONDecodeError, AlertasInvalidosError) as erro:
                logger.error("Arquivo de alertas inválido (%s); criando backup", erro)
                self._preservar_corrompido()
                return None

    def _preservar_corrompido(self) -> None:
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = self.arquivo.with_name(f"{self.arquivo.stem}.{carimbo}.bak")
        try:
            os.replace(self.arquivo, destino)
            logger.warning("Arquivo corrompido preservado em %s", destino)
        except OSError:
            logger.exception("Falha ao criar backup de %s", self.arquivo)
