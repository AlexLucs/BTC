'use strict';

// ---------------------------------------------------------------------------
// Métricas de desempenho da página.
//
// Coleta marcos da abertura, durações de funções, tempos de rede (Resource
// Timing), tarefas longas (> 50 ms), memória do JS e eventos de visibilidade.
// Os dados de cada período são enviados ao Python por script.js (enviarMetricas)
// e gravados em %APPDATA%\btcstatus\metricas.jsonl. Análise:
// tools/analisar_metricas.py. No navegador, use Metricas.resumo() no console.
//
// Carregado antes de script.js; sem dependências. Também importado pelos testes no Node.
// ---------------------------------------------------------------------------

const Metricas = (() => {
	const ATIVAS = true;               // false desliga toda a coleta (as funções viram atalhos)
	const MAX_AMOSTRAS = 2000;         // por nome e por período
	const MAX_EVENTOS = 500;
	const MAX_TAREFAS_LONGAS = 500;
	const INTERVALO_MEMORIA = 60000;

	let amostras = new Map();          // nome -> number[] (ms)
	let linhaTempo = new Map();        // nome -> [epochMs, valor][] (para correlacionar com eventos)
	let contadores = new Map();        // nome -> inteiro
	let eventos = [];                  // {t: epochMs, tipo, ...}
	let tarefasLongas = [];            // [epochMs, duração]
	const marcos = {};                 // nome -> ms desde performance.timeOrigin (só o 1º)

	const agora = () => performance.now();
	const epoch = () => performance.timeOrigin + performance.now();
	const arredondar = valor => Math.round(valor * 1000) / 1000;

	function marcar(nome) {
		if (ATIVAS && !(nome in marcos)) marcos[nome] = arredondar(agora());
	}

	/** Guarda uma duração (ms). comTempo também a registra com o instante, para a linha do tempo. */
	function registrar(nome, valor, { comTempo = false } = {}) {
		if (!ATIVAS || !Number.isFinite(valor)) return;
		const lista = amostras.get(nome) ?? [];
		if (lista.length < MAX_AMOSTRAS) lista.push(arredondar(valor));
		amostras.set(nome, lista);
		if (comTempo) {
			const pontos = linhaTempo.get(nome) ?? [];
			if (pontos.length < MAX_AMOSTRAS) pontos.push([Math.round(epoch()), arredondar(valor)]);
			linhaTempo.set(nome, pontos);
		}
	}

	function contar(nome, quantidade = 1) {
		if (ATIVAS) contadores.set(nome, (contadores.get(nome) ?? 0) + quantidade);
	}

	function evento(tipo, dados = {}) {
		if (ATIVAS && eventos.length < MAX_EVENTOS) eventos.push({ t: Math.round(epoch()), tipo, ...dados });
	}

	/** Executa a função e registra quanto ela levou. */
	function medir(nome, funcao) {
		if (!ATIVAS) return funcao();
		const inicio = agora();
		try {
			return funcao();
		} finally {
			registrar(nome, agora() - inicio);
		}
	}

	async function medirAsync(nome, funcao) {
		if (!ATIVAS) return funcao();
		const inicio = agora();
		try {
			return await funcao();
		} finally {
			registrar(nome, agora() - inicio);
		}
	}

	/** n, média, p50, p95 e máximo (interpolação linear, igual a metricas.py). */
	function estatisticas(valores) {
		if (!valores?.length) return { n: 0 };
		const ordenados = [...valores].sort((a, b) => a - b);
		const percentil = p => {
			const posicao = (ordenados.length - 1) * p;
			const abaixo = Math.floor(posicao);
			const acima = Math.ceil(posicao);
			return ordenados[abaixo] + (ordenados[acima] - ordenados[abaixo]) * (posicao - abaixo);
		};
		const soma = ordenados.reduce((total, valor) => total + valor, 0);
		return {
			n: ordenados.length,
			media: arredondar(soma / ordenados.length),
			p50: arredondar(percentil(0.5)),
			p95: arredondar(percentil(0.95)),
			max: ordenados[ordenados.length - 1],
		};
	}

	function memoriaMb() {
		const bytes = performance.memory?.usedJSHeapSize; // só no Chromium (WebView2)
		return Number.isFinite(bytes) ? arredondar(bytes / 1048576) : null;
	}

	function observarTipo(tipo, aoReceber) {
		const suportados = typeof PerformanceObserver === 'function' ? PerformanceObserver.supportedEntryTypes ?? [] : [];
		if (!suportados.includes(tipo)) return;
		new PerformanceObserver(lista => lista.getEntries().forEach(aoReceber)).observe({ type: tipo, buffered: true });
	}

	/** Liga os observadores do navegador. Chamar uma vez, o mais cedo possível. */
	function observar() {
		if (!ATIVAS || typeof document === 'undefined') return;

		observarTipo('navigation', entrada => {
			marcos.nav_resposta_fim = arredondar(entrada.responseEnd);
			marcos.nav_dom_interativo = arredondar(entrada.domInteractive);
			marcos.nav_dom_pronto = arredondar(entrada.domContentLoadedEventEnd);
			if (entrada.loadEventEnd > 0) marcos.nav_load = arredondar(entrada.loadEventEnd);
		});
		observarTipo('paint', entrada => { marcos[entrada.name] = arredondar(entrada.startTime); });
		// Para entender a distância entre o DOMContentLoaded e a primeira pintura:
		// quando sai o 1º quadro e quando termina o carregamento da fonte (Roboto).
		if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => marcar('primeiro_quadro'));
		document.fonts?.addEventListener?.('loadingdone', () => marcar('fontes_prontas'));
		observarTipo('longtask', entrada => {
			if (tarefasLongas.length < MAX_TAREFAS_LONGAS) {
				tarefasLongas.push([Math.round(performance.timeOrigin + entrada.startTime), arredondar(entrada.duration)]);
			}
		});
		observarTipo('resource', entrada => {
			if (entrada.initiatorType !== 'fetch') return;
			try {
				registrar(`rede:${new URL(entrada.name).host}`, entrada.duration);
			} catch {
				// URL inválida: ignora
			}
		});
		// O Resource Timing guarda no máximo 250 entradas; o observador já recebeu cada uma.
		performance.addEventListener?.('resourcetimingbufferfull', () => performance.clearResourceTimings());

		document.addEventListener('visibilitychange', () => evento('visibilidade', { estado: document.visibilityState }));
		window.addEventListener('focus', () => evento('foco', { estado: 'ganhou' }));
		window.addEventListener('blur', () => evento('foco', { estado: 'perdeu' }));
		window.addEventListener('online', () => evento('rede', { estado: 'online' }));
		window.addEventListener('offline', () => evento('rede', { estado: 'offline' }));

		setInterval(() => {
			const mb = memoriaMb();
			if (mb !== null) registrar('memoria_mb', mb, { comTempo: true });
		}, INTERVALO_MEMORIA);
	}

	/**
	 * Monta o relatório do período e começa um período novo.
	 * Os marcos da abertura seguem em todos os relatórios (são poucos).
	 */
	function relatorio(motivo) {
		const dados = {
			versao: 1,
			motivo,
			timeOrigin: arredondar(performance.timeOrigin),
			enviadoEm: Math.round(epoch()),
			visibilidade: typeof document === 'undefined' ? null : document.visibilityState,
			memoriaMb: memoriaMb(),
			marcos: { ...marcos },
			amostras: Object.fromEntries(amostras),
			linhaTempo: Object.fromEntries(linhaTempo),
			contadores: Object.fromEntries(contadores),
			eventos,
			tarefasLongas,
		};
		amostras = new Map();
		linhaTempo = new Map();
		contadores = new Map();
		eventos = [];
		tarefasLongas = [];
		return dados;
	}

	/** Para o console do navegador: estatísticas do período atual, sem zerar. */
	function resumo() {
		const linhas = {};
		for (const [nome, valores] of amostras) linhas[nome] = estatisticas(valores);
		if (typeof console.table === 'function') console.table(linhas);
		return { marcos: { ...marcos }, funcoes: linhas, contadores: Object.fromEntries(contadores), tarefasLongas: tarefasLongas.length };
	}

	return { ATIVAS, marcos, marcar, registrar, contar, evento, medir, medirAsync, estatisticas, observar, relatorio, resumo };
})();

if (typeof module !== 'undefined' && module.exports) {
	module.exports = { Metricas };
}
