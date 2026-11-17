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
    import logging  # noqa: PLC0415
    import logging.handlers  # noqa: F401, PLC0415
    import pathlib  # noqa: F401, PLC0415
    import threading  # noqa: F401, PLC0415

    import webview  # noqa: F401, PLC0415

    import alertas_store  # noqa: F401, PLC0415
    import argumentos_webview2  # noqa: F401, PLC0415
    import atalho_global  # noqa: F401, PLC0415
    import bordas_janela  # noqa: F401, PLC0415
    import camada_fundo  # noqa: F401, PLC0415
    import instancia_unica  # noqa: F401, PLC0415
    import servidor_local  # noqa: F401, PLC0415
    import topo_janela  # noqa: F401, PLC0415


INICIO_PARALELO: inicio_paralelo.ResultadoParalelo | None = None
if (__name__ == "__main__" and sys.platform == "win32"
        and not _desligado_antes_dos_imports(VARIAVEL_SEM_NET_CEDO)):
    INICIO_PARALELO = inicio_paralelo.rodar(_importar_clr, _importar_o_resto)

import configparser  # noqa: E402
import contextlib  # noqa: E402
import logging  # noqa: E402
import threading  # noqa: E402
from logging.handlers import RotatingFileHandler  # noqa: E402
from pathlib import Path  # noqa: E402

# Antes do "import webview": o pywebview importa o ssl no topo, e o executável não o leva.
import ssl_ausente  # noqa: E402

ssl_ausente.garantir()

import webview  # noqa: E402

import argumentos_webview2  # noqa: E402
import instancia_unica  # noqa: E402
import topo_janela  # noqa: E402
from atalho_global import OuvinteAtalho, SistemaWin32Atalho  # noqa: E402
from bordas_janela import Arrastador, area_livre  # noqa: E402
from camada_fundo import (  # noqa: E402
    CAMADAS,
    CAMADAS_LEMBRADAS,
    ControladorCamada,
    EstadoPublicado,
    SistemaWin32Fundo,
    camada_salva,
)
from alertas_store import AlertasInvalidosError, RepositorioAlertas  # noqa: E402
from servidor_local import PORTA as PORTA_LOCAL  # noqa: E402
from servidor_local import criar_aplicativo  # noqa: E402

# Medição de desempenho: presente no código-fonte e no build com -ComMedicao; o build de
# produção exclui o módulo metricas (ver "BTC Monitor.spec") e tudo vira operação vazia.
try:
    from metricas import MetricasInvalidasError, RegistroMetricas, validar_relatorio_js
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


# BTC_DEPURAR_FUNDO=1: o log ganha as linhas de depuração da camada fundo (camada_fundo.py)
# e do atalho global (atalho_global.py).
VARIAVEL_DEPURAR_FUNDO = "BTC_DEPURAR_FUNDO"
LOGS_DE_DEPURACAO = ("camada_fundo", "atalho_global")


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

    # Diagnóstico da camada fundo e do atalho (vale também no .exe): decisões e "linha de
    # vida" da vigia.
    if os.getenv(VARIAVEL_DEPURAR_FUNDO) == "1":
        for nome in LOGS_DE_DEPURACAO:
            logging.getLogger(nome).setLevel(logging.DEBUG)

    registrar_excecoes_soltas()


def registrar_excecoes_soltas() -> None:
    """Exceção não tratada (no processo ou em qualquer thread) vai para o log.

    O .exe não tem console: sem isto, um erro numa thread sem try (ex.: handler de evento
    do pywebview) sumiria sem rastro. As chamadas da js_api já são registradas pelo próprio
    pywebview (webview/util.py).
    """

    def no_processo(tipo, valor, rastro) -> None:
        if issubclass(tipo, KeyboardInterrupt):
            sys.__excepthook__(tipo, valor, rastro)
            return
        logger.critical("Exceção não tratada", exc_info=(tipo, valor, rastro))

    def na_thread(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        nome = args.thread.name if args.thread is not None else "?"
        logger.error("Exceção não tratada na thread %s", nome,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = no_processo
    threading.excepthook = na_thread


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
# A página pergunta pelo atalho logo após a ponte; ele é registrado no evento shown.
ESPERA_AVISO_ATALHO_S = 3.0
SECAO_JANELA = "Janela"


# Sem interpolação: um "%" escrito à mão no .ini levantaria InterpolationSyntaxError na
# leitura de qualquer valor, e o app não abriria.
def _novo_config() -> configparser.ConfigParser:
    return configparser.ConfigParser(interpolation=None)


def _ler_config() -> configparser.ConfigParser | None:
    if not ARQUIVO_CONFIG.is_file():
        return None
    config = _novo_config()
    try:
        # utf-8-sig: aceita o arquivo salvo com BOM por um editor de texto.
        config.read(ARQUIVO_CONFIG, encoding="utf-8-sig")
    except (configparser.Error, OSError, UnicodeDecodeError) as erro:
        logger.warning("Configuração da janela ilegível: %s", erro)
        return None
    return config


# Valor padrão dos carregar_*: ler o .ini agora. abrir_janela lê uma vez e passa o resultado.
_LER_AGORA = object()


def carregar_posicao(monitores: list, config=_LER_AGORA) -> tuple[int, int] | None:
    """Lê a última posição salva, se ela ainda estiver dentro de algum monitor."""
    config = _ler_config() if config is _LER_AGORA else config
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


def posicao_salva() -> tuple[int | None, int | None]:
    """A posição gravada no .ini, sem conferir monitores; (None, None) se não houver."""
    config = _ler_config()
    try:
        if config is not None:
            return config.getint(SECAO_POSICAO, "x"), config.getint(SECAO_POSICAO, "y")
    except (configparser.Error, ValueError):
        pass  # sem posição válida: nenhuma é gravada (a próxima abertura centraliza)
    return None, None


def carregar_modo_compacto(config=_LER_AGORA) -> bool:
    """Lê o modo da janela salvo; sem arquivo ou com valor inválido, o modo completo."""
    config = _ler_config() if config is _LER_AGORA else config
    if config is None:
        return False
    try:
        return config.getboolean(SECAO_JANELA, "compacto", fallback=False)
    except (ValueError, configparser.Error) as erro:
        logger.warning("Modo da janela salvo inválido: %s", erro)
        return False


def carregar_camada(config=_LER_AGORA) -> str:
    """Lê a camada da janela salva ("normal" ou "fundo"); sem arquivo ou inválida, "normal".

    A fixação no topo não é lembrada (como antes): "topo" nunca é gravado.
    """
    config = _ler_config() if config is _LER_AGORA else config
    if config is None:
        return "normal"
    try:
        return camada_salva(config.get(SECAO_JANELA, "camada", fallback=None))
    except configparser.Error as erro:
        logger.warning("Camada da janela salva inválida: %s", erro)
        return "normal"


def salvar_configuracao(x: int | None, y: int | None, compacto: bool, camada: str = "normal") -> None:
    """Grava posição, modo e camada juntos: o arquivo é sempre reescrito por inteiro.

    Sem posição (x/y None: janela minimizada ao fechar), a seção [Position] fica de fora e a
    próxima abertura centraliza, como sem arquivo. Gravação atômica (.tmp + replace): uma
    queda no meio nunca deixa o .ini pela metade.
    """
    config = _novo_config()
    if x is not None and y is not None:
        config[SECAO_POSICAO] = {"x": str(x), "y": str(y)}
    config[SECAO_JANELA] = {
        "compacto": "1" if compacto else "0",
        "camada": camada if camada in CAMADAS_LEMBRADAS else "normal",
    }
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    temporario = ARQUIVO_CONFIG.with_name(ARQUIVO_CONFIG.name + ".tmp")
    with temporario.open("w", encoding="utf-8") as arquivo:
        config.write(arquivo)
    temporario.replace(ARQUIVO_CONFIG)


# ---------------------------------------------------------------------------
# API exposta ao JavaScript
# ---------------------------------------------------------------------------

class ExposedApi:
    """API chamada pelo JavaScript através de window.pywebview.api.

    O pywebview expõe ao JS todo método e todo objeto público desta classe.
    Por isso a janela e o repositório ficam em atributos com "_", que não são expostos.
    """

    def __init__(self, repositorio: RepositorioAlertas, metricas, compacto: bool = False,
                 camada: str = "normal") -> None:
        self._janela: webview.Window | None = None
        self._handle: int | None = None
        self._repositorio = repositorio
        self._metricas = metricas
        self._compacto = compacto
        self._arrastador = Arrastador(self._handle_janela)
        # Camada da janela: "normal", "topo" (topo_janela.py) ou "fundo" (camada_fundo.py).
        # A salva no .ini ("fundo") é aplicada quando a janela aparece (registrar_camada_inicial);
        # até lá, camada_atual já a informa à página.
        self._camada = "normal"
        self._camada_pendente: str | None = camada if camada == "fundo" else None
        self._trava_camada = threading.Lock()
        self._controlador_fundo: ControladorCamada | None = None
        # Na camada fundo: coberta por outras janelas e usuário ausente (ócio do sistema).
        # A página lê por espera longa (aguardar_estado_janela): coberta, desliga o que
        # desliga minimizada; ausente, pausa como na inatividade.
        self._estado_janela = EstadoPublicado()
        # Atalho global (atalho_global.py): ligado no shown (registrar_atalho_global),
        # desligado ao fechar. A página pergunta uma vez se alguma combinação estava em uso.
        self._criar_sistema_atalho = SistemaWin32Atalho if sys.platform == "win32" else None
        self._atalho: OuvinteAtalho | None = None
        self._atalho_tentado = threading.Event()
        self._aviso_atalho_entregue = False
        self._trava_atalho = threading.Lock()

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
        except Exception:  # a página só precisa saber que falhou
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

    def definir_camada(self, camada: str) -> str:
        """Leva a janela à camada pedida e retorna a camada real.

        "normal": janela comum; "topo": fixada acima das outras (topo_janela.py, nunca
        window.on_top); "fundo": atrás das outras e fora da barra de tarefas, sobe ao ser
        clicada e volta ao fundo quando outra janela ganha o foco (camada_fundo.py).
        Sai sempre da camada anterior antes de entrar na nova. Valor desconhecido: nada muda.
        """
        with self._metricas.medir("definir_camada"):
            if camada not in CAMADAS:
                logger.warning("Camada da janela inválida: %r", camada)
                return self._camada
            with self._trava_camada:
                self._camada_pendente = None
                return self._definir_camada(camada)

    def camada_atual(self) -> str:
        """Camada da janela (a salva, enquanto ainda não foi aplicada na abertura)."""
        # Com a trava: a correção de "topo" para "normal" não pode cruzar com uma troca de
        # camada em andamento (definir_camada roda noutra thread da js_api).
        with self._metricas.medir("camada_atual"), self._trava_camada:
            pendente = self._camada_pendente
            if pendente is not None:
                return pendente
            if self._camada == "topo" and not self._esta_no_topo():
                self._camada = "normal"  # alguém tirou a fixação por fora
            return self._camada

    def destacar_alarme(self, ativo: bool) -> bool:
        """Na camada fundo: com alarme na tela, a janela fica acima de todas (sem ativar).

        Fora do fundo não faz nada (na normal e no topo o alarme segue como sempre).
        Retorna se a janela ficou no estado pedido.
        """
        with self._metricas.medir("destacar_alarme"), self._trava_camada:
            if self._camada != "fundo" or self._controlador_fundo is None:
                return False
            return self._controlador_fundo.destacar(bool(ativo))

    def aguardar_estado_janela(self, versao: int) -> dict:
        """Espera longa: volta quando o estado da janela mudar da `versao` dada (ou em ~25 s).

        Retorna {"versao": int, "coberto": bool, "ausente": bool}; os dois só valem na
        camada fundo (fora dela, sempre False). Sem medição (o tempo é a própria espera).
        """
        if not isinstance(versao, int) or isinstance(versao, bool):
            versao = -1  # valor inválido: responde na hora com o estado atual
        return self._estado_janela.aguardar(versao)

    def aviso_do_atalho(self) -> dict | None:
        """Se alguma combinação do atalho global estava em uso por outro programa.

        Retorna {"ativo": "Ctrl+Shift+Alt+B" ou None, "em_uso": ["Ctrl+Alt+B", ...]}, ou
        None quando não há o que avisar. Responde só na 1ª chamada da execução (o ↻ não
        repete o aviso). Espera o registro, feito no evento shown, por até alguns segundos.
        """
        with self._metricas.medir("aviso_do_atalho"):
            self._atalho_tentado.wait(ESPERA_AVISO_ATALHO_S)
            with self._trava_atalho:
                if self._aviso_atalho_entregue:
                    return None
                self._aviso_atalho_entregue = True
            atalho = self._atalho
            if atalho is None or not atalho.recusados:
                return None
            return {
                "ativo": atalho.registrado.nome if atalho.registrado else None,
                "em_uso": [recusado.nome for recusado in atalho.recusados],
            }

    def _ligar_atalho(self) -> None:
        """Registra o atalho global (ver registrar_atalho_global). Só no Windows."""
        try:
            if self._criar_sistema_atalho is None or self._atalho is not None:
                return
            self._atalho = OuvinteAtalho(
                self._criar_sistema_atalho(), self._handle_janela, lambda: self._camada,
            )
            self._atalho.iniciar()
        except Exception:  # o app segue sem atalho
            logger.exception("Falha ao ligar o atalho global")
        finally:
            self._atalho_tentado.set()

    def _desligar_atalho(self) -> None:
        if self._atalho is not None:
            self._atalho.parar()

    def _definir_camada(self, camada: str) -> str:
        if camada == self._camada:
            return self._camada
        if self._camada == "fundo":
            self._controlador().sair_do_fundo()
        elif self._camada == "topo":
            self._definir_topo(False)
        self._camada = "normal"
        if camada == "topo":
            if self._definir_topo(True):
                self._camada = "topo"
        elif camada == "fundo":
            try:
                if self._controlador().entrar_no_fundo():
                    self._camada = "fundo"
            except Exception:  # a janela continua na camada normal
                logger.exception("Falha ao enviar a janela para o fundo")
        return self._camada

    def _controlador(self) -> ControladorCamada:
        """Controlador da camada fundo, criado no 1º uso (só no Windows)."""
        if self._controlador_fundo is None:
            self._controlador_fundo = ControladorCamada(
                SistemaWin32Fundo(), self._handle_janela, publicar=self._estado_janela.publicar,
            )
        return self._controlador_fundo

    def _aplicar_camada_inicial(self) -> None:
        """Aplica a camada salva no .ini (ver registrar_camada_inicial)."""
        with self._trava_camada:
            pendente, self._camada_pendente = self._camada_pendente, None
            if pendente is not None:
                self._definir_camada(pendente)

    def _encerrar_camada(self) -> None:
        """No fechamento: libera a espera longa da página e para a vigia da camada fundo.

        As chamadas da API rodam em threads não-daemon do pywebview: uma espera presa
        seguraria o fim do processo por até 25 s.
        """
        self._estado_janela.encerrar()
        if self._controlador_fundo is not None:
            self._controlador_fundo.encerrar()

    def _camada_para_salvar(self) -> str:
        return self._camada_pendente or self._camada

    def _posicao_para_salvar(self) -> tuple[int | None, int | None]:
        """Posição a gravar ao fechar. Minimizada (fechada pela barra de tarefas), a janela
        está em (-32000, -32000): vale a posição que já estava no .ini (ou nenhuma)."""
        if self._janela is None:
            return None, None
        if sys.platform == "win32":
            handle = self._handle_janela()
            try:
                if handle is not None and topo_janela.esta_minimizada(handle):
                    return posicao_salva()
            except OSError:
                logger.exception("Falha ao conferir se a janela está minimizada")
        return self._janela.x, self._janela.y

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
        except Exception:  # a janela continua utilizável, só um pouco menor
            logger.exception("Falha ao ajustar o tamanho inicial da janela")

    janela.events.shown += ajustar


def registrar_camada_inicial(janela: webview.Window, api: ExposedApi) -> None:
    """Leva a janela à camada salva no .ini ("fundo") assim que ela é exibida (evento shown).

    Antes de a página carregar: a página pergunta a camada (camada_atual) só depois da
    ponte e já recebe a salva, mesmo que o handler ainda não tenha rodado. Handler sem
    parâmetros e sem retorno (ver registrar_ajuste_de_tamanho).
    """

    def aplicar() -> None:
        try:
            api._aplicar_camada_inicial()
        except Exception:  # a janela continua utilizável na camada normal
            logger.exception("Falha ao aplicar a camada inicial da janela")

    janela.events.shown += aplicar


def registrar_atalho_global(janela: webview.Window, api: ExposedApi) -> None:
    """Liga o atalho global quando a janela aparece (o handle dela já existe).

    O registro fica numa thread própria (atalho_global.py); o handler só espera o
    resultado (alguns ms). Handler sem parâmetros e sem retorno.
    """

    def ligar() -> None:
        api._ligar_atalho()  # não levanta: falhas vão ao log

    janela.events.shown += ligar


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
    config = _ler_config()  # uma leitura do .ini para modo, camada e posição
    compacto = carregar_modo_compacto(config)
    classe_api = ExposedApiComMedicao if MEDICAO_ATIVA else ExposedApi
    api = classe_api(RepositorioAlertas(PASTA_DADOS), METRICAS, compacto=compacto, camada=carregar_camada(config))

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
    posicao = carregar_posicao(monitores, config)
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
    registrar_camada_inicial(janela, api)
    registrar_atalho_global(janela, api)
    METRICAS.marcar("janela_criada")
    if MEDICAO_ATIVA:
        registrar_eventos_metricas(janela)

    def ao_fechar() -> None:
        try:
            salvar_configuracao(*api._posicao_para_salvar(), api._modo_compacto(), api._camada_para_salvar())
        except Exception:  # nunca impedir o fechamento da janela
            logger.exception("Falha ao salvar a posição e o modo da janela")
        try:
            api._encerrar_camada()
        except Exception:  # nunca impedir o fechamento da janela
            logger.exception("Falha ao encerrar a camada da janela")
        try:
            api._desligar_atalho()
        except Exception:  # nunca impedir o fechamento da janela
            logger.exception("Falha ao desligar o atalho global")

    janela.events.closing += ao_fechar
    # Antes de o WebView2 ser criado: sem a rede "de fundo" do navegador (ver o módulo).
    if not recurso_desligado_na_medicao(VARIAVEL_SEM_ARGUMENTOS_WEBVIEW2):
        argumentos_webview2.aplicar()
    METRICAS.marcar("webview_start")
    webview.start(user_agent="pywebview", **opcoes_de_armazenamento())


def ja_existe_outra_instancia() -> bool:
    """True se o BTC Status já estava aberto (a janela dele é trazida para a frente).

    Ver instancia_unica.py. Só no Windows; qualquer falha ao conferir deixa o app abrir.
    """
    if sys.platform != "win32":
        return False
    try:
        sistema = instancia_unica.SistemaWin32Instancia()
    except Exception:  # nunca impedir o app de abrir
        logger.exception("Instância única: não foi possível conferir")
        return False
    return not instancia_unica.garantir(sistema, WINDOW_TITLE)


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
    # Depois do log (a decisão vai para ele). A busca do 1º preço já começou: numa 2ª
    # instância ela se perde, sem efeito.
    if ja_existe_outra_instancia():
        return
    try:
        abrir_janela()
    except Exception:
        logger.exception("Erro fatal ao abrir a janela")
        raise


if __name__ == "__main__":
    main()
