'use strict';

// ---------------------------------------------------------------------------
// Constantes de tipo de alerta (evita strings mágicas espalhadas no código)
// ---------------------------------------------------------------------------
const TIPO_MAIOR = "maior";
const TIPO_MENOR = "menor";
const TIPO_DESATIVADO = "desativado";

// ---------------------------------------------------------------------------
// Constante de ambiente — centraliza a checagem do user-agent
// ---------------------------------------------------------------------------
const isPyWebView = navigator.userAgent.includes("pywebview");

// ---------------------------------------------------------------------------
// Configurações de tempo
// ---------------------------------------------------------------------------
const UPDATE_TIME = 3000;        // Intervalo base de atualização de preço (ms)
const UPDATE_TAXAS = 50000;      // Intervalo base de atualização de taxas (ms)
const TEMPO_VERIFICAR_INATIVIDADE = 1000; // Intervalo do tick de inatividade (ms)
const MAX_FALHAS = 10;           // Máximo de falhas consecutivas de API antes de pausar

// ---------------------------------------------------------------------------
// Estado global
// ---------------------------------------------------------------------------
let transicaoAlarme = 0;
let contadorAlerta = 0;
let lastPriceBRL;
let wakeLock = null;
let loadingTime = 100;
let tempoInatividade = 0;
let varSetaMostrar;
let varSetaOld;
let ativo = true;
let falhasConsecutivas = 0;
let tempoLimite = 1000; // Tempo máximo de inatividade em segundos (~17 min)

// IDs de intervalo/timeout — declarados no escopo global para acesso em todo o script
let intervaloID;
let taxaIntervaloID;
let alarmesID;
let transicaoAlarmeID;

// Referência ao listener de teclado do campo de alerta (para remover antes de readicionar)
let valorAlertaKeydownHandler = null;

// ---------------------------------------------------------------------------
// Inatividade
// ---------------------------------------------------------------------------

function resetarInatividade() {
	tempoInatividade = 0;
	if (ativo) return;
	document.getElementById('overlay').style.display = 'none';
	ativo = true;
	inicial();
	atualiza_taxas();
	clearInterval(intervaloID);
	intervaloID = setInterval(inicial, UPDATE_TIME);
	clearInterval(taxaIntervaloID);
	taxaIntervaloID = setInterval(atualiza_taxas, UPDATE_TAXAS);
}

function verificarInatividade() {
	if (!ativo) return;
	tempoInatividade++;
	if (tempoLimite > 0 && tempoInatividade >= tempoLimite) {
		document.getElementById('overlay').style.display = 'flex';
		ativo = false;
		clearTimeout(alarmesID);
		clearInterval(intervaloID);
		clearInterval(taxaIntervaloID);
		liberarWakeLock();
	}
}

// Registra os listeners de inatividade uma única vez no carregamento
document.addEventListener('keydown', resetarInatividade);
document.addEventListener('mousemove', resetarInatividade);

// ---------------------------------------------------------------------------
// WakeLock — wrapper seguro
// ---------------------------------------------------------------------------

async function adquirirWakeLock() {
	try {
		wakeLock = await navigator.wakeLock.request('screen');
	} catch (err) {
		console.warn('WakeLock não disponível:', err);
		wakeLock = null;
	}
}

function liberarWakeLock() {
	if (wakeLock) {
		wakeLock.release().catch(err => console.warn('Erro ao liberar wakeLock:', err));
		wakeLock = null;
	}
}

// ---------------------------------------------------------------------------
// Transição de alarme (silencia alarmes temporariamente)
// ---------------------------------------------------------------------------

function fazerTransicaoAlarme(tempoTransicao = 15000) {
	transicaoAlarme = 1;
	clearTimeout(transicaoAlarmeID);
	transicaoAlarmeID = setTimeout(() => {
		transicaoAlarme = 0;
	}, tempoTransicao);
}

// ---------------------------------------------------------------------------
// Integração PyWebView
// ---------------------------------------------------------------------------

function pyWebviewFechar() {
	window.pywebview.api.fechar();
}

function pyWebviewMinimize() {
	window.pywebview.api.minimizar();
}

function pyWebviewCentralizar() {
	// Passa booleano verdadeiro; o Python recebe como truthy corretamente
	window.pywebview.api.centralizar(true);
}

function pyWebviewSalvarAlerta(json) {
	window.pywebview.api.salvar_alerta(json);
}

async function pyWebviewCarregarAlerta() {
	try {
		return await window.pywebview.api.carregar_alerta();
	} catch (erro) {
		console.error("Erro ao carregar alertas:", erro);
		return [];
	}
}

// ---------------------------------------------------------------------------
// Controles da janela
// ---------------------------------------------------------------------------

function reiniciar() {
	const fixarBtn = document.getElementById('fixar-btn');
	if (fixarBtn.textContent === '▽') {
		fixarBtn.textContent = '△'; // corrigido: era == (comparação) em vez de = (atribuição)
		window.pywebview.api.fixarTopo();
	}
	location.reload();
}

function pararIniciar() {
	if (ativo) {
		ativo = false;
		document.getElementById('overlay').style.display = 'flex';
		clearTimeout(alarmesID);
		clearInterval(intervaloID);
		clearInterval(taxaIntervaloID);
		liberarWakeLock();
		document.removeEventListener('keydown', resetarInatividade);
		document.removeEventListener('mousemove', resetarInatividade);
		alternarBtnPausa();
	} else {
		ativo = true;
		falhasConsecutivas = 0;
		document.getElementById('overlay').style.display = 'none';
		inicial();
		clearInterval(intervaloID);
		intervaloID = setInterval(inicial, UPDATE_TIME);
		atualiza_taxas();
		clearInterval(taxaIntervaloID);
		taxaIntervaloID = setInterval(atualiza_taxas, UPDATE_TAXAS);
		document.addEventListener('keydown', resetarInatividade);
		document.addEventListener('mousemove', resetarInatividade);
		fazerTransicaoAlarme();
		alternarBtnPausa();
	}
}

function alternarBtnPausa() {
	const btn = document.getElementById("pausar-btn");
	btn.setAttribute("title", btn.getAttribute("title") === "Pausar" ? "Reiniciar" : "Pausar");
}

function pyWebviewFixar() {
	const btn = document.getElementById('fixar-btn');
	if (btn.textContent === '△') {
		tempoLimite = 0;
		btn.setAttribute('title', 'Desafixar');
		btn.setAttribute('alt', 'Desafixar');
		btn.textContent = '▽';
	} else {
		tempoLimite = 1000;
		btn.setAttribute('title', 'Fixar');
		btn.setAttribute('alt', 'Fixar');
		btn.textContent = '△';
	}
	window.pywebview.api.fixarTopo();
}

function botoesPywebview() {
	if (isPyWebView) {
		["reload-btn", "centralizar-btn", "fixar-btn", "alerta-btn",
		 "minimize-btn", "close-btn", "pausar-btn", "grafico-btn"].forEach(id => {
			document.getElementById(id).style.display = "flex";
		});
	} else {
		const pausarBtn = document.getElementById("pausar-btn");
		pausarBtn.style.left = "unset";
		pausarBtn.style.right = "0px";
		pausarBtn.style.display = "flex";
		const alertaBtn = document.getElementById("alerta-btn");
		alertaBtn.style.left = "0px";
		alertaBtn.style.display = "flex";
	}
}

function graficoAlternar() {
	const grafico = document.getElementById("grafico");
	// Usa getComputedStyle para ler o valor real do CSS na primeira chamada,
	// quando style.display ainda é string vazia (nenhum valor inline definido).
	const displayAtual = grafico.style.display || getComputedStyle(grafico).display;
	grafico.style.display = displayAtual === "flex" ? "none" : "flex";
}

// ---------------------------------------------------------------------------
// Atualização de preços
// ---------------------------------------------------------------------------

async function inicial() {
	if (!ativo) return;

	await adquirirWakeLock();

	try {
		const responseBRL = await fetch('https://api.binance.com/api/v3/ticker/24hr?symbol=BTCBRL');
		const dataBRL = await responseBRL.json();

		lastPriceBRL = parseFloat(dataBRL.lastPrice);
		falhasConsecutivas = 0; // Requisição bem-sucedida — reseta contador de falhas

		const formattedPriceBRL = lastPriceBRL.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
		const priceChangePercent = parseFloat(dataBRL.priceChangePercent);

		// Calcular direção da variação e mostrar seta correspondente
		if (varSetaOld !== undefined) {
			if (varSetaOld > priceChangePercent) {
				varSetaMostrar = "\u00A0\u00A0↓";
			} else if (varSetaOld < priceChangePercent) {
				varSetaMostrar = "\u00A0\u00A0↑";
			} else {
				varSetaMostrar = "↔";
			}
		} else {
			varSetaMostrar = "↔";
		}
		varSetaOld = priceChangePercent;

		const formattedPercent = priceChangePercent.toFixed(2) + '%';

		// Formatar data e hora com Intl.DateTimeFormat
		const now = new Date();
		const formattedTime =
			new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit' }).format(now) +
			" - " +
			new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(now);

		document.title = `${formattedPriceBRL} | ${formattedPercent}`;

		document.getElementById('highPrice').textContent = parseFloat(dataBRL.highPrice).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
		document.getElementById('lowPrice').textContent = parseFloat(dataBRL.lowPrice).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
		document.getElementById('info-price').textContent = formattedPriceBRL;
		document.getElementById('info-time').textContent = formattedTime;

		if (ativo) {
			document.getElementById('info-percent').textContent = formattedPercent;
			const setaLimpa = varSetaMostrar.replaceAll('\u00A0', '');
			document.getElementById('info-seta').style.color = setaLimpa === '↔' ? 'white' : '#f7931a';
			// Reinicia a animação da seta
			const setaEl = document.getElementById('info-seta');
			setaEl.style.opacity = '0';
			setaEl.style.animation = 'none';
			setaEl.offsetHeight; // força reflow para reiniciar animação CSS
			setaEl.style.animation = 'surgindo 1s forwards';
			setaEl.textContent = varSetaMostrar;
		}

		atualiza_USD(lastPriceBRL);

	} catch (error) {
		console.error('Erro ao buscar dados da API BTC/BRL Binance:', error);
		document.title = 'Sem Dados';
		document.getElementById('info-price').textContent = '▶Sem Dados◀';

		// Lógica de falhas consecutivas: pausa o monitoramento após MAX_FALHAS tentativas
		falhasConsecutivas++;
		if (falhasConsecutivas >= MAX_FALHAS) {
			console.warn(`${MAX_FALHAS} falhas consecutivas — pausando monitoramento.`);
			pararIniciar();
			return;
		}
	}

	// Reagendar com intervalo aleatório para evitar picos sincronizados de requisição
	const proximoIntervalo = Math.floor(Math.random() * 3001 + UPDATE_TIME);
	clearInterval(intervaloID);
	intervaloID = setInterval(inicial, proximoIntervalo);

	clearTimeout(alarmesID);
	alarmesID = setTimeout(checarAlarmes, 1000);
}

async function atualiza_B3(dollarExchangeRate) {
	try {
		const responseBRLx = await fetch('https://economia.awesomeapi.com.br/json/last/USD-BRL');
		const dataBRLx = await responseBRLx.json();
		const lastPriceBRLaskx = parseFloat(dataBRLx.USDBRL.ask);
		const lastPriceBRLbidx = parseFloat(dataBRLx.USDBRL.bid);
		const lastPriceBRLx = (lastPriceBRLaskx + lastPriceBRLbidx) / 2;
		const formattedPriceBRLx = lastPriceBRLx.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
		document.getElementById('info-dolar').textContent = `${dollarExchangeRate} | ${formattedPriceBRLx}`;
	} catch (error) {
		console.error('Erro ao buscar dados do BRL/USDT AwesomeAPI:', error);
		document.getElementById('info-dolar').textContent = 'Sem Dados';
	}
}

async function atualiza_USD(priceBRL) {
	try {
		const responseUSD = await fetch('https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT');
		const dataUSD = await responseUSD.json();
		const lastPriceUSD = parseFloat(dataUSD.lastPrice);
		const formattedPriceUSD = lastPriceUSD.toLocaleString('pt-BR', { style: 'currency', currency: 'USD' });

		document.getElementById('info-usdt').textContent = formattedPriceUSD;

		const dollarExchangeRate = (priceBRL / lastPriceUSD).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

		document.getElementById('highPriceDol').textContent = parseFloat(dataUSD.highPrice).toLocaleString('pt-BR', { style: 'currency', currency: 'USD' });
		document.getElementById('lowPriceDol').textContent = parseFloat(dataUSD.lowPrice).toLocaleString('pt-BR', { style: 'currency', currency: 'USD' });

		atualiza_B3(dollarExchangeRate);
	} catch (error) {
		console.error('Erro ao buscar dados do BTC/USDT Binance:', error);
		document.getElementById('info-usdt').textContent = 'Sem Dados';
		document.getElementById('info-dolar').textContent = 'Sem Dados';
	}
}

async function atualiza_taxas() {
	if (!ativo) return;
	try {
		const responseFees = await fetch('https://mempool.space/api/v1/fees/precise');
		const dataFees = await responseFees.json();
		const fmt = v => `${parseFloat(v).toFixed(2).replace('.', ',')} sat/vB`;
		document.getElementById('fastestFee').textContent = fmt(dataFees.fastestFee);
		document.getElementById('halfHourFee').textContent = fmt(dataFees.halfHourFee);
		document.getElementById('hourFee').textContent = fmt(dataFees.hourFee);
		document.getElementById('minimumFee').textContent = fmt(dataFees.minimumFee);
	} catch (error) {
		console.error('Erro ao buscar dados de taxas:', error);
	}

	// Reagendar com intervalo aleatório
	const proximoIntervalo = Math.floor(Math.random() * 20001 + UPDATE_TAXAS);
	clearInterval(taxaIntervaloID);
	taxaIntervaloID = setInterval(atualiza_taxas, proximoIntervalo);
}

// ---------------------------------------------------------------------------
// Carregamento inicial
// ---------------------------------------------------------------------------

function verificarCarregamento() {
	if (document.getElementById('info-price').textContent === '') {
		loadingTime *= 1.2;
		if (loadingTime > 2000) {
			location.reload();
		}
		setTimeout(verificarCarregamento, loadingTime);
	} else {
		document.getElementById('tela-carregamento').style.display = 'none';
		document.getElementById('conteudo').style.display = 'block';
		loadingTime = 100;
		if (isPyWebView) {
			sincronizaAlertas();
		}
		// Silencia alarmes por 5s após o carregamento para evitar disparos imediatos
		fazerTransicaoAlarme(5000);
	}
}

// ---------------------------------------------------------------------------
// Sincronização de alertas com backend Python
// ---------------------------------------------------------------------------

async function sincronizaAlertas() {
	const alertasPython = await pyWebviewCarregarAlerta();
	const alertasLocais = JSON.parse(localStorage.getItem('alertasjson')) || [];
	const alertasSalvos = alertasPython || [];
	if (JSON.stringify(alertasSalvos) !== JSON.stringify(alertasLocais)) {
		localStorage.setItem('alertasjson', JSON.stringify(alertasSalvos));
	}
}

// ---------------------------------------------------------------------------
// Alertas — lógica de verificação
// ---------------------------------------------------------------------------

function checarAlarmes() {
	let alertas = [];
	try {
		alertas = JSON.parse(localStorage.getItem('alertasjson')) || [];
	} catch (e) {
		console.error("Erro ao parsear alertas do localStorage:", e);
		return;
	}

	if (transicaoAlarme !== 0 || alertas.length === 0) return;

	alertas.forEach((alerta, index) => {
		if (alerta.tipo === TIPO_MAIOR && lastPriceBRL >= alerta.valor) {
			dispararAlerta('O Preço do Bitcoin superou', alerta.valor, index);
		} else if (alerta.tipo === TIPO_MENOR && lastPriceBRL <= alerta.valor) {
			dispararAlerta('O Preço do Bitcoin caiu abaixo de', alerta.valor, index);
		} else if (alerta.tipo === TIPO_DESATIVADO) {
			fazerTransicaoAlarme();
		} else if (alerta.tipo !== TIPO_MAIOR && alerta.tipo !== TIPO_MENOR && alerta.tipo !== TIPO_DESATIVADO) {
			console.warn("Tipo de alarme desconhecido:", alerta.tipo);
		}
	});
}

function dispararAlerta(mensagem, valor, index) {
	if (contadorAlerta !== 0) return;
	contadorAlerta = 1;
	const valorFormatado = (parseFloat(valor) || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
	$.alert({
		title: 'ALERTA',
		content: `${mensagem}<br>${valorFormatado}`,
		theme: 'dark',
		onClose: function() {
			contadorAlerta = 0;
			mudarTipo(index, true); // passa booleano em vez de expressão de atribuição
		},
		draggable: false,
		boxWidth: '300px',
		useBootstrap: false,
	});
	tocarAlerta();
}

// ---------------------------------------------------------------------------
// Alertas — CRUD e interface
// ---------------------------------------------------------------------------

function mostrarTelaAlerta() {
	const modal = document.getElementById("modalAlerta");
	const darkback = document.getElementById('darkback');
	const estaAberto = modal.style.display === "block";
	modal.style.display = estaAberto ? "none" : "block";
	darkback.style.display = estaAberto ? "none" : "flex";
	carregarAlertas();
}

function criarAlerta() {
	const valor = document.getElementById("valorAlerta").value; // corrigido: era variável global implícita
	if (validarValor(valor)) {
		salvarAlerta(valor, TIPO_MAIOR, 0);
	} else {
		$.alert({
			title: 'FALHA',
			content: 'Digite um número válido.',
			theme: 'dark',
			draggable: false,
			boxWidth: '300px',
			useBootstrap: false,
			autoClose: 'ok|15000',
		});
	}
	carregarAlertas();
}

function validarValor(numero) {
	const paraValidar = parseFloat(numero);
	return !isNaN(paraValidar) && String(numero).trim() !== "";
}

function salvarAlerta(valor, tipo, vazio) {
	let alertas = JSON.parse(localStorage.getItem('alertasjson')) || [];
	const alertaExistente = alertas.find(a => a.valor === valor && a.tipo === tipo);
	if (alertaExistente) {
		$.alert({
			title: 'FALHA',
			content: 'Existe um alerta com esse mesmo valor.',
			theme: 'dark',
			draggable: false,
			boxWidth: '300px',
			useBootstrap: false,
			autoClose: 'ok|15000',
		});
		return;
	}
	alertas.push({ valor, tipo, vazio });
	localStorage.setItem('alertasjson', JSON.stringify(alertas));
	if (isPyWebView) {
		pyWebviewSalvarAlerta(alertas);
	}
	fazerTransicaoAlarme();
}

function voltarAlerta() {
	limparValor();
	mostrarTelaAlerta();
}

function limparValor() {
	const campo = document.getElementById('valorAlerta');
	if (campo.value !== "") campo.value = "";
}

function limparMoeda(numero) {
	const valorSemSimbolo = numero.replace('R$', '').trim();
	const valorSemMilhar = valorSemSimbolo.replace('.', '').replace(',', '.');
	return parseFloat(valorSemMilhar);
}

function apagarAlertas(index) {
	let alertas = JSON.parse(localStorage.getItem('alertasjson')) || [];
	alertas.splice(index, 1);
	localStorage.setItem('alertasjson', JSON.stringify(alertas));
	if (isPyWebView) {
		pyWebviewSalvarAlerta(alertas);
	}
	carregarAlertas();
}

function carregarAlertas() {
	const tabela = document.getElementById("alertasTabela").getElementsByTagName('tbody')[0];
	tabela.innerHTML = '';

	let alertas = [];
	try {
		alertas = JSON.parse(localStorage.getItem('alertasjson')) || [];
		const alertasOrdenados = [...alertas].sort((a, b) => b.valor - a.valor);
		if (JSON.stringify(alertas) !== JSON.stringify(alertasOrdenados)) {
			localStorage.setItem('alertasjson', JSON.stringify(alertasOrdenados));
			alertas = alertasOrdenados;
		}
	} catch (e) {
		console.error("Erro ao parsear alertas do localStorage:", e);
	}

	// Usar DocumentFragment para inserir todas as linhas de uma vez (evita múltiplos reflows)
	const fragment = document.createDocumentFragment();

	alertas.forEach((valorAlerta, index) => {
		const valorAlertaFormatado = parseFloat(valorAlerta.valor).toLocaleString('pt-BR', {
			style: 'currency',
			currency: 'BRL',
			minimumFractionDigits: 2
		});

		const novaLinha = document.createElement('tr');

		// Célula de tipo
		const celulatipo = document.createElement('td');
		const botaotipo = document.createElement("button");
		botaotipo.className = "botaoTipo"; // corrigido: classe em vez de ID duplicado
		botaotipo.type = "button";
		botaotipo.onclick = function() {
			mudarTipo(index);
			fazerTransicaoAlarme();
		};
		if (valorAlerta.tipo === TIPO_MAIOR) {
			botaotipo.textContent = "Maior △";
			botaotipo.title = "Alertar quando BTC for maior que " + valorAlertaFormatado;
			botaotipo.style.opacity = "1";
		} else if (valorAlerta.tipo === TIPO_MENOR) {
			botaotipo.textContent = "Menor ▽";
			botaotipo.title = "Alertar quando BTC for menor que " + valorAlertaFormatado;
			botaotipo.style.opacity = "1";
		} else if (valorAlerta.tipo === TIPO_DESATIVADO) {
			botaotipo.textContent = "Desativado";
			botaotipo.title = "Alarme desativado";
			botaotipo.style.opacity = "0.5";
		}
		celulatipo.appendChild(botaotipo);
		novaLinha.appendChild(celulatipo);

		// Célula de valor
		const celulaValor = document.createElement('td');
		celulaValor.textContent = valorAlertaFormatado;
		celulaValor.title = valorAlertaFormatado;
		novaLinha.appendChild(celulaValor);

		// Célula de ação
		const celulaAcao = document.createElement('td');
		const botaoApagar = document.createElement("button");
		botaoApagar.className = "botaoApagar"; // corrigido: classe em vez de ID duplicado
		botaoApagar.textContent = "Apagar";
		botaoApagar.title = "Apagar alarme " + valorAlertaFormatado;
		botaoApagar.onclick = function() { apagarAlertas(index); };
		celulaAcao.appendChild(botaoApagar);
		novaLinha.appendChild(celulaAcao);

		fragment.appendChild(novaLinha);
	});

	tabela.appendChild(fragment); // Inserção única no DOM

	// Limpa e foca o campo
	const campoValor = document.getElementById('valorAlerta');
	campoValor.value = "";
	campoValor.focus();

	// Remove o listener anterior antes de adicionar um novo (evita acúmulo de listeners)
	if (valorAlertaKeydownHandler) {
		campoValor.removeEventListener('keydown', valorAlertaKeydownHandler);
	}
	valorAlertaKeydownHandler = function(event) {
		if (event.key === 'Enter') {
			event.preventDefault();
			if (document.getElementById("modalAlerta").style.display === "block" && this.value.trim() !== '') {
				criarAlerta();
			}
		}
		if (event.key === 'Escape') {
			if (document.getElementById("modalAlerta").style.display === "block") {
				voltarAlerta();
			}
		}
	};
	campoValor.addEventListener('keydown', valorAlertaKeydownHandler);
}

function mudarTipo(index, desativarForçado = false) {
	let alertas = [];
	try {
		alertas = JSON.parse(localStorage.getItem('alertasjson')) || [];
	} catch (e) {
		console.error("Erro ao parsear alertas do localStorage:", e);
		return;
	}

	if (index < 0 || index >= alertas.length) {
		console.error("Índice de alerta inválido:", index);
		return;
	}

	const valor = alertas[index].valor;
	const tipoOriginal = alertas[index].tipo;

	let tipoAlterado;
	if (desativarForçado) {
		tipoAlterado = TIPO_DESATIVADO;
	} else if (tipoOriginal === TIPO_MAIOR) {
		tipoAlterado = TIPO_MENOR;
	} else if (tipoOriginal === TIPO_MENOR) {
		tipoAlterado = TIPO_DESATIVADO;
	} else if (tipoOriginal === TIPO_DESATIVADO) {
		tipoAlterado = TIPO_MAIOR;
	} else {
		console.warn("Tipo de alerta desconhecido:", tipoOriginal);
		return;
	}

	alertas[index].tipo = tipoAlterado;

	// Checar duplicata com o novo tipo (excluindo o próprio alerta)
	const alertaExistente = alertas.some((a, i) => a.valor === valor && a.tipo === tipoAlterado && i !== index);
	if (alertaExistente) {
		$.alert({
			title: 'FALHA',
			content: 'Existe um alerta com esse mesmo valor.',
			theme: 'dark',
			draggable: false,
			boxWidth: '300px',
			useBootstrap: false,
			autoClose: 'ok|5000',
		});
		return;
	}

	try {
		localStorage.setItem('alertasjson', JSON.stringify(alertas));
		if (isPyWebView) {
			pyWebviewSalvarAlerta(alertas);
		}
	} catch (e) {
		console.error("Erro ao salvar alertas no localStorage:", e);
	}

	carregarAlertas();
}

// ---------------------------------------------------------------------------
// Áudio de alerta
// ---------------------------------------------------------------------------

function tocarAlerta(repeticoes = 1, volume = 1) {
	const audio = new Audio('alerta.mp3');
	audio.volume = volume;
	audio.preload = 'auto';
	let contador = 0;

	audio.addEventListener('canplaythrough', () => {
		const tocar = () => {
			if (contador < repeticoes) {
				audio.play().catch(() => {
					$.alert({
						title: 'FALHA',
						content: 'Falha ao reproduzir áudio.',
						theme: 'dark',
						draggable: false,
						boxWidth: '300px',
						useBootstrap: false,
						autoClose: 'ok|3000',
					});
				});
				contador++;
				audio.onended = () => setTimeout(tocar, 100);
			}
		};
		tocar();
	}, { once: true }); // 'once: true' evita acúmulo do listener no mesmo objeto de audio

	audio.load();
}

// ---------------------------------------------------------------------------
// Inicialização
// ---------------------------------------------------------------------------

window.addEventListener('load', () => {
	botoesPywebview();
	inicial();
	atualiza_taxas();
	setTimeout(verificarCarregamento, loadingTime);
	setInterval(verificarInatividade, TEMPO_VERIFICAR_INATIVIDADE);
});
