'use strict';

// ---------------------------------------------------------------------------
// Regras puras (alertas e estado salvo), sem DOM nem rede.
// Carregado antes do script.js no navegador e importado pelos testes no Node.
// ---------------------------------------------------------------------------

const TIPO = Object.freeze({
	MAIOR: 'maior',
	MENOR: 'menor',
	DESATIVADO: 'desativado',
});

const TIPOS_VALIDOS = new Set(Object.values(TIPO));

// Ciclo do botão de tipo na tabela: Maior → Menor → Desativado → Maior
const PROXIMO_TIPO = Object.freeze({
	[TIPO.MAIOR]: TIPO.MENOR,
	[TIPO.MENOR]: TIPO.DESATIVADO,
	[TIPO.DESATIVADO]: TIPO.MAIOR,
});

const MAX_ALERTAS = 100;       // mesmo limite validado no Python
const MAX_TAMANHO_ID = 64;

function novoId() {
	if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
		return globalThis.crypto.randomUUID();
	}
	return Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}

/**
 * Converte o valor digitado (ou salvo) em número positivo com 2 casas.
 * @returns {number|null} null se o valor for inválido.
 */
function converterValor(entrada) {
	const numero = typeof entrada === 'number' ? entrada : Number(String(entrada ?? '').trim());
	if (!Number.isFinite(numero) || numero <= 0) return null;
	return Math.round(numero * 100) / 100;
}

/**
 * Normaliza um alerta vindo do armazenamento. Alertas antigos (sem id,
 * com valor em texto e campo "vazio") são migrados para o formato atual.
 * @returns {{id: string, valor: number, tipo: string}|null}
 */
function normalizarAlerta(bruto) {
	if (!bruto || typeof bruto !== 'object') return null;
	const valor = converterValor(bruto.valor);
	if (valor === null || !TIPOS_VALIDOS.has(bruto.tipo)) return null;
	const idValido = typeof bruto.id === 'string' && bruto.id.length > 0 && bruto.id.length <= MAX_TAMANHO_ID;
	return { id: idValido ? bruto.id : novoId(), valor, tipo: bruto.tipo };
}

/**
 * Normaliza e ordena uma lista de alertas.
 * @returns {{alertas: Array, alterado: boolean}} alterado indica que o
 *          resultado difere da entrada e precisa ser regravado.
 */
function normalizarLista(bruta) {
	if (!Array.isArray(bruta)) return { alertas: [], alterado: true };
	const alertas = ordenarAlertas(bruta.map(normalizarAlerta).filter(Boolean)).slice(0, MAX_ALERTAS);
	return { alertas, alterado: JSON.stringify(alertas) !== JSON.stringify(bruta) };
}

/** Ordena do maior para o menor valor, sem alterar a lista original. */
function ordenarAlertas(alertas) {
	return [...alertas].sort((a, b) => b.valor - a.valor);
}

function existeDuplicado(alertas, valor, tipo, ignorarId = null) {
	return alertas.some(a => a.id !== ignorarId && a.valor === valor && a.tipo === tipo);
}

function deveDisparar(alerta, preco) {
	if (!Number.isFinite(preco)) return false;
	if (alerta.tipo === TIPO.MAIOR) return preco >= alerta.valor;
	if (alerta.tipo === TIPO.MENOR) return preco <= alerta.valor;
	return false; // desativado
}

/** Primeiro alerta (na ordem da lista) que deve disparar com o preço atual. */
function alertaParaDisparar(alertas, preco) {
	return alertas.find(alerta => deveDisparar(alerta, preco)) ?? null;
}

/**
 * Desativa o alerta após ter disparado. Se já existir um alerta desativado
 * com o mesmo valor, o disparado é removido (fusão) em vez de ficar duplicado.
 */
function desativarAposDisparo(alertas, id) {
	const alvo = alertas.find(a => a.id === id);
	if (!alvo) return alertas;
	if (existeDuplicado(alertas, alvo.valor, TIPO.DESATIVADO, id)) {
		return alertas.filter(a => a.id !== id);
	}
	return alertas.map(a => (a.id === id ? { ...a, tipo: TIPO.DESATIVADO } : a));
}

/**
 * Tipo de um alerta desativado que volta a valer: o lado que não dispara com o
 * preço atual (preço acima do valor → "menor"; abaixo → "maior"). Preço igual ao
 * valor (os dois disparariam) ou desconhecido (NaN) → "maior".
 */
function tipoAoReativar(valor, preco) {
	return Number.isFinite(preco) && preco > valor ? TIPO.MENOR : TIPO.MAIOR;
}

/** Próximo tipo do botão da tabela: Maior → Menor → Desativado → (tipoAoReativar). */
function proximoTipo(alerta, preco) {
	return alerta.tipo === TIPO.DESATIVADO ? tipoAoReativar(alerta.valor, preco) : PROXIMO_TIPO[alerta.tipo];
}

/**
 * Muda o valor de um alerta (edição na tabela). Um alerta desativado volta a valer
 * pelo lado que não dispara com o preço atual (tipoAoReativar, com o valor novo); os
 * outros mantêm o tipo. Valor igual ao atual não muda nada.
 * @returns {{lista: Array}|{erro: 'invalido'|'inexistente'|'igual'|'duplicado'}}
 */
function editarValorAlerta(alertas, id, entrada, preco = NaN) {
	const valor = converterValor(entrada);
	if (valor === null) return { erro: 'invalido' };
	const alvo = alertas.find(a => a.id === id);
	if (!alvo) return { erro: 'inexistente' };
	if (valor === alvo.valor) return { erro: 'igual' };
	const tipo = alvo.tipo === TIPO.DESATIVADO ? tipoAoReativar(valor, preco) : alvo.tipo;
	if (existeDuplicado(alertas, valor, tipo, id)) return { erro: 'duplicado' };
	return { lista: ordenarAlertas(alertas.map(a => (a.id === id ? { ...a, valor, tipo } : a))) };
}

/** Há algum alerta que ainda pode disparar (maior ou menor)? */
function existeAlertaAtivo(alertas) {
	return alertas.some(alerta => alerta.tipo !== TIPO.DESATIVADO);
}

// ---------------------------------------------------------------------------
// Último estado salvo: valores exibidos ao abrir, até chegarem dados novos.
// ---------------------------------------------------------------------------

const VERSAO_ESTADO = 1;
const CAMPOS_TICKER = ['preco', 'variacao', 'maxima', 'minima'];
const CAMPOS_TAXAS = ['fastestFee', 'halfHourFee', 'hourFee', 'minimumFee'];

function tickerValido(ticker) {
	if (!ticker || typeof ticker !== 'object') return null;
	if (!CAMPOS_TICKER.every(campo => Number.isFinite(ticker[campo])) || ticker.preco <= 0) return null;
	return Object.fromEntries(CAMPOS_TICKER.map(campo => [campo, ticker[campo]]));
}

/**
 * Valida o estado lido do armazenamento. Partes inválidas viram null; sem
 * preço BRL válido ou com versão diferente, o estado inteiro é descartado.
 * @returns {{versao: number, salvoEm: number, brl: object, usdt: object|null, dolar: number|null, taxas: object|null}|null}
 */
function validarEstadoSalvo(bruto) {
	if (!bruto || typeof bruto !== 'object' || bruto.versao !== VERSAO_ESTADO) return null;
	const brl = tickerValido(bruto.brl);
	if (!brl || !Number.isFinite(bruto.salvoEm)) return null;
	const taxasOk = bruto.taxas && typeof bruto.taxas === 'object'
		&& CAMPOS_TAXAS.every(campo => Number.isFinite(bruto.taxas[campo]));
	return {
		versao: VERSAO_ESTADO,
		salvoEm: bruto.salvoEm,
		brl,
		usdt: tickerValido(bruto.usdt),
		dolar: Number.isFinite(bruto.dolar) && bruto.dolar > 0 ? bruto.dolar : null,
		taxas: taxasOk ? Object.fromEntries(CAMPOS_TAXAS.map(campo => [campo, bruto.taxas[campo]])) : null,
	};
}

/** Direção do preço em relação ao anterior: -1 (caiu), 0 (igual ou sem referência), 1 (subiu). */
function direcaoPreco(anterior, atual) {
	if (!Number.isFinite(anterior) || !Number.isFinite(atual) || anterior === atual) return 0;
	return atual > anterior ? 1 : -1;
}

// ---------------------------------------------------------------------------
// Rede: o que buscar e de quanto em quanto tempo (para gastar menos banda)
// ---------------------------------------------------------------------------

/**
 * Variação percentual em relação à abertura da janela de 24 h: (preço − abertura) ÷ abertura.
 * É o que a Binance manda pronto em "priceChangePercent"/"P"; o stream <par>@miniTicker
 * só traz a abertura.
 * @returns {number} NaN se algum valor for inválido ou a abertura não for positiva.
 */
function variacaoPercentual(preco, abertura) {
	if (!Number.isFinite(preco) || !Number.isFinite(abertura) || abertura <= 0) return NaN;
	return (preco - abertura) / abertura * 100;
}

/**
 * Quais fontes de dados precisam estar ligadas agora.
 * - preços: com a página visível, ou oculta com algum alerta ativo (é o preço que o dispara);
 * - dólar comercial e gráfico: só com a página visível;
 * - taxas: só com a página visível e fora do modo compacto (que não as mostra).
 * Com o monitoramento pausado, nada.
 */
function fontesNecessarias({ ativo, visivel, compacto, alertaAtivo }) {
	return {
		precos: ativo && (visivel || alertaAtivo),
		// O BTC/USDT só serve para exibição (preço em dólar e dólar implícito): com a página
		// oculta e um alerta ativo, basta o BTC/BRL.
		usdt: ativo && visivel,
		dolar: ativo && visivel,
		taxas: ativo && visivel && !compacto,
		grafico: ativo && visivel && !compacto,
	};
}

/**
 * Intervalo com recuo, para um valor que fica muito tempo parado (dólar comercial fora do
 * pregão). Enquanto o valor muda, consulta no intervalo mínimo; depois de "tolerancia"
 * consultas seguidas sem mudança, dobra o intervalo a cada consulta, até o máximo. A 1ª
 * mudança volta ao mínimo.
 * @param {{intervalo: number, semMudanca: number}} estado estado devolvido pela chamada anterior
 * @returns {{intervalo: number, semMudanca: number}}
 */
function intervaloComRecuo(estado, mudou, { minimo, maximo, tolerancia }) {
	if (mudou) return { intervalo: minimo, semMudanca: 0 };
	const semMudanca = estado.semMudanca + 1;
	if (semMudanca < tolerancia) return { intervalo: minimo, semMudanca };
	return { intervalo: Math.min(maximo, Math.max(minimo, estado.intervalo) * 2), semMudanca };
}

/**
 * true se algum valor se afastou da referência pelo menos "limiar" (fração: 0.05 = 5%).
 * Sem referência (1ª leitura), conta como mudança.
 */
function variouAlemDoLimiar(referencia, valores, limiar) {
	if (!Array.isArray(referencia) || referencia.length !== valores.length) return true;
	return valores.some((valor, indice) => {
		const base = referencia[indice];
		if (!Number.isFinite(base) || !Number.isFinite(valor)) return true;
		if (base === 0) return valor !== 0;
		return Math.abs(valor - base) / Math.abs(base) >= limiar;
	});
}

/**
 * Intervalo pela atividade recente, para um valor que muda em rajadas (taxas da rede).
 * "historico" tem um booleano por consulta (true: o valor mudou), o mais recente por
 * último; só as últimas "janela" contam. Quanto mais mudanças recentes, mais perto do
 * mínimo; sem nenhuma, o máximo. Consultas que ainda não existem contam como mudança
 * (começa rápido e só desacelera depois de ver o valor parado).
 */
function intervaloPorAtividade(historico, { minimo, maximo, janela }) {
	const recentes = historico.slice(-janela);
	const mudancas = recentes.filter(Boolean).length + (janela - recentes.length);
	return Math.round(maximo - (maximo - minimo) * (mudancas / janela));
}

if (typeof module !== 'undefined' && module.exports) {
	module.exports = {
		TIPO, PROXIMO_TIPO, MAX_ALERTAS,
		converterValor, normalizarAlerta, normalizarLista, ordenarAlertas,
		existeDuplicado, deveDisparar, alertaParaDisparar, desativarAposDisparo, editarValorAlerta,
		tipoAoReativar, proximoTipo,
		direcaoPreco, existeAlertaAtivo, validarEstadoSalvo, VERSAO_ESTADO,
		variacaoPercentual, fontesNecessarias, intervaloComRecuo, variouAlemDoLimiar, intervaloPorAtividade,
	};
}
