// Testes do coletor de métricas: node --test tests/metricas.test.js
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { Metricas } = require('../metricas.js');

test('estatisticas usa interpolação linear (mesmos valores de tests/test_metricas.py)', () => {
	assert.deepEqual(Metricas.estatisticas([4, 1, 3, 2, 10]), { n: 5, media: 4, p50: 3, p95: 8.8, max: 10 });
	assert.deepEqual(Metricas.estatisticas([7]), { n: 1, media: 7, p50: 7, p95: 7, max: 7 });
	assert.deepEqual(Metricas.estatisticas([]), { n: 0 });
});

test('medir devolve o resultado, registra a duração e não engole exceções', () => {
	assert.equal(Metricas.medir('t:soma', () => 1 + 1), 2);
	assert.throws(() => Metricas.medir('t:erro', () => { throw new Error('x'); }), /x/);
	const { amostras } = Metricas.relatorio('teste');
	assert.equal(amostras['t:soma'].length, 1);
	assert.equal(amostras['t:erro'].length, 1); // registrada mesmo com erro
});

test('relatorio zera o período, mas mantém os marcos', async () => {
	Metricas.marcar('t:marco');
	Metricas.marcar('t:marco'); // só o primeiro conta
	Metricas.registrar('t:valor', 1.23456, { comTempo: true });
	Metricas.contar('t:contador');
	Metricas.contar('t:contador', 2);
	Metricas.evento('t:evento', { estado: 'a' });
	await Metricas.medirAsync('t:async', async () => 'ok');

	const primeiro = Metricas.relatorio('periodico');
	assert.equal(primeiro.motivo, 'periodico');
	assert.deepEqual(primeiro.amostras['t:valor'], [1.235]);
	assert.equal(primeiro.linhaTempo['t:valor'][0][1], 1.235);
	assert.equal(primeiro.contadores['t:contador'], 3);
	assert.equal(primeiro.eventos[0].tipo, 't:evento');
	assert.equal(primeiro.amostras['t:async'].length, 1);
	assert.ok('t:marco' in primeiro.marcos);

	const segundo = Metricas.relatorio('periodico');
	assert.deepEqual(segundo.amostras, {});
	assert.deepEqual(segundo.contadores, {});
	assert.ok('t:marco' in segundo.marcos);
});

test('registrar ignora valores não finitos e limita as amostras por período', () => {
	Metricas.registrar('t:nan', NaN);
	for (let i = 0; i < 2500; i++) Metricas.registrar('t:muitas', i);
	const { amostras } = Metricas.relatorio('teste');
	assert.equal(amostras['t:nan'], undefined);
	assert.equal(amostras['t:muitas'].length, 2000);
});

test('relatório cabe no limite aceito pelo Python mesmo cheio', () => {
	for (let i = 0; i < 2000; i++) {
		for (const nome of ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']) Metricas.registrar(`t:${nome}`, i * 1.123);
	}
	const tamanho = JSON.stringify(Metricas.relatorio('teste')).length;
	assert.ok(tamanho < 512000, `tamanho ${tamanho}`);
});

test('o substituto de produção tem a mesma interface e não coleta nada', () => {
	const { Metricas: vazio } = require('../metricas_desligadas.js');
	assert.deepEqual(Object.keys(vazio).sort(), Object.keys(Metricas).sort());
	for (const [nome, valor] of Object.entries(Metricas)) {
		assert.equal(typeof vazio[nome], typeof valor, nome);
	}
	assert.equal(vazio.ATIVAS, false);
	assert.equal(vazio.medir('x', () => 42), 42);
	vazio.marcar('x');
	vazio.registrar('x', 1);
	assert.deepEqual(vazio.marcos, {});
	assert.equal(vazio.relatorio('x'), null);
});
