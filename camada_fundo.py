"""Camada "fundo" da janela: atrás das outras janelas e fora da barra de tarefas.

A janela continua com o mesmo layout (completo ou compacto); muda só a posição
na pilha do Windows:

- ao entrar no fundo, sai da barra de tarefas e do Alt+Tab (`WS_EX_TOOLWINDOW`,
  sem `WS_EX_APPWINDOW`), não some no Aero Peek (`DWMWA_EXCLUDED_FROM_PEEK`) e
  vai para trás de todas as janelas (`HWND_BOTTOM`), sem ser ativada;
- clicada, o Windows a traz para a frente normalmente (teclado funciona);
- quando outra janela ganha o foco, volta ao fundo;
- com um alarme na tela, a página pede o destaque (`destacar`): a janela fica acima
  de todas, sem ser ativada, até o alarme sair da tela ou receber o OK.

O "Mostrar área de trabalho" (Win+D) esconde a janela, como esconde as outras: no
Windows 11 26H2 a fixação no topo pedida durante ele não tem efeito (armadilha).
Durante o Win+D a janela conta como coberta (a área de trabalho fica acima dela).

Cobertura: no fundo, a janela passa a maior parte do tempo coberta. A vigia calcula se
sobra alguma parte dela à vista (as janelas opacas acima, subtraídas do retângulo dela,
como o Chromium e o Rainmeter) e publica o estado (`EstadoPublicado`); a página o
recebe por espera longa (`aguardar`) e, coberta, liga só o que liga com a janela
minimizada. Recalcula quando a pilha muda (arrastar, minimizar, cloak, troca de
primeiro plano) e, de reserva, a cada `TIQUES_POR_CONFERENCIA` tiques. Sem ganchos de
mostrar/ocultar/destruir objeto: chegam aos milhares (de todos os programas) e cada
um passaria pelo Python.

Ausência: no fundo quase ninguém mexe na janela, então a pausa por inatividade da
página usa o ócio do sistema (`GetLastInputInfo`): a vigia publica `ausente` quando
não há tecla nem movimento do mouse em lugar nenhum há `LIMITE_AUSENCIA_MS`, e volta
a `False` com a 1ª tecla ou movimento.

O tique é cronometrado pelo próprio laço (espera com prazo), não por WM_TIMER: o
WM_TIMER só sai da fila quando ela está vazia e, com muitos eventos chegando, pode
nunca sair.

Organização (mesmo padrão do `bordas_janela.py`):

- lógica pura: `estilo_para_fundo`, `camada_salva`, `deve_afundar`, `subtrair`,
  `area_visivel`, `esta_coberta`, `usuario_ausente`;
- `EstadoPublicado`: cobertura e ausência, com versão e espera longa;
- `ControladorCamada`: as transições, com o sistema injetado por parâmetro;
- `VigiaPrimeiroPlano`: thread própria com laço de mensagens. O gancho
  `WINEVENT_OUTOFCONTEXT` é entregue na thread que o instalou, então o Python
  do gancho roda nela, nunca na thread da interface (armadilha 1). Nada de
  subclasse da janela em Python;
- `SistemaWin32Fundo`: chamadas ao Windows por ctypes, com `argtypes`/`restype`
  declarados (armadilha 15) e um `WinDLL` próprio.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)

# Camadas aceitas pela API. "topo" continua sendo feito pelo topo_janela.py.
CAMADAS: tuple[str, ...] = ("normal", "topo", "fundo")
# Só "fundo" é lembrada entre execuções (a fixação no topo não é, como hoje).
CAMADAS_LEMBRADAS: tuple[str, ...] = ("normal", "fundo")

WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

ESPERA_ENCERRAR_VIGIA_S = 2.0
# Tique da vigia: cobertura e ausência.
INTERVALO_VIGIA_MS = 250
# Cobertura recalculada sem evento a cada 4 tiques (1 s): janelas abertas, fechadas ou
# movidas por programas (sem gancho barato para isso).
TIQUES_POR_CONFERENCIA = 4
# Diagnóstico (BTC_DEPURAR_FUNDO=1): uma linha de "vida" no log a cada tantos tiques (~10 s).
TIQUES_POR_LINHA_DE_VIDA = 40
# Abaixo desta fração da área à vista, a janela conta como coberta (uma fresta não mostra nada).
FRACAO_MINIMA_VISIVEL = 0.01
# Espera longa da página: devolve o estado atual depois deste prazo, mesmo sem mudança.
PRAZO_AGUARDAR_ESTADO_S = 25.0
# Ausência: o mesmo prazo da pausa por inatividade da página (LIMITE_INATIVIDADE no script.js).
LIMITE_AUSENCIA_MS = 1000 * 1000
# Volta da ausência: houve tecla ou movimento há menos que isto.
VOLTA_DA_AUSENCIA_MS = 1000

# Retângulo em pixels: (esquerda, topo, direita, base), direita/base exclusivas.
Retangulo = tuple[int, int, int, int]


# ---------------------------------------------------------------------------
# Lógica pura
# ---------------------------------------------------------------------------

def estilo_para_fundo(estilo: int) -> int:
    """Estilo estendido da janela no fundo: janela de ferramenta, sem `APPWINDOW`.

    Com `WS_EX_APPWINDOW` (o WinForms o põe quando `ShowInTaskbar` é verdadeiro)
    o botão continuaria na barra mesmo com `WS_EX_TOOLWINDOW`.
    """
    return (estilo | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW


def camada_salva(valor: str | None) -> str:
    """Camada lida do `.ini`: "fundo" ou, para qualquer outra coisa, "normal"."""
    if valor is not None and valor.strip().lower() == "fundo":
        return "fundo"
    return "normal"


def deve_afundar(camada: str, primeiro_plano: int | None, propria: int | None) -> bool:
    """Se a janela deve voltar ao fundo depois de uma troca de primeiro plano.

    `primeiro_plano` e `propria` são as janelas raiz (`GA_ROOT`). Sem janela em
    primeiro plano (transições do Windows) ou sem a própria janela, nada muda.
    """
    if camada != "fundo" or not primeiro_plano or not propria:
        return False
    return primeiro_plano != propria


def usuario_ausente(ocioso_ms: int, ja_ausente: bool, limite_ms: int = LIMITE_AUSENCIA_MS) -> bool:
    """Ausente depois de `limite_ms` sem tecla nem mouse; volta na 1ª tecla ou movimento.

    Com histerese: já ausente, só volta com atividade recente (`VOLTA_DA_AUSENCIA_MS`),
    para o tique (a cada 250 ms) não oscilar perto do limite.
    """
    if ja_ausente:
        return ocioso_ms >= VOLTA_DA_AUSENCIA_MS
    return ocioso_ms >= limite_ms


def subtrair(alvo: Retangulo, corte: Retangulo) -> list[Retangulo]:
    """Partes de `alvo` fora de `corte` (até 4 retângulos, sem sobreposição)."""
    e, t, d, b = alvo
    ce, ct, cd, cb = corte
    if ce >= d or cd <= e or ct >= b or cb <= t:
        return [alvo]  # sem interseção
    partes: list[Retangulo] = []
    if ct > t:
        partes.append((e, t, d, ct))          # faixa de cima
    if cb < b:
        partes.append((e, cb, d, b))          # faixa de baixo
    meio_t, meio_b = max(t, ct), min(b, cb)
    if ce > e:
        partes.append((e, meio_t, ce, meio_b))  # esquerda, na altura do corte
    if cd < d:
        partes.append((cd, meio_t, d, meio_b))  # direita, na altura do corte
    return partes


def area_visivel(alvo: Retangulo, cobertores: list[Retangulo]) -> int:
    """Área de `alvo` que nenhum dos `cobertores` tapa."""
    sobra = [alvo] if alvo[0] < alvo[2] and alvo[1] < alvo[3] else []
    for corte in cobertores:
        if not sobra:
            break
        sobra = [parte for pedaco in sobra for parte in subtrair(pedaco, corte)]
    return sum((d - e) * (b - t) for e, t, d, b in sobra)


def esta_coberta(
    alvo: Retangulo | None,
    cobertores: list[Retangulo],
    fracao_minima: float = FRACAO_MINIMA_VISIVEL,
) -> bool:
    """Coberta: sem retângulo (oculta, minimizada, em outra área virtual) ou quase nada à vista."""
    if alvo is None:
        return True
    area = (alvo[2] - alvo[0]) * (alvo[3] - alvo[1])
    if area <= 0:
        return True
    return area_visivel(alvo, cobertores) < area * fracao_minima


class EstadoPublicado:
    """Estado da janela no fundo (coberta, usuário ausente), lido pela página por espera longa.

    `aguardar(versao)` volta assim que a versão for diferente da que a página já tem
    (ou no prazo). `encerrar` libera quem espera: o pywebview roda cada chamada da API
    numa thread NÃO-daemon, e uma espera presa seguraria o fechamento do app.
    """

    def __init__(self) -> None:
        self._condicao = threading.Condition()
        self._versao = 0
        self._estado = {"coberto": False, "ausente": False}
        self._encerrado = False

    def publicar(self, coberto: bool | None = None, ausente: bool | None = None) -> None:
        """Muda os campos dados (None: mantém). A versão só sobe se algo mudou."""
        with self._condicao:
            novo = dict(self._estado)
            if coberto is not None:
                novo["coberto"] = coberto
            if ausente is not None:
                novo["ausente"] = ausente
            if novo == self._estado:
                return
            self._estado = novo
            self._versao += 1
            self._condicao.notify_all()

    def encerrar(self) -> None:
        with self._condicao:
            self._encerrado = True
            self._condicao.notify_all()

    def atual(self) -> dict:
        with self._condicao:
            return {"versao": self._versao, **self._estado}

    def aguardar(self, versao: int, prazo_s: float = PRAZO_AGUARDAR_ESTADO_S) -> dict:
        with self._condicao:
            self._condicao.wait_for(lambda: self._versao != versao or self._encerrado, timeout=prazo_s)
            return {"versao": self._versao, **self._estado}


# ---------------------------------------------------------------------------
# Sistema (Windows) — interface usada pelo controlador e pela vigia
# ---------------------------------------------------------------------------

class SistemaFundo(Protocol):
    """Chamadas ao sistema usadas pela camada fundo (`SistemaWin32Fundo` no app)."""

    def ler_estilo(self, hwnd: int) -> int: ...
    def gravar_estilo(self, hwnd: int, estilo: int) -> None: ...
    def atualizar_moldura(self, hwnd: int) -> None: ...
    def ocultar(self, hwnd: int) -> None: ...
    def mostrar_sem_ativar(self, hwnd: int) -> None: ...
    def excluir_do_peek(self, hwnd: int, excluir: bool) -> None: ...
    def enviar_para_fundo(self, hwnd: int) -> None: ...
    def trazer_para_frente_sem_ativar(self, hwnd: int) -> None: ...
    def fixar_temporariamente(self, hwnd: int) -> None: ...
    def tirar_do_topo(self, hwnd: int) -> None: ...
    def janela_em_primeiro_plano(self) -> int | None: ...
    def raiz(self, hwnd: int | None) -> int | None: ...
    # Cobertura: retângulo da janela (None se oculta/minimizada/cloaked) e os opacos acima dela
    def estado_de_cobertura(self, hwnd: int) -> tuple[Retangulo | None, list[Retangulo]]: ...
    # Ausência: ms desde a última tecla ou movimento do mouse na sessão
    def ocioso_ms(self) -> int: ...
    # Vigia (laço de mensagens numa thread própria; tudo nela)
    def preparar_fila(self) -> int: ...
    def instalar_gancho_primeiro_plano(self, ao_mudar: Callable[[int | None], None]) -> object: ...
    def instalar_ganchos_de_pilha(self, ao_mudar: Callable[[], None]) -> list: ...
    def remover_gancho(self, gancho: object) -> None: ...
    def iniciar_tique(self, intervalo_ms: int) -> int: ...
    def parar_tique(self, id_tique: int) -> None: ...
    def rodar_laco(self, ao_tique: Callable[[], None]) -> None: ...
    def encerrar_laco(self, id_thread: int) -> None: ...


# ---------------------------------------------------------------------------
# Vigia do primeiro plano
# ---------------------------------------------------------------------------

class VigiaPrimeiroPlano:
    """Thread com laço de mensagens que avisa cada troca de janela em primeiro plano.

    Só existe enquanto a janela está no fundo. `iniciar` volta depois de o gancho
    estar instalado; `parar` encerra o laço e espera a thread (com prazo).
    Com `ao_tique`, a thread também o chama a cada `intervalo_ms`; com `ao_mudar_pilha`,
    avisa quando a pilha muda. Sem um ou outro (falha ao instalar), segue só com o
    gancho. Os avisos nunca levantam exceção (o `.exe` não tem console): erros vão ao log.
    """

    def __init__(
        self,
        sistema: SistemaFundo,
        ao_mudar: Callable[[int | None], None],
        ao_tique: Callable[[], None] | None = None,
        intervalo_ms: int = INTERVALO_VIGIA_MS,
        ao_mudar_pilha: Callable[[], None] | None = None,
    ) -> None:
        self._sistema = sistema
        self._ao_mudar = ao_mudar
        self._ao_tique = ao_tique
        self._ao_mudar_pilha = ao_mudar_pilha
        self._intervalo_ms = intervalo_ms
        self._thread: threading.Thread | None = None
        self._id_thread: int | None = None
        self._pronta = threading.Event()
        self._erro: BaseException | None = None

    @property
    def ativa(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def iniciar(self) -> bool:
        """Inicia a thread (se ainda não houver). `False` se o gancho falhou."""
        if self.ativa:
            return True
        self._pronta.clear()
        self._erro = None
        self._id_thread = None
        self._thread = threading.Thread(target=self._rodar, name="vigia-fundo", daemon=True)
        self._thread.start()
        self._pronta.wait(ESPERA_ENCERRAR_VIGIA_S)
        if self._erro is not None or self._id_thread is None:
            logger.error("Camada fundo: vigia não iniciou: %s", self._erro)
            return False
        return True

    def parar(self) -> None:
        """Encerra o laço e espera a thread terminar."""
        thread, id_thread = self._thread, self._id_thread
        if thread is None:
            return
        if id_thread is not None and thread.is_alive():
            try:
                self._sistema.encerrar_laco(id_thread)
            except Exception:
                logger.exception("Camada fundo: falha ao encerrar a vigia")
        thread.join(ESPERA_ENCERRAR_VIGIA_S)
        if thread.is_alive():
            logger.error("Camada fundo: vigia não terminou no prazo")
        self._thread = None
        self._id_thread = None

    def _avisar(self, hwnd: int | None) -> None:
        try:
            self._ao_mudar(hwnd)
        except Exception:
            logger.exception("Camada fundo: falha ao tratar a troca de primeiro plano")

    def _avisar_pilha(self) -> None:
        try:
            self._ao_mudar_pilha()  # type: ignore[misc]
        except Exception:
            logger.exception("Camada fundo: falha ao tratar a mudança na pilha de janelas")

    def _tique(self) -> None:
        if self._ao_tique is None:
            return
        try:
            self._ao_tique()
        except Exception:
            logger.exception("Camada fundo: falha no tique da vigia")

    def _preparar_tique(self) -> int | None:
        try:
            return self._sistema.iniciar_tique(self._intervalo_ms)
        except Exception:
            logger.exception("Camada fundo: sem tique, a cobertura e a ausência não serão conferidas")
            return None

    def _rodar(self) -> None:
        gancho = None
        try:
            # A fila precisa existir antes de `encerrar_laco` poder postar nela.
            self._id_thread = self._sistema.preparar_fila()
            gancho = self._sistema.instalar_gancho_primeiro_plano(self._avisar)
        except BaseException as erro:  # noqa: BLE001 — repassado a `iniciar`
            self._erro = erro
            self._id_thread = None
            self._pronta.set()
            return
        ganchos_pilha: list = []
        if self._ao_mudar_pilha is not None:
            try:
                ganchos_pilha = self._sistema.instalar_ganchos_de_pilha(self._avisar_pilha)
            except Exception:
                logger.exception("Camada fundo: sem ganchos de pilha, a cobertura só é conferida pelo tique")
        tique = self._preparar_tique() if self._ao_tique is not None else None
        self._pronta.set()
        try:
            self._sistema.rodar_laco(self._tique)
        except Exception:
            logger.exception("Camada fundo: falha no laço da vigia")
        finally:
            if tique is not None:
                try:
                    self._sistema.parar_tique(tique)
                except Exception:
                    logger.exception("Camada fundo: falha ao parar o tique")
            for item in (*ganchos_pilha, gancho):
                try:
                    self._sistema.remover_gancho(item)
                except Exception:
                    logger.exception("Camada fundo: falha ao remover o gancho")


# ---------------------------------------------------------------------------
# Controlador
# ---------------------------------------------------------------------------

class ControladorCamada:
    """Entra e sai da camada fundo e a mantém atrás das outras janelas.

    `obter_janela` devolve o handle da janela do app (título + PID, armadilha 2)
    ou `None`. As transições usam uma trava; os avisos da vigia usam
    `acquire(blocking=False)`: durante uma transição são ignorados (a própria
    transição confere o primeiro plano no fim) e `parar` nunca espera um aviso
    parado na trava.
    """

    def __init__(
        self,
        sistema: SistemaFundo,
        obter_janela: Callable[[], int | None],
        criar_vigia: Callable[..., VigiaPrimeiroPlano] | None = None,
        publicar: Callable[..., None] | None = None,
    ) -> None:
        self._sistema = sistema
        self._obter_janela = obter_janela
        self._trava = threading.Lock()
        self._no_fundo = False
        self._estilo_original: int | None = None
        self._hwnd: int | None = None
        # Acima de todas enquanto há alarme na tela (pedido pela página).
        self._destaque = False
        # Estado publicado para a página: publicar(coberto=..., ausente=...).
        self._publicar = publicar or (lambda **_campos: None)
        # Cobertura recalculada quando a pilha muda ou a cada TIQUES_POR_CONFERENCIA
        # tiques. A marca é só uma atribuição (sem trava).
        self._pilha_mudou = True
        self._tiques = 0
        self._ausente = False
        self._ocioso_falhou = False  # para avisar no log uma vez só
        fabrica = criar_vigia or VigiaPrimeiroPlano
        self._vigia = fabrica(
            sistema, self.ao_mudar_primeiro_plano, self.ao_tique, INTERVALO_VIGIA_MS, self.ao_mudar_pilha,
        )

    @property
    def no_fundo(self) -> bool:
        return self._no_fundo

    @property
    def em_destaque(self) -> bool:
        return self._destaque

    def entrar_no_fundo(self) -> bool:
        """Leva a janela para a camada fundo. Devolve se ela está no fundo."""
        with self._trava:
            if self._no_fundo:
                return True
            hwnd = self._obter_janela()
            if not hwnd:
                logger.error("Camada fundo: janela não encontrada")
                return False
            sistema = self._sistema
            try:
                original = sistema.ler_estilo(hwnd)
            except Exception:
                logger.exception("Camada fundo: falha ao ler o estilo da janela")
                return False
            alterou = False
            try:
                # Estilo trocado com a janela oculta: só assim a barra de tarefas
                # tira o botão. Nunca `Form.ShowInTaskbar` (recria o handle).
                sistema.ocultar(hwnd)
                sistema.gravar_estilo(hwnd, estilo_para_fundo(original))
                alterou = True
                sistema.atualizar_moldura(hwnd)
                sistema.excluir_do_peek(hwnd, True)
            except Exception:
                logger.exception("Camada fundo: falha ao entrar no fundo")
                if alterou:
                    self._restaurar_estilo(hwnd, original)
                sistema.mostrar_sem_ativar(hwnd)
                return False
            sistema.mostrar_sem_ativar(hwnd)

            self._hwnd = hwnd
            self._estilo_original = original
            self._no_fundo = True
            self._destaque = False
            self._pilha_mudou = True
            self._ausente = False
            if not self._vigia.iniciar():
                logger.warning("Camada fundo: sem vigia, a janela não volta sozinha ao fundo")
            self._afundar_se_preciso()
            return True

    def sair_do_fundo(self) -> bool:
        """Devolve a janela à camada normal. Devolve se ela saiu (ou já estava fora)."""
        with self._trava:
            if not self._no_fundo:
                return True
            self._vigia.parar()
            hwnd = self._hwnd
            original = self._estilo_original
            destaque = self._destaque
            self._no_fundo = False
            self._destaque = False
            self._hwnd = None
            self._estilo_original = None
            self._ausente = False
            # Fora do fundo, a página volta a decidir pela visibilidade e pela própria janela.
            self._publicar(coberto=False, ausente=False)
            if not hwnd or original is None:
                return True
            sistema = self._sistema
            if destaque:
                try:
                    sistema.tirar_do_topo(hwnd)
                except Exception:
                    logger.exception("Camada fundo: falha ao tirar a janela do topo")
            try:
                sistema.ocultar(hwnd)
            except Exception:
                logger.exception("Camada fundo: falha ao ocultar a janela para sair do fundo")
            self._restaurar_estilo(hwnd, original)
            try:
                sistema.mostrar_sem_ativar(hwnd)
            except Exception:
                logger.exception("Camada fundo: falha ao mostrar a janela ao sair do fundo")
            try:
                sistema.trazer_para_frente_sem_ativar(hwnd)
            except Exception:
                logger.exception("Camada fundo: falha ao trazer a janela para a frente")
            return True

    def destacar(self, ativo: bool) -> bool:
        """Com alarme na tela: acima de todas, sem ativar. Sem alarme: de volta ao fundo.

        Ao sair do destaque com a própria janela em uso (primeiro plano), ela só deixa
        de ser TOPMOST e fica na frente; afunda quando outra janela ganhar o foco.
        Devolve se a janela ficou no estado pedido.
        """
        with self._trava:
            if not self._no_fundo or not self._hwnd:
                return False
            if ativo == self._destaque:
                return True
            sistema, propria = self._sistema, self._hwnd
            try:
                if ativo:
                    sistema.fixar_temporariamente(propria)
                elif sistema.raiz(sistema.janela_em_primeiro_plano()) == propria:
                    sistema.tirar_do_topo(propria)
                else:
                    sistema.enviar_para_fundo(propria)  # também tira o TOPMOST
            except Exception:
                logger.exception("Camada fundo: falha ao %s o destaque do alarme", "aplicar" if ativo else "tirar")
                return False
            self._destaque = ativo
            self._pilha_mudou = True
            logger.debug("Camada fundo: destaque do alarme %s", "ligado" if ativo else "desligado")
            return True

    def encerrar(self) -> None:
        """No fechamento: para a vigia sem mexer na janela."""
        with self._trava:
            self._vigia.parar()

    def ao_mudar_pilha(self) -> None:
        """Aviso da vigia: alguma janela foi arrastada, minimizada ou cloaked."""
        self._pilha_mudou = True

    def ao_mudar_primeiro_plano(self, hwnd: int | None) -> None:
        """Aviso da vigia (thread `vigia-fundo`): outra janela no primeiro plano → fundo.

        Com o destaque do alarme, a janela fica acima de todas até a página tirá-lo.
        """
        if not self._trava.acquire(blocking=False):
            return
        try:
            if not self._no_fundo or not self._hwnd:
                return
            self._pilha_mudou = True
            primeiro = self._sistema.raiz(hwnd)
            if not self._destaque and deve_afundar("fundo", primeiro, self._hwnd):
                logger.debug("Camada fundo: primeiro plano em %s, janela volta ao fundo", primeiro)
                self._sistema.enviar_para_fundo(self._hwnd)
        finally:
            self._trava.release()

    def ao_tique(self) -> None:
        """Tique da vigia (thread `vigia-fundo`): cobertura e ausência do usuário."""
        if not self._trava.acquire(blocking=False):
            return
        try:
            if not self._no_fundo or not self._hwnd:
                return
            self._tiques += 1
            if self._pilha_mudou or self._tiques % TIQUES_POR_CONFERENCIA == 0:
                self._pilha_mudou = False
                self._atualizar_cobertura()
            self._atualizar_ausencia()
            if self._tiques % TIQUES_POR_LINHA_DE_VIDA == 0 and logger.isEnabledFor(logging.DEBUG):
                logger.debug("Camada fundo: tique %d, destaque=%s, ausente=%s",
                             self._tiques, self._destaque, self._ausente)
        finally:
            self._trava.release()

    # -- internos (chamados com a trava) -----------------------------------

    def _atualizar_cobertura(self) -> None:
        try:
            proprio, cobertores = self._sistema.estado_de_cobertura(self._hwnd)  # type: ignore[arg-type]
            coberta = esta_coberta(proprio, cobertores)
        except Exception:
            logger.exception("Camada fundo: falha ao calcular a cobertura da janela")
            coberta = False  # na dúvida, a página segue como visível
        self._publicar(coberto=coberta)

    def _atualizar_ausencia(self) -> None:
        try:
            ocioso = self._sistema.ocioso_ms()
        except Exception:
            if not self._ocioso_falhou:
                self._ocioso_falhou = True
                logger.exception("Camada fundo: falha ao ler o tempo sem uso do sistema")
            return
        ausente = usuario_ausente(ocioso, self._ausente)
        if ausente != self._ausente:
            self._ausente = ausente
            logger.debug("Camada fundo: usuário %s", "ausente" if ausente else "de volta")
            self._publicar(ausente=ausente)

    def _restaurar_estilo(self, hwnd: int, original: int) -> None:
        sistema = self._sistema
        try:
            sistema.gravar_estilo(hwnd, original)
            sistema.atualizar_moldura(hwnd)
        except Exception:
            logger.exception("Camada fundo: falha ao restaurar o estilo da janela")
        try:
            sistema.excluir_do_peek(hwnd, False)
        except Exception:
            logger.exception("Camada fundo: falha ao devolver a janela ao Aero Peek")

    def _afundar_se_preciso(self) -> None:
        try:
            primeiro = self._sistema.raiz(self._sistema.janela_em_primeiro_plano())
            # Sem primeiro plano conhecido (ex.: a ativação saiu da janela oculta e
            # ainda não chegou a outra), afunda assim mesmo: acabamos de pedir o fundo.
            if primeiro is None or deve_afundar("fundo", primeiro, self._hwnd):
                self._sistema.enviar_para_fundo(self._hwnd)  # type: ignore[arg-type]
        except Exception:
            logger.exception("Camada fundo: falha ao enviar a janela para o fundo")


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

class SistemaWin32Fundo:
    """Implementação por ctypes. Criada só no Windows (no 1º uso da camada fundo)."""

    GWL_EXSTYLE = -20
    SW_HIDE = 0
    SW_SHOWNA = 8
    HWND_TOP = 0
    HWND_BOTTOM = 1
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    GW_HWNDPREV = 3
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_LAYERED = 0x00080000
    LWA_COLORKEY = 0x1
    LWA_ALPHA = 0x2
    COMPLEXREGION = 3
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    DWMWA_CLOAKED = 14
    OBJID_WINDOW = 0
    # Eventos que mudam o que cobre a janela (EVENT_OBJECT_LOCATIONCHANGE fica de fora:
    # dispara a cada movimento do cursor, no sistema todo).
    FAIXAS_EVENTOS_PILHA = (
        (0x000A, 0x000B),  # EVENT_SYSTEM_MOVESIZESTART/END
        (0x0016, 0x0017),  # EVENT_SYSTEM_MINIMIZESTART/END
        (0x8017, 0x8018),  # EVENT_OBJECT_CLOAKED/UNCLOAKED
    )
    CLASSES_BARRA = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd")
    # A área de trabalho acima da janela (Win+D) sempre a cobre: o Progman do 26H2 não
    # passa pelos critérios de opacidade e a janela contaria como à vista.
    CLASSES_AREA_DE_TRABALHO = ("Progman", "WorkerW")
    # Laço da vigia
    QS_ALLINPUT = 0x04FF
    MWMO_INPUTAVAILABLE = 0x0004
    WAIT_FAILED = 0xFFFFFFFF
    PM_REMOVE = 0x0001
    MENSAGENS_POR_VOLTA = 256  # depois de tantas, confere o tique mesmo com a fila cheia
    # Espera máxima de uma volta, mesmo sem tique: os ganchos fora de contexto só são
    # entregues dentro do PeekMessage, e o laço nunca deve depender só de ser acordado.
    ESPERA_MAXIMA_MS = 250
    LIMITE_PILHA = 10_000  # proteção contra laço na caminhada pela pilha
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020
    SWP_NOOWNERZORDER = 0x0200
    GA_ROOT = 2
    EVENT_SYSTEM_FOREGROUND = 0x0003
    WINEVENT_OUTOFCONTEXT = 0x0000
    WM_QUIT = 0x0012
    PM_NOREMOVE = 0x0000
    DWMWA_EXCLUDED_FROM_PEEK = 12

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        LONG_PTR = ctypes.c_ssize_t

        self.WINEVENTPROC = ctypes.WINFUNCTYPE(
            None,
            wintypes.HANDLE,  # hWinEventHook
            wintypes.DWORD,   # event
            wintypes.HWND,    # hwnd
            wintypes.LONG,    # idObject
            wintypes.LONG,    # idChild
            wintypes.DWORD,   # idEventThread
            wintypes.DWORD,   # dwmsEventTime
        )

        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        d = ctypes.WinDLL("dwmapi")

        u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowLongPtrW.restype = LONG_PTR
        u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
        u.SetWindowLongPtrW.restype = LONG_PTR
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.ShowWindow.restype = wintypes.BOOL
        u.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.UINT,
        ]
        u.SetWindowPos.restype = wintypes.BOOL
        u.GetForegroundWindow.argtypes = []
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetAncestor.restype = wintypes.HWND
        u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetWindow.restype = wintypes.HWND
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindowVisible.restype = wintypes.BOOL
        u.IsIconic.argtypes = [wintypes.HWND]
        u.IsIconic.restype = wintypes.BOOL
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetWindowRect.restype = wintypes.BOOL
        u.GetLayeredWindowAttributes.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.COLORREF), ctypes.POINTER(wintypes.BYTE),
            ctypes.POINTER(wintypes.DWORD),
        ]
        u.GetLayeredWindowAttributes.restype = wintypes.BOOL
        u.GetWindowRgnBox.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetWindowRgnBox.restype = ctypes.c_int
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetClassNameW.restype = ctypes.c_int

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        self.LASTINPUTINFO = LASTINPUTINFO
        u.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
        u.GetLastInputInfo.restype = wintypes.BOOL
        k.GetTickCount.argtypes = []
        k.GetTickCount.restype = wintypes.DWORD
        u.MsgWaitForMultipleObjectsEx.argtypes = [
            wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        ]
        u.MsgWaitForMultipleObjectsEx.restype = wintypes.DWORD
        u.SetWinEventHook.argtypes = [
            wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, self.WINEVENTPROC,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        ]
        u.SetWinEventHook.restype = wintypes.HANDLE
        u.UnhookWinEvent.argtypes = [wintypes.HANDLE]
        u.UnhookWinEvent.restype = wintypes.BOOL
        u.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT,
        ]
        u.PeekMessageW.restype = wintypes.BOOL
        # GetMessageW devolve -1 em erro: restype inteiro, não BOOL.
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        u.GetMessageW.restype = ctypes.c_int
        u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.TranslateMessage.restype = wintypes.BOOL
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.DispatchMessageW.restype = LONG_PTR
        u.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.PostThreadMessageW.restype = wintypes.BOOL
        k.GetCurrentThreadId.argtypes = []
        k.GetCurrentThreadId.restype = wintypes.DWORD
        d.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        d.DwmSetWindowAttribute.restype = ctypes.c_long  # HRESULT
        d.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        d.DwmGetWindowAttribute.restype = ctypes.c_long  # HRESULT

        self._u, self._k, self._d = u, k, d
        # Referência a cada callback de gancho (por gancho): sem ela o ctypes o libera e
        # o Windows chamaria memória solta.
        self._callbacks: dict[int, object] = {}
        self._intervalo_tique_s: float | None = None  # definido por iniciar_tique

    def _erro(self, funcao: str) -> OSError:
        codigo = self._ctypes.get_last_error()
        return OSError(codigo, f"{funcao} falhou (erro {codigo})")

    def _hwnd(self, valor: int):
        return self._wintypes.HWND(valor)

    def ler_estilo(self, hwnd: int) -> int:
        self._ctypes.set_last_error(0)
        estilo = self._u.GetWindowLongPtrW(self._hwnd(hwnd), self.GWL_EXSTYLE)
        if estilo == 0 and self._ctypes.get_last_error():
            raise self._erro("GetWindowLongPtrW")
        return int(estilo)

    def gravar_estilo(self, hwnd: int, estilo: int) -> None:
        # Retorno 0 é ambíguo (estilo anterior zero): confere o último erro.
        self._ctypes.set_last_error(0)
        anterior = self._u.SetWindowLongPtrW(self._hwnd(hwnd), self.GWL_EXSTYLE, estilo)
        if anterior == 0 and self._ctypes.get_last_error():
            raise self._erro("SetWindowLongPtrW")

    def _posicionar(self, hwnd: int, depois_de: int, flags: int, funcao: str) -> None:
        if not self._u.SetWindowPos(self._hwnd(hwnd), self._hwnd(depois_de), 0, 0, 0, 0, flags):
            raise self._erro(funcao)

    def atualizar_moldura(self, hwnd: int) -> None:
        flags = (self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOZORDER
                 | self.SWP_NOACTIVATE | self.SWP_FRAMECHANGED)
        self._posicionar(hwnd, 0, flags, "SetWindowPos(FRAMECHANGED)")

    def ocultar(self, hwnd: int) -> None:
        # O retorno diz se estava visível, não se deu certo.
        self._u.ShowWindow(self._hwnd(hwnd), self.SW_HIDE)

    def mostrar_sem_ativar(self, hwnd: int) -> None:
        self._u.ShowWindow(self._hwnd(hwnd), self.SW_SHOWNA)

    def excluir_do_peek(self, hwnd: int, excluir: bool) -> None:
        valor = self._wintypes.BOOL(1 if excluir else 0)
        resultado = self._d.DwmSetWindowAttribute(
            self._hwnd(hwnd), self.DWMWA_EXCLUDED_FROM_PEEK,
            self._ctypes.byref(valor), self._ctypes.sizeof(valor),
        )
        if resultado != 0:
            raise OSError(resultado, f"DwmSetWindowAttribute falhou (HRESULT {resultado & 0xFFFFFFFF:#010x})")

    def enviar_para_fundo(self, hwnd: int) -> None:
        flags = self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE | self.SWP_NOOWNERZORDER
        self._posicionar(hwnd, self.HWND_BOTTOM, flags, "SetWindowPos(HWND_BOTTOM)")

    def trazer_para_frente_sem_ativar(self, hwnd: int) -> None:
        flags = self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE
        self._posicionar(hwnd, self.HWND_TOP, flags, "SetWindowPos(HWND_TOP)")

    def fixar_temporariamente(self, hwnd: int) -> None:
        flags = self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE
        self._posicionar(hwnd, self.HWND_TOPMOST, flags, "SetWindowPos(HWND_TOPMOST)")

    def tirar_do_topo(self, hwnd: int) -> None:
        flags = self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE
        self._posicionar(hwnd, self.HWND_NOTOPMOST, flags, "SetWindowPos(HWND_NOTOPMOST)")

    # -- usuário ---------------------------------------------------------------

    def ocioso_ms(self) -> int:
        """Tempo desde a última tecla ou movimento do mouse em qualquer janela da sessão."""
        info = self.LASTINPUTINFO(cbSize=self._ctypes.sizeof(self.LASTINPUTINFO))
        if not self._u.GetLastInputInfo(self._ctypes.byref(info)):
            raise self._erro("GetLastInputInfo")
        # Contadores de 32 bits em ms (voltam a zero a cada ~49,7 dias): diferença módulo 2^32.
        return (int(self._k.GetTickCount()) - int(info.dwTime)) & 0xFFFFFFFF

    # -- cobertura -----------------------------------------------------------

    def _cloaked(self, hwnd: int) -> bool:
        valor = self._wintypes.DWORD()
        resultado = self._d.DwmGetWindowAttribute(
            self._hwnd(hwnd), self.DWMWA_CLOAKED, self._ctypes.byref(valor), self._ctypes.sizeof(valor),
        )
        return resultado == 0 and valor.value != 0

    def _limites(self, hwnd: int) -> Retangulo | None:
        """Retângulo visível (sem a borda invisível de redimensionar do Windows 10/11)."""
        rect = self._wintypes.RECT()
        ref = self._ctypes.byref(rect)
        if self._d.DwmGetWindowAttribute(
            self._hwnd(hwnd), self.DWMWA_EXTENDED_FRAME_BOUNDS, ref, self._ctypes.sizeof(rect),
        ) != 0 and not self._u.GetWindowRect(self._hwnd(hwnd), ref):
            return None
        if rect.left >= rect.right or rect.top >= rect.bottom:
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)

    def _classe(self, hwnd: int) -> str:
        buffer = self._ctypes.create_unicode_buffer(64)
        self._u.GetClassNameW(self._hwnd(hwnd), buffer, 64)
        return buffer.value

    def _opaca(self, hwnd: int) -> bool:
        """Mesmos critérios do Rainmeter (vindos do Chromium): na dúvida, não cobre."""
        classe = self._classe(hwnd)
        if classe in self.CLASSES_AREA_DE_TRABALHO:
            return True
        estilo = int(self._u.GetWindowLongPtrW(self._hwnd(hwnd), self.GWL_EXSTYLE))
        if estilo & self.WS_EX_TRANSPARENT:
            return False
        if estilo & WS_EX_TOOLWINDOW and classe not in self.CLASSES_BARRA:
            return False  # sobreposições do shell e de captura têm partes transparentes
        if estilo & self.WS_EX_LAYERED:
            chave, alfa, flags = self._wintypes.COLORREF(), self._wintypes.BYTE(), self._wintypes.DWORD()
            if not self._u.GetLayeredWindowAttributes(
                self._hwnd(hwnd), self._ctypes.byref(chave), self._ctypes.byref(alfa), self._ctypes.byref(flags),
            ):
                return False  # transparência por pixel (UpdateLayeredWindow)
            if flags.value & self.LWA_COLORKEY:
                return False
            if flags.value & self.LWA_ALPHA and (alfa.value & 0xFF) < 255:
                return False
        caixa = self._wintypes.RECT()
        return self._u.GetWindowRgnBox(self._hwnd(hwnd), self._ctypes.byref(caixa)) != self.COMPLEXREGION

    def estado_de_cobertura(self, hwnd: int) -> tuple[Retangulo | None, list[Retangulo]]:
        u = self._u
        if not u.IsWindowVisible(self._hwnd(hwnd)) or u.IsIconic(self._hwnd(hwnd)) or self._cloaked(hwnd):
            return None, []
        proprio = self._limites(hwnd)
        if proprio is None:
            return None, []
        e, t, d, b = proprio
        cobertores: list[Retangulo] = []
        janela = hwnd
        for _ in range(self.LIMITE_PILHA):
            janela = u.GetWindow(self._hwnd(janela), self.GW_HWNDPREV)
            if not janela:
                break
            # Das mais baratas às mais caras; a maioria das janelas acima é oculta.
            if not u.IsWindowVisible(self._hwnd(janela)) or u.IsIconic(self._hwnd(janela)):
                continue
            limites = self._limites(janela)
            if limites is None:
                continue
            le, lt, ld, lb = limites
            if le >= d or ld <= e or lt >= b or lb <= t:
                continue  # não alcança a janela
            if self._cloaked(janela) or not self._opaca(janela):
                continue
            cobertores.append(limites)
        return proprio, cobertores

    def janela_em_primeiro_plano(self) -> int | None:
        return self._u.GetForegroundWindow() or None

    def raiz(self, hwnd: int | None) -> int | None:
        if not hwnd:
            return None
        return self._u.GetAncestor(self._hwnd(hwnd), self.GA_ROOT) or None

    # -- vigia (chamados na thread `vigia-fundo`) ---------------------------

    def preparar_fila(self) -> int:
        msg = self._wintypes.MSG()
        # A 1ª chamada a uma função de mensagens cria a fila da thread.
        self._u.PeekMessageW(self._ctypes.byref(msg), None, 0, 0, self.PM_NOREMOVE)
        return int(self._k.GetCurrentThreadId())

    def instalar_gancho_primeiro_plano(self, ao_mudar: Callable[[int | None], None]) -> object:
        def _proc(_gancho, _evento, hwnd, _objeto, _filho, _thread, _instante):
            ao_mudar(hwnd or None)

        return self._instalar(self.EVENT_SYSTEM_FOREGROUND, self.EVENT_SYSTEM_FOREGROUND, _proc)

    def instalar_ganchos_de_pilha(self, ao_mudar: Callable[[], None]) -> list:
        def _proc(_gancho, evento, _hwnd, objeto, _filho, _thread, _instante):
            # Eventos de objeto (0x8000+) chegam também de cursores, menus etc.: só janelas.
            if evento < 0x8000 or objeto == self.OBJID_WINDOW:
                ao_mudar()

        ganchos: list = []
        try:
            for minimo, maximo in self.FAIXAS_EVENTOS_PILHA:
                ganchos.append(self._instalar(minimo, maximo, _proc))
        except OSError:
            for gancho in ganchos:
                self.remover_gancho(gancho)
            raise
        return ganchos

    def _instalar(self, minimo: int, maximo: int, proc) -> int:
        callback = self.WINEVENTPROC(proc)
        gancho = self._u.SetWinEventHook(minimo, maximo, None, callback, 0, 0, self.WINEVENT_OUTOFCONTEXT)
        if not gancho:
            raise self._erro("SetWinEventHook")
        self._callbacks[int(gancho)] = callback
        return int(gancho)

    def remover_gancho(self, gancho: object) -> None:
        if gancho:
            self._u.UnhookWinEvent(gancho)
            self._callbacks.pop(int(gancho), None)  # type: ignore[call-overload]

    def iniciar_tique(self, intervalo_ms: int) -> int:
        """Liga o tique do laço (cronometrado por ele mesmo; ver rodar_laco)."""
        self._intervalo_tique_s = intervalo_ms / 1000
        return 1

    def parar_tique(self, id_tique: int) -> None:
        self._intervalo_tique_s = None

    def rodar_laco(self, ao_tique: Callable[[], None]) -> None:
        """Processa mensagens (e os ganchos fora de contexto) e chama `ao_tique` no prazo.

        Não usa WM_TIMER: ele só é entregue com a fila vazia e, sob uma enxurrada de
        mensagens, nunca chegaria. Aqui o prazo é conferido a cada volta, e cada volta
        processa no máximo MENSAGENS_POR_VOLTA mensagens.
        """
        msg = self._wintypes.MSG()
        ref = self._ctypes.byref(msg)
        u = self._u
        proximo = time.monotonic() + self._intervalo_tique_s if self._intervalo_tique_s else None
        while True:
            espera = self.ESPERA_MAXIMA_MS
            if proximo is not None:
                espera = min(espera, max(0, int((proximo - time.monotonic()) * 1000)))
            if u.MsgWaitForMultipleObjectsEx(0, None, espera, self.QS_ALLINPUT, self.MWMO_INPUTAVAILABLE) \
                    == self.WAIT_FAILED:
                raise self._erro("MsgWaitForMultipleObjectsEx")
            for _ in range(self.MENSAGENS_POR_VOLTA):
                if not u.PeekMessageW(ref, None, 0, 0, self.PM_REMOVE):
                    break
                if msg.message == self.WM_QUIT:
                    return
                u.TranslateMessage(ref)
                u.DispatchMessageW(ref)
            if proximo is not None and time.monotonic() >= proximo:
                ao_tique()
                intervalo = self._intervalo_tique_s
                proximo = time.monotonic() + intervalo if intervalo else None  # sem acumular atraso

    def encerrar_laco(self, id_thread: int) -> None:
        if not self._u.PostThreadMessageW(id_thread, self.WM_QUIT, 0, 0):
            raise self._erro("PostThreadMessageW")
