"""Testes da camada fundo (`camada_fundo.py`): lógica pura, controlador, vigia e Win32 real."""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import camada_fundo  # noqa: E402
from camada_fundo import (  # noqa: E402
    LIMITE_AUSENCIA_MS,
    TIQUES_POR_CONFERENCIA,
    VOLTA_DA_AUSENCIA_MS,
    WS_EX_APPWINDOW,
    WS_EX_TOOLWINDOW,
    ControladorCamada,
    EstadoPublicado,
    VigiaPrimeiroPlano,
    area_visivel,
    camada_salva,
    deve_afundar,
    esta_coberta,
    estilo_para_fundo,
    subtrair,
    usuario_ausente,
)

JANELA = 0x1000
RET_JANELA = (100, 100, 600, 910)  # 500x810
FILHA = 0x1001  # ex.: o controle do WebView2 dentro da janela
OUTRA = 0x2000
AREA = 0x3000  # a área de trabalho (Progman), sempre no fim da pilha
ESTILO_WINFORMS = WS_EX_APPWINDOW | 0x00000100  # APPWINDOW + WINDOWEDGE


# ---------------------------------------------------------------------------
# Sistema falso
# ---------------------------------------------------------------------------

class SistemaFalso:
    """Registra as chamadas; a vigia roda um laço que espera `encerrar_laco`.

    Imita a pilha de janelas (`ordem`, de cima para baixo) com a área de trabalho presa
    embaixo: HWND_BOTTOM fica logo acima dela, como no Windows.
    """

    def __init__(self, estilo: int = ESTILO_WINFORMS, primeiro_plano: int | None = OUTRA) -> None:
        self.estilo = estilo
        self.primeiro_plano = primeiro_plano
        self.chamadas: list[tuple] = []
        self.falhar: set[str] = set()
        self.visivel = True
        self.no_peek = True
        self._fim_laco = threading.Event()
        self.ao_mudar = None
        self.ao_tique = None
        self.gancho_removido = False
        self.ordem: list[int] = [OUTRA, JANELA, AREA]
        self.topmost: set[int] = set()
        self.ocioso = 0  # ms sem tecla nem mouse
        self.cobertura = (RET_JANELA, [])  # (retângulo da janela, opacos acima)
        self.calculos = 0
        self.ao_mudar_pilha = None

    def _tirar(self, hwnd):
        if hwnd in self.ordem:
            self.ordem.remove(hwnd)

    def _registrar(self, nome: str, *args) -> None:
        self.chamadas.append((nome, *args))
        if nome in self.falhar:
            raise OSError(5, f"{nome} falhou")

    def nomes(self) -> list[str]:
        return [c[0] for c in self.chamadas]

    def ler_estilo(self, hwnd):
        self._registrar("ler_estilo", hwnd)
        return self.estilo

    def gravar_estilo(self, hwnd, estilo):
        self._registrar("gravar_estilo", hwnd, estilo)
        assert not self.visivel, "estilo deve ser trocado com a janela oculta"
        self.estilo = estilo

    def atualizar_moldura(self, hwnd):
        self._registrar("atualizar_moldura", hwnd)

    def ocultar(self, hwnd):
        self._registrar("ocultar", hwnd)
        self.visivel = False

    def mostrar_sem_ativar(self, hwnd):
        self._registrar("mostrar_sem_ativar", hwnd)
        self.visivel = True

    def excluir_do_peek(self, hwnd, excluir):
        self._registrar("excluir_do_peek", hwnd, excluir)
        self.no_peek = not excluir

    def enviar_para_fundo(self, hwnd):
        self._registrar("enviar_para_fundo", hwnd)
        self.topmost.discard(hwnd)  # HWND_BOTTOM tira o TOPMOST
        self._tirar(hwnd)
        self.ordem.insert(self.ordem.index(AREA), hwnd)

    def trazer_para_frente_sem_ativar(self, hwnd):
        self._registrar("trazer_para_frente_sem_ativar", hwnd)
        self._tirar(hwnd)
        self.ordem.insert(len([h for h in self.ordem if h in self.topmost]), hwnd)

    def fixar_temporariamente(self, hwnd):
        self._registrar("fixar_temporariamente", hwnd)
        self.topmost.add(hwnd)
        self._tirar(hwnd)
        self.ordem.insert(0, hwnd)

    def tirar_do_topo(self, hwnd):
        self._registrar("tirar_do_topo", hwnd)
        self.topmost.discard(hwnd)

    def estado_de_cobertura(self, hwnd):
        self.calculos += 1
        if "estado_de_cobertura" in self.falhar:
            raise OSError(5, "falha simulada")
        return self.cobertura

    def esta_acima(self, alvo, referencia):
        return self.ordem.index(alvo) < self.ordem.index(referencia)

    def ocioso_ms(self):
        if "ocioso_ms" in self.falhar:
            raise OSError(5, "falha simulada")
        return self.ocioso

    def instalar_ganchos_de_pilha(self, ao_mudar):
        self._registrar("instalar_ganchos_de_pilha")
        self.ao_mudar_pilha = ao_mudar
        return ["pilha1", "pilha2"]

    def tique(self):
        """Simula o WM_TIMER da vigia (na thread do teste)."""
        assert self.ao_tique is not None, "vigia sem laço"
        self.ao_tique()

    def janela_em_primeiro_plano(self):
        return self.primeiro_plano

    def raiz(self, hwnd):
        if hwnd == FILHA:
            return JANELA
        return hwnd or None

    def preparar_fila(self):
        self._registrar("preparar_fila")
        self._fim_laco.clear()
        return 77

    def instalar_gancho_primeiro_plano(self, ao_mudar):
        self._registrar("instalar_gancho")
        self.ao_mudar = ao_mudar
        self.gancho_removido = False
        return "gancho"

    def remover_gancho(self, gancho):
        self.chamadas.append(("remover_gancho", gancho))
        self.gancho_removido = True
        self.ao_mudar = None

    def iniciar_tique(self, intervalo_ms):
        self._registrar("iniciar_tique", intervalo_ms)
        return 9

    def parar_tique(self, id_tique):
        self._registrar("parar_tique", id_tique)

    def rodar_laco(self, ao_tique):
        self.ao_tique = ao_tique
        self._fim_laco.wait(5)
        self.ao_tique = None

    def encerrar_laco(self, id_thread):
        self.chamadas.append(("encerrar_laco", id_thread))
        self._fim_laco.set()

    def trocar_primeiro_plano(self, hwnd):
        """Simula o Windows avisando a vigia (na thread do teste)."""
        self.primeiro_plano = hwnd
        assert self.ao_mudar is not None, "vigia sem gancho"
        self.ao_mudar(hwnd)


def criar(sistema: SistemaFalso, janela: int | None = JANELA) -> ControladorCamada:
    return ControladorCamada(sistema, lambda: janela)


# ---------------------------------------------------------------------------
# Lógica pura
# ---------------------------------------------------------------------------

def test_estilo_para_fundo_vira_ferramenta_sem_appwindow():
    estilo = estilo_para_fundo(ESTILO_WINFORMS)
    assert estilo & WS_EX_TOOLWINDOW
    assert not estilo & WS_EX_APPWINDOW
    assert estilo & 0x00000100, "outros bits ficam"


def test_estilo_para_fundo_e_idempotente():
    uma = estilo_para_fundo(ESTILO_WINFORMS)
    assert estilo_para_fundo(uma) == uma


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("fundo", "fundo"), (" Fundo ", "fundo"), ("normal", "normal"), ("topo", "normal"),
     ("", "normal"), ("xyz", "normal"), (None, "normal")],
)
def test_camada_salva(valor, esperado):
    assert camada_salva(valor) == esperado


def test_camadas_lembradas_nao_incluem_topo():
    assert "topo" in camada_fundo.CAMADAS
    assert "topo" not in camada_fundo.CAMADAS_LEMBRADAS


@pytest.mark.parametrize(
    ("camada", "primeiro", "propria", "esperado"),
    [
        ("fundo", OUTRA, JANELA, True),
        ("fundo", JANELA, JANELA, False),
        ("fundo", None, JANELA, False),
        ("fundo", OUTRA, None, False),
        ("normal", OUTRA, JANELA, False),
        ("topo", OUTRA, JANELA, False),
    ],
)
def test_deve_afundar(camada, primeiro, propria, esperado):
    assert deve_afundar(camada, primeiro, propria) is esperado


# ---------------------------------------------------------------------------
# Controlador: entrar
# ---------------------------------------------------------------------------

def test_entrar_troca_estilo_com_a_janela_oculta_e_afunda():
    sistema = SistemaFalso()
    controlador = criar(sistema)
    try:
        assert controlador.entrar_no_fundo() is True
        assert controlador.no_fundo
        nomes = sistema.nomes()
        assert nomes.index("ocultar") < nomes.index("gravar_estilo") < nomes.index("mostrar_sem_ativar")
        assert sistema.estilo == estilo_para_fundo(ESTILO_WINFORMS)
        assert sistema.visivel
        assert sistema.no_peek is False
        assert ("enviar_para_fundo", JANELA) in sistema.chamadas
        assert "instalar_gancho" in nomes
    finally:
        controlador.encerrar()


def test_entrar_sem_primeiro_plano_conhecido_afunda():
    sistema = SistemaFalso(primeiro_plano=None)
    controlador = criar(sistema)
    try:
        controlador.entrar_no_fundo()
        assert ("enviar_para_fundo", JANELA) in sistema.chamadas
    finally:
        controlador.encerrar()


def test_entrar_com_a_propria_janela_em_primeiro_plano_nao_afunda_na_hora():
    sistema = SistemaFalso(primeiro_plano=FILHA)
    controlador = criar(sistema)
    try:
        controlador.entrar_no_fundo()
        assert ("enviar_para_fundo", JANELA) not in sistema.chamadas
    finally:
        controlador.encerrar()


def test_entrar_duas_vezes_nao_perde_o_estilo_original():
    sistema = SistemaFalso()
    controlador = criar(sistema)
    try:
        controlador.entrar_no_fundo()
        sistema.chamadas.clear()
        assert controlador.entrar_no_fundo() is True
        assert sistema.chamadas == []
        controlador.sair_do_fundo()
        assert sistema.estilo == ESTILO_WINFORMS
    finally:
        controlador.encerrar()


def test_entrar_sem_janela_falha_sem_mexer_em_nada(caplog):
    sistema = SistemaFalso()
    controlador = criar(sistema, janela=None)
    with caplog.at_level(logging.ERROR):
        assert controlador.entrar_no_fundo() is False
    assert sistema.chamadas == []
    assert not controlador.no_fundo
    assert "janela não encontrada" in caplog.text


def test_falha_ao_ler_estilo_nao_esconde_a_janela():
    sistema = SistemaFalso()
    sistema.falhar.add("ler_estilo")
    controlador = criar(sistema)
    assert controlador.entrar_no_fundo() is False
    assert "ocultar" not in sistema.nomes()
    assert sistema.visivel


def test_falha_ao_gravar_estilo_mostra_a_janela_de_novo(caplog):
    sistema = SistemaFalso()
    sistema.falhar.add("gravar_estilo")
    controlador = criar(sistema)
    with caplog.at_level(logging.ERROR):
        assert controlador.entrar_no_fundo() is False
    assert sistema.visivel, "nunca deixar a janela oculta"
    assert not controlador.no_fundo
    assert "instalar_gancho" not in sistema.nomes()
    assert "falha ao entrar no fundo" in caplog.text


def test_falha_depois_de_gravar_restaura_o_estilo():
    sistema = SistemaFalso()
    sistema.falhar.add("excluir_do_peek")
    controlador = criar(sistema)
    assert controlador.entrar_no_fundo() is False
    assert sistema.estilo == ESTILO_WINFORMS
    assert sistema.visivel


def test_falha_ao_afundar_vai_ao_log_e_mantem_o_fundo(caplog):
    sistema = SistemaFalso()
    sistema.falhar.add("enviar_para_fundo")
    controlador = criar(sistema)
    try:
        with caplog.at_level(logging.ERROR):
            assert controlador.entrar_no_fundo() is True
        assert controlador.no_fundo
        assert "falha ao enviar a janela para o fundo" in caplog.text
    finally:
        controlador.encerrar()


# ---------------------------------------------------------------------------
# Controlador: sair
# ---------------------------------------------------------------------------

def test_sair_restaura_estilo_peek_e_traz_para_frente():
    sistema = SistemaFalso()
    controlador = criar(sistema)
    controlador.entrar_no_fundo()
    sistema.chamadas.clear()
    assert controlador.sair_do_fundo() is True
    assert not controlador.no_fundo
    assert sistema.estilo == ESTILO_WINFORMS
    assert sistema.no_peek is True
    assert sistema.visivel
    nomes = sistema.nomes()
    assert nomes.index("encerrar_laco") < nomes.index("ocultar")
    assert nomes.index("ocultar") < nomes.index("gravar_estilo") < nomes.index("mostrar_sem_ativar")
    assert nomes[-1] == "trazer_para_frente_sem_ativar"
    assert sistema.gancho_removido


def test_sair_fora_do_fundo_nao_faz_nada():
    sistema = SistemaFalso()
    controlador = criar(sistema)
    assert controlador.sair_do_fundo() is True
    assert sistema.chamadas == []


def test_sair_restaura_e_mostra_mesmo_se_ocultar_falhar(caplog):
    sistema = SistemaFalso()
    controlador = criar(sistema)
    controlador.entrar_no_fundo()
    sistema.falhar.add("ocultar")
    sistema.visivel = False  # o falso exige janela oculta para gravar o estilo
    with caplog.at_level(logging.ERROR):
        assert controlador.sair_do_fundo() is True
    assert sistema.visivel
    assert sistema.estilo == ESTILO_WINFORMS
    assert not controlador.no_fundo
    assert "falha ao ocultar" in caplog.text


# ---------------------------------------------------------------------------
# Controlador: troca de primeiro plano (aviso da vigia)
# ---------------------------------------------------------------------------

def test_outra_janela_no_primeiro_plano_afunda():
    sistema = SistemaFalso(primeiro_plano=JANELA)
    controlador = criar(sistema)
    try:
        controlador.entrar_no_fundo()
        sistema.chamadas.clear()
        sistema.trocar_primeiro_plano(OUTRA)
        assert sistema.chamadas == [("enviar_para_fundo", JANELA)]
    finally:
        controlador.encerrar()


def test_clique_na_propria_janela_nao_afunda():
    sistema = SistemaFalso()
    controlador = criar(sistema)
    try:
        controlador.entrar_no_fundo()
        sistema.chamadas.clear()
        sistema.trocar_primeiro_plano(FILHA)  # raiz = a própria janela
        sistema.trocar_primeiro_plano(JANELA)
        assert sistema.chamadas == []
    finally:
        controlador.encerrar()


def test_aviso_sem_janela_em_primeiro_plano_e_ignorado():
    sistema = SistemaFalso()
    controlador = criar(sistema)
    try:
        controlador.entrar_no_fundo()
        sistema.chamadas.clear()
        sistema.trocar_primeiro_plano(None)
        assert sistema.chamadas == []
    finally:
        controlador.encerrar()


def test_aviso_durante_transicao_e_ignorado_sem_travar():
    sistema = SistemaFalso()
    controlador = criar(sistema)
    try:
        controlador.entrar_no_fundo()
        sistema.chamadas.clear()
        with controlador._trava:  # transição em andamento
            controlador.ao_mudar_primeiro_plano(OUTRA)
        assert sistema.chamadas == []
    finally:
        controlador.encerrar()


def test_aviso_depois_de_sair_nao_afunda():
    sistema = SistemaFalso()
    controlador = criar(sistema)
    controlador.entrar_no_fundo()
    aviso = sistema.ao_mudar
    controlador.sair_do_fundo()
    sistema.chamadas.clear()
    aviso(OUTRA)  # aviso atrasado, já fora do fundo
    assert sistema.chamadas == []


# ---------------------------------------------------------------------------
# Vigia
# ---------------------------------------------------------------------------

def test_vigia_inicia_uma_vez_e_para():
    sistema = SistemaFalso()
    avisos: list = []
    vigia = VigiaPrimeiroPlano(sistema, avisos.append)
    assert vigia.iniciar() is True
    assert vigia.ativa
    assert vigia.iniciar() is True
    assert sistema.nomes().count("instalar_gancho") == 1
    sistema.ao_mudar(OUTRA)
    assert avisos == [OUTRA]
    vigia.parar()
    assert not vigia.ativa
    assert sistema.gancho_removido
    assert ("encerrar_laco", 77) in sistema.chamadas


def test_vigia_pode_reiniciar_depois_de_parar():
    sistema = SistemaFalso()
    vigia = VigiaPrimeiroPlano(sistema, lambda _h: None)
    vigia.iniciar()
    vigia.parar()
    assert vigia.iniciar() is True
    assert sistema.nomes().count("instalar_gancho") == 2
    vigia.parar()


def test_vigia_com_gancho_que_falha_nao_inicia(caplog):
    sistema = SistemaFalso()
    sistema.falhar.add("instalar_gancho")
    vigia = VigiaPrimeiroPlano(sistema, lambda _h: None)
    with caplog.at_level(logging.ERROR):
        assert vigia.iniciar() is False
    assert "vigia não iniciou" in caplog.text
    vigia.parar()  # sem thread viva: não trava


def test_erro_no_aviso_vai_ao_log_sem_derrubar_a_vigia(caplog):
    sistema = SistemaFalso()

    def explode(_hwnd):
        raise RuntimeError("boom")

    vigia = VigiaPrimeiroPlano(sistema, explode)
    vigia.iniciar()
    try:
        with caplog.at_level(logging.ERROR):
            sistema.ao_mudar(OUTRA)
        assert "falha ao tratar a troca de primeiro plano" in caplog.text
        assert vigia.ativa
    finally:
        vigia.parar()


def test_controlador_sem_vigia_continua_no_fundo(caplog):
    sistema = SistemaFalso()
    sistema.falhar.add("instalar_gancho")
    controlador = criar(sistema)
    with caplog.at_level(logging.WARNING):
        assert controlador.entrar_no_fundo() is True
    assert "sem vigia" in caplog.text
    controlador.sair_do_fundo()
    assert sistema.estilo == ESTILO_WINFORMS


# ---------------------------------------------------------------------------
# Tique e destaque do alarme
# ---------------------------------------------------------------------------

def entrar_e_limpar(sistema: SistemaFalso) -> ControladorCamada:
    controlador = criar(sistema)
    assert controlador.entrar_no_fundo()
    sistema.chamadas.clear()
    return controlador


def test_o_tique_nao_mexe_na_posicao_da_janela():
    sistema = SistemaFalso()
    controlador = entrar_e_limpar(sistema)
    try:
        for primeiro in (OUTRA, JANELA, None, AREA):
            sistema.primeiro_plano = primeiro
            sistema.tique()
        assert sistema.chamadas == []
    finally:
        controlador.encerrar()


def test_tique_durante_transicao_e_ignorado():
    sistema = SistemaFalso()
    controlador, publicados = controlador_publicando(sistema)
    try:
        with controlador._trava:
            sistema.tique()
        assert publicados == []
        sistema.tique()  # depois da transição, o próximo tique pega
        assert publicados == [{"coberto": False}]
    finally:
        controlador.encerrar()


def test_erro_no_tique_vai_ao_log_sem_derrubar_a_vigia(caplog):
    sistema = SistemaFalso()

    def explode():
        raise RuntimeError("boom")

    vigia = VigiaPrimeiroPlano(sistema, lambda _h: None, explode)
    vigia.iniciar()
    try:
        with caplog.at_level(logging.ERROR):
            sistema.tique()
        assert "falha no tique da vigia" in caplog.text
        assert vigia.ativa
    finally:
        vigia.parar()


def test_sem_tique_o_fundo_continua_pela_troca_de_primeiro_plano(caplog):
    sistema = SistemaFalso(primeiro_plano=JANELA)
    sistema.falhar.add("iniciar_tique")
    with caplog.at_level(logging.ERROR):
        controlador = entrar_e_limpar(sistema)
    try:
        assert "sem tique" in caplog.text
        sistema.trocar_primeiro_plano(OUTRA)
        assert ("enviar_para_fundo", JANELA) in sistema.chamadas
    finally:
        controlador.encerrar()
    assert "parar_tique" not in sistema.nomes()


def test_destaque_do_alarme_sobe_sem_ativar_e_resiste_a_troca_de_primeiro_plano():
    sistema = SistemaFalso()
    controlador = entrar_e_limpar(sistema)
    try:
        assert controlador.destacar(True) is True
        assert sistema.chamadas == [("fixar_temporariamente", JANELA)]
        assert controlador.em_destaque and JANELA in sistema.topmost
        assert controlador.destacar(True) is True  # já em destaque: nada a fazer
        assert len(sistema.chamadas) == 1
        sistema.trocar_primeiro_plano(OUTRA)  # o usuário segue trabalhando em outra janela
        assert ("enviar_para_fundo", JANELA) not in sistema.chamadas
    finally:
        controlador.encerrar()


def test_fim_do_destaque_devolve_ao_fundo():
    sistema = SistemaFalso()
    controlador = entrar_e_limpar(sistema)
    try:
        controlador.destacar(True)
        sistema.chamadas.clear()
        assert controlador.destacar(False) is True
        assert sistema.chamadas == [("enviar_para_fundo", JANELA)]
        assert not controlador.em_destaque and JANELA not in sistema.topmost
        sistema.trocar_primeiro_plano(OUTRA)  # sem destaque, a troca volta a afundar
        assert sistema.chamadas[-1] == ("enviar_para_fundo", JANELA)
    finally:
        controlador.encerrar()


def test_fim_do_destaque_com_a_janela_em_uso_so_tira_do_topo():
    """Clicou no OK: a janela está em primeiro plano e fica na frente até perder o foco."""
    sistema = SistemaFalso()
    controlador = entrar_e_limpar(sistema)
    try:
        controlador.destacar(True)
        sistema.chamadas.clear()
        sistema.primeiro_plano = FILHA
        controlador.destacar(False)
        assert sistema.chamadas == [("tirar_do_topo", JANELA)]
    finally:
        controlador.encerrar()


def test_destaque_fora_do_fundo_nao_faz_nada():
    sistema = SistemaFalso()
    controlador = criar(sistema)
    assert controlador.destacar(True) is False
    assert sistema.chamadas == []


def test_falha_no_destaque_vai_ao_log_e_mantem_o_estado(caplog):
    sistema = SistemaFalso()
    controlador = entrar_e_limpar(sistema)
    try:
        sistema.falhar.add("fixar_temporariamente")
        with caplog.at_level(logging.ERROR):
            assert controlador.destacar(True) is False
        assert not controlador.em_destaque
        assert "falha ao aplicar o destaque" in caplog.text
    finally:
        controlador.encerrar()


def test_sair_do_fundo_em_destaque_tira_do_topo_antes():
    sistema = SistemaFalso()
    controlador = entrar_e_limpar(sistema)
    controlador.destacar(True)
    sistema.chamadas.clear()
    controlador.sair_do_fundo()
    nomes = sistema.nomes()
    assert nomes.index("tirar_do_topo") < nomes.index("trazer_para_frente_sem_ativar")
    assert JANELA not in sistema.topmost and not controlador.em_destaque


# ---------------------------------------------------------------------------
# Ausência do usuário (ócio do sistema)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("ocioso", "ja_ausente", "esperado"),
    [
        (0, False, False),
        (LIMITE_AUSENCIA_MS - 1, False, False),
        (LIMITE_AUSENCIA_MS, False, True),
        (LIMITE_AUSENCIA_MS + 5000, True, True),
        (VOLTA_DA_AUSENCIA_MS, True, True),        # ainda sem atividade recente
        (VOLTA_DA_AUSENCIA_MS - 1, True, False),   # tecla ou mouse agora: voltou
    ],
)
def test_usuario_ausente(ocioso, ja_ausente, esperado):
    assert usuario_ausente(ocioso, ja_ausente) is esperado


def test_ausencia_publicada_so_nas_mudancas():
    sistema = SistemaFalso()
    controlador, publicados = controlador_publicando(sistema)
    try:
        sistema.tique()
        assert {"ausente": True} not in publicados
        sistema.ocioso = LIMITE_AUSENCIA_MS
        sistema.tique()
        sistema.ocioso = LIMITE_AUSENCIA_MS + 250
        sistema.tique()
        assert [p for p in publicados if "ausente" in p] == [{"ausente": True}]
        sistema.ocioso = 10  # mexeu no mouse em qualquer lugar
        sistema.tique()
        assert [p for p in publicados if "ausente" in p] == [{"ausente": True}, {"ausente": False}]
    finally:
        controlador.encerrar()


def test_falha_ao_ler_o_ocio_avisa_uma_vez_e_segue(caplog):
    sistema = SistemaFalso()
    sistema.falhar.add("ocioso_ms")
    controlador, publicados = controlador_publicando(sistema)
    try:
        with caplog.at_level(logging.ERROR):
            for _ in range(5):
                sistema.tique()
        assert caplog.text.count("tempo sem uso do sistema") == 1
        assert all("ausente" not in p for p in publicados)
        assert publicados[0] == {"coberto": False}  # a cobertura continua
    finally:
        controlador.encerrar()


# ---------------------------------------------------------------------------
# Cobertura (fase 3)
# ---------------------------------------------------------------------------

def test_subtrair_sem_intersecao_devolve_o_alvo():
    assert subtrair((0, 0, 10, 10), (20, 20, 30, 30)) == [(0, 0, 10, 10)]
    assert subtrair((0, 0, 10, 10), (10, 0, 20, 10)) == [(0, 0, 10, 10)]  # só encosta


def test_subtrair_corte_no_meio_deixa_quatro_partes_sem_sobreposicao():
    partes = subtrair((0, 0, 10, 10), (3, 3, 7, 7))
    assert sum((d - e) * (b - t) for e, t, d, b in partes) == 100 - 16
    assert len(partes) == 4


def test_subtrair_corte_que_cobre_tudo():
    assert subtrair((2, 2, 8, 8), (0, 0, 10, 10)) == []


@pytest.mark.parametrize(
    ("cobertores", "visivel"),
    [
        ([], 500 * 810),
        ([(0, 0, 2000, 2000)], 0),                         # janela maximizada por cima
        ([(100, 100, 600, 500)], 500 * 410),               # metade de cima tapada
        ([(100, 100, 600, 500), (100, 500, 600, 910)], 0),  # duas janelas tapam tudo
        ([(100, 100, 600, 600), (100, 400, 600, 910)], 0),  # sobrepostas entre si
        ([(0, 0, 595, 2000)], 5 * 810),                    # fresta de 5 px
    ],
)
def test_area_visivel(cobertores, visivel):
    assert area_visivel(RET_JANELA, cobertores) == visivel


def test_esta_coberta():
    assert esta_coberta(None, []) is True  # oculta, minimizada ou em outra área virtual
    assert esta_coberta(RET_JANELA, []) is False
    assert esta_coberta(RET_JANELA, [(0, 0, 2000, 2000)]) is True
    assert esta_coberta(RET_JANELA, [(0, 0, 596, 2000)]) is True   # fresta de 4 px (<1%)
    assert esta_coberta(RET_JANELA, [(0, 0, 500, 2000)]) is False  # 100 px à vista


def test_estado_publicado_so_muda_a_versao_quando_o_estado_muda():
    estado = EstadoPublicado()
    assert estado.atual() == {"versao": 0, "coberto": False, "ausente": False}
    estado.publicar(coberto=False)
    assert estado.atual()["versao"] == 0
    estado.publicar(coberto=True)
    estado.publicar(coberto=True)
    assert estado.atual() == {"versao": 1, "coberto": True, "ausente": False}
    estado.publicar(ausente=True)  # o outro campo fica como estava
    assert estado.atual() == {"versao": 2, "coberto": True, "ausente": True}


def test_aguardar_volta_na_hora_com_versao_antiga_e_no_prazo_sem_mudanca():
    estado = EstadoPublicado()
    estado.publicar(coberto=True)
    assert estado.aguardar(0, prazo_s=5) == {"versao": 1, "coberto": True, "ausente": False}
    inicio = time.monotonic()
    assert estado.aguardar(1, prazo_s=0.05) == {"versao": 1, "coberto": True, "ausente": False}
    assert time.monotonic() - inicio >= 0.04


def test_aguardar_acorda_com_a_mudanca_e_com_o_encerramento():
    estado = EstadoPublicado()
    resultados: list = []
    espera = threading.Thread(target=lambda: resultados.append(estado.aguardar(0, prazo_s=5)))
    espera.start()
    time.sleep(0.05)
    estado.publicar(coberto=True)
    espera.join(1)
    assert resultados == [{"versao": 1, "coberto": True, "ausente": False}]

    # Fechamento: as chamadas da API rodam em threads NÃO-daemon; nenhuma pode ficar presa.
    espera = threading.Thread(target=lambda: resultados.append(estado.aguardar(1, prazo_s=5)))
    espera.start()
    time.sleep(0.05)
    estado.encerrar()
    espera.join(1)
    assert not espera.is_alive()


def controlador_publicando(sistema: SistemaFalso) -> tuple[ControladorCamada, list]:
    publicados: list = []
    controlador = ControladorCamada(sistema, lambda: JANELA, publicar=lambda **campos: publicados.append(campos))
    assert controlador.entrar_no_fundo()
    sistema.chamadas.clear()
    return controlador, publicados


def coberturas(publicados: list) -> list:
    return [p["coberto"] for p in publicados if "coberto" in p]


def test_cobertura_publicada_no_tique():
    sistema = SistemaFalso()
    controlador, publicados = controlador_publicando(sistema)
    try:
        sistema.tique()
        assert coberturas(publicados) == [False]
        sistema.cobertura = (RET_JANELA, [(0, 0, 2000, 2000)])
        sistema.ao_mudar_pilha()  # uma janela foi arrastada por cima
        sistema.tique()
        assert coberturas(publicados) == [False, True]
        sistema.cobertura = (None, [])  # minimizada/oculta/cloaked
        sistema.ao_mudar_pilha()
        sistema.tique()
        assert coberturas(publicados)[-1] is True
    finally:
        controlador.encerrar()


def test_sem_mudanca_na_pilha_recalcula_so_de_tempos_em_tempos():
    sistema = SistemaFalso()
    controlador, _ = controlador_publicando(sistema)
    try:
        sistema.tique()  # 1º: a entrada marcou a pilha como mudada
        calculos = sistema.calculos
        for _ in range(TIQUES_POR_CONFERENCIA):
            sistema.tique()
        assert sistema.calculos == calculos + 1, "um cálculo de reserva a cada TIQUES_POR_CONFERENCIA"
        sistema.trocar_primeiro_plano(OUTRA)  # a troca de primeiro plano também marca
        sistema.tique()
        assert sistema.calculos == calculos + 2
    finally:
        controlador.encerrar()


def test_falha_no_calculo_vai_ao_log_e_conta_como_visivel(caplog):
    sistema = SistemaFalso()
    controlador, publicados = controlador_publicando(sistema)
    try:
        sistema.falhar.add("estado_de_cobertura")
        with caplog.at_level(logging.ERROR):
            sistema.tique()
        assert coberturas(publicados) == [False]
        assert "falha ao calcular a cobertura" in caplog.text
    finally:
        controlador.encerrar()


def test_sair_do_fundo_publica_visivel_e_presente():
    sistema = SistemaFalso()
    controlador, publicados = controlador_publicando(sistema)
    sistema.cobertura = (RET_JANELA, [(0, 0, 2000, 2000)])
    sistema.ocioso = LIMITE_AUSENCIA_MS
    sistema.tique()
    assert coberturas(publicados) == [True]
    controlador.sair_do_fundo()
    assert publicados[-1] == {"coberto": False, "ausente": False}


def test_vigia_instala_e_remove_os_ganchos_de_pilha():
    sistema = SistemaFalso()
    controlador = criar(sistema)
    controlador.entrar_no_fundo()
    assert "instalar_ganchos_de_pilha" in sistema.nomes()
    controlador.sair_do_fundo()
    removidos = [c[1] for c in sistema.chamadas if c[0] == "remover_gancho"]
    assert {"pilha1", "pilha2", "gancho"} <= set(removidos)


def test_sem_ganchos_de_pilha_o_tique_ainda_confere(caplog):
    sistema = SistemaFalso()
    sistema.falhar.add("instalar_ganchos_de_pilha")
    with caplog.at_level(logging.ERROR):
        controlador, publicados = controlador_publicando(sistema)
    try:
        assert "sem ganchos de pilha" in caplog.text
        sistema.cobertura = (RET_JANELA, [(0, 0, 2000, 2000)])
        for _ in range(TIQUES_POR_CONFERENCIA):
            sistema.tique()
        assert coberturas(publicados)[-1] is True
    finally:
        controlador.encerrar()


# ---------------------------------------------------------------------------
# Win32 real (só Windows)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="só no Windows")
def test_sistema_win32_cria_e_consulta_sem_erro():
    sistema = camada_fundo.SistemaWin32Fundo()
    sistema.janela_em_primeiro_plano()  # pode ser None (sessão sem área de trabalho)
    assert sistema.raiz(None) is None


@pytest.mark.skipif(sys.platform != "win32", reason="só no Windows")
def test_vigia_real_instala_gancho_e_encerra():
    sistema = camada_fundo.SistemaWin32Fundo()
    vigia = VigiaPrimeiroPlano(sistema, lambda _h: None)
    assert vigia.iniciar() is True
    vigia.parar()
    assert not vigia.ativa


@pytest.mark.skipif(sys.platform != "win32", reason="só no Windows")
def test_cobertura_e_ocio_reais_e_ganchos_de_pilha():
    sistema = camada_fundo.SistemaWin32Fundo()
    vigia = VigiaPrimeiroPlano(sistema, lambda _h: None, lambda: None, 50, lambda: None)
    assert vigia.iniciar() is True
    try:
        assert 0 <= sistema.ocioso_ms() < 2**32
        primeiro = sistema.janela_em_primeiro_plano()
        if primeiro:
            proprio, cobertores = sistema.estado_de_cobertura(primeiro)
            assert proprio is None or (proprio[0] < proprio[2] and proprio[1] < proprio[3])
            assert all(e < d and t < b for e, t, d, b in cobertores)
    finally:
        vigia.parar()


@pytest.mark.skipif(sys.platform != "win32", reason="só no Windows")
def test_tique_real_continua_com_a_fila_cheia():
    """O tique não pode vir de WM_TIMER: ele só sai da fila quando ela está vazia e, com
    mensagens chegando sem parar, nunca viria (cobertura e ausência paradas)."""
    sistema = camada_fundo.SistemaWin32Fundo()
    tiques: list[float] = []
    vigia = VigiaPrimeiroPlano(sistema, lambda _h: None, lambda: tiques.append(time.monotonic()), 50)
    assert vigia.iniciar() is True
    try:
        fim = time.monotonic() + 1.0
        while time.monotonic() < fim:
            for _ in range(200):
                sistema._u.PostThreadMessageW(vigia._id_thread, 0x0400, 0, 0)  # WM_USER
            time.sleep(0.001)
        assert len(tiques) >= 10, f"só {len(tiques)} tiques em 1 s de fila cheia (esperado ~20)"
    finally:
        vigia.parar()
    assert not vigia.ativa
