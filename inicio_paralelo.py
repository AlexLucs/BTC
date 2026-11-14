"""Roda duas tarefas de inicialização ao mesmo tempo: uma nesta thread, outra numa auxiliar.

Usado no início do BTC_Monitor.py para subir o .NET ("import clr", ~120 ms, boa parte
fora do Python e sem prender o GIL) enquanto os imports pesados do app (logging,
pywebview, bottle...) correm na thread auxiliar. Antes, as duas coisas aconteciam uma
depois da outra.

Nenhuma das duas tarefas derruba a abertura: a exceção de cada uma fica guardada no
resultado, e o caminho normal (os imports do topo do BTC_Monitor.py e o "import clr" do
próprio pywebview) refaz o que tiver falhado e mostra o erro de verdade.

Leve de propósito: no topo só threading e time (é importado antes de tudo o que pesa).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class ResultadoParalelo:
    """Instantes (time.perf_counter) e erros das duas tarefas."""

    def __init__(self) -> None:
        self.inicio: float = time.perf_counter()
        self.fim_principal: float | None = None
        self.fim_auxiliar: float | None = None
        self.erro_principal: BaseException | None = None
        self.erro_auxiliar: BaseException | None = None
        self._thread: threading.Thread | None = None

    def esperar_auxiliar(self, prazo_s: float) -> bool:
        """Espera a tarefa auxiliar terminar. True se terminou dentro do prazo."""
        if self._thread is None:
            return True
        self._thread.join(prazo_s)
        return not self._thread.is_alive()

    def erros(self) -> list[str]:
        """Descrição dos erros guardados, para o log."""
        achados = []
        if self.erro_principal is not None:
            achados.append(f"tarefa principal: {self.erro_principal!r}")
        if self.erro_auxiliar is not None:
            achados.append(f"tarefa auxiliar: {self.erro_auxiliar!r}")
        return achados


def rodar(principal: Callable[[], None], auxiliar: Callable[[], None],
          nome_da_thread: str = "inicio-paralelo") -> ResultadoParalelo:
    """Inicia auxiliar() numa thread e roda principal() nesta. Volta quando principal()
    termina; a auxiliar pode ainda estar rodando (ver ResultadoParalelo.esperar_auxiliar)."""
    resultado = ResultadoParalelo()

    def rodar_auxiliar() -> None:
        try:
            auxiliar()
        except BaseException as erro:  # noqa: BLE001 - guardado; o caminho normal refaz
            resultado.erro_auxiliar = erro
        finally:
            resultado.fim_auxiliar = time.perf_counter()

    resultado._thread = threading.Thread(target=rodar_auxiliar, name=nome_da_thread, daemon=True)
    resultado._thread.start()
    try:
        principal()
    except Exception as erro:  # noqa: BLE001 - guardado; o caminho normal refaz
        resultado.erro_principal = erro
    finally:
        resultado.fim_principal = time.perf_counter()
    return resultado
