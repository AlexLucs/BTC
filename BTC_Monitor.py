"""BTC Status: janela pywebview que exibe o preço do Bitcoin e as taxas da rede.

Coordenadas de janela e de monitor estão sempre em pixels lógicos, que é a
unidade usada pelo pywebview (window.x/y, window.move e webview.screens).
"""

from __future__ import annotations

# Primeira medição da abertura: antes de qualquer outro import.
import time

_INICIO_PERF = time.perf_counter()
_INICIO_EPOCH = time.time()

import os  # noqa: E402 - os imports vêm depois do marco inicial de propósito
import sys  # noqa: E402

# ---------------------------------------------------------------------------
# 1º preço: a requisição sai AQUI, antes dos imports pesados (logging, pywebview...).
#
# Ela leva ~350-500 ms e a página fica pronta para usá-la ~600 ms depois da criação do
# processo: cada ms ganho no início vale para o preço chegar a tempo de ir dentro do HTML.
# Por isso o primeiro_preco é leve (só threading e time no topo) e nada pesado pode ser
# importado antes deste bloco. Só ao executar o app: importar este módulo (testes) não
# faz nenhuma requisição.
# ---------------------------------------------------------------------------
from primeiro_preco import BuscaPrimeiroPreco  # noqa: E402

# Só na medição (tools/medir_abertura.py --comparar): preco-python não busca o preço pelo
# Python (a página fica só com o REST); preco-cedo o busca só no main(), depois dos imports.
VARIAVEL_SEM_PRECO_PYTHON = "BTC_SEM_PRECO_PYTHON"
VARIAVEL_SEM_PRECO_CEDO = "BTC_SEM_PRECO_CEDO"

# adiar_log: o log em arquivo só é configurado no main(); uma falha antes disso é
# registrada quando ele estiver pronto (liberar_log).
BUSCA_PRIMEIRO_PRECO = BuscaPrimeiroPreco(adiar_log=True)


def _desligado_antes_dos_imports(*variaveis: str) -> bool:
    """True se alguma variável BTC_SEM_* está ligada E a medição existe neste build.

    Vale antes de MEDICAO_ATIVA existir. O módulo metricas só é importado se alguma
    variável estiver ligada (o que só o medir_abertura.py faz): no uso normal esta função
    não importa nada, e na produção, sem o módulo, as variáveis são ignoradas.
    """
    if not any(os.environ.get(variavel) == "1" for variavel in variaveis):
        return False
    try:
        import metricas  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


if __name__ == "__main__" and not _desligado_antes_dos_imports(VARIAVEL_SEM_PRECO_PYTHON, VARIAVEL_SEM_PRECO_CEDO):
    BUSCA_PRIMEIRO_PRECO.iniciar()

# ---------------------------------------------------------------------------
# .NET em paralelo com os imports.
#
# Subir o .NET ("import clr": pythonnet + CLR, ~120 ms) e importar o resto do app (~40 ms)
# aconteciam um depois do outro. Boa parte do "import clr" roda fora do Python e não
# prende o GIL: aqui ele roda nesta thread (a mesma em que o pywebview o usaria) enquanto
# uma thread auxiliar faz os imports pesados. Os imports logo abaixo acham os módulos já
# carregados (ou esperam o que estiver em andamento), e o "import clr" do pywebview
# (webview/platforms/winforms.py) acha o .NET pronto. Se algo falhar aqui, o erro fica
# guardado para o log e esses caminhos normais refazem o trabalho.
# ---------------------------------------------------------------------------
import inicio_paralelo  # noqa: E402

# Só na medição (--comparar net-cedo): o .NET sobe só no 1º webview.screens, como antes.
VARIAVEL_SEM_NET_CEDO = "BTC_SEM_NET_CEDO"


def _importar_clr() -> None:
    import clr  # noqa: F401, PLC0415 - o mesmo import que o pywebview faz


def _importar_o_resto() -> None:
    """Os imports pesados do app, na mesma ordem do topo deste arquivo."""
    import ssl_ausente  # noqa: PLC0415

    ssl_ausente.garantir()  # antes do "import webview"
    import configparser  # noqa: F401, PLC0415
    import contextlib  # noqa: F401, PLC0415
    import logging  # noqa: F401, PLC0415
    import logging.handlers  # noqa: F401, PLC0415
    import pathlib  # noqa: F401, PLC0415

    import webview  # noqa: F401, PLC0415

    import alertas_store  # noqa: F401, PLC0415
    import argumentos_webview2  # noqa: F401, PLC0415
    import bordas_janela  # noqa: F401, PLC0415
    import servidor_local  # noqa: F401, PLC0415
    import topo_janela  # noqa: F401, PLC0415


INICIO_PARALELO: inicio_paralelo.ResultadoParalelo | None = None
if (__name__ == "__main__" and sys.platform == "win32"
        and not _desligado_antes_dos_imports(VARIAVEL_SEM_NET_CEDO)):
    INICIO_PARALELO = inicio_paralelo.rodar(_importar_clr, _importar_o_resto)

import configparser  # noqa: E402
import contextlib  # noqa: E402
import logging  # noqa: E402
from logging.handlers import RotatingFileHandler  # noqa: E402
from pathlib import Path  # noqa: E402

# Antes do "import webview": o pywebview importa o ssl no topo, e o executável não o leva.
import ssl_ausente  # noqa: E402

ssl_ausente.garantir()

import webview  # noqa: E402

import argumentos_webview2  # noqa: E402
import topo_janela  # noqa: E402
from bordas_janela import Arrastador, area_livre  # noqa: E402
from alertas_store import AlertasInvalidosError, RepositorioAlertas  # noqa: E402
from servidor_local import PORTA as PORTA_LOCAL  # noqa: E402
from servidor_local import criar_aplicativo  # noqa: E402

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
# Modo compacto (style.css: html.compacto): sem logo, tabela e gráfico. A altura deixa
# abaixo do rodapé (máxima/mínima) a mesma margem que há acima dos botões (12 px).
WINDOW_HEIGHT_COMPACTA = 388

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

    def marcar(self, nome: str, instante_perf: float | None = None) -> None:
        pass

    def medir(self, nome: str):
        return contextlib.nullcontext()


METRICAS = RegistroMetricas(PASTA_DADOS, _INICIO_PERF, _INICIO_EPOCH) if MEDICAO_ATIVA else _SemMedicao()
if INICIO_PARALELO is not None:
    # Os imports acima já esperaram os módulos em andamento; aqui só o fim da thread.
    INICIO_PARALELO.esperar_auxiliar(10)
    METRICAS.marcar("net_cedo_inicio", INICIO_PARALELO.inicio)
    METRICAS.marcar("net_cedo_clr", INICIO_PARALELO.fim_principal)
    METRICAS.marcar("net_cedo_imports", INICIO_PARALELO.fim_auxiliar)
METRICAS.marcar("imports_concluidos")

# A busca do 1º preço começou antes de o registro de métricas existir (início deste
# arquivo): os marcos dela foram guardados com o instante de cada um e entram agora.
BUSCA_PRIMEIRO_PRECO.ligar_metricas(METRICAS)


def deve_buscar_preco_pelo_python() -> bool:
    return not (MEDICAO_ATIVA and os.getenv(VARIAVEL_SEM_PRECO_PYTHON) == "1")


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


def altura_da_janela(compacto: bool) -> int:
    return WINDOW_HEIGHT_COMPACTA if compacto else WINDOW_HEIGHT


def posicao_centralizada(monitor, largura: int = WINDOW_WIDTH, altura: int = WINDOW_HEIGHT) -> tuple[int, int]:
    """Calcula o canto superior esquerdo que centraliza a janela na área livre do monitor."""
    area = area_livre(monitor)
    return (
        area.esquerda + (area.largura - largura) // 2,
        area.topo + (area.altura - altura) // 2,
    )


def posicao_dentro_do_monitor(x: int, y: int, largura: int, altura: int, monitor) -> tuple[int, int]:
    """Desloca (x, y) o mínimo necessário para a janela inteira caber na área livre do monitor.

    A área livre exclui a barra de tarefas (ver bordas_janela.area_livre; sem ela, vale a
    área total). Se a janela for maior que a área, prevalece o canto superior esquerdo (a
    barra de botões continua alcançável).
    """
    area = area_livre(monitor)
    x = max(area.esquerda, min(x, area.direita - largura))
    y = max(area.topo, min(y, area.base - altura))
    return x, y


SECAO_POSICAO = "Position"
SECAO_JANELA = "Janela"


def _ler_config() -> configparser.ConfigParser | None:
    if not ARQUIVO_CONFIG.is_file():
        return None
    config = configparser.ConfigParser()
    try:
        config.read(ARQUIVO_CONFIG, encoding="utf-8")
    except (configparser.Error, OSError) as erro:
        logger.warning("Configuração da janela ilegível: %s", erro)
        return None
    return config


def carregar_posicao(monitores: list) -> tuple[int, int] | None:
    """Lê a última posição salva, se ela ainda estiver dentro de algum monitor."""
    config = _ler_config()
    if config is None:
        return None
    try:
        x = config.getint(SECAO_POSICAO, "x")
        y = config.getint(SECAO_POSICAO, "y")
    except (configparser.Error, ValueError) as erro:
        logger.warning("Posição salva inválida: %s", erro)
        return None

    if monitor_no_ponto(x, y, monitores) is None:
        return None
    return x, y


def carregar_modo_compacto() -> bool:
    """Lê o modo da janela salvo; sem arquivo ou com valor inválido, o modo completo."""
    config = _ler_config()
    if config is None:
        return False
    try:
        return config.getboolean(SECAO_JANELA, "compacto", fallback=False)
    except ValueError as erro:
        logger.warning("Modo da janela salvo inválido: %s", erro)
        return False


def salvar_configuracao(x: int, y: int, compacto: bool) -> None:
    """Grava posição e modo juntos: o arquivo é sempre reescrito por inteiro."""
    config = configparser.ConfigParser()
    config[SECAO_POSICAO] = {"x": str(x), "y": str(y)}
    config[SECAO_JANELA] = {"compacto": "1" if compacto else "0"}
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

    def __init__(self, repositorio: RepositorioAlertas, metricas, compacto: bool = False) -> None:
        self._janela: webview.Window | None = None
        self._handle: int | None = None
        self._repositorio = repositorio
        self._metricas = metricas
        self._compacto = compacto
        self._arrastador = Arrastador(self._handle_janela)

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
        altura = altura_da_janela(self._compacto)
        centro_x = self._janela.x + WINDOW_WIDTH // 2
        centro_y = self._janela.y + altura // 2
        monitor = monitor_no_ponto(centro_x, centro_y, monitores) or monitor_principal(monitores)
        if monitor is None:
            logger.warning("Nenhum monitor encontrado para centralizar a janela")
            return
        self._janela.move(*posicao_centralizada(monitor, WINDOW_WIDTH, altura))

    def definir_compacto(self, ativo: bool) -> bool:
        """Liga ou desliga o modo compacto: muda a altura da janela mantendo o topo.

        Se a janela maior passar da borda do monitor, ela sobe o necessário. Retorna
        True se a janela foi redimensionada. O modo é gravado no .ini ao fechar.

        window.resize do pywebview 6.2.1 (WinForms) chama SetWindowPos pelo ctypes, que
        libera o GIL (como window.move, usado em centralizar): não trava como o setter de
        TopMost (ver topo_janela.py).
        """
        if not self._janela:
            return False
        with self._metricas.medir("definir_compacto"):
            return self._definir_compacto(bool(ativo))

    def _definir_compacto(self, ativo: bool) -> bool:
        altura = altura_da_janela(ativo)
        try:
            self._janela.resize(WINDOW_WIDTH, altura)  # topo fixo (FixPoint.NORTH | WEST, o padrão)
            self._compacto = ativo
            x, y = self._janela.x, self._janela.y
            monitores = webview.screens
            monitor = monitor_no_ponto(x, y, monitores) or monitor_principal(monitores)
            if monitor is not None:
                nova = posicao_dentro_do_monitor(x, y, WINDOW_WIDTH, altura, monitor)
                if nova != (x, y):
                    self._janela.move(*nova)
        except Exception:  # noqa: BLE001 - a página só precisa saber que falhou
            logger.exception("Falha ao mudar o modo compacto")
            return False
        return True

    def _modo_compacto(self) -> bool:
        return self._compacto

    def _handle_janela(self) -> int | None:
        """Handle Win32 da janela, localizado na primeira vez e depois reutilizado."""
        if self._handle is None:
            try:
                self._handle = topo_janela.encontrar_janela(WINDOW_TITLE)
            except OSError:
                logger.exception("Falha ao localizar a janela")
        return self._handle

    def iniciar_arraste(self) -> bool:
        """Começa a arrastar a janela com o mouse, com bordas magnéticas.

        Chamado pelo script.js ao pressionar o botão principal na região de arrasto. O
        arraste segue numa thread própria até o botão ser solto (ver bordas_janela.py) e
        este método retorna na hora: False se já houver um arraste em andamento.
        Substitui o easy_drag do pywebview, que não respeita as bordas da tela.
        """
        with self._metricas.medir("iniciar_arraste"):
            return self._arrastador.iniciar()

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
# Tamanho inicial da janela
# ---------------------------------------------------------------------------

def registrar_ajuste_de_tamanho(janela: webview.Window, api: ExposedApi) -> None:
    """Corrige o tamanho da janela assim que ela é exibida (evento shown).

    O pywebview 6.2.1 (WinForms) define o tamanho da janela ainda com a moldura normal e
    só depois aplica o frameless; o WinForms mantém a área interna, e a janela nasce menor
    pela moldura (~16 px na largura e ~40 px na altura com 100% de escala). O resize usa
    SetWindowPos pelo ctypes (libera o GIL, como em definir_compacto). A janela é exibida
    antes de a página começar a carregar, então a correção acontece com ela ainda vazia.
    """

    def ajustar() -> None:  # sem parâmetros e sem retorno (ver armadilha dos handlers)
        try:
            janela.resize(WINDOW_WIDTH, altura_da_janela(api._modo_compacto()))
            METRICAS.marcar("tamanho_ajustado")
        except Exception:  # noqa: BLE001 - a janela continua utilizável, só um pouco menor
            logger.exception("Falha ao ajustar o tamanho inicial da janela")

    janela.events.shown += ajustar


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


# Só na medição: tools/medir_abertura.py --comparar preconnect liga esta variável em metade
# das aberturas, e a página é servida sem as dicas de pré-conexão do <head>.
VARIAVEL_SEM_PRECONNECT = "BTC_SEM_PRECONNECT"
# Idem para --comparar preload-fonte: o servidor local não ajusta o preload da fonte.
VARIAVEL_SEM_AJUSTE_PRELOAD = "BTC_SEM_AJUSTE_PRELOAD"
# Idem para --comparar tipos-fixos: o servidor local deixa o bottle adivinhar o tipo de
# cada arquivo (mimetypes, que lê o registro do Windows na 1ª vez).
VARIAVEL_SEM_TIPOS_FIXOS = "BTC_SEM_TIPOS_FIXOS"
# Idem para --comparar preco-no-html: o 1º preço não vai dentro do HTML (só /preco-inicial).
VARIAVEL_SEM_PRECO_NO_HTML = "BTC_SEM_PRECO_NO_HTML"
# Idem para --comparar argumentos-webview2 (e tools/medir_trafego.py --comparar-adotados): o
# WebView2 sobe sem os argumentos extras de argumentos_webview2.py.
VARIAVEL_SEM_ARGUMENTOS_WEBVIEW2 = "BTC_SEM_ARGUMENTOS_WEBVIEW2"


def recurso_desligado_na_medicao(variavel: str) -> bool:
    """As variáveis BTC_SEM_* só valem com a medição ativa; a produção as ignora."""
    return MEDICAO_ATIVA and os.getenv(variavel) == "1"


def remover_preconnect(html: str) -> str:
    """Tira do HTML as linhas com <link rel="preconnect"> ou <link rel="dns-prefetch">."""
    dicas = ('rel="preconnect"', 'rel="dns-prefetch"')
    return "".join(linha for linha in html.splitlines(keepends=True)
                   if not (linha.lstrip().startswith("<link") and any(d in linha for d in dicas)))


def html_da_pagina() -> str:
    """HTML entregue em "/" pelo servidor local (sem as dicas de pré-conexão, se a medição pedir)."""
    html = (PASTA_RECURSOS / "index.html").read_text(encoding="utf-8")
    if MEDICAO_ATIVA and os.getenv(VARIAVEL_SEM_PRECONNECT) == "1":
        return remover_preconnect(html)
    return html


def abrir_janela() -> None:
    index = PASTA_RECURSOS / "index.html"
    if not index.is_file():
        logger.error("index.html não encontrado em %s", PASTA_RECURSOS)
        return
    compacto = carregar_modo_compacto()
    classe_api = ExposedApiComMedicao if MEDICAO_ATIVA else ExposedApi
    api = classe_api(RepositorioAlertas(PASTA_DADOS), METRICAS, compacto=compacto)

    aplicativo = criar_aplicativo(
        PASTA_RECURSOS, html_da_pagina, BUSCA_PRIMEIRO_PRECO,
        ajustar_preload=not recurso_desligado_na_medicao(VARIAVEL_SEM_AJUSTE_PRELOAD),
        tipos_fixos=not recurso_desligado_na_medicao(VARIAVEL_SEM_TIPOS_FIXOS),
        preco_no_html=not recurso_desligado_na_medicao(VARIAVEL_SEM_PRECO_NO_HTML),
        marcar=METRICAS.marcar if MEDICAO_ATIVA else None,
        modo_compacto=api._modo_compacto,
    )

    # A 1ª leitura de webview.screens inicializa o motor gráfico (pythonnet/.NET);
    # o marco separa esse custo do create_window.
    altura = altura_da_janela(compacto)
    monitores = webview.screens
    posicao = carregar_posicao(monitores)
    if posicao is not None:
        monitor = monitor_no_ponto(*posicao, monitores)
        x, y = posicao_dentro_do_monitor(*posicao, WINDOW_WIDTH, altura, monitor)
    else:
        monitor = monitor_principal(monitores)
        x, y = posicao_centralizada(monitor, WINDOW_WIDTH, altura) if monitor else (None, None)
    METRICAS.marcar("posicao_calculada")

    # url = aplicativo WSGI: o pywebview o serve em http://127.0.0.1:PORTA_LOCAL/ (a mesma
    # origem do servidor padrão, então o localStorage é mantido). Ver servidor_local.py.
    janela = webview.create_window(
        WINDOW_TITLE,
        aplicativo,
        http_port=PORTA_LOCAL,
        width=WINDOW_WIDTH,
        height=altura,
        frameless=True,
        # O arraste é do app (iniciar_arraste + bordas_janela.py), com bordas magnéticas.
        # O easy_drag do pywebview move a janela pelo JS sem noção das bordas da tela.
        easy_drag=False,
        background_color="#000000",
        x=x,
        y=y,
        js_api=api,
    )
    api._vincular(janela)
    registrar_ajuste_de_tamanho(janela, api)
    METRICAS.marcar("janela_criada")
    if MEDICAO_ATIVA:
        registrar_eventos_metricas(janela)

    def ao_fechar() -> None:
        try:
            salvar_configuracao(janela.x, janela.y, api._modo_compacto())
        except Exception:  # noqa: BLE001 - nunca impedir o fechamento da janela
            logger.exception("Falha ao salvar a posição e o modo da janela")

    janela.events.closing += ao_fechar
    # Antes de o WebView2 ser criado: sem a rede "de fundo" do navegador (ver o módulo).
    if not recurso_desligado_na_medicao(VARIAVEL_SEM_ARGUMENTOS_WEBVIEW2):
        argumentos_webview2.aplicar()
    METRICAS.marcar("webview_start")
    webview.start(user_agent="pywebview", **opcoes_de_armazenamento())


def main() -> None:
    # A busca do 1º preço normalmente já começou, antes dos imports (início deste arquivo);
    # aqui só começa se aquele início foi desligado na medição (iniciar() vale uma vez só).
    if deve_buscar_preco_pelo_python():
        BUSCA_PRIMEIRO_PRECO.iniciar()
    configurar_log()
    BUSCA_PRIMEIRO_PRECO.liberar_log()
    if INICIO_PARALELO is not None:
        for erro in INICIO_PARALELO.erros():
            logger.warning("Início em paralelo (.NET e imports): %s", erro)
    METRICAS.marcar("log_configurado")
    try:
        abrir_janela()
    except Exception:
        logger.exception("Erro fatal ao abrir a janela")
        raise


if __name__ == "__main__":
    main()
