# BTC Status — Contexto do projeto

> Estado atual do projeto (sem histórico). Leia antes de alterar qualquer código.
> Ao mudar arquitetura, arquivos, dependências, convenções ou build, atualize este documento.

## 1. Visão geral

App desktop para **Windows** que mostra em tempo real:
- preço do Bitcoin em BRL e em USDT (Binance), com máxima e mínima de 24 h, variação percentual e seta de direção;
- dólar implícito (BTC/BRL ÷ BTC/USDT) e dólar comercial (AwesomeAPI);
- taxas da rede Bitcoin (mempool.space);
- gráfico de candles BTC/BRL (widget do TradingView), sobreposto à tabela de máximas/mínimas/taxas;
- alertas de preço com som e diálogo.

É uma janela **pywebview** sem moldura (500×810). A página (HTML/CSS/JS) é servida pelo **servidor local do próprio app** (`servidor_local.py`) em `http://127.0.0.1:42001/`. O **1º preço** é buscado pelo Python logo ao abrir, em paralelo com a subida do .NET e do WebView2, e chega **dentro do HTML**. Depois, os preços vêm pelo **WebSocket da Binance** (~1 s), com REST como reserva. Antes de qualquer dado novo, a tela mostra o **último estado salvo**.

A página também abre direto do disco (`file://`) num navegador comum, com funções reduzidas: só Alertas (⏱), Gráfico (⇄) e Pausar, e os alertas ficam no `localStorage`.

A **medição de desempenho** existe só no código-fonte e no build de teste (`-ComMedicao`). O `.exe` de produção não tem medição (ver §3 e §9).

Interface, nomes de funções e variáveis, comentários e mensagens estão em **português (pt-BR)**.

## 2. Ambiente

| Item | Valor |
|---|---|
| Sistema | Windows 10/11 (requer o Microsoft Edge WebView2 Runtime) |
| Python | 3.14, venv em `.venv` na raiz do projeto |
| Pasta do projeto | `%USERPROFILE%\Downloads\Diversos\Bot\btcstatus` |
| pywebview | 6.2.1 (motor EdgeChromium via WinForms/pythonnet; instala o `pythonnet` e o `bottle` sozinho) |
| Build | PyInstaller 6.22.x, modo pasta (onedir), **sem setuptools** (ver §8) |
| Testes | pytest 9.x; Node.js (`node --test`); Playwright ≥ 1.48 com o Microsoft Edge instalado |

**Dependências:**
- `requirements.txt`: só `pywebview>=6.2,<7`. O `bottle`, usado pelo `servidor_local.py`, é dependência obrigatória do pywebview e já é importado por ele.
- `requirements-dev.txt`: acrescenta `pyinstaller`, `pytest` e `playwright>=1.48`.
- `fonttools`/`brotli`: só para regenerar a fonte reduzida (§9). Não estão nos requirements.
- **Não** são usados: `pygetwindow`, `screeninfo`, `pywin32`, jQuery e jquery-confirm.

## 3. Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `BTC_Monitor.py` | **Ponto de entrada.** Busca do 1º preço, log, posição da janela, perfil do WebView2, `ExposedApi` (API chamada pelo JS), servidor local e criação da janela. A medição é opcional (`MEDICAO_ATIVA`) |
| `primeiro_preco.py` | `BuscaPrimeiroPreco`: pede os tickers à Binance numa thread (`urllib`, importado dentro da thread) e entrega o resultado **uma vez só** (`resultado(espera_s)`), descartando-o após 15 s |
| `servidor_local.py` | Aplicativo WSGI (bottle) que o pywebview serve na porta 42001: `/` (HTML com o preload ajustado e o 1º preço embutido), `/preco-inicial` e a lista fechada de arquivos da página, com tipos fixos |
| `alertas_store.py` | Validação (`validar_alertas`) e persistência atômica e com trava (`RepositorioAlertas`) dos alertas. Sem dependências de GUI |
| `topo_janela.py` | Fixar/desafixar no topo via Win32 com `ctypes` (ver §8) |
| `metricas.py` | Registro de métricas em `metricas.jsonl` (`RegistroMetricas`, `validar_relatorio_js`, `estatisticas`). **Fica fora do `.exe` de produção** |
| `index.html` | Estrutura, CSP, pré-conexões, preload da fonte, `<template id="grafico-modelo">` do TradingView, `<dialog>` de avisos |
| `metricas.js` | Coletor de métricas da página (`Metricas`) |
| `metricas_desligadas.js` | Substituto vazio do `metricas.js`, com a mesma interface. **É empacotado com o nome `metricas.js` no `.exe` de produção** |
| `regras.js` | Regras puras, sem DOM: alertas, `existeAlertaAtivo`, `validarEstadoSalvo`, `direcaoPreco`. Compartilhadas entre o navegador e os testes Node |
| `script.js` | Rede (preço inicial, REST e WebSocket), ciclos, exibição, estado salvo, pausa/inatividade, WakeLock, ponte com o Python, gráfico, diálogo e alertas |
| `style.css` | Estilos; cores em variáveis CSS (`--laranja: #f7931a`, etc.) |
| `Roboto.woff2` | Subconjunto "latin" da Roboto (24,6 KB; comando no `style.css` e na §9) |
| `alerta.mp3` | Som do alerta (MP3 mono, 22 kHz, 32 kbps, ~2,1 s, 8,6 KB) |
| `btc-logo.svg`, `btc-logo.ico` | Favicon e ícone do `.exe` |
| `BTC Monitor.spec` | **Única fonte da configuração do build** (produção × medição, exclusão do setuptools) |
| `criar_exe_btc.ps1` | Para se houver um `BTC Monitor.exe` aberto da pasta `dist`; roda os testes e gera o exe. `-SemTestes` pula os testes; `-ComMedicao` gera o build de teste |
| `runbtc.ps1` | Executa o app pelo Python do `.venv`, sem build (com medição) |
| `pytest.ini` | Marcador `desempenho`; esses testes ficam fora da execução padrão |
| `MEDICAO.md` | Guia dos instrumentos de medição |
| `tools/analisar_metricas.py` | Relatório do `metricas.jsonl`: abertura etapa a etapa (com cada arquivo da página), thread ocupada (1b), funções/rede, contadores, janela minimizada |
| `tools/medir_abertura.py` | Abre o app N vezes e mede a abertura; `--comparar <recurso>` alterna aberturas com e sem um recurso (com `--exe`, exige o build `-ComMedicao`) |
| `tools/medir_websocket.py` | Compara as portas 9443 e 443 do stream da Binance (rede real) |
| `tests/test_alertas_store.py`, `tests/test_metricas.py` | Testes Python dos módulos |
| `tests/test_producao.py` | O app sem o módulo de medição: nada medido nem gravado, variáveis `BTC_SEM_*` ignoradas |
| `tests/test_primeiro_preco.py` | Busca do 1º preço com um servidor HTTP local no lugar da Binance |
| `tests/test_servidor_local.py` | Rotas, lista fechada, tipos, `mimetypes` nunca iniciado, preload, preço no HTML, marcos da medição |
| `tests/test_preconnect.py` | Dicas de pré-conexão × CSP e as funções do `medir_abertura.py`/`analisar_metricas.py` |
| `tests/regras.test.js`, `tests/metricas.test.js` | Testes Node (o segundo confere a interface do substituto vazio) |
| `tests/apoio_pagina.py` | Apoio aos testes com Playwright: `RedeSimulada` (REST, WebSocket e TradingView simulados), `ServidorDaPagina` (o `servidor_local` real numa porta livre), fixture `navegador`, timers acelerados |
| `tests/test_pagina_funcional.py` | Testes funcionais da página no Edge, por `file://` e pelo servidor local (rodam no `pytest tests`; pulados se faltar o Playwright ou o navegador) |
| `tests/desempenho/` | Suíte de desempenho (`-m desempenho`); grava `resultados/<data-hora>.json` e compara com a execução anterior |

Ordem no `<head>`: CSP → pré-conexões → preload de `Roboto.woff2` → `style.css` → `metricas.js` → `regras.js` → `script.js` (os três scripts com `defer`). Servido pelo app, o HTML ganha antes do `</head>` o bloco `<script type="application/json" id="preco-inicial">` quando o Python já tem o preço. A inicialização ocorre no `DOMContentLoaded`.

## 4. Arquitetura

### Python (`BTC_Monitor.py`)
- As primeiras linhas guardam `_INICIO_PERF`/`_INICIO_EPOCH`, antes de qualquer outro import. Depois: `main()` → `BUSCA_PRIMEIRO_PRECO.iniciar()` (antes de tudo) → `configurar_log()` → `abrir_janela()`.
- `import metricas` dentro de `try`. Se faltar (build de produção), `MEDICAO_ATIVA = False`, `METRICAS` vira `_SemMedicao` (marcar/medir vazios), a API usada é `ExposedApi`, e os eventos de métricas não são registrados.
- **Variáveis de medição `BTC_SEM_*`** (só valem com `MEDICAO_ATIVA`; `recurso_desligado_na_medicao`): `BTC_SEM_PRECONNECT`, `BTC_SEM_PRECO_PYTHON`, `BTC_SEM_AJUSTE_PRELOAD`, `BTC_SEM_TIPOS_FIXOS`, `BTC_SEM_PRECO_NO_HTML`. Cada uma desliga um recurso para o `medir_abertura.py --comparar`.
- Recursos lidos de `PASTA_RECURSOS` (`sys._MEIPASS` no exe; pasta do script em desenvolvimento).
- Dados do usuário em `%APPDATA%\btcstatus\`:
  - `Alertas.json`;
  - `BTC Monitor.ini` (posição da janela);
  - `btcstatus.log` (rotativo, 512 KB × 3);
  - `webview\` (perfil persistente do WebView2);
  - `metricas.jsonl` (só com medição; rotaciona para `.1` acima de 5 MB).
- **Janela:** `webview.create_window(..., url=aplicativo_wsgi, http_port=42001)`. Com um aplicativo como `url`, o pywebview o serve em `http://127.0.0.1:42001/` (verificado no código do 6.2.1). A origem fixa mantém o `localStorage`.
- **Perfil do WebView2:** `webview.start(user_agent="pywebview", **opcoes_de_armazenamento())`, com `private_mode=False` e `storage_path=PASTA_WEBVIEW`. Isso mantém o cache entre execuções e o `localStorage` (usado pelo estado salvo). Se a pasta não for gravável, o app cai no modo privado e registra no log.
- **Posição inicial:** a salva no `.ini`, se ainda estiver dentro de algum monitor; senão, centralizada no monitor principal (o que tem origem em 0,0). É salva ao fechar (`events.closing`).
- Monitores obtidos de `webview.screens`, e a 1ª leitura inicializa o .NET (~300 ms). **Todas as coordenadas são em pixels lógicos.**
- O pywebview executa **cada chamada da js_api numa thread nova**: as chamadas podem ser simultâneas. A ponte JS→Python usa as mensagens do WebView2 (`chrome.webview.postMessage`), não o servidor HTTP.

**Servidor local (`servidor_local.py`, `criar_aplicativo`):**

| Rota | Resposta |
|---|---|
| `/` e `/index.html` | O `index.html` com o preload da fonte ganhando `crossorigin` (`ajustar_preload_para_http`) e, se a busca já tiver o preço (`resultado(0)`, sem esperar), o bloco `#preco-inicial` (`embutir_preco`, com `<` escapado como `\u003c`) |
| `/preco-inicial` | Espera a busca até 1,5 s: 200 com os tickers (entrega única) ou 204 |
| `/<arquivo>` | Só os de `ARQUIVOS_DA_PAGINA` (nome → tipo); qualquer outro dá 404. `static_file(..., mimetype=tipo)` |

- Todas as respostas levam `Cache-Control: no-cache, no-store, must-revalidate` (iguais às do servidor padrão do pywebview).
- Com medição, um envoltório registra `servidor_pedido:<arquivo>` e `servidor_fim:<arquivo>` (no `close()` da resposta) e `servidor_preco_no_html`.

**`ExposedApi`** — métodos disponíveis no JS via `window.pywebview.api`:

| Método | Retorno | Observação |
|---|---|---|
| `fechar()` / `minimizar()` | — | |
| `centralizar()` | — | No monitor que contém o centro da janela (ou no principal) |
| `definir_topo(fixar: bool)` | `bool` (estado real) | Via `topo_janela`, nunca via `window.on_top` |
| `esta_no_topo()` | `bool` | Lê o estilo real da janela |
| `salvar_alerta(alertas)` | `bool` | Valida no Python; `False` se rejeitado ou se houver erro de disco |
| `carregar_alerta()` | `list` ou `None` | `[]` se o arquivo não existe; `None` se ilegível ou corrompido (o arquivo é preservado como `Alertas.<data-hora>.bak`) |
| `registrar_metricas(relatorio)` | `bool` | **Só em `ExposedApiComMedicao`** (medição ativa). Valida (objeto JSON simples, até 512 KB) e grava |

### JavaScript (`script.js`)

**Abertura** (`DOMContentLoaded`):
1. `capturarElementos()` (cache `ui`), `registrarEventos()`, `configurarBotoesJanela()`.
2. `restaurarEstadoSalvo()`: mostra o último estado e tira a tela de carregamento.
3. Alertas: `sincronizarAlertas()` no app ou `carregarAlertasLocais()` no navegador.
4. `iniciarCiclos()`: a 1ª consulta de preço (`buscarTickers`) usa o preço do HTML, se houver.
5. Gráfico e som só depois do `load` (`aposCarregarPagina`).

**1º preço no app** (`precoPythonPendente`: pywebview e página por `http:`; vale só para a 1ª consulta):
1. `lerPrecoNoHtml()`: lê e remove o bloco `#preco-inicial`. Se houver dados, são usados direto, sem nenhum pedido de rede (contador `primeiro_preco:html`).
2. Sem o bloco: `/preco-inicial` corre contra o REST (`Promise.any`); vale o primeiro com dados (`primeiro_preco:python` ou `primeiro_preco:rest`). Se os dois falharem, vale o erro do REST.
- Fora do app (navegador, `file://`) é sempre o REST.

**Rede de preços:**

| Fonte | Uso | Detalhe |
|---|---|---|
| Python (`primeiro_preco.py`) | 1º preço no app | Mesmo pedido REST, feito no início do `main()`; chega no HTML ou em `/preco-inicial` |
| REST `api/v3/ticker/24hr?symbols=["BTCBRL","BTCUSDT"]` | 1º preço fora do app; reserva | 1 requisição traz os dois pares (peso 2). Ciclo de 3–6 s **só enquanto o WebSocket não está recebendo** |
| WebSocket `wss://stream.binance.com:9443/stream?streams=btcbrl@ticker/btcusdt@ticker` | Fonte principal | Campos `s`, `c`, `P`, `h`, `l`, `E`. A Binance só envia quando algo muda |
| mempool.space `/api/v1/fees/precise` | Taxas | Ciclo de 50–70 s |
| AwesomeAPI `USD-BRL` | Dólar comercial | Ciclo de 60–70 s |

- **Pré-conexões** no `<head>`: `preconnect` com `crossorigin` para `api.binance.com`, `economia.awesomeapi.com.br` e `mempool.space` (o `fetch()` entre origens usa conexões sem credenciais); `preconnect` sem o atributo para `s3.tradingview.com`; `dns-prefetch` para `stream.binance.com`. Cada dica fica numa linha só (a medição as remove por linha).
- **WebSocket:**
  - `wsSaudavel` fica verdadeiro no 1º BTC/BRL. Aí o polling REST para, e a resposta REST que estiver a caminho é descartada.
  - A vigia de silêncio (`WS_LIMITE_SILENCIO` = 10 s) é rearmada por **qualquer** mensagem (BRL ou USDT).
  - Se a conexão fechar ou ficar em silêncio, `perderWebSocket` volta ao REST na hora e reconecta com espera crescente (1 s → 60 s, ×0,5–1 aleatório). `wsTentativas` zera a cada mensagem válida.
  - Pausar fecha a conexão; retomar abre de novo. Sem `WebSocket` disponível, só o REST.
- **Ciclos com `setTimeout` encadeado** via `agendar()`, que também mede o atraso do timer. Nunca há requisições sobrepostas. `cadeiaRestAtiva` indica se há REST de preço agendado ou em andamento.
- `buscarJSON(url)`: timeout de 8 s **combinado** com o `AbortController` do ciclo (`AbortSignal.any`), para que pausar aborte as requisições em andamento; erro em `!response.ok`. Os campos são validados com `paraNumero`.
- **`geracaoCiclo`**: incrementado ao iniciar ou parar. Respostas e mensagens de ciclos encerrados são descartadas (`cicloAtual(geracao)`).
- **Atualizações:**
  - `aplicarBRL`/`aplicarUSD` atualizam a tela; `registrarFalhaBRL`/`registrarFalhaUSD` tratam as falhas.
  - `depoisDeAtualizarPrecos` cuida de dólar, estado, fim do carregamento e alarmes.
  - `agendarChecagemAlarmes` checa 1 s depois e **não reinicia um prazo pendente**.
- **Falhas:** o último valor fica na tela por `CICLOS_ANTES_SEM_DADOS` (3) falhas seguidas e depois vira "Sem Dados" (máx./mín./% viram "—"). Desde a 1ª falha, os alarmes usam NaN. Com `MAX_FALHAS` (10) falhas seguidas do BTC/BRL (REST), o monitoramento pausa como se fosse pausa manual.
- **Seta:** compara o preço com o anterior (`direcaoPreco`). Se o preço se repete, a seta mantém a última direção. A animação usa `element.animate` (sem reflow forçado) e só roda quando o preço muda.
- **Escrita no DOM** via `definirTexto` (só escreve se o texto mudou). `document.title` só é usado fora do app.
- **Pausa:**
  - `pausar(manual)` e `retomar({silenciar})`.
  - A pausa manual (botão ou falhas) só é desfeita com clique no overlay ou no botão.
  - A pausa por inatividade (~17 min sem mouse/teclado) é desfeita com qualquer movimento ou tecla.
  - A inatividade **não é verificada** com a janela fixada no topo **nem com algum alerta ativo** (`existeAlertaAtivo`).
- **Gráfico:**
  - O widget fica no `<template id="grafico-modelo">` e só existe enquanto está visível **e** o monitoramento está ativo (`atualizarGrafico`). Pausar ou ocultar com ⇄ remove o iframe; mostrar clona o template de novo (`document.importNode`). O ⇄ existe no app e no navegador.
  - Na abertura, é montado só depois do `load` e, no app, depois da ponte com o Python (ou do prazo de 5 s), via `requestIdleCallback`.
  - Widget com `"autosize": true`, `"width": "100%"`, `"height": "100%"`; o `#grafico` tem fundo preto opaco e o container do widget ocupa 100% dele.
  - **Posição** (`posicionarGrafico`, chamada ao montar e via `ResizeObserver` em `#conteudoMenosBotoes`): a borda de cima fica sobre a linha separadora (`.separator`) do topo da tabela de máximas/mínimas/taxas; largura = tabela + `SOBRA_GRAFICO` (2 px) de cada lado; altura = proporção 310/440 da largura, nunca antes do fim da tabela e nunca além do fim da janela. Na janela do app (500×810): `top` 449, `left` 24, 452×318 (os mesmos valores estão no CSS).
- **Último estado salvo** (`localStorage['ultimoEstado']`, `{versao, salvoEm, brl, usdt, dolar, taxas}`, validado por `validarEstadoSalvo`):
  - Na abertura, preenche só os textos: preço e horário esmaecidos (`.desatualizado`), com "atualizando… (salvo em …)". `ultimoPrecoBRL` continua NaN, então **nunca dispara alarme**. No app, o preço do HTML o substitui quase no mesmo instante.
  - É gravado no máximo a cada 30 s e também ao fechar, recarregar, ocultar a página ou sair dela (`pagehide`).
- **WakeLock:** pedido ao iniciar e em `visibilitychange`; liberado ao pausar.
- **Ponte com o Python:**
  - Sempre via `chamarApi(metodo, ...args)`, que nunca rejeita e retorna `undefined` fora do pywebview ou em falha.
  - `obterApi()` espera o `pywebviewready` (prazo de 5 s) só enquanto a API não está pronta.
  - A ponte só fica pronta depois do `load` da página, e a injeção dela ocupa a página por ~50 ms (ver §8).
- **Diálogo:** `<dialog id="dialogo">` nativo com fila (`mostrarDialogo`, `aviso(titulo, msg, autoFecharMs)`). O conteúdo é sempre texto. Com auto-fechamento, o botão mostra `OK (n)`.
- Formatadores `Intl` criados uma vez: `formatoBRL`, `formatoUSD`, `formatoTaxa`, `formatoData`, `formatoHora`.
- **Medição:**
  - `Metricas.marcar/registrar/contar/evento/medir` espalhados no `script.js`. No substituto de produção, todos são atalhos vazios.
  - Marcos do 1º preço: `preco_no_html`, `preco_inicial_pedido`, `preco_inicial_resposta`, `preco_inicial_dados`, `precos_continuacao`.
  - O `metricas.js` também registra: a 1ª requisição a cada servidor (`rede1:<host>`); cada arquivo da própria página (`recurso_inicio:`/`recurso:<arquivo>` e o contador `recurso_n:<arquivo>`); e, nos primeiros 2 s, os momentos em que a thread da página ficou ocupada por mais de 15 ms (`bloqueios`, por um timer encadeado). Antes de cada relatório, `takeRecords()` recolhe as entradas pendentes dos observadores.
  - `enviarMetricas(motivo)` sai cedo se `!Metricas.ATIVAS`.
  - Relatórios: abertura (quando já houver o 1º preço novo e o gráfico tiver carregado, ou 15 s após o 1º preço), periódico (5 min), recarga e encerramento (botão x).

**Abertura medida** (`.exe` com medição, ms desde a criação do processo, medianas):

| Etapa | Tempo |
|---|---|
| Imports concluídos / busca do 1º preço começa | ~90 |
| .NET iniciado (1º `webview.screens`) | ~395 |
| Janela exibida | ~475 |
| 1º preço recebido pelo Python | ~495 |
| Página começa a carregar | ~620 |
| Servidor entrega o HTML (com o preço) | ~630 |
| CSS e JS recebidos | ~650 |
| `DOMContentLoaded` | ~660 |
| **1º preço novo na tela** | **~665** |
| `load` da página | ~675 |
| Ponte JS→Python | ~725 |
| Gráfico | ~800 |

## 5. Alertas

**Formato** (igual no `localStorage` e no `Alertas.json`):
```json
[{ "id": "uuid", "valor": 500000, "tipo": "maior" }]
```
- `tipo`: `maior` | `menor` | `desativado`. `valor`: número > 0 com 2 casas. No máximo 100 alertas. `id` com até 64 caracteres.
- Lista sempre ordenada do maior para o menor valor.
- Os dados antigos (sem `id`, valor em texto, campo `vazio`) são migrados por `normalizarLista` (JS) e aceitos por `validar_alertas` (Python).

**Persistência:**
- No JS, a lista `alertas` em memória é a fonte da verdade, normalizada uma vez ao carregar. As listas nunca são alteradas no lugar.
- **No app**, a persistência é o `Alertas.json`: `sincronizarAlertas()` lê no `DOMContentLoaded`, e `gravarAlertas` → `persistirEmDisco` grava. O `localStorage` não é usado para alertas no app.
- **No navegador**, a persistência é o `localStorage['alertasjson']`.
- As gravações em disco passam por uma **fila** (`filaGravacao`), que chega ao Python na ordem das mudanças. O `RepositorioAlertas` usa `threading.Lock` (a js_api roda em threads paralelas) e grava de forma atômica (`.tmp` + `fsync` + `os.replace`).
- Se a leitura do disco falhar: com `null` (arquivo corrompido), o app avisa que guardou uma cópia `.bak`; com `undefined` (falha na chamada), avisa que não conseguiu carregar.

**Regras** (`regras.js`):
- `alertaParaDisparar`: primeiro alerta da lista que satisfaz `maior` (preço ≥ valor) ou `menor` (preço ≤ valor). Desativados são ignorados; preço NaN nunca dispara.
- Um alerta por vez (`alertaAberto`). Ao fechar o diálogo, `desativarAposDisparo` desativa o alerta pelo `id`; se já existir um desativado com o mesmo valor, os dois se fundem. Se o alerta foi apagado nesse meio-tempo, nada é gravado.
- Botão de tipo: Maior → Menor → Desativado → Maior (`PROXIMO_TIPO`), bloqueado se gerar duplicata.
- **Silêncio** (`silenciarAlarmes`): 5 s após o 1º preço novo; 15 s após criar ou alterar um alerta e após retomar manualmente.
- **Tela de alertas:** só a lista (`#listaAlertas`) rola, e o campo e os botões ficam sempre visíveis. A tabela usa um único listener delegado (`data-acao` e `data-id`).

## 6. Segurança

**CSP** no `<meta>` do `index.html`:
- `script-src 'self' file: 'unsafe-eval' https://s3.tradingview.com`. O `'unsafe-eval'` é **obrigatório**: o `api.js` do pywebview cria a ponte com `new Function`. O bloco `#preco-inicial` é `type="application/json"` (não é executado) e não precisa de exceção.
- `style-src 'self' file: 'unsafe-inline'` (pywebview e TradingView injetam `<style>`).
- `font-src`, `img-src` e `media-src`: `'self' file:` (`img-src` também aceita `data:`).
- `connect-src`: `'self'` (para `/preco-inicial`), `https://api.binance.com`, `wss://stream.binance.com:9443`, `https://economia.awesomeapi.com.br`, `https://mempool.space`.
- `frame-src`: `https://*.tradingview.com`, `https://*.tradingview-widget.com`.
- O Chromium só segue uma dica de pré-conexão se alguma diretiva da CSP permitir o endereço (`tests/test_preconnect.py` confere).
- Ao trocar de API, porta ou widget, atualize a CSP e as pré-conexões.

**Outras regras:**
- Sem handlers inline (`onclick`). Todos os eventos são registrados em `registrarEventos()`.
- O Python valida todo dado vindo do JS (`validar_alertas`, `validar_relatorio_js`).
- A `ExposedApi` expõe ao JS todo método **e todo objeto** público (o pywebview percorre atributos recursivamente). Estado interno fica em atributos ou métodos com `_`.
- O servidor local só entrega os arquivos da lista fechada (o servidor padrão do pywebview entregava qualquer arquivo da pasta, inclusive os `.py`). Escuta só em `127.0.0.1`.
- O script do TradingView roda no contexto da página (com acesso à ponte) só enquanto o gráfico está montado.
- O `.exe` de produção não expõe `registrar_metricas`, não grava métricas e ignora as variáveis `BTC_SEM_*`.

## 7. Convenções

- **Python:** snake_case, type hints, `pathlib`, `logging` (nunca `print` no app; o exe não tem console), docstrings em português, 4 espaços.
- **JS:**
  - `'use strict'`, camelCase, `const`/`let`, indentação com **tab**, sem jQuery.
  - Sem `innerHTML` com dados: usar `textContent`/`replaceChildren`/`definirTexto`.
  - Constantes de tempo e URLs no topo do `script.js`.
- **Formatação pt-BR:** moeda via `Intl.NumberFormat('pt-BR')`, taxas com 2 casas e vírgula (`3,50 sat/vB`), data `dd/mm/aa - hh:mm:ss`. A variação percentual usa `toFixed(2)` (ponto decimal).
- **CSS:**
  - Cores em variáveis `:root`.
  - Botões de formulário, tabela e diálogo usam `.botao-padrao`; controles do topo usam `.btns` (ocultos por padrão; `configurarBotoesJanela()` exibe os que se aplicam: no navegador, ⏱ à esquerda, ⇄ ao lado e ■ à direita).
  - Transições só nas propriedades que mudam (sem `all`).
- **Lógica pura nova** (alertas, estado salvo) vai para `regras.js`, com teste em `tests/regras.test.js`.
- **Arquivo novo usado pela página:** entra em `datas` no `.spec` **e** em `ARQUIVOS_DA_PAGINA` (com o tipo) no `servidor_local.py`. `tests/test_servidor_local.py` confere que todo arquivo citado no HTML está na lista.
- **Medição:**
  - Novos pontos de medida usam `Metricas.*`.
  - Ao mudar a interface de `metricas.js`, mude também `metricas_desligadas.js` (`tests/metricas.test.js` confere).
  - Novos marcos de abertura entram em `ETAPAS_ABERTURA` (`tools/analisar_metricas.py`). Marcos do Python e do JS não podem ter o mesmo nome (a linha do tempo junta os dois).
  - Recurso novo da abertura que se queira medir ganha uma variável `BTC_SEM_*` (só com medição) e uma entrada em `COMPARACOES` do `medir_abertura.py`.
  - Toda otimização entra com comparação A/B (`--comparar`); fica só se o ganho se repetir.
- **Testes:**
  - Comportamento de página novo ganha teste em `tests/test_pagina_funcional.py` (rede simulada, timers acelerados 50×). O que depende de `http://` usa `ServidorDaPagina`.
  - Um teste que corrige um defeito deve falhar com o código antigo (ou ter um caso de controle que mostre o defeito).
- **Scripts `.ps1`:** mensagens sem acentos (o PowerShell 5.1 lê UTF-8 sem BOM como ANSI) e finais de linha CRLF.

## 8. Armadilhas conhecidas (não reintroduzir)

1. **Não usar `window.on_top` do pywebview 6.2.1.** O setter altera a propriedade `TopMost` do WinForms pela thread da js_api via pythonnet, segurando o GIL, e trava o app. Usar `topo_janela.py` (ctypes libera o GIL). Pelo mesmo motivo, evitar em métodos da `ExposedApi` qualquer setter de propriedade .NET que não use `Invoke`.
2. **Não fixar a janela com `GetForegroundWindow()`**: pode fixar a janela de outro programa. O handle é obtido por título **e** PID (`encontrar_janela`).
3. **Pixels lógicos:** o pywebview (`x`, `y`, `move`, `screens`) usa pixels lógicos. Não misturar com bibliotecas que retornam pixels físicos.
4. O pywebview **não** sincroniza o título nativo da janela com `document.title`. A janela sempre se chama "BTC Status", e `encontrar_janela` depende disso.
5. `element.style.display` vem vazio quando o valor vem só do CSS. Para ler o valor efetivo, usar `getComputedStyle`. A tela de alertas é aberta com `style.display = 'block'`, por isso o flex fica no `.modal-content`, não no `.modal`.
6. A **AwesomeAPI** sem chave mantém cache de 1 min e tem cota mensal de 100 mil requisições. Não consultar com menos de 60 s de intervalo.
7. Os dois endpoints de taxas da mempool.space (`recommended` e `precise`) têm os mesmos campos; o `precise` traz casas decimais.
8. Nunca reagendar ciclos com `setInterval` dentro de função `async`; usar a cadeia de `setTimeout` com `geracaoCiclo`.
9. O build deve sempre usar o `.spec`. Passar o `.py` com opções ao PyInstaller **sobrescreve** o `.spec`. Não incluir `python3xx.dll` à mão.
10. Arquivo novo usado pela página (JS, CSS, mídia) precisa entrar em `datas` no `.spec` **e** em `ARQUIVOS_DA_PAGINA` no `servidor_local.py` (senão dá 404 no app). Módulos Python importados entram automaticamente. O `metricas.js` é a exceção no `.spec`: entra pelo `a.datas +=` (coletor real ou substituto vazio).
11. **A ponte do pywebview só fica pronta no `load` da página e ocupa a página por ~50 ms.** Ela é injetada no `NavigationCompleted` do WebView2, que acompanha o `load`: o pywebview executa na página ~70 KB de JS dele (`polyfill.js`, `dom_json.js`, `api.js`...). O `load` espera iframes, fontes e mídia: nada pesado pode ser montado antes dele, e o gráfico entra depois da ponte. Tudo o que depender de um evento assíncrono logo depois do `load` (ex.: resposta de um `fetch`) espera essa injeção; por isso o 1º preço vem no HTML.
12. **As chamadas da js_api rodam em threads paralelas.** Todo recurso compartilhado (como o `Alertas.json`) precisa de trava no Python, e a ordem das gravações é garantida pela fila no JS.
13. **Handlers de eventos do pywebview:**
    - um handler com parâmetros recebe os argumentos do evento (use funções sem parâmetros);
    - **retornar `False` cancela a ação** em `closing`, `initialized`, `before_show` e `before_load`;
    - os handlers rodam em threads.
14. **`private_mode=True` (padrão do pywebview)** apaga o perfil a cada execução (sem cache) e, ao fechar, espera até 3 s pelo processo do navegador. O app usa `private_mode=False` com `storage_path`.
15. **ctypes no Windows 64 bits:** sempre declarar `argtypes`/`restype` de funções que usam handles. Sem isso, o `HANDLE` volta truncado em 32 bits e a chamada falha (era o caso do `GetCurrentProcess`).
16. **Build sem setuptools:** o `cffi` só o usa para compilar, mas o runtime hook do PyInstaller o importaria em toda abertura (~100 ms). Excluir `setuptools`, `pkg_resources` e `_distutils_hack`. **Não** excluir `distutils`: quebra o build (o hook do PyInstaller o redireciona).
17. **Preload da fonte: `file://` SEM `crossorigin`, `http` COM.** Com a regra trocada, o Chromium descarta o preload e lê a fonte duas vezes. O `index.html` vem sem o atributo (navegador e testes por `file://`), e o `servidor_local.py` o acrescenta procurando a linha exata `PRELOAD_FONTE`: não mudar essa linha do HTML sem mudar a constante. Testes: `test_preload_da_fonte_e_aproveitado` (`file://`) e `test_preload_da_fonte_pelo_servidor_local` (`http`).
18. **O BTC/BRL fica em silêncio no WebSocket** por 5 a 16 s quando não há negociação: a Binance só envia o ticker que mudou. A vigia de silêncio precisa contar qualquer par (o USDT chega a cada ~1 s), senão gera quedas e reconexões falsas.
19. **Estrangulamento de timers do Chromium com a página oculta:** a página recebe `hidden` ao minimizar. Timers aninhados (nível ≥ 5) passam a rodar no máximo 1 vez por minuto. Os ciclos daqui reagendam depois de um `await fetch`, o que zera o aninhamento, e por isso só sofrem o alinhamento de ~1 s. Não reagendar ciclos críticos diretamente de dentro de um callback de timer. Mensagens do WebSocket não são estranguladas.
20. **Widget do TradingView:** o script `embed-widget-*.js` lê o JSON do próprio `<script>` via `currentScript`. Para recriá-lo, clonar o `<template>` (`document.importNode`). `innerHTML` não executa o script. Não fixar o tamanho do widget nem ampliá-lo com `transform: scale`: a proporção da tabela muda com a janela e sobra texto nas bordas; usar `autosize` dentro do quadro opaco posicionado sobre a tabela.
21. **Playwright (testes):**
    - no handler de `route_web_socket` (API síncrona), chamar `ws.close()` **trava**;
    - registrar `on_close` gera `KeyError: 'code'` na biblioteca. Fechar de fora do handler e com `code`;
    - um `Proxy` usado como `window.pywebview.api` não pode responder `then`, senão vira "thenable" e as Promises nunca resolvem;
    - no `nova_pagina`, a rota registrada por último tem precedência.
22. **Medir o `.exe` exige o build `-ComMedicao`.** O `.exe` de produção não gera relatório, e o `medir_abertura.py --exe` avisa.
23. **Porta fixa 42001.** O `localStorage` (último estado salvo) pertence à origem `http://127.0.0.1:42001`: mudar a porta perde o estado salvo. O servidor do pywebview (wsgiref) abre a porta mesmo ocupada (no Windows, `SO_REUSEADDR`), e a página pode vir de **outra instância aberta** (ex.: o `.exe` de produção durante uma medição): sem medição, sem os arquivos novos, ou 404. O `medir_abertura.py` para se a porta estiver ocupada.
24. **O `servidor_local.py` depende de duas opções do `create_window` do pywebview 6.2.1:** um aplicativo WSGI como `url` (`is_app`) e `http_port`. Ao atualizar o pywebview, conferir no código dele (`window._initialize` e `http.BottleServer.start_server`) que continuam iguais; os testes da página não cobrem o servidor do pywebview.
25. **Nunca deixar o bottle adivinhar o tipo dos arquivos.** Sem `mimetype`, o `static_file` chama `mimetypes.guess_type`, e a 1ª chamada do processo lê a tabela de tipos do registro do Windows (~22 ms). Os pedidos simultâneos da abertura faziam isso cada um, em fila no GIL, e seguravam CSS e JS por ~60 ms. O registro também pode trazer tipos errados (ex.: `.js` como `text/plain`). `test_entregar_arquivos_nao_inicia_o_mimetypes` confere.
26. **`TCP_NODELAY` no servidor local não traz ganho** (medido): a demora dos arquivos era o `mimetypes`, não a rede local. Não reintroduzir, inclusive porque exige acessar o socket por um detalhe interno do wsgiref.
27. **O build falha se houver um `BTC Monitor.exe` aberto da pasta `dist`** (ele trava o `ClrLoader.dll`, e o PyInstaller não consegue apagar a pasta). O `criar_exe_btc.ps1` confere antes e para; não encerra o processo sozinho.

## 9. Comandos

```powershell
# Dependências
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Executar sem build (com medição)
.\runbtc.ps1

# Testes (inclui os funcionais de página; os de desempenho ficam fora)
.venv\Scripts\python.exe -m pytest tests
node --test tests/regras.test.js tests/metricas.test.js

# Suíte de desempenho (BTC_SEM_ORCAMENTO=1 só mede; BTC_REDE_REAL=1 usa a internet)
.venv\Scripts\python.exe -m pytest tests\desempenho -m desempenho

# Gerar o exe de PRODUÇÃO (roda os testes antes; -SemTestes para pular)
.\criar_exe_btc.ps1
# Build de TESTE, com medição (para tools\medir_abertura.py --exe)
.\criar_exe_btc.ps1 -ComMedicao
# Comparação A/B com o setuptools no build
$env:BTC_MANTER_SETUPTOOLS = "1"; .\criar_exe_btc.ps1; Remove-Item Env:BTC_MANTER_SETUPTOOLS
# Encerrar um BTC Monitor aberto da pasta dist (o build para se houver um)
Get-Process | Where-Object { $_.Path -like "*\dist\BTC Monitor\*" } | Stop-Process -Force

# Medição (ver MEDICAO.md); feche todos os BTC Status antes
.venv\Scripts\python.exe tools\analisar_metricas.py --ultimas 3
.venv\Scripts\python.exe tools\medir_abertura.py --vezes 10
.venv\Scripts\python.exe tools\medir_abertura.py --vezes 10 --exe "dist\BTC Monitor\BTC Monitor.exe"
# Com e sem um recurso: preconnect | preco-python | preload-fonte | tipos-fixos | preco-no-html
.venv\Scripts\python.exe tools\medir_abertura.py --comparar preco-no-html --vezes 20 --exe "dist\BTC Monitor\BTC Monitor.exe"
.venv\Scripts\python.exe tools\medir_websocket.py --vezes 10

# Regenerar a fonte reduzida (a partir da Roboto Regular completa; pip install fonttools brotli)
pyftsubset Roboto-original.woff2 --unicodes="U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD" --layout-features='*' --flavor=woff2 --output-file=Roboto.woff2
```
- Saída: `dist\BTC Monitor\BTC Monitor.exe`. Para distribuir, copiar a pasta `dist\BTC Monitor` inteira.
- No PowerShell, abrir um executável com espaço no caminho: `& ".\dist\BTC Monitor\BTC Monitor.exe"`.
- **Depuração:**
  - Erros do Python vão para `%APPDATA%\btcstatus\btcstatus.log` (inclui "1º preço pelo Python falhou"). Erros da página não vão para o log.
  - Para ver os erros da página, acrescentar temporariamente `debug=True` ao `webview.start(...)` em `abrir_janela()`, o que abre o DevTools.
  - No navegador, `Metricas.resumo()` no console mostra as medidas do período.

## 10. Verificação manual após mudanças

- [ ] A tela abre já com o preço novo (sem ficar no estado salvo esmaecido); sem internet, mostra o último estado salvo e depois "Sem Dados"
- [ ] O preço muda a cada ~1 s (WebSocket) e a seta só muda quando o preço muda
- [ ] Criar, alternar tipo e apagar alerta; os alertas persistem após fechar e reabrir; com muitos alertas, só a lista rola
- [ ] Um alerta dispara (som + diálogo) e fica desativado após fechar o diálogo
- [ ] Pausar/retomar: o overlay aparece, o gráfico some, a rede para e tudo volta ao retomar
- [ ] Fixar/desafixar no topo; ↻ com a janela fixada desafixa e recarrega
- [ ] Centralizar, minimizar, fechar (a posição é restaurada ao reabrir)
- [ ] O gráfico aparece cobrindo a tabela inteira, com a borda de cima sobre a linha separadora, e o botão ⇄ o oculta e o mostra de novo; no navegador, idem em vários tamanhos de janela
- [ ] A fonte Roboto aparece normalmente
- [ ] O `.exe` de produção abre e não cria nem altera o `%APPDATA%\btcstatus\metricas.jsonl`

### Em aberto (próximos passos)

Referência: a tabela "Abertura medida" na §4. O 1º preço já aparece logo depois do `DOMContentLoaded`; o que sobra depende de a página começar mais cedo ou mexe só na ponte, no gráfico e no WebSocket.

1. **Cache dos arquivos da página.** O servidor local envia `no-store`. Trocar por `no-cache` com validação pela data do arquivo (304) permitiria ao WebView2 guardar o `script.js` já compilado entre aberturas. Ganho estimado pequeno (5–20 ms na execução dos scripts); medir com `--comparar`.
2. **Rodar `tools\medir_websocket.py`** e decidir a porta (9443 × 443). O WebSocket conecta só em ~1,5–2 s e é o que traz o 2º preço em diante.
3. **Imports do Python** (~40 ms entre o bootloader e os imports): medir com `python -X importtime` antes de propor algo.
4. **Injeção da ponte pelo pywebview** (~50 ms de JS na página depois do `load`): só reduzível alterando o comportamento interno do pywebview (ex.: não injetar o `polyfill.js`). Afeta a ponte e o gráfico, não o preço. Alto risco em atualizações.
5. **Medir a latência dos domínios públicos da Binance** (`data-api.binance.vision` / `data-stream.binance.vision`). Hoje só afetaria o REST de reserva e os ciclos seguintes. Verificar antes se os domínios existem e estão em uso.
6. **Medir CPU e memória do widget do TradingView** (o processo `msedgewebview2` dele). Se for alto, avaliar trocá-lo por um gráfico próprio com os candles da Binance.
7. *(Estrutural)* A subida do .NET (~305 ms) e do WebView2 (~220 ms até a página começar) é o que hoje segura a página e o 1º preço. Só cai trocando o pywebview por um hospedeiro de WebView2 sem .NET.
