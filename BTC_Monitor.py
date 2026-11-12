"""BTC Status: janela pywebview que exibe o preço do Bitcoin e as taxas da rede.

Coordenadas de janela e de monitor estão sempre em pixels lógicos, que é a
unidade usada pelo pywebview (window.x/y, window.move e webview.screens).
"""

from __future__ import annotations

# Primeira medição da abertura: antes de qualquer outro import.
import time

_INICIO_PERF = time.perf_counter()
_INICIO_EPOCH = time.time()

import configparser  # noqa: E402 - os imports vêm depois do marco inicial de propósito
import contextlib  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from logging.handlers import RotatingFileHandler  # noqa: E402
from pathlib import Path  # noqa: E402

import webview  # noqa: E402

import topo_janela  # noqa: E402
from alertas_store import AlertasInvalidosError, RepositorioAlertas  # noqa: E402

# Medição de desempenho: presente no código-fonte e no build com -ComMedicao; o build de
# produção exclui o módulo metricas (ver "BTC Monitor.spec") e tudo vira operação vazia.
try:
    from metricas import MetricasInvalidasError, RegistroMetricas, validar_relatorio_js  # noqa: E402
except ImportError:
    RegistroMetricas = None
MEDICAO_ATIVA = RegistroMetricas is not None

WINDOW_TITLE = "BTC Status"
WINDOW_WIDTH = 500
WINDOW_HEIGHT = 810

PASTA_DADOS = Path(os.getenv("APPDATA") or Path.home()) / "btcstatus"
ARQUIVO_CONFIG = PASTA_DADOS / "BTC Monitor.ini"
ARQUIVO_LOG = PASTA_DADOS / "btcstatus.log"
# Perfil persistente do WebView2 (cache HTTP, código JS compilado, localStorage).
PASTA_WEBVIEW = PASTA_DADOS / "webview"
# No executável do PyInstaller os recursos ficam em sys._MEIPASS.
PASTA_RECURSOS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

logger = logging.getLogger("btcstatus")

class _SemMedicao:
    """Substituto usado no build de produção: não mede nem grava nada."""

    def marcar(self, nome: str) -> None:
        pass

    def medir(self, nome: str):
        return contextlib.nullcontext()


METRICAS = RegistroMetricas(PASTA_DADOS, _INICIO_PERF, _INICIO_EPOCH) if MEDICAO_ATIVA else _SemMedicao()
METRICAS.marcar("imports_concluidos")


def configurar_log() -> None:
    """Grava o log em arquivo, já que o executável não tem console."""
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    formato = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    arquivo = RotatingFileHandler(ARQUIVO_LOG, maxBytes=512_000, backupCount=2, encoding="utf-8")
    arquivo.setFormatter(formato)
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.addHandler(arquivo)

    if sys.stderr is not None:  # None quando executado sem console (pythonw / exe)
        console = logging.StreamHandler()
        console.setFormatter(formato)
        raiz.addHandler(console)


# ---------------------------------------------------------------------------
# Monitores e posição da janela
# ---------------------------------------------------------------------------

def monitor_principal(monitores: list) -> object | None:
    """O monitor principal do Windows é o que tem origem em (0, 0)."""
    if not monitores:
        return None
    return next((m for m in monitores if m.x == 0 and m.y == 0), monitores[0])


def monitor_no_ponto(x: int, y: int, monitores: list) -> object | None:
    """Retorna o monitor que contém o ponto (x, y), ou None."""
    return next(
        (
            m for m in monitores
            if m.x <= x < m.x + m.width and m.y <= y < m.y + m.height
        ),
        None,
    )


def posicao_centralizada(monitor) -> tuple[int, int]:
    """Calcula o canto superior esquerdo que centraliza a janela no monitor."""
    return (
        monitor.x + (monitor.width - WINDOW_WIDTH) // 2,
        monitor.y + (monitor.height - WINDOW_HEIGHT) // 2,
    )


def carregar_posicao() -> tuple[int, int] | None:
    """Lê a última posição salva, se ela ainda estiver dentro de algum monitor."""
    if not ARQUIVO_CONFIG.is_file():
        return None

    config = configparser.ConfigParser()
    try:
        config.read(ARQUIVO_CONFIG, encoding="utf-8")
        x = config.getint("Position", "x")
        y = config.getint("Position", "y")
    except (configparser.Error, ValueError, OSError) as erro:
        logger.warning("Posição salva inválida: %s", erro)
        return None

    if monitor_no_ponto(x, y, webview.screens) is None:
        return None
    return x, y


def salvar_posicao(x: int, y: int) -> None:
    config = configparser.ConfigParser()
    config["Position"] = {"x": str(x), "y": str(y)}
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as arquivo:
        config.write(arquivo)


# ---------------------------------------------------------------------------
# API exposta ao JavaScript
# ---------------------------------------------------------------------------

class ExposedApi:
    """API chamada pelo JavaScript através de window.pywebview.api.

    O pywebview expõe ao JS todo método e todo objeto público desta classe.
    Por isso a janela e o repositório ficam em atributos com "_", que não são expostos.
    """

    def __init__(self, repositorio: RepositorioAlertas, metricas) -> None:
        self._janela: webview.Window | None = None
        self._handle: int | None = None
        self._repositorio = repositorio
        self._metricas = metricas

    def _vincular(self, janela: webview.Window) -> None:
        self._janela = janela

    def fechar(self) -> None:
        if self._janela:
            self._janela.destroy()

    def minimizar(self) -> None:
        if self._janela:
            self._janela.minimize()

    def centralizar(self) -> None:
        """Centraliza a janela no monitor em que ela está (ou no principal)."""
        if not self._janela:
            return
        with self._metricas.medir("centralizar"):
            self._centralizar()

    def _centralizar(self) -> None:
        monitores = webview.screens
        centro_x = self._janela.x + WINDOW_WIDTH // 2
        centro_y = self._janela.y + WINDOW_HEIGHT // 2
        monitor = monitor_no_ponto(centro_x, centro_y, monitores) or monitor_principal(monitores)
        if monitor is None:
            logger.warning("Nenhum monitor encontrado para centralizar a janela")
            return
        self._janela.move(*posicao_centralizada(monitor))

    def _handle_janela(self) -> int | None:
        """Handle Win32 da janela, localizado na primeira vez e depois reutilizado."""
        if self._handle is None:
            try:
                self._handle = topo_janela.encontrar_janela(WINDOW_TITLE)
            except OSError:
                logger.exception("Falha ao localizar a janela")
        return self._handle

    def definir_topo(self, fixar: bool) -> bool:
        """Fixa ou desafixa a janela do app no topo e retorna o estado final.

        Não usa window.on_top do pywebview: ver o motivo em topo_janela.py.
        """
        with self._metricas.medir("definir_topo"):
            return self._definir_topo(fixar)

    def _definir_topo(self, fixar: bool) -> bool:
        handle = self._handle_janela()
        if handle is None:
            logger.warning("Janela não encontrada para fixar no topo")
            return False
        try:
            return topo_janela.definir_topo(handle, bool(fixar))
        except OSError:
            logger.exception("Falha ao alterar a fixação no topo")
            return self._esta_no_topo()

    def esta_no_topo(self) -> bool:
        with self._metricas.medir("esta_no_topo"):
            return self._esta_no_topo()

    def _esta_no_topo(self) -> bool:
        handle = self._handle_janela()
        if handle is None:
            return False
        try:
            return topo_janela.esta_no_topo(handle)
        except OSError:
            logger.exception("Falha ao consultar a fixação no topo")
            return False

    def salvar_alerta(self, alertas) -> bool:
        """Grava os alertas em disco. Retorna False se os dados forem rejeitados."""
        try:
            with self._metricas.medir("salvar_alerta"):
                self._repositorio.salvar(alertas)
            return True
        except AlertasInvalidosError as erro:
            logger.warning("Alertas rejeitados: %s", erro)
        except OSError:
            logger.exception("Falha ao gravar alertas")
        return False

    def carregar_alerta(self) -> list | None:
        """Retorna a lista de alertas, ou None se o arquivo não pôde ser lido."""
        with self._metricas.medir("carregar_alerta"):
            return self._repositorio.carregar()


class ExposedApiComMedicao(ExposedApi):
    """ExposedApi + recebimento dos relatórios do metricas.js (só quando a medição está ativa).

    No build de produção a API exposta ao JS não tem registrar_metricas.
    """

    def registrar_metricas(self, relatorio) -> bool:
        """Grava um relatório de desempenho enviado pela página (metricas.js)."""
        try:
            dados = validar_relatorio_js(relatorio)
        except MetricasInvalidasError as erro:
            logger.warning("Relatório de métricas rejeitado: %s", erro)
            return False
        motivo = str(dados.get("motivo", ""))
        self._metricas.gravar_api_python(motivo)
        return self._metricas.gravar("js", {"relatorio": dados})


# ---------------------------------------------------------------------------
# Métricas de desempenho (ver metricas.py)
# ---------------------------------------------------------------------------

def registrar_eventos_metricas(janela: webview.Window) -> None:
    """Marca as etapas da abertura e registra minimizar/restaurar e o encerramento.

    Os handlers não têm parâmetros (o pywebview repassaria argumentos do evento) e
    sempre retornam None: em eventos como closing e initialized, retornar False
    cancelaria a ação.
    """

    def marcador(nome: str):
        def marcar() -> None:
            METRICAS.marcar(nome)
        return marcar

    def gravador_janela(nome: str):
        def gravar() -> None:
            METRICAS.gravar("janela", {"evento": nome})
        return gravar

    def ao_carregar() -> None:
        METRICAS.marcar("evento_loaded")
        METRICAS.gravar_abertura_python()

    def ao_encerrar() -> None:
        METRICAS.gravar_api_python("encerramento")
        METRICAS.gravar("encerramento", {})

    for nome in ("initialized", "before_show", "shown", "before_load"):
        evento = getattr(janela.events, nome)
        evento += marcador(f"evento_{nome}")  # Event.__iadd__ registra no próprio objeto
    janela.events.loaded += ao_carregar
    janela.events.minimized += gravador_janela("minimized")
    janela.events.restored += gravador_janela("restored")
    janela.events.closing += ao_encerrar


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

def opcoes_de_armazenamento() -> dict:
    """Perfil persistente do WebView2 em PASTA_WEBVIEW.

    Com private_mode=True (padrão do pywebview), cada abertura começa sem cache
    (o widget do TradingView é baixado de novo) e, ao fechar, o pywebview apaga o
    perfil esperando o processo do navegador terminar. Se a pasta não puder ser
    criada, mantém o modo privado para o app abrir mesmo assim.
    """
    try:
        PASTA_WEBVIEW.mkdir(parents=True, exist_ok=True)
        if not os.access(PASTA_WEBVIEW, os.W_OK):
            raise PermissionError(f"sem permissão de escrita em {PASTA_WEBVIEW}")
    except OSError as erro:
        logger.warning("Perfil persistente indisponível (%s); usando modo privado", erro)
        return {}
    return {"private_mode": False, "storage_path": str(PASTA_WEBVIEW)}


def abrir_janela() -> None:
    index = PASTA_RECURSOS / "index.html"
    if not index.is_file():
        logger.error("index.html não encontrado em %s", PASTA_RECURSOS)
        return

    classe_api = ExposedApiComMedicao if MEDICAO_ATIVA else ExposedApi
    api = classe_api(RepositorioAlertas(PASTA_DADOS), METRICAS)

    # A 1ª leitura de webview.screens inicializa o motor gráfico (pythonnet/.NET);
    # o marco separa esse custo do create_window.
    posicao = carregar_posicao()
    METRICAS.marcar("posicao_calculada")
    if posicao is not None:
        x, y = posicao
    else:
        monitor = monitor_principal(webview.screens)
        x, y = posicao_centralizada(monitor) if monitor else (None, None)

    janela = webview.create_window(
        WINDOW_TITLE,
        str(index),
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        frameless=True,
        background_color="#000000",
        x=x,
        y=y,
        js_api=api,
    )
    api._vincular(janela)
    METRICAS.marcar("janela_criada")
    if MEDICAO_ATIVA:
        registrar_eventos_metricas(janela)

    def ao_fechar() -> None:
        try:
            salvar_posicao(janela.x, janela.y)
        except Exception:  # noqa: BLE001 - nunca impedir o fechamento da janela
            logger.exception("Falha ao salvar a posição da janela")

    janela.events.closing += ao_fechar
    METRICAS.marcar("webview_start")
    webview.start(user_agent="pywebview", **opcoes_de_armazenamento())


def main() -> None:
    configurar_log()
    METRICAS.marcar("log_configurado")
    try:
        abrir_janela()
    except Exception:
        logger.exception("Erro fatal ao abrir a janela")
        raise


if __name__ == "__main__":
    main()
