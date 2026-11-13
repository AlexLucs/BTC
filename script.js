'use strict';

// Depende de regras.js (TIPO, PROXIMO_TIPO, normalizarLista, ...) e de metricas.js
// (Metricas), carregados antes.

Metricas.marcar('script_inicio');
Metricas.observar();

// ---------------------------------------------------------------------------
// Ambiente e endpoints
// ---------------------------------------------------------------------------
const isPyWebView = navigator.userAgent.includes('pywebview');

// Um único pedido traz os dois pares (na Binance, "symbols" com 1 a 20 pares pesa 2,
// o mesmo que um par só).
const SIMBOLO_BRL = 'BTCBRL';
const SIMBOLO_USDT = 'BTCUSDT';
const URL_TICKERS = `https://api.binance.com/api/v3/ticker/24hr?symbols=${encodeURIComponent(JSON.stringify([SIMBOLO_BRL, SIMBOLO_USDT]))}`;
// WebSocket da Binance (stream combinado <par>@ticker): preço a cada ~1 s, sem requisições.
// O REST acima busca o 1º preço na abertura e serve de reserva quando o WebSocket cai.
const URL_WS_TICKERS = `wss://stream.binance.com:9443/stream?streams=${[SIMBOLO_BRL, SIMBOLO_USDT].map(par => `${par.toLowerCase()}@ticker`).join('/')}`;
const URL_USD_BRL = 'https://economia.awesomeapi.com.br/json/last/USD-BRL';
const URL_TAXAS = 'https://mempool.space/api/v1/fees/precise';

const CHAVE_ALERTAS = 'alertasjson';
const CHAVE_ESTADO = 'ultimoEstado';     // último estado exibido (ver "Último estado salvo")
const CHAVE_COMPACTO = 'modoCompacto';   // só no navegador; no app, o modo fica no .ini (Python)
const CAMPOS_TAXA = ['fastestFee', 'halfHourFee', 'hourFee', 'minimumFee'];

// ---------------------------------------------------------------------------
// Tempos (ms). Cada ciclo espera "mínimo + aleatório(0..variação)" entre as
// atualizações, para não sincronizar picos de requisição.
// ---------------------------------------------------------------------------
const PRECO_INTERVALO_MIN = 3000;
const PRECO_INTERVALO_VARIACAO = 3000;
const TAXAS_INTERVALO_MIN = 50000;
const TAXAS_INTERVALO_VARIACAO = 20000;
// A AwesomeAPI sem chave mantém cache de 1 min e tem cota mensal: consultar mais
// que isso só gasta cota.
const DOLAR_INTERVALO_MIN = 60000;
const DOLAR_INTERVALO_VARIACAO = 10000;

const WS_LIMITE_SILENCIO = 10000;  // nenhuma mensagem (BRL ou USDT) por 10 s: conexão considerada perdida
const WS_RECONEXAO_MIN = 1000;     // espera da 1ª reconexão; dobra a cada tentativa
const WS_RECONEXAO_MAX = 60000;
const TIMEOUT_REQUISICAO = 8000;
const TIMEOUT_API_PYTHON = 5000;
const ATRASO_CHECAGEM_ALARMES = 1000;
const SILENCIO_PADRAO = 15000;
const SILENCIO_APOS_CARREGAR = 5000;
const LIMITE_INATIVIDADE = 1000 * 1000; // ~17 min sem mouse/teclado pausa o monitoramento
const INTERVALO_VERIFICAR_INATIVIDADE = 1000;
const INTERVALO_SALVAR_ESTADO = 30000;  // no máximo uma gravação do último estado a cada 30 s
const ESPERA_OCIOSA_GRAFICO = 300;      // prazo máximo do requestIdleCallback que monta o gráfico
// Geometria do gráfico: o quadro (fundo preto opaco) cobre a tabela de máximas/mínimas/
// taxas com SOBRA_GRAFICO px a mais de cada lado. A borda de cima fica sobre a linha
// separadora da tabela, então a distância até a data e hora é a mesma de sem o gráfico.
// A altura segue a proporção original do widget (310/440), mas nunca termina antes da
// tabela nem passa do fim da janela. O widget usa "autosize" e preenche o quadro.
const PROPORCAO_GRAFICO = 310 / 440;
const SOBRA_GRAFICO = 2;
const INTERVALO_RELATORIO_METRICAS = 5 * 60 * 1000;
const ESPERA_MAX_RELATORIO_ABERTURA = 15000; // após o 1º preço, se o gráfico não carregar antes
const MAX_FALHAS = 10;             // falhas seguidas da cotação BTC/BRL antes de pausar (só sem alertas cadastrados)
// Falhas seguidas da fonte de um campo em que o último valor (salvo ou novo) continua na tela.
// Vale para todos: preço BRL e USDT (Binance), dólar comercial (AwesomeAPI) e taxas (mempool.space).
// Sem nenhum valor na tela (1ª execução), a 1ª falha já mostra "Sem Dados".
const CICLOS_ANTES_SEM_DADOS = 3;

// ---------------------------------------------------------------------------
// Formatadores (criados uma vez só)
// ---------------------------------------------------------------------------
const formatoBRL = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const formatoUSD = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'USD' });
const formatoTaxa = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const formatoData = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit' });
const formatoHora = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

// O espaço antes da seta e a largura dela vêm do style.css (#info-seta), não do texto.
const SETA_POR_DIRECAO = { [-1]: '↓', 0: '↔', 1: '↑' };
const SEM_VALOR = '—';
// Web Animations API: reinicia o "surgimento" da seta sem forçar reflow.
const ANIMACAO_SETA = [{ opacity: 0 }, { opacity: 1 }];
const DURACAO_ANIMACAO_SETA = 1000;

// ---------------------------------------------------------------------------
// Estado
// ---------------------------------------------------------------------------
let ativo = false;
let pausaManual = false;          // pausa pelo botão ou por falhas: só retoma com clique
let geracaoCiclo = 0;             // invalida respostas de ciclos já encerrados
let controleCiclo = new AbortController(); // cancela as requisições em andamento ao pausar
let carregado = false;            // já chegou o 1º preço novo
let conteudoVisivel = false;      // a tela de carregamento já saiu (estado salvo ou 1º preço)
let exibindoEstadoSalvo = false;  // a tela mostra o último estado salvo, ainda sem dados novos
let estadoAtual = null;           // último estado com dados novos, para gravar
let ultimaGravacaoEstado = 0;

// Últimos valores válidos. Continuam na tela por CICLOS_ANTES_SEM_DADOS falhas.
let ultimoPrecoBRL = NaN;
let ultimoPrecoUSD = NaN;
let ultimaCotacaoDolar = NaN;
let precoAnterior = NaN;          // referência da seta de direção
let falhasBRL = 0;
let falhasUSD = 0;
let falhasDolar = 0;
let falhasTaxas = 0;
// Valores na tela (salvos ou novos; NaN/false em "Sem Dados"). Só para exibição: o estado
// salvo nunca entra nos alarmes, que usam ultimoPrecoBRL.
let precoBRLExibido = NaN;
let precoUSDExibido = NaN;
let taxasNaTela = false;
// Grupos de campos que ainda mostram o valor do estado salvo: ficam esmaecidos até a fonte
// deles responder (ou até virarem "Sem Dados"). Ver marcarSalvo/marcarAtualizado.
const gruposSalvos = new Set();

let ws = null;                    // conexão atual com o stream da Binance
let wsSaudavel = false;           // recebendo BTC/BRL pelo WebSocket: o polling REST fica parado
let wsTentativas = 0;             // reconexões seguidas sem receber preço (define a espera)
let cadeiaRestAtiva = false;      // há uma consulta REST de preço agendada ou em andamento
let ultimaMensagemBRL = 0;        // performance.now() da última mensagem de BTC/BRL pelo WebSocket

let alertas = [];                 // lista em memória (normalizada e ordenada): fonte da verdade no JS
let alarmesSilenciados = false;
let alertaAberto = false;
let audioAlerta = null;

let graficoVisivel = false;       // escolha do usuário pelo botão ⇄ (padrão: atributo "hidden" de #grafico no HTML)
let compacto = false;             // modo compacto: classe "compacto" no <html> (no app, vem do servidor local na abertura)
let filaCompacto = Promise.resolve(); // pedidos de redimensionamento ao Python, na ordem dos cliques
let fixado = false;
let monitorarInatividade = true;  // desligado enquanto a janela está fixada no topo
let ultimaInteracao = Date.now();
// Um alarme disparou e ainda não houve atividade depois dele: a inatividade não pausa até o
// usuário voltar (e só conta os ~17 min a partir dessa atividade).
let alarmeSemAtividade = false;

let wakeLock = null;
let pedindoWakeLock = false;

const timers = { preco: 0, taxas: 0, dolar: 0, alarmes: 0, silencio: 0, wsVigia: 0, wsReconexao: 0 };

const el = id => document.getElementById(id);

/** Elementos usados com frequência, capturados uma vez no carregamento. */
let ui = null;

function capturarElementos() {
	ui = {
		preco: el('info-price'),
		usdt: el('info-usdt'),
		dolarImplicito: el('dolar-implicito'),
		dolarComercial: el('dolar-comercial'),
		percentual: el('info-percent'),
		seta: el('info-seta'),
		horario: el('info-time'),
		maxima: el('highPrice'),
		minima: el('lowPrice'),
		faixaMaxima: el('faixaMaxima'),
		faixaMinima: el('faixaMinima'),
		maximaUSD: el('highPriceDol'),
		minimaUSD: el('lowPriceDol'),
		taxas: Object.fromEntries(CAMPOS_TAXA.map(campo => [campo, el(campo)])),
		overlay: el('overlay'),
		grafico: el('grafico'),
		tabelaInfo: document.querySelector('.bottom-left-info table'),
		separadorInfo: document.querySelector('.bottom-left-info .separator'),
		graficoModelo: el('grafico-modelo'),
		modal: el('modalAlerta'),
		darkback: el('darkback'),
		campoValor: el('valorAlerta'),
		corpoTabela: el('alertasTabela').tBodies[0],
	};
	ui.grupos = {
		brl: [ui.preco, ui.horario, document.querySelector('.percentual'), ui.maxima, ui.minima, ui.faixaMaxima, ui.faixaMinima],
		usdt: [ui.usdt, ui.maximaUSD, ui.minimaUSD],
		dolarImplicito: [ui.dolarImplicito],
		dolarComercial: [ui.dolarComercial],
		taxas: Object.values(ui.taxas),
	};
}

/** O grupo passa a mostrar o valor do estado salvo (esmaecido). */
function marcarSalvo(grupo) {
	gruposSalvos.add(grupo);
	for (const elemento of ui.grupos[grupo]) elemento.classList.add('desatualizado');
}

/** A fonte do grupo respondeu (ou o grupo virou "Sem Dados"): sai o esmaecimento. */
function marcarAtualizado(grupo) {
	if (!gruposSalvos.delete(grupo)) return; // só mexe no DOM uma vez
	for (const elemento of ui.grupos[grupo]) elemento.classList.remove('desatualizado');
}

/** Só altera o DOM quando o texto muda (atribuir textContent sempre invalida o layout). */
function definirTexto(elemento, texto) {
	if (elemento.textContent !== texto) elemento.textContent = texto;
}

// ---------------------------------------------------------------------------
// Rede
// ---------------------------------------------------------------------------

/** Sinal que aborta por timeout ou quando o monitoramento é pausado. */
function sinalRequisicao() {
	const limite = AbortSignal.timeout(TIMEOUT_REQUISICAO);
	return typeof AbortSignal.any === 'function' ? AbortSignal.any([controleCiclo.signal, limite]) : limite;
}

async function buscarJSON(url) {
	const resposta = await fetch(url, { signal: sinalRequisicao(), cache: 'no-store' });
	if (!resposta.ok) throw new Error(`HTTP ${resposta.status} em ${url}`);
	return resposta.json();
}

function paraNumero(valor, campo) {
	const numero = parseFloat(valor);
	if (!Number.isFinite(numero)) throw new Error(`Campo "${campo}" inválido: ${valor}`);
	return numero;
}

function lerTicker(dados) {
	return {
		preco: paraNumero(dados.lastPrice, 'lastPrice'),
		variacao: paraNumero(dados.priceChangePercent, 'priceChangePercent'),
		maxima: paraNumero(dados.highPrice, 'highPrice'),
		minima: paraNumero(dados.lowPrice, 'lowPrice'),
	};
}

/** Lê o ticker de uma mensagem do WebSocket (campos c, P, h, l da Binance). */
function lerTickerWs(dados) {
	return {
		preco: paraNumero(dados.c, 'c'),
		variacao: paraNumero(dados.P, 'P'),
		maxima: paraNumero(dados.h, 'h'),
		minima: paraNumero(dados.l, 'l'),
	};
}

/**
 * Extrai um par da resposta da Binance. Um campo inválido afeta só aquele par.
 * @returns {{ticker?: object, erro?: Error}}
 */
function extrairTicker(porSimbolo, simbolo, erroRede) {
	if (erroRede) return { erro: erroRede };
	const dados = porSimbolo.get(simbolo);
	if (!dados) return { erro: new Error(`Par ${simbolo} ausente na resposta da Binance`) };
	try {
		return { ticker: lerTicker(dados) };
	} catch (erro) {
		return { erro };
	}
}

// ---------------------------------------------------------------------------
// Ciclos de atualização (cadeias de setTimeout: a próxima execução só é
// agendada quando a atual termina, então requisições nunca se sobrepõem)
// ---------------------------------------------------------------------------

function cicloAtual(geracao) {
	return ativo && geracao === geracaoCiclo;
}

function agendar(nome, funcao, minimo, variacao, geracao) {
	clearTimeout(timers[nome]);
	const espera = minimo + Math.floor(Math.random() * (variacao + 1));
	const previsto = performance.now() + espera;
	timers[nome] = setTimeout(() => {
		// Atraso em relação ao previsto: revela timers estrangulados (ex.: janela minimizada).
		Metricas.registrar(`atraso_timer:${nome}`, performance.now() - previsto, { comTempo: true });
		funcao(geracao);
	}, espera);
}

function iniciarCiclos() {
	ativo = true;
	const geracao = ++geracaoCiclo;
	controleCiclo = new AbortController();
	adquirirWakeLock();
	cadeiaRestAtiva = true;
	atualizarPrecos(geracao); // REST: 1º preço rápido
	conectarWebSocket(geracao);
	atualizarTaxas(geracao);
	atualizarDolar(geracao);
}

function pararCiclos() {
	ativo = false;
	geracaoCiclo++;
	controleCiclo.abort();
	fecharWebSocket();
	wsTentativas = 0;
	cadeiaRestAtiva = false;
	for (const nome of ['preco', 'taxas', 'dolar', 'alarmes', 'wsReconexao']) {
		clearTimeout(timers[nome]);
		timers[nome] = 0;
	}
	liberarWakeLock();
}

// No app, o Python pede o 1º preço logo ao abrir, antes de a página existir
// (primeiro_preco.py). O servidor local (servidor_local.py) o entrega dentro do HTML, num
// bloco de dados, se já o tiver quando a página é pedida; senão, em /preco-inicial. Assim o
// preço não depende do "load" nem da ponte do pywebview. Vale só para a 1ª consulta.
const ID_PRECO_NO_HTML = 'preco-inicial';
const URL_PRECO_INICIAL = '/preco-inicial';
let precoPythonPendente = isPyWebView && location.protocol === 'http:';

/** Preço que o servidor local pôs no HTML (lido uma vez; o bloco sai da página). */
function lerPrecoNoHtml() {
	const bloco = document.getElementById(ID_PRECO_NO_HTML);
	if (!bloco) return null;
	bloco.remove();
	try {
		const dados = JSON.parse(bloco.textContent);
		return Array.isArray(dados) ? dados : null;
	} catch {
		return null;
	}
}

async function buscarPrecoInicial() {
	Metricas.marcar('preco_inicial_pedido');
	const resposta = await fetch(URL_PRECO_INICIAL, { signal: sinalRequisicao(), cache: 'no-store' });
	Metricas.marcar('preco_inicial_resposta');
	if (resposta.status !== 200) throw new Error(`O Python não tem o 1º preço (HTTP ${resposta.status})`);
	const dados = await resposta.json();
	Metricas.marcar('preco_inicial_dados');
	if (!Array.isArray(dados)) throw new Error('1º preço do Python em formato inesperado');
	return dados;
}

/**
 * Tickers da Binance pelo REST. Na 1ª consulta do app, usa o preço que o Python pôs no
 * HTML; sem ele, corre /preco-inicial contra o REST e usa o que chegar antes (se os dois
 * falharem, vale o erro do REST).
 */
function buscarTickers() {
	if (!precoPythonPendente) return buscarJSON(URL_TICKERS);
	precoPythonPendente = false;
	const noHtml = lerPrecoNoHtml();
	if (noHtml) {
		// Recém-buscado pelo Python: não precisa de REST nem de /preco-inicial.
		Metricas.marcar('preco_no_html');
		Metricas.contar('primeiro_preco:html');
		return Promise.resolve(noHtml);
	}
	const rest = buscarJSON(URL_TICKERS);
	const peloPython = buscarPrecoInicial().then(dados => ({ origem: 'python', dados }));
	const peloRest = rest.then(dados => ({ origem: 'rest', dados }));
	return Promise.any([peloPython, peloRest]).then(
		({ origem, dados }) => {
			Metricas.contar(`primeiro_preco:${origem}`);
			return dados;
		},
		() => rest,
	);
}

async function atualizarPrecos(geracao) {
	const inicio = performance.now();
	let porSimbolo = null;
	let erroRede = null;
	try {
		const dados = await buscarTickers();
		Metricas.marcar('precos_continuacao'); // o código volta a rodar com os dados em mãos
		if (!Array.isArray(dados)) throw new Error('Resposta da Binance não é uma lista');
		porSimbolo = new Map(dados.map(item => [item?.symbol, item]));
	} catch (erro) {
		erroRede = erro;
	}
	if (!cicloAtual(geracao)) return; // pausado enquanto esperava a resposta
	const fimRede = performance.now();
	Metricas.registrar('espera:precos', fimRede - inicio);
	Metricas.marcar('primeira_resposta_binance');
	if (erroRede) Metricas.contar('falha:binance');
	processarPrecos(geracao, porSimbolo, erroRede);
	Metricas.registrar('processamento:precos', performance.now() - fimRede);
}

function processarPrecos(geracao, porSimbolo, erroRede) {
	// O WebSocket assumiu enquanto esta consulta estava em andamento: os dados dele são mais novos.
	if (wsSaudavel) {
		cadeiaRestAtiva = false;
		return;
	}
	const brl = extrairTicker(porSimbolo, SIMBOLO_BRL, erroRede);
	const usd = extrairTicker(porSimbolo, SIMBOLO_USDT, erroRede);

	if (brl.ticker) Metricas.medir('render:brl', () => aplicarBRL(brl.ticker));
	else registrarFalhaBRL(brl.erro);
	if (usd.ticker) aplicarUSD(usd.ticker);
	else registrarFalhaUSD(usd.erro);
	depoisDeAtualizarPrecos(geracao, { ...(brl.ticker && { brl: brl.ticker }), ...(usd.ticker && { usdt: usd.ticker }) });

	// Com alertas cadastrados nunca pausa: quando a internet voltar, os alertas precisam
	// estar sendo checados. O preço já mostra "Sem Dados" e o ciclo segue tentando.
	if (falhasBRL >= MAX_FALHAS && alertas.length === 0) {
		console.warn(`${MAX_FALHAS} falhas consecutivas: pausando monitoramento.`);
		pausar(true);
		return;
	}
	agendar('preco', atualizarPrecos, PRECO_INTERVALO_MIN, PRECO_INTERVALO_VARIACAO, geracao);
}

function aplicarBRL(ticker) {
	falhasBRL = 0;
	ultimoPrecoBRL = ticker.preco;
	exibirBRL(ticker);
}

function aplicarUSD(ticker) {
	falhasUSD = 0;
	ultimoPrecoUSD = ticker.preco;
	exibirUSD(ticker);
}

function registrarFalhaBRL(erro) {
	console.error('Erro ao buscar BTC/BRL na Binance:', erro);
	Metricas.contar('falha:brl');
	falhasBRL++;
	// Mantém o último preço na tela por alguns ciclos (inclusive o do estado salvo).
	if (falhasBRL >= CICLOS_ANTES_SEM_DADOS || !Number.isFinite(precoBRLExibido)) {
		ultimoPrecoBRL = NaN;
		exibirSemDadosBRL();
	}
}

function registrarFalhaUSD(erro) {
	console.error('Erro ao buscar BTC/USDT na Binance:', erro);
	Metricas.contar('falha:usdt');
	falhasUSD++;
	if (falhasUSD >= CICLOS_ANTES_SEM_DADOS || !Number.isFinite(precoUSDExibido)) {
		ultimoPrecoUSD = NaN;
		exibirSemDadosUSD();
	}
}

/** Passos comuns após qualquer atualização de preço (REST ou WebSocket). */
function depoisDeAtualizarPrecos(geracao, parteEstado) {
	exibirDolar();
	if (Object.keys(parteEstado).length) atualizarEstado(parteEstado);
	concluirCarregamento(); // antes de agendar os alarmes: o silêncio inicial já vale
	agendarChecagemAlarmes(geracao);
}

/** Checa os alarmes logo depois da atualização. Não reinicia um prazo pendente:
 *  pelo WebSocket chegam mensagens a cada ~1 s e o prazo nunca venceria. */
function agendarChecagemAlarmes(geracao) {
	if (timers.alarmes) return;
	timers.alarmes = setTimeout(() => {
		timers.alarmes = 0;
		if (cicloAtual(geracao)) checarAlarmes();
	}, ATRASO_CHECAGEM_ALARMES);
}

// ---------------------------------------------------------------------------
// WebSocket da Binance
//
// Depois do 1º BTC/BRL, o polling REST fica parado. Se a conexão fechar ou ficar
// WS_LIMITE_SILENCIO sem nenhuma mensagem (BRL ou USDT), o REST volta na hora e o app
// tenta reconectar com espera crescente (1 s, 2 s, 4 s... até 60 s, com variação
// aleatória). Pausar fecha a conexão; retomar abre de novo.
// ---------------------------------------------------------------------------

function conectarWebSocket(geracao) {
	if (!cicloAtual(geracao) || typeof WebSocket !== 'function') return;
	fecharWebSocket();
	Metricas.contar('ws:conexoes');
	let socket;
	try {
		socket = new WebSocket(URL_WS_TICKERS);
	} catch (erro) {
		console.warn('Não foi possível abrir o WebSocket da Binance:', erro);
		agendarReconexao(geracao);
		return;
	}
	ws = socket;
	const inicio = performance.now();
	socket.addEventListener('open', () => {
		if (ws !== socket) return;
		Metricas.registrar('ws:conexao', performance.now() - inicio);
		Metricas.marcar('ws_conectado');
		rearmarVigia(geracao); // aberto mas mudo também conta como perdido
	});
	socket.addEventListener('message', evento => {
		if (ws === socket && cicloAtual(geracao)) aoReceberMensagemWs(evento.data, geracao);
	});
	// "error" é sempre seguido de "close".
	socket.addEventListener('close', () => {
		if (ws === socket) perderWebSocket(geracao, 'fechado');
	});
}

function fecharWebSocket() {
	const socket = ws;
	ws = null;
	wsSaudavel = false;
	clearTimeout(timers.wsVigia);
	timers.wsVigia = 0;
	if (socket && socket.readyState <= WebSocket.OPEN) socket.close();
}

/** A conexão caiu ou ficou muda: volta ao REST e agenda uma nova tentativa. */
function perderWebSocket(geracao, motivo) {
	fecharWebSocket();
	Metricas.contar(`ws:queda:${motivo}`);
	Metricas.evento('ws', { estado: motivo });
	if (!cicloAtual(geracao)) return;
	if (!cadeiaRestAtiva) {
		cadeiaRestAtiva = true;
		atualizarPrecos(geracao);
	}
	agendarReconexao(geracao);
}

function agendarReconexao(geracao) {
	const base = Math.min(WS_RECONEXAO_MAX, WS_RECONEXAO_MIN * 2 ** wsTentativas);
	const espera = Math.round(base * (0.5 + Math.random() / 2)); // variação para não sincronizar
	wsTentativas++;
	clearTimeout(timers.wsReconexao);
	timers.wsReconexao = setTimeout(() => {
		timers.wsReconexao = 0;
		conectarWebSocket(geracao);
	}, espera);
}

function rearmarVigia(geracao) {
	clearTimeout(timers.wsVigia);
	timers.wsVigia = setTimeout(() => perderWebSocket(geracao, 'silencio'), WS_LIMITE_SILENCIO);
}

function aoReceberMensagemWs(texto, geracao) {
	let dados;
	let ticker;
	try {
		dados = JSON.parse(texto).data;
		ticker = lerTickerWs(dados);
	} catch (erro) {
		Metricas.contar('ws:mensagem_invalida');
		console.warn('Mensagem inválida do WebSocket:', erro);
		return;
	}
	const inicio = performance.now();
	Metricas.contar('ws:mensagens');
	if (Number.isFinite(dados.E)) Metricas.registrar('ws:idade_evento', Date.now() - dados.E); // inclui diferença de relógio

	if (dados.s !== SIMBOLO_BRL && dados.s !== SIMBOLO_USDT) return;
	// Qualquer par mantém a conexão viva: o BTC/BRL tem pouca negociação e a Binance só
	// envia o ticker quando algo muda (silêncios de 5 a 16 s são normais). O BTC/USDT
	// chega a cada ~1 s; se os dois calarem por WS_LIMITE_SILENCIO, a conexão caiu.
	rearmarVigia(geracao);
	wsTentativas = 0;

	if (dados.s === SIMBOLO_BRL) {
		if (ultimaMensagemBRL) Metricas.registrar('ws:intervalo_brl', inicio - ultimaMensagemBRL);
		ultimaMensagemBRL = inicio;
		// O polling REST só para quando chega o 1º BTC/BRL (é ele que dispara os alarmes).
		if (!wsSaudavel) {
			wsSaudavel = true;
			Metricas.marcar('ws_primeiro_preco');
			Metricas.evento('ws', { estado: 'recebendo' });
			clearTimeout(timers.preco); // o polling REST para; a consulta em andamento é descartada
			timers.preco = 0;
			cadeiaRestAtiva = false;
		}
		Metricas.medir('render:brl', () => aplicarBRL(ticker));
		depoisDeAtualizarPrecos(geracao, { brl: ticker });
	} else {
		aplicarUSD(ticker);
		depoisDeAtualizarPrecos(geracao, { usdt: ticker });
	}
	Metricas.registrar('processamento:ws', performance.now() - inicio);
}

async function atualizarDolar(geracao) {
	const inicio = performance.now();
	let cotacao = NaN;
	let falha = null;
	try {
		const dados = await buscarJSON(URL_USD_BRL);
		const compra = paraNumero(dados.USDBRL?.bid, 'USDBRL.bid');
		const venda = paraNumero(dados.USDBRL?.ask, 'USDBRL.ask');
		cotacao = (compra + venda) / 2;
	} catch (erro) {
		falha = erro;
	}
	if (!cicloAtual(geracao)) return;
	Metricas.registrar('ciclo:dolar', performance.now() - inicio);
	if (falha) {
		console.error('Erro ao buscar USD/BRL na AwesomeAPI:', falha);
		Metricas.contar('falha:dolar');
		falhasDolar++;
		// Mantém a última cotação (salva ou nova) por alguns ciclos, como o preço.
		if (falhasDolar >= CICLOS_ANTES_SEM_DADOS || !Number.isFinite(ultimaCotacaoDolar)) {
			ultimaCotacaoDolar = NaN;
			marcarAtualizado('dolarComercial');
		}
	} else {
		falhasDolar = 0;
		ultimaCotacaoDolar = cotacao;
		marcarAtualizado('dolarComercial');
		atualizarEstado({ dolar: cotacao });
	}
	exibirDolar();
	agendar('dolar', atualizarDolar, DOLAR_INTERVALO_MIN, DOLAR_INTERVALO_VARIACAO, geracao);
}

async function atualizarTaxas(geracao) {
	const inicio = performance.now();
	let valores = null;
	let falha = null;
	try {
		const dados = await buscarJSON(URL_TAXAS);
		// Valida todos os campos antes de escrever: nunca deixa a tela meio atualizada.
		valores = CAMPOS_TAXA.map(campo => paraNumero(dados[campo], campo));
	} catch (erro) {
		falha = erro;
	}
	if (!cicloAtual(geracao)) return;
	Metricas.registrar('ciclo:taxas', performance.now() - inicio);
	if (falha) {
		console.error('Erro ao buscar taxas na mempool.space:', falha);
		Metricas.contar('falha:taxas');
		falhasTaxas++;
		// Mantém as últimas taxas (salvas ou novas) por alguns ciclos, como o preço.
		if (falhasTaxas >= CICLOS_ANTES_SEM_DADOS || !taxasNaTela) exibirSemDadosTaxas();
	} else {
		falhasTaxas = 0;
		const taxas = Object.fromEntries(CAMPOS_TAXA.map((campo, indice) => [campo, valores[indice]]));
		exibirTaxas(taxas);
		atualizarEstado({ taxas });
	}
	agendar('taxas', atualizarTaxas, TAXAS_INTERVALO_MIN, TAXAS_INTERVALO_VARIACAO, geracao);
}

// ---------------------------------------------------------------------------
// Exibição
// ---------------------------------------------------------------------------

/** Máxima e mínima de 24 h em BRL: na tabela (modo completo) e no rodapé do modo compacto. */
function exibirMaximaMinimaBRL(maxima, minima) {
	definirTexto(ui.maxima, maxima);
	definirTexto(ui.minima, minima);
	definirTexto(ui.faixaMaxima, maxima);
	definirTexto(ui.faixaMinima, minima);
}

function exibirBRL({ preco, variacao, maxima, minima }) {
	const precoFormatado = formatoBRL.format(preco);
	const variacaoFormatada = `${variacao.toFixed(2)}%`;
	const agora = new Date();

	// No app o título nativo não acompanha o document.title (sempre "BTC Status").
	if (!isPyWebView) document.title = `${precoFormatado} | ${variacaoFormatada}`;
	sairDoEstadoSalvo();
	precoBRLExibido = preco;
	definirTexto(ui.preco, precoFormatado);
	exibirMaximaMinimaBRL(formatoBRL.format(maxima), formatoBRL.format(minima));
	definirTexto(ui.horario, `${formatoData.format(agora)} - ${formatoHora.format(agora)}`);
	definirTexto(ui.percentual, variacaoFormatada);

	// A seta mostra a direção da última MUDANÇA de preço: com o WebSocket chegam
	// atualizações a cada ~1 s e o preço muitas vezes se repete; nesse caso a seta fica.
	const direcao = direcaoPreco(precoAnterior, preco);
	precoAnterior = preco;
	if (direcao === 0 && ui.seta.textContent !== '') return;
	ui.seta.classList.toggle('seta-neutra', direcao === 0);
	ui.seta.textContent = SETA_POR_DIRECAO[direcao];
	ui.seta.animate(ANIMACAO_SETA, DURACAO_ANIMACAO_SETA);
}

function exibirSemDadosBRL() {
	if (!isPyWebView) document.title = 'Sem Dados';
	sairDoEstadoSalvo();
	precoBRLExibido = NaN;
	definirTexto(ui.preco, '▶Sem Dados◀');
	exibirMaximaMinimaBRL(SEM_VALOR, SEM_VALOR);
	definirTexto(ui.percentual, SEM_VALOR);
	ui.seta.textContent = '';
	precoAnterior = NaN; // ao voltar, a seta recomeça neutra
}

function exibirUSD({ preco, maxima, minima }) {
	precoUSDExibido = preco;
	marcarAtualizado('usdt');
	definirTexto(ui.usdt, formatoUSD.format(preco));
	definirTexto(ui.maximaUSD, formatoUSD.format(maxima));
	definirTexto(ui.minimaUSD, formatoUSD.format(minima));
}

function exibirSemDadosUSD() {
	precoUSDExibido = NaN;
	marcarAtualizado('usdt');
	definirTexto(ui.usdt, 'Sem Dados');
	definirTexto(ui.maximaUSD, SEM_VALOR);
	definirTexto(ui.minimaUSD, SEM_VALOR);
}

/**
 * Mostra "dólar implícito (BTC/BRL ÷ BTC/USDT) | dólar comercial", com os valores que estão
 * na tela (salvos ou novos). O implícito só deixa de estar esmaecido quando BRL e USDT
 * já são novos (ou quando vira "Sem Dados").
 */
function exibirDolar() {
	const formatar = valor => (Number.isFinite(valor) ? formatoBRL.format(valor) : 'Sem Dados');
	const implicito = precoBRLExibido / precoUSDExibido;
	definirTexto(ui.dolarImplicito, formatar(implicito));
	definirTexto(ui.dolarComercial, formatar(ultimaCotacaoDolar));
	if (!Number.isFinite(implicito) || (!gruposSalvos.has('brl') && !gruposSalvos.has('usdt'))) {
		marcarAtualizado('dolarImplicito');
	}
}

function exibirTaxas(taxas) {
	taxasNaTela = true;
	marcarAtualizado('taxas');
	for (const campo of CAMPOS_TAXA) definirTexto(ui.taxas[campo], `${formatoTaxa.format(taxas[campo])} sat/vB`);
}

function exibirSemDadosTaxas() {
	taxasNaTela = false;
	marcarAtualizado('taxas');
	for (const campo of CAMPOS_TAXA) definirTexto(ui.taxas[campo], SEM_VALOR);
}

/** Esconde a tela de carregamento (ao exibir o estado salvo ou a 1ª resposta de preço). */
function mostrarConteudo() {
	if (conteudoVisivel) return;
	conteudoVisivel = true;
	el('tela-carregamento').style.display = 'none';
	el('conteudo').style.display = 'block';
	Metricas.marcar('conteudo_visivel');
}

// ---------------------------------------------------------------------------
// Último estado salvo
//
// Ao abrir, a tela mostra os últimos valores recebidos (esmaecidos, com o horário
// em que foram salvos) até chegarem dados novos. Eles NUNCA entram nos alarmes:
// só os campos de texto são preenchidos; ultimoPrecoBRL continua NaN.
// No app, depende do perfil persistente do WebView2 (localStorage entre execuções).
// ---------------------------------------------------------------------------

function restaurarEstadoSalvo() {
	let estado;
	try {
		estado = validarEstadoSalvo(JSON.parse(localStorage.getItem(CHAVE_ESTADO) ?? 'null'));
	} catch (erro) {
		console.warn('Último estado salvo inválido:', erro);
		return;
	}
	if (!estado) return;
	estadoAtual = estado; // base para as próximas gravações
	Metricas.medir('render:estado_salvo', () => exibirEstadoSalvo(estado));
	Metricas.marcar('estado_restaurado');
	mostrarConteudo();
}

function exibirEstadoSalvo({ salvoEm, brl, usdt, dolar, taxas }) {
	exibindoEstadoSalvo = true;
	const salvo = new Date(salvoEm);

	if (!isPyWebView) document.title = `${formatoBRL.format(brl.preco)} (salvo)`;
	definirTexto(ui.preco, formatoBRL.format(brl.preco));
	exibirMaximaMinimaBRL(formatoBRL.format(brl.maxima), formatoBRL.format(brl.minima));
	definirTexto(ui.percentual, `${brl.variacao.toFixed(2)}%`);
	// Seta neutra já com o número: o 1º preço novo a mantém até o preço mudar (exibirBRL).
	ui.seta.classList.add('seta-neutra');
	ui.seta.textContent = SETA_POR_DIRECAO[0];
	definirTexto(ui.horario, `atualizando… (salvo em ${formatoData.format(salvo)} - ${formatoHora.format(salvo)})`);
	precoBRLExibido = brl.preco; // só exibição: ultimoPrecoBRL continua NaN
	marcarSalvo('brl');
	if (usdt) {
		exibirUSD(usdt);
		marcarSalvo('usdt');
	}
	// O dólar comercial salvo segue a mesma regra das falhas (só exibição).
	if (dolar !== null) ultimaCotacaoDolar = dolar;
	exibirDolar();
	if (Number.isFinite(precoBRLExibido / precoUSDExibido)) marcarSalvo('dolarImplicito');
	if (dolar !== null) marcarSalvo('dolarComercial');
	if (taxas) {
		exibirTaxas(taxas);
		marcarSalvo('taxas');
	}
}

/** Chamado quando chega dado novo de BRL (ou quando ele falha de vez). */
function sairDoEstadoSalvo() {
	if (!exibindoEstadoSalvo) return;
	exibindoEstadoSalvo = false;
	marcarAtualizado('brl');
}

/** Junta dados novos ao estado e grava (no máximo a cada INTERVALO_SALVAR_ESTADO). */
function atualizarEstado(parte) {
	estadoAtual = { ...(estadoAtual ?? {}), ...parte, versao: VERSAO_ESTADO };
	if (parte.brl) estadoAtual.salvoEm = Date.now();
	gravarEstado(false);
}

function gravarEstado(forcar) {
	if (!estadoAtual?.brl || !Number.isFinite(estadoAtual.salvoEm)) return;
	const agora = Date.now();
	if (!forcar && agora - ultimaGravacaoEstado < INTERVALO_SALVAR_ESTADO) return;
	ultimaGravacaoEstado = agora;
	try {
		localStorage.setItem(CHAVE_ESTADO, JSON.stringify(estadoAtual));
	} catch (erro) {
		console.warn('Não foi possível gravar o último estado:', erro);
	}
}

/** Fim do carregamento: chegou a 1ª resposta de preço (com ou sem sucesso). */
function concluirCarregamento() {
	if (carregado) return;
	carregado = true;
	mostrarConteudo();
	silenciarAlarmes(SILENCIO_APOS_CARREGAR); // evita disparo imediato ao abrir
	Metricas.marcar('primeiro_preco');
	enviarRelatorioAbertura(); // se a abertura já terminou (ver aberturaConcluida), o relatório sai agora
	setTimeout(() => enviarRelatorioAbertura(true), ESPERA_MAX_RELATORIO_ABERTURA);
	setInterval(() => enviarMetricas('periodico'), INTERVALO_RELATORIO_METRICAS);
}

// ---------------------------------------------------------------------------
// Métricas: envio dos relatórios ao Python (ver metricas.js)
// ---------------------------------------------------------------------------

let relatorioAberturaEnviado = false;

/** Envia o relatório do período. Fora do app, só mostra no console. */
async function enviarMetricas(motivo) {
	if (!Metricas.ATIVAS) return;
	const relatorio = Metricas.relatorio(motivo);
	if (isPyWebView) await chamarApi('registrar_metricas', relatorio);
	else console.info(`[métricas] ${motivo}`, relatorio);
}

let sincronizacaoAlertasConcluida = false; // no app, carregar_alerta já respondeu (ou falhou)

/**
 * A abertura terminou: o relatório pode ser montado. Metricas.relatorio zera os dados ao
 * montar, então tudo o que for marcado depois só aparece no relatório seguinte.
 * - gráfico visível: quando ele carrega;
 * - gráfico oculto, no app: quando os alertas foram lidos do disco (logo depois da ponte);
 * - gráfico oculto, no navegador: depois do "load".
 */
function aberturaConcluida() {
	if (graficoVisivel && !compacto) return 'grafico_carregado' in Metricas.marcos;
	return isPyWebView ? sincronizacaoAlertasConcluida : document.readyState === 'complete';
}

/** O relatório da abertura sai quando a abertura termina ou, no máximo, 15 s após o 1º preço. */
function enviarRelatorioAbertura(forcar = false) {
	if (relatorioAberturaEnviado || !carregado) return;
	if (!forcar && !aberturaConcluida()) return;
	relatorioAberturaEnviado = true;
	enviarMetricas('abertura');
}

// ---------------------------------------------------------------------------
// Gráfico (widget do TradingView)
// ---------------------------------------------------------------------------

/**
 * O widget só existe enquanto está visível e o monitoramento está ativo.
 * Ocultar ou pausar remove o iframe (para CPU, memória e rede); exibir clona de
 * novo o <template>, e o script do TradingView recria o gráfico.
 */
function atualizarGrafico() {
	const mostrar = graficoVisivel && ativo && !compacto;
	ui.grafico.style.display = mostrar ? 'flex' : 'none';
	ui.grafico.hidden = !mostrar; // mantém o atributo do HTML coerente com o que está na tela
	if (!mostrar) {
		observadorGrafico?.disconnect();
		ui.grafico.replaceChildren();
	} else if (!ui.grafico.firstElementChild) {
		posicionarGrafico();
		const inicio = performance.now();
		Metricas.contar('grafico:montagens');
		observarCargaGrafico(inicio);
		Metricas.medir('grafico:montar', () => ui.grafico.append(document.importNode(ui.graficoModelo.content, true)));
	}
}

let observadorGrafico = null;

/** Mede da montagem até o "load" do iframe criado pelo script do TradingView. */
function observarCargaGrafico(inicio) {
	observadorGrafico?.disconnect();
	observadorGrafico = new MutationObserver(() => {
		const iframe = ui.grafico.querySelector('iframe');
		if (!iframe) return;
		observadorGrafico.disconnect();
		iframe.addEventListener('load', () => {
			Metricas.registrar('grafico:montagem_ate_carga', performance.now() - inicio);
			Metricas.marcar('grafico_carregado');
			enviarRelatorioAbertura();
		}, { once: true });
	});
	observadorGrafico.observe(ui.grafico, { childList: true, subtree: true });
}

/** Põe o gráfico sobre a tabela de máximas/mínimas/taxas, cobrindo-a por inteiro. */
function posicionarGrafico() {
	const tabela = ui.tabelaInfo.getBoundingClientRect();
	if (tabela.width <= 0) return; // conteúdo ainda não exibido
	const topo = Math.round((ui.separadorInfo ?? ui.tabelaInfo).getBoundingClientRect().top);
	const esquerda = Math.floor(tabela.left - SOBRA_GRAFICO);
	const largura = Math.ceil(tabela.right + SOBRA_GRAFICO) - esquerda;
	const alturaMinima = Math.ceil(tabela.bottom + SOBRA_GRAFICO) - topo; // cobre até o fim da tabela
	const altura = Math.min(Math.max(Math.round(largura * PROPORCAO_GRAFICO), alturaMinima), window.innerHeight - topo);
	Object.assign(ui.grafico.style, { top: `${topo}px`, left: `${esquerda}px`, width: `${largura}px`, height: `${altura}px` });
}

let reposicionamentoPendente = false;

/**
 * Reposiciona no próximo quadro (várias mudanças seguidas viram um só cálculo).
 * Chamado pelo ResizeObserver do bloco de informações: a tabela desce quando os textos
 * acima dela são preenchidos (1º preço, "Sem Dados") e quando a janela muda de tamanho.
 */
function aoRedimensionar() {
	if (reposicionamentoPendente || !ui.grafico.firstElementChild) return;
	reposicionamentoPendente = true;
	requestAnimationFrame(() => {
		reposicionamentoPendente = false;
		if (ui.grafico.firstElementChild) posicionarGrafico();
	});
}

function alternarGrafico() {
	graficoVisivel = !graficoVisivel;
	atualizarGrafico();
}

// ---------------------------------------------------------------------------
// Modo compacto
//
// A classe "compacto" no <html> define o layout (style.css). No app, o Python
// também redimensiona a janela (definir_compacto) e guarda o modo no .ini; na
// abertura e no ↻, o servidor local já entrega o HTML com a classe. No navegador,
// só o layout muda e o modo fica no localStorage. A escolha do ⇄ é mantida: o gráfico sai
// no modo compacto e volta, se estava aberto, no modo completo.
// ---------------------------------------------------------------------------

function alternarCompacto() {
	compacto = !compacto;
	Metricas.evento('compacto', { ativo: compacto });
	aplicarCompacto();
	if (!isPyWebView) {
		gravarCompactoLocal(compacto);
		return;
	}
	const pedido = compacto;
	// Em fila: cada chamada da js_api roda numa thread do Python, e dois cliques
	// seguidos poderiam redimensionar a janela fora de ordem.
	filaCompacto = filaCompacto
		.then(() => chamarApi('definir_compacto', pedido)) // chamarApi nunca rejeita
		.then(resultado => {
			if (resultado !== true) console.warn('Falha ao redimensionar a janela para o modo', pedido ? 'compacto' : 'completo');
		});
}

/** No navegador, o modo fica no localStorage (no app, no .ini, pelo Python). */
function lerCompactoLocal() {
	try {
		return localStorage.getItem(CHAVE_COMPACTO) === '1';
	} catch (erro) {
		console.warn('Não foi possível ler o modo compacto salvo:', erro);
		return false;
	}
}

function gravarCompactoLocal(ativo) {
	try {
		localStorage.setItem(CHAVE_COMPACTO, ativo ? '1' : '0');
	} catch (erro) {
		console.warn('Não foi possível salvar o modo compacto:', erro);
	}
}

function aplicarCompacto() {
	document.documentElement.classList.toggle('compacto', compacto);
	atualizarBotaoCompacto();
	atualizarGrafico();
}

function atualizarBotaoCompacto() {
	const botao = el('compacto-btn');
	const rotulo = compacto ? 'Modo completo' : 'Modo compacto';
	botao.textContent = compacto ? '⊞' : '⊟';
	botao.title = rotulo;
	botao.setAttribute('aria-label', rotulo);
}

// ---------------------------------------------------------------------------
// Pausa, retomada e inatividade
// ---------------------------------------------------------------------------

function pausar(manual) {
	if (!ativo) return;
	pausaManual = manual;
	Metricas.evento('pausa', { manual });
	pararCiclos();
	ui.overlay.style.display = 'flex';
	atualizarBotaoPausa();
	atualizarGrafico();
}

function retomar({ silenciar }) {
	if (ativo) return;
	pausaManual = false;
	Metricas.evento('retomada', { silenciar });
	falhasBRL = 0;
	falhasUSD = 0;
	falhasDolar = 0;
	falhasTaxas = 0;
	ultimaInteracao = Date.now();
	ui.overlay.style.display = 'none';
	iniciarCiclos();
	if (silenciar) silenciarAlarmes();
	atualizarBotaoPausa();
	atualizarGrafico();
}

function pararIniciar() {
	if (ativo) pausar(true);
	else retomar({ silenciar: true });
}

function atualizarBotaoPausa() {
	const rotulo = ativo ? 'Pausar' : 'Retomar';
	const botao = el('pausar-btn');
	botao.title = rotulo;
	botao.setAttribute('aria-label', rotulo);
}

/** Conta como atividade sem retomar nada (os cliques têm as ações deles: ⏸, ■, OK...). */
function registrarAtividade() {
	ultimaInteracao = Date.now();
	alarmeSemAtividade = false;
}

function registrarInteracao() {
	registrarAtividade();
	if (!ativo && !pausaManual) retomar({ silenciar: false });
}

function verificarInatividade() {
	if (!ativo || !monitorarInatividade) return;
	// Com algum alerta ativo, nunca pausa: é com o usuário longe que o alerta mais importa.
	if (existeAlertaAtivo(alertas)) return;
	// Depois de um alarme, só volta a contar a partir da próxima atividade do usuário.
	if (alarmeSemAtividade) return;
	if (Date.now() - ultimaInteracao >= LIMITE_INATIVIDADE) pausar(false);
}

// ---------------------------------------------------------------------------
// WakeLock (impede o desligamento da tela enquanto monitora)
// ---------------------------------------------------------------------------

async function adquirirWakeLock() {
	if (!('wakeLock' in navigator) || wakeLock || pedindoWakeLock || document.visibilityState !== 'visible') return;
	pedindoWakeLock = true;
	try {
		const sentinela = await navigator.wakeLock.request('screen');
		if (!ativo) {
			sentinela.release().catch(() => {});
			return;
		}
		wakeLock = sentinela;
		sentinela.addEventListener('release', () => {
			if (wakeLock === sentinela) wakeLock = null;
		});
	} catch (erro) {
		console.warn('WakeLock não disponível:', erro);
	} finally {
		pedindoWakeLock = false;
	}
}

function liberarWakeLock() {
	const sentinela = wakeLock;
	wakeLock = null;
	if (sentinela) sentinela.release().catch(erro => console.warn('Erro ao liberar WakeLock:', erro));
}

// ---------------------------------------------------------------------------
// Ponte com o Python (pywebview)
// ---------------------------------------------------------------------------

let apiPython = null;

// A API só fica disponível depois do evento "pywebviewready".
const apiPronta = new Promise(resolve => {
	if (!isPyWebView) return;
	const pronta = () => {
		Metricas.marcar('api_python_pronta');
		apiPython = window.pywebview.api;
		resolve(apiPython);
	};
	if (typeof window.pywebview?.api?.carregar_alerta === 'function') pronta();
	else window.addEventListener('pywebviewready', pronta, { once: true });
});

/** Espera a API (até TIMEOUT_API_PYTHON) só enquanto ela ainda não está pronta. */
async function obterApi() {
	if (apiPython) return apiPython;
	let timer = 0;
	const limite = new Promise((_, rejeitar) => {
		timer = setTimeout(() => rejeitar(new Error('API pywebview indisponível')), TIMEOUT_API_PYTHON);
	});
	try {
		return await Promise.race([apiPronta, limite]);
	} finally {
		clearTimeout(timer);
	}
}

/** Chama um método Python. Retorna undefined fora do pywebview ou em caso de erro (nunca rejeita). */
async function chamarApi(metodo, ...argumentos) {
	if (!isPyWebView) return undefined;
	const inicio = performance.now();
	try {
		const api = await obterApi();
		return await api[metodo](...argumentos);
	} catch (erro) {
		Metricas.contar(`falha:python:${metodo}`);
		console.error(`Erro na chamada Python "${metodo}":`, erro);
		return undefined;
	} finally {
		// Ida e volta pela ponte do pywebview (inclui o tempo do método no Python).
		Metricas.registrar(`python:${metodo}`, performance.now() - inicio);
	}
}

// ---------------------------------------------------------------------------
// Controles da janela
// ---------------------------------------------------------------------------

async function reiniciar() {
	gravarEstado(true);
	await enviarMetricas('recarga');
	if (fixado) await chamarApi('definir_topo', false);
	location.reload();
}

async function alternarFixar() {
	const estado = await chamarApi('definir_topo', !fixado);
	if (typeof estado === 'boolean') aplicarEstadoFixado(estado);
}

async function sincronizarEstadoTopo() {
	const estado = await chamarApi('esta_no_topo');
	if (typeof estado === 'boolean') aplicarEstadoFixado(estado);
}

function aplicarEstadoFixado(estado) {
	fixado = estado;
	monitorarInatividade = !estado;
	ultimaInteracao = Date.now();
	const botao = el('fixar-btn');
	const rotulo = estado ? 'Desafixar' : 'Fixar no topo';
	botao.textContent = estado ? '▽' : '△';
	botao.title = rotulo;
	botao.setAttribute('aria-label', rotulo);
}

function configurarBotoesJanela() {
	if (isPyWebView) {
		for (const botao of document.querySelectorAll('.btns')) botao.style.display = 'flex';
		return;
	}
	// No navegador só fazem sentido Alertas, Gráfico, Modo compacto (só o layout) e Pausar
	// (os demais controlam a janela do app).
	const posicoes = {
		'alerta-btn': { left: '0px' },
		'grafico-btn': { left: '40px' },
		'pausar-btn': { left: 'unset', right: '0px' },
		'compacto-btn': { right: '40px' },
	};
	for (const [id, posicao] of Object.entries(posicoes)) {
		Object.assign(el(id).style, posicao, { display: 'flex' });
	}
}

/** Controles com ação própria ao pressionar: não arrastam a janela. */
const SELETOR_SEM_ARRASTE = 'button, input, select, textarea, a, label';

/** Clique na barra de rolagem de um elemento (ex.: lista de alertas), que não é arraste. */
function cliqueNaBarraDeRolagem(evento) {
	const alvo = evento.target;
	return (alvo.scrollHeight > alvo.clientHeight && evento.offsetX >= alvo.clientWidth)
		|| (alvo.scrollWidth > alvo.clientWidth && evento.offsetY >= alvo.clientHeight);
}

/**
 * Só no app: o botão principal pressionado na região de arrasto pede ao Python que mova a
 * janela até o botão ser solto, encaixando nas bordas da tela (bordas_janela.py). Os
 * controles e as barras de rolagem ficam de fora.
 */
function aoPressionarParaArrastar(evento) {
	if (evento.button !== 0) return;
	const alvo = evento.target;
	if (!(alvo instanceof Element) || !alvo.closest('.regiao-arraste')) return;
	if (alvo.closest(SELETOR_SEM_ARRASTE) || cliqueNaBarraDeRolagem(evento)) return;
	chamarApi('iniciar_arraste');
}

// ---------------------------------------------------------------------------
// Diálogo (substitui o jquery-confirm). Mensagens ficam em fila.
// ---------------------------------------------------------------------------

const filaDialogos = [];
let dialogoAtual = null;

/**
 * @param {{titulo: string, linhas: string[], autoFecharMs?: number, aoFechar?: Function}} opcoes
 */
function mostrarDialogo(opcoes) {
	filaDialogos.push(opcoes);
	if (!dialogoAtual) exibirProximoDialogo();
}

function aviso(titulo, mensagem, autoFecharMs = 0) {
	mostrarDialogo({ titulo, linhas: [mensagem], autoFecharMs });
}

function exibirProximoDialogo() {
	dialogoAtual = filaDialogos.shift() ?? null;
	if (!dialogoAtual) return;

	const dialogo = el('dialogo');
	el('dialogo-titulo').textContent = dialogoAtual.titulo;
	const conteudo = el('dialogo-conteudo');
	conteudo.replaceChildren();
	dialogoAtual.linhas.forEach((linha, indice) => {
		if (indice > 0) conteudo.append(document.createElement('br'));
		conteudo.append(linha); // texto puro: nunca interpretado como HTML
	});

	const botao = el('dialogo-ok');
	botao.textContent = 'OK';
	if (dialogoAtual.autoFecharMs > 0) {
		let restante = Math.ceil(dialogoAtual.autoFecharMs / 1000);
		botao.textContent = `OK (${restante})`;
		dialogoAtual.contagem = setInterval(() => {
			restante--;
			if (restante <= 0) dialogo.close();
			else botao.textContent = `OK (${restante})`;
		}, 1000);
	}
	dialogo.showModal();
	botao.focus();
}

function aoFecharDialogo() {
	const encerrado = dialogoAtual;
	clearInterval(encerrado?.contagem);
	try {
		encerrado?.aoFechar?.();
	} finally {
		exibirProximoDialogo();
	}
}

// ---------------------------------------------------------------------------
// Alertas: armazenamento
//
// A lista "alertas" em memória é a fonte da verdade no JS. Ela é normalizada
// uma única vez, ao carregar. No app a persistência é o Alertas.json (o
// localStorage do pywebview não sobrevive ao reinício); no navegador, o localStorage.
// ---------------------------------------------------------------------------

/** No navegador, carrega a lista do localStorage (no app, ver sincronizarAlertas). */
function carregarAlertasLocais() {
	let bruto;
	try {
		bruto = JSON.parse(localStorage.getItem(CHAVE_ALERTAS) ?? '[]');
	} catch (erro) {
		console.error('Alertas inválidos no localStorage:', erro);
		return;
	}
	const { alertas: lista, alterado } = normalizarLista(bruto);
	alertas = lista;
	if (alterado) gravarLocal(alertas);
}

function gravarLocal(lista) {
	try {
		localStorage.setItem(CHAVE_ALERTAS, JSON.stringify(lista));
	} catch (erro) {
		console.error('Erro ao gravar alertas no localStorage:', erro);
	}
}

// Gravações em disco em fila: a ordem de chegada ao Python é a ordem das mudanças.
let filaGravacao = Promise.resolve();

function persistirEmDisco(lista) {
	filaGravacao = filaGravacao
		.then(() => chamarApi('salvar_alerta', lista)) // chamarApi nunca rejeita
		.then(sucesso => {
			if (sucesso !== true) aviso('FALHA', 'Não foi possível salvar os alertas em disco.', 15000);
		});
}

/** Ordena, atualiza a lista em memória e persiste. As listas nunca são alteradas no lugar. */
function gravarAlertas(lista) {
	alertas = ordenarAlertas(lista);
	if (isPyWebView) persistirEmDisco(alertas);
	else gravarLocal(alertas);
}

/** No app, o arquivo em disco é a fonte da verdade. */
async function sincronizarAlertas() {
	try {
		const doDisco = await chamarApi('carregar_alerta');
		if (!Array.isArray(doDisco)) {
			// null = arquivo ilegível ou corrompido (o Python guarda uma cópia .bak); undefined = falha na chamada.
			if (doDisco === null) {
				aviso('FALHA', 'O arquivo de alertas estava corrompido. Uma cópia .bak foi salva em %APPDATA%\\btcstatus.');
			} else {
				aviso('FALHA', 'Não foi possível carregar os alertas salvos.');
			}
			return;
		}
		const { alertas: lista, alterado } = normalizarLista(doDisco);
		alertas = lista;
		Metricas.marcar('alertas_sincronizados');
		if (alterado) persistirEmDisco(alertas); // migração de formato antigo
		if (modalAlertaAberto()) renderizarTabelaAlertas();
	} finally {
		// Com ou sem sucesso: é o último passo da abertura no app (ver aberturaConcluida).
		sincronizacaoAlertasConcluida = true;
		enviarRelatorioAbertura();
	}
}

// ---------------------------------------------------------------------------
// Alertas: verificação e disparo
// ---------------------------------------------------------------------------

function silenciarAlarmes(duracao = SILENCIO_PADRAO) {
	alarmesSilenciados = true;
	clearTimeout(timers.silencio);
	timers.silencio = setTimeout(() => { alarmesSilenciados = false; }, duracao);
}

function checarAlarmes() {
	if (alarmesSilenciados || alertaAberto) return;
	// O preço mantido na tela durante falhas não dispara alarmes.
	const preco = falhasBRL === 0 ? ultimoPrecoBRL : NaN;
	const alerta = Metricas.medir('alarmes:checar', () => alertaParaDisparar(alertas, preco));
	if (alerta) dispararAlerta(alerta);
}

function dispararAlerta(alerta) {
	alertaAberto = true;
	alarmeSemAtividade = true;
	const mensagem = alerta.tipo === TIPO.MAIOR ? 'O Preço do Bitcoin superou' : 'O Preço do Bitcoin caiu abaixo de';
	mostrarDialogo({
		titulo: 'ALERTA',
		linhas: [mensagem, formatoBRL.format(alerta.valor)],
		aoFechar: () => {
			alertaAberto = false;
			const atualizada = desativarAposDisparo(alertas, alerta.id);
			if (atualizada === alertas) return; // o alerta foi apagado enquanto o diálogo estava aberto
			gravarAlertas(atualizada);
			if (modalAlertaAberto()) renderizarTabelaAlertas();
		},
	});
	tocarAlerta();
}

function tocarAlerta() {
	audioAlerta ??= new Audio('alerta.mp3');
	audioAlerta.currentTime = 0;
	audioAlerta.play().catch(() => aviso('FALHA', 'Falha ao reproduzir áudio.', 3000));
}

// ---------------------------------------------------------------------------
// Alertas: tela de cadastro
// ---------------------------------------------------------------------------

function modalAlertaAberto() {
	return ui.modal.style.display === 'block';
}

function alternarTelaAlerta() {
	const abrir = !modalAlertaAberto();
	ui.modal.style.display = abrir ? 'block' : 'none';
	ui.darkback.style.display = abrir ? 'flex' : 'none';
	if (abrir) renderizarTabelaAlertas();
	else ui.campoValor.value = '';
}

function criarAlerta() {
	const valor = converterValor(ui.campoValor.value);

	if (valor === null) {
		aviso('FALHA', 'Digite um número válido maior que zero.', 15000);
	} else if (existeDuplicado(alertas, valor, TIPO.MAIOR)) {
		aviso('FALHA', 'Existe um alerta com esse mesmo valor.', 15000);
	} else if (alertas.length >= MAX_ALERTAS) {
		aviso('FALHA', `Limite de ${MAX_ALERTAS} alertas atingido.`, 15000);
	} else {
		gravarAlertas([...alertas, { id: novoId(), valor, tipo: TIPO.MAIOR }]);
		silenciarAlarmes();
	}
	renderizarTabelaAlertas();
}

function apagarAlerta(id) {
	gravarAlertas(alertas.filter(a => a.id !== id));
	renderizarTabelaAlertas();
}

function alternarTipoAlerta(id) {
	const alvo = alertas.find(a => a.id === id);
	if (!alvo) return;

	const novoTipo = PROXIMO_TIPO[alvo.tipo];
	if (existeDuplicado(alertas, alvo.valor, novoTipo, id)) {
		aviso('FALHA', 'Existe um alerta com esse mesmo valor.', 5000);
		return;
	}
	gravarAlertas(alertas.map(a => (a.id === id ? { ...a, tipo: novoTipo } : a)));
	silenciarAlarmes();
	renderizarTabelaAlertas();
}

const ROTULO_TIPO = {
	[TIPO.MAIOR]: { texto: 'Maior △', dica: v => `Alertar quando BTC for maior que ${v}` },
	[TIPO.MENOR]: { texto: 'Menor ▽', dica: v => `Alertar quando BTC for menor que ${v}` },
	[TIPO.DESATIVADO]: { texto: 'Desativado', dica: () => 'Alarme desativado' },
};

function criarBotao(classe, acao, texto, dica) {
	const botao = document.createElement('button');
	botao.type = 'button';
	botao.className = `botao-padrao ${classe}`;
	botao.dataset.acao = acao;
	botao.textContent = texto;
	botao.title = dica;
	return botao;
}

function criarCelula(...filhos) {
	const celula = document.createElement('td');
	celula.append(...filhos);
	return celula;
}

function renderizarTabelaAlertas() {
	Metricas.medir('render:tabela_alertas', montarTabelaAlertas);
}

function montarTabelaAlertas() {
	const linhas = document.createDocumentFragment();

	for (const alerta of alertas) {
		const valorFormatado = formatoBRL.format(alerta.valor);
		const rotulo = ROTULO_TIPO[alerta.tipo];

		const botaoTipo = criarBotao('botaoTipo', 'tipo', rotulo.texto, rotulo.dica(valorFormatado));
		botaoTipo.classList.toggle('desativado', alerta.tipo === TIPO.DESATIVADO);
		const botaoApagar = criarBotao('botaoApagar', 'apagar', 'Apagar', `Apagar alarme ${valorFormatado}`);

		const celulaValor = criarCelula(valorFormatado);
		celulaValor.title = valorFormatado;

		const linha = document.createElement('tr');
		linha.dataset.id = alerta.id;
		linha.append(criarCelula(botaoTipo), celulaValor, criarCelula(botaoApagar));
		linhas.append(linha);
	}

	ui.corpoTabela.replaceChildren(linhas);

	ui.campoValor.value = '';
	if (modalAlertaAberto()) ui.campoValor.focus();
}

/** Um único listener para todos os botões da tabela (delegação de eventos). */
function aoClicarTabela(evento) {
	const botao = evento.target.closest('button[data-acao]');
	const id = botao?.closest('tr')?.dataset.id;
	if (!id) return;
	if (botao.dataset.acao === 'tipo') alternarTipoAlerta(id);
	else if (botao.dataset.acao === 'apagar') apagarAlerta(id);
}

function aoTeclarValorAlerta(evento) {
	if (!modalAlertaAberto()) return;
	if (evento.key === 'Enter') {
		evento.preventDefault();
		if (evento.target.value.trim() !== '') criarAlerta();
	} else if (evento.key === 'Escape') {
		alternarTelaAlerta();
	}
}

// ---------------------------------------------------------------------------
// Inicialização
// ---------------------------------------------------------------------------

function aposCarregarPagina() {
	audioAlerta ??= new Audio('alerta.mp3');
	audioAlerta.preload = 'auto';
	// No app, o gráfico espera também a ponte do Python: o script do TradingView
	// (tarefa longa de ~60 ms) atrasaria a injeção do pywebview, que vem logo após o "load".
	const montar = () => quandoOcioso(atualizarGrafico, ESPERA_OCIOSA_GRAFICO);
	if (isPyWebView) obterApi().catch(() => {}).finally(montar);
	else montar();
	enviarRelatorioAbertura(); // no navegador, a abertura termina no "load" (ver aberturaConcluida)
}

function quandoOcioso(funcao, prazoMs) {
	if (typeof requestIdleCallback === 'function') requestIdleCallback(() => funcao(), { timeout: prazoMs });
	else setTimeout(funcao, 0);
}

async function fecharJanela() {
	gravarEstado(true);
	await enviarMetricas('encerramento');
	chamarApi('fechar');
}

function registrarEventos() {
	const cliques = {
		'centralizar-btn': () => chamarApi('centralizar'),
		'reload-btn': reiniciar,
		'pausar-btn': pararIniciar,
		'fixar-btn': alternarFixar,
		'alerta-btn': alternarTelaAlerta,
		'minimize-btn': () => chamarApi('minimizar'),
		'close-btn': fecharJanela,
		'close-btn-carregamento': fecharJanela,
		'grafico-btn': alternarGrafico,
		'compacto-btn': alternarCompacto,
		'overlay': pararIniciar,
		'darkback': alternarTelaAlerta,
		'salvarBotao': criarAlerta,
		'voltarBotao': alternarTelaAlerta,
	};
	for (const [id, acao] of Object.entries(cliques)) el(id).addEventListener('click', acao);

	ui.corpoTabela.addEventListener('click', aoClicarTabela);
	el('inputForm').addEventListener('submit', evento => evento.preventDefault());
	ui.campoValor.addEventListener('keydown', aoTeclarValorAlerta);
	el('dialogo').addEventListener('close', aoFecharDialogo);

	document.addEventListener('keydown', registrarInteracao, { passive: true });
	document.addEventListener('mousemove', registrarInteracao, { passive: true });
	// Um clique sem mover o mouse (ex.: fechar o alarme com o ponteiro já sobre o OK) também é atividade.
	// Não retoma a pausa por inatividade: quem retoma é o movimento ou o clique no ⏸.
	document.addEventListener('pointerdown', registrarAtividade, { passive: true });
	if (isPyWebView) document.addEventListener('mousedown', aoPressionarParaArrastar, { passive: true });
	document.addEventListener('visibilitychange', () => {
		if (document.visibilityState === 'hidden') gravarEstado(true);
		else if (ativo) adquirirWakeLock();
	});
	window.addEventListener('pagehide', () => gravarEstado(true));
	if (typeof ResizeObserver === 'function') new ResizeObserver(aoRedimensionar).observe(el('conteudoMenosBotoes'));
	else window.addEventListener('resize', aoRedimensionar, { passive: true });
}

document.addEventListener('DOMContentLoaded', () => {
	Metricas.marcar('dom_pronto');
	capturarElementos();
	graficoVisivel = !ui.grafico.hidden; // padrão de abertura vem do index.html
	// No app, o modo vem do servidor local (classe no <html>); no navegador, do localStorage.
	// Aplicado antes de o conteúdo aparecer: a tela de carregamento cobre a troca.
	if (isPyWebView) compacto = document.documentElement.classList.contains('compacto');
	else document.documentElement.classList.toggle('compacto', compacto = lerCompactoLocal());
	atualizarBotaoCompacto();
	registrarEventos();
	configurarBotoesJanela();
	restaurarEstadoSalvo(); // antes das requisições: a tela já abre com os últimos valores
	if (isPyWebView) sincronizarAlertas(); // a tela de carregamento cobre a interface até lá
	else carregarAlertasLocais();
	iniciarCiclos();
	atualizarBotaoPausa();
	// O gráfico e o som só entram depois do "load": um iframe ou mídia ainda carregando
	// atrasaria o "load" e, com ele, a ponte do pywebview (injetada no
	// NavigationCompleted do WebView2, que acompanha o "load").
	if (document.readyState === 'complete') aposCarregarPagina();
	else window.addEventListener('load', aposCarregarPagina, { once: true });
	setInterval(verificarInatividade, INTERVALO_VERIFICAR_INATIVIDADE);
	if (isPyWebView) sincronizarEstadoTopo();
	Metricas.marcar('inicializacao_js_concluida');
});
