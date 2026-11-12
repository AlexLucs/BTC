'use strict';

// ---------------------------------------------------------------------------
// Substituto vazio do metricas.js na versão de PRODUÇÃO.
//
// O "BTC Monitor.spec" empacota este arquivo com o nome metricas.js quando o
// build é feito sem -ComMedicao: mesma interface, nenhuma coleta, nenhum envio.
// As chamadas Metricas.* de script.js viram atalhos (medir só executa a função).
// Ao mudar a interface de metricas.js, mude aqui também (tests/metricas.test.js confere).
// ---------------------------------------------------------------------------

const Metricas = Object.freeze({
	ATIVAS: false,
	marcos: Object.freeze({}),
	marcar() {},
	registrar() {},
	contar() {},
	evento() {},
	medir: (_nome, funcao) => funcao(),
	medirAsync: (_nome, funcao) => funcao(),
	estatisticas: () => ({ n: 0 }),
	observar() {},
	relatorio: () => null,
	resumo: () => null,
});

if (typeof module !== 'undefined' && module.exports) {
	module.exports = { Metricas };
}
