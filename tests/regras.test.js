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
