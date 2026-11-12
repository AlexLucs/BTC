// Microbenchmarks das funções puras (regras.js e metricas.js).
// Executado por tests/desempenho/test_desempenho_js.py; também roda sozinho:
//   node tests/desempenho/bench_js.js
// Saída: JSON {nome: {n, media, p50, p95, max}} com a duração de UMA chamada em µs.
'use strict';
const r = require('../../regras.js');
const { Metricas } = require('../../metricas.js');

const LOTES = 50;
const AQUECIMENTO = 200;

/** Mede lotes de "porLote" chamadas e devolve a duração média por chamada (µs) de cada lote. */
function bench(funcao, porLote) {
	for (let i = 0; i < AQUECIMENTO; i++) funcao();
	const porChamada = [];
	for (let lote = 0; lote < LOTES; lote++) {
		const inicio = performance.now();
		for (let i = 0; i < porLote; i++) funcao();
		porChamada.push(((performance.now() - inicio) / porLote) * 1000);
	}
	return Metricas.estatisticas(porChamada);
}

const TIPOS = ['maior', 'menor', 'desativado'];
const bruta100 = Array.from({ length: 100 }, (_, i) => ({ id: `id-${i}`, valor: 100000 + i * 1000.5, tipo: TIPOS[i % 3] }));
const alertas100 = r.normalizarLista(bruta100).alertas;
const antiga100 = bruta100.map(({ valor, tipo }) => ({ valor: String(valor), tipo, vazio: 0 })); // formato antigo

const resultados = {
	'normalizarLista(100, já normalizada)': bench(() => r.normalizarLista(alertas100), 200),
	'normalizarLista(100, formato antigo)': bench(() => r.normalizarLista(antiga100), 100),
	'ordenarAlertas(100)': bench(() => r.ordenarAlertas(alertas100), 1000),
	'alertaParaDisparar(100, nenhum dispara)': bench(() => r.alertaParaDisparar(alertas100, 50000), 5000),
	'desativarAposDisparo(100)': bench(() => r.desativarAposDisparo(alertas100, 'id-50'), 2000),
	'existeDuplicado(100)': bench(() => r.existeDuplicado(alertas100, 1, 'maior'), 5000),
	'Metricas.registrar': bench(() => Metricas.registrar('bench', 1.5), 1000),
	'Metricas.medir(função vazia)': bench(() => Metricas.medir('bench2', () => 0), 1000),
};
Metricas.relatorio('descartar');

// Relatório de 5 min típico: ~70 ciclos de preço em 7 medidas.
const montarRelatorio = () => {
	for (let i = 0; i < 70; i++) {
		for (const nome of ['espera', 'processamento', 'render', 'alarmes', 'rede', 'atraso', 'python']) Metricas.registrar(nome, i * 0.123);
	}
	return Metricas.relatorio('bench');
};
resultados['Metricas.relatorio(período típico) + JSON'] = bench(() => JSON.stringify(montarRelatorio()), 20);

process.stdout.write(JSON.stringify(resultados));
