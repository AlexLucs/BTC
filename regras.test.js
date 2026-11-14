// Testes das regras de alerta: node --test tests/regras.test.js
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const r = require('../regras.js');

test('converterValor aceita positivos e arredonda para centavos', () => {
	assert.equal(r.converterValor('500000'), 500000);
	assert.equal(r.converterValor(' 1.239 '), 1.24);
	for (const invalido of ['', '  ', 'abc', '0', '-3', null, undefined, Infinity, NaN]) {
		assert.equal(r.converterValor(invalido), null, String(invalido));
	}
});

test('normalizarLista migra formato antigo, descarta inválidos e ordena', () => {
	const { alertas, alterado } = r.normalizarLista([
		{ valor: '100', tipo: 'maior', vazio: 0 },
		{ valor: 'x', tipo: 'maior' },
		{ id: 'b', valor: 200, tipo: 'menor' },
		{ id: 'c', valor: 50, tipo: 'invalido' },
	]);
	assert.equal(alterado, true);
	assert.deepEqual(alertas.map(a => [a.valor, a.tipo]), [[200, 'menor'], [100, 'maior']]);
	assert.equal(alertas[0].id, 'b');
	assert.ok(alertas[1].id.length > 0);
});

test('normalizarLista não marca alteração quando já está normalizada', () => {
	const lista = [{ id: 'a', valor: 2, tipo: 'maior' }, { id: 'b', valor: 1, tipo: 'menor' }];
	assert.equal(r.normalizarLista(lista).alterado, false);
	assert.deepEqual(r.normalizarLista('lixo'), { alertas: [], alterado: true });
});

test('deveDisparar respeita tipo e ignora preço inválido', () => {
	assert.equal(r.deveDisparar({ valor: 100, tipo: 'maior' }, 100), true);
	assert.equal(r.deveDisparar({ valor: 100, tipo: 'maior' }, 99), false);
	assert.equal(r.deveDisparar({ valor: 100, tipo: 'menor' }, 100), true);
	assert.equal(r.deveDisparar({ valor: 100, tipo: 'menor' }, 101), false);
	assert.equal(r.deveDisparar({ valor: 100, tipo: 'desativado' }, 1e9), false);
	assert.equal(r.deveDisparar({ valor: 100, tipo: 'maior' }, NaN), false);
});

test('alertaParaDisparar ignora desativados e retorna o primeiro aplicável', () => {
	const alertas = [
		{ id: 'd', valor: 300, tipo: 'desativado' },
		{ id: 'm', valor: 200, tipo: 'maior' },
		{ id: 'n', valor: 100, tipo: 'menor' },
	];
	assert.equal(r.alertaParaDisparar(alertas, 250).id, 'm');
	assert.equal(r.alertaParaDisparar(alertas, 150), null);
});

test('desativarAposDisparo desativa ou funde com desativado de mesmo valor', () => {
	const simples = r.desativarAposDisparo([{ id: 'a', valor: 10, tipo: 'maior' }], 'a');
	assert.deepEqual(simples, [{ id: 'a', valor: 10, tipo: 'desativado' }]);

	const comDuplicado = r.desativarAposDisparo([
		{ id: 'a', valor: 10, tipo: 'maior' },
		{ id: 'b', valor: 10, tipo: 'desativado' },
	], 'a');
	assert.deepEqual(comDuplicado, [{ id: 'b', valor: 10, tipo: 'desativado' }]);

	const inexistente = [{ id: 'a', valor: 10, tipo: 'maior' }];
	assert.equal(r.desativarAposDisparo(inexistente, 'zzz'), inexistente);
});

test('editarValorAlerta muda o valor, reordena e reativa o desativado como maior', () => {
	const lista = Object.freeze([
		Object.freeze({ id: 'a', valor: 30, tipo: 'menor' }),
		Object.freeze({ id: 'b', valor: 20, tipo: 'desativado' }),
		Object.freeze({ id: 'c', valor: 10, tipo: 'maior' }),
	]);

	// Mantém o tipo e reordena (do maior para o menor valor); a lista original não muda.
	assert.deepEqual(r.editarValorAlerta(lista, 'a', '5.555'), { lista: [
		{ id: 'b', valor: 20, tipo: 'desativado' },
		{ id: 'c', valor: 10, tipo: 'maior' },
		{ id: 'a', valor: 5.56, tipo: 'menor' },
	] });
	assert.equal(lista[0].valor, 30);

	// Desativado volta a valer como "maior".
	assert.deepEqual(r.editarValorAlerta(lista, 'b', 40).lista[0], { id: 'b', valor: 40, tipo: 'maior' });
});

test('editarValorAlerta recusa valor inválido, igual, duplicado e alerta inexistente', () => {
	const lista = [
		{ id: 'a', valor: 30, tipo: 'menor' },
		{ id: 'b', valor: 20, tipo: 'desativado' },
		{ id: 'c', valor: 10, tipo: 'maior' },
	];
	for (const invalido of ['', 'abc', '0', '-1']) {
		assert.deepEqual(r.editarValorAlerta(lista, 'a', invalido), { erro: 'invalido' }, invalido);
	}
	assert.deepEqual(r.editarValorAlerta(lista, 'a', '30'), { erro: 'igual' });
	assert.deepEqual(r.editarValorAlerta(lista, 'zzz', '5'), { erro: 'inexistente' });
	// Mesmo valor de outro alerta, mas de outro tipo: permitido (como na criação).
	assert.ok(r.editarValorAlerta(lista, 'c', '30').lista);
	// Mesmo valor e mesmo tipo de outro alerta: recusado.
	assert.deepEqual(r.editarValorAlerta([...lista, { id: 'd', valor: 5, tipo: 'menor' }], 'a', '5'), { erro: 'duplicado' });
	// O desativado reativado como "maior" colide com um "maior" de mesmo valor.
	assert.deepEqual(r.editarValorAlerta(lista, 'b', '10'), { erro: 'duplicado' });
});

test('ciclo de tipos e duplicidade', () => {
	assert.equal(r.PROXIMO_TIPO.maior, 'menor');
	assert.equal(r.PROXIMO_TIPO.menor, 'desativado');
	assert.equal(r.PROXIMO_TIPO.desativado, 'maior');
	const alertas = [{ id: 'a', valor: 10, tipo: 'maior' }];
	assert.equal(r.existeDuplicado(alertas, 10, 'maior'), true);
	assert.equal(r.existeDuplicado(alertas, 10, 'maior', 'a'), false);
});

test('direcaoPreco', () => {
	assert.equal(r.direcaoPreco(NaN, 1), 0);
	assert.equal(r.direcaoPreco(1, 1), 0);
	assert.equal(r.direcaoPreco(1, 2), 1);
	assert.equal(r.direcaoPreco(2, 1), -1);
});

test('existeAlertaAtivo ignora desativados', () => {
	assert.equal(r.existeAlertaAtivo([]), false);
	assert.equal(r.existeAlertaAtivo([{ id: 'a', valor: 1, tipo: 'desativado' }]), false);
	assert.equal(r.existeAlertaAtivo([{ id: 'a', valor: 1, tipo: 'desativado' }, { id: 'b', valor: 2, tipo: 'menor' }]), true);
});

test('validarEstadoSalvo aceita estado completo e descarta partes inválidas', () => {
	const ticker = { preco: 500000, variacao: -1.5, maxima: 510000, minima: 490000 };
	const completo = {
		versao: r.VERSAO_ESTADO, salvoEm: 1700000000000, brl: ticker,
		usdt: { preco: 100000, variacao: 0, maxima: 101000, minima: 99000 },
		dolar: 5.01, taxas: { fastestFee: 3.4, halfHourFee: 2, hourFee: 1.5, minimumFee: 1 },
	};
	assert.deepEqual(r.validarEstadoSalvo(completo), completo);

	const parcial = r.validarEstadoSalvo({ ...completo, usdt: { preco: 'x' }, dolar: -1, taxas: { fastestFee: 1 }, extra: 1 });
	assert.deepEqual(parcial, { ...completo, usdt: null, dolar: null, taxas: null });

	for (const invalido of [null, 'x', {}, { ...completo, versao: 99 }, { ...completo, brl: { ...ticker, preco: 0 } },
		{ ...completo, salvoEm: 'ontem' }]) {
		assert.equal(r.validarEstadoSalvo(invalido), null, JSON.stringify(invalido));
	}
});

test('variacaoPercentual usa a abertura da janela de 24 h', () => {
	assert.equal(r.variacaoPercentual(110, 100), 10);
	assert.equal(r.variacaoPercentual(95, 100), -5);
	assert.equal(r.variacaoPercentual(100, 100), 0);
	// Mesmo número que a Binance manda pronto: 507100 contra abertura 500938,45 dá 1,23%.
	assert.equal(r.variacaoPercentual(507100, 500938.45).toFixed(2), '1.23');
	for (const [preco, abertura] of [[NaN, 100], [100, NaN], [100, 0], [100, -1], [Infinity, 100]]) {
		assert.ok(Number.isNaN(r.variacaoPercentual(preco, abertura)), `${preco} / ${abertura}`);
	}
});

test('fontesNecessarias: visível, oculta com e sem alerta, compacto e pausa', () => {
	const base = { ativo: true, visivel: true, compacto: false, alertaAtivo: false };
	assert.deepEqual(r.fontesNecessarias(base), { precos: true, usdt: true, dolar: true, taxas: true, grafico: true });
	// Modo compacto: as taxas e o gráfico não aparecem.
	assert.deepEqual(r.fontesNecessarias({ ...base, compacto: true }), { precos: true, usdt: true, dolar: true, taxas: false, grafico: false });
	// Oculta sem alerta ativo: nada.
	assert.deepEqual(r.fontesNecessarias({ ...base, visivel: false }), { precos: false, usdt: false, dolar: false, taxas: false, grafico: false });
	// Oculta com alerta ativo: só o preço em reais, que é o que dispara o alerta.
	assert.deepEqual(r.fontesNecessarias({ ...base, visivel: false, alertaAtivo: true }), { precos: true, usdt: false, dolar: false, taxas: false, grafico: false });
	// Pausado: nada, mesmo visível e com alerta.
	assert.deepEqual(r.fontesNecessarias({ ...base, ativo: false, alertaAtivo: true }), { precos: false, usdt: false, dolar: false, taxas: false, grafico: false });
});

test('intervaloComRecuo dobra depois da tolerância e volta ao mínimo quando muda', () => {
	const config = { minimo: 60000, maximo: 600000, tolerancia: 3 };
	let estado = { intervalo: config.minimo, semMudanca: 0 };
	const intervalos = [];
	for (let i = 0; i < 8; i++) {
		estado = r.intervaloComRecuo(estado, false, config);
		intervalos.push(estado.intervalo);
	}
	// Duas consultas paradas ainda no mínimo; da 3ª em diante dobra até o máximo.
	assert.deepEqual(intervalos, [60000, 60000, 120000, 240000, 480000, 600000, 600000, 600000]);
	estado = r.intervaloComRecuo(estado, true, config);
	assert.deepEqual(estado, { intervalo: 60000, semMudanca: 0 });
	// Nunca abaixo do mínimo nem acima do máximo, qualquer que seja o estado recebido.
	assert.equal(r.intervaloComRecuo({ intervalo: 1, semMudanca: 10 }, false, config).intervalo, 120000);
	assert.equal(r.intervaloComRecuo({ intervalo: 9e9, semMudanca: 10 }, false, config).intervalo, 600000);
});

test('variouAlemDoLimiar compara cada valor com a referência', () => {
	const referencia = [10, 5, 2, 1];
	assert.equal(r.variouAlemDoLimiar(referencia, [10, 5, 2, 1], 0.05), false);
	assert.equal(r.variouAlemDoLimiar(referencia, [10.4, 5.2, 2.09, 1.04], 0.05), false); // todos abaixo de 5%
	assert.equal(r.variouAlemDoLimiar(referencia, [10, 5, 2, 1.05], 0.05), true);         // um chegou a 5%
	assert.equal(r.variouAlemDoLimiar(referencia, [9.5, 5, 2, 1], 0.05), true);           // queda também conta
	assert.equal(r.variouAlemDoLimiar(null, [10, 5, 2, 1], 0.05), true);                  // 1ª leitura
	assert.equal(r.variouAlemDoLimiar([10, 5], [10, 5, 2, 1], 0.05), true);
	assert.equal(r.variouAlemDoLimiar([0, 1], [0, 1], 0.05), false);
	assert.equal(r.variouAlemDoLimiar([0, 1], [0.1, 1], 0.05), true);
});

test('intervaloPorAtividade vai do mínimo ao máximo conforme as mudanças recentes', () => {
	const config = { minimo: 60000, maximo: 300000, janela: 4 };
	const T = true;
	const F = false;
	assert.equal(r.intervaloPorAtividade([], config), 60000);            // sem histórico: começa rápido
	assert.equal(r.intervaloPorAtividade([F], config), 120000);
	assert.equal(r.intervaloPorAtividade([F, F], config), 180000);
	assert.equal(r.intervaloPorAtividade([F, F, F], config), 240000);
	assert.equal(r.intervaloPorAtividade([F, F, F, F], config), 300000); // parado: 5 min
	assert.equal(r.intervaloPorAtividade([F, F, F, T], config), 240000); // 1 mudança recente
	assert.equal(r.intervaloPorAtividade([F, T, F, T], config), 180000);
	assert.equal(r.intervaloPorAtividade([T, T, T, T], config), 60000);  // agitado: 1 min
	// Só as últimas "janela" consultas contam.
	assert.equal(r.intervaloPorAtividade([T, T, T, T, F, F, F, F], config), 300000);
	assert.equal(r.intervaloPorAtividade([F, F, F, F, T, T, T, T], config), 60000);
});
