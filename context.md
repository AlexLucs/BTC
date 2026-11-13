# BTC Status — Contexto do projeto

> Estado atual do projeto (sem histórico). Leia antes de alterar qualquer código.
> Ao mudar arquitetura, arquivos, dependências, convenções ou build, atualize este documento.

## 1. Visão geral

App desktop para **Windows** que mostra em tempo real:
- preço do Bitcoin em BRL e em USDT (Binance), com máxima e mínima de 24 h, variação percentual e seta de direção;
- dólar implícito (BTC/BRL ÷ BTC/USDT) e dólar comercial (AwesomeAPI);
- taxas da rede Bitcoin (mempool.space);
- gráfico de candles BTC/BRL (widget do TradingView), sobreposto à tabela de máximas/mínimas/taxas, **oculto ao abrir** e exibido pelo botão ⇄;
- alertas de preço com som e diálogo.

É uma janela **pywebview** sem moldura com dois modos:
- **completo**, 500×810;
- **compacto**, 500×388: sem logo, tabela e gráfico, com máxima e mínima em BRL numa linha de rodapé.

O botão ⊟/⊞ alterna os modos. O modo é lembrado entre execuções.

A janela é arrastada pelo próprio app, não pelo `easy_drag` do pywebview, e tem **bordas magnéticas**: ao chegar a até 20 px de uma borda da **área livre** do monitor (sem a barra de tarefas), ela gruda nessa borda. A posição ao abrir, o ▣ e a troca de modo também respeitam a área livre.

A página (HTML/CSS/JS) é servida pelo **servidor local do próprio app** (`servidor_local.py`) em `http://127.0.0.1:42001/`. O **1º preço** é buscado pelo Python logo ao abrir, em paralelo com a subida do .NET e do WebView2, e chega **dentro do HTML**. Depois, os preços vêm pelo **WebSocket da Binance** (~1 s), com REST como reserva. Antes de qualquer dado novo, a tela mostra o **último estado salvo**, esmaecido campo a campo até a fonte de cada um responder.

A página também abre direto do disco (`file://`) num navegador comum, com funções reduzidas:
- botões: só Alertas (⏱), Gráfico (⇄), Modo compacto (⊟/⊞) e Pausar;
- os alertas e o modo compacto ficam no `localStorage`;
- o modo compacto muda só o layout (a janela do navegador não muda de tamanho);
- não há arraste da janela.

A **medição de desempenho** existe só no código-fonte e no build de teste (`-ComMedicao`). O `.exe` de produção não tem medição (ver §3 e §9).

Interface, nomes de funções e variáveis, comentários e mensagens estão em **português (pt-BR)**.

## 2. Ambiente

| Item | Valor |
|---|---|
| Sistema | Windows 10/11 (requer o Microsoft Edge WebView2 Runtime) |
| Python | 3.14, venv em `.venv` na raiz do projeto |
| Pasta do projeto | `%USERPROFILE%\Downloads\Diversos\Bot\btcstatus` |
| pywebview | 6.2.1 (motor EdgeChromium via WinForms/pythonnet; instala o `pythonnet` e o `bottle` sozinho; traz o SDK do WebView2 1.0.3856.49) |
| Build | PyInstaller 6.22.x, modo pasta (onedir), **sem setuptools** (ver §8) |
| Testes | pytest 9.x; Node.js (`node --test`); Playwright ≥ 1.48 com o Microsoft Edge instalado |

**Dependências:**
- `requirements.txt`: só `pywebview>=6.2,<7`. O `bottle`, usado pelo `servidor_local.py`, é dependência obrigatória do pywebview e já é importado por ele.
- `requirements-dev.txt`: acrescenta `pyinstaller`, `pytest` e `playwright>=1.48`.
- `fonttools`/`brotli`: só para regenerar a fonte reduzida (§9). Não estão nos requirements.
- **Não** são usados: `pygetwindow`, `screeninfo`, `pywin32`, jQuery e jquery-confirm. As chamadas ao Win32 são feitas com `ctypes` (`topo_janela.py`, `bordas_janela.py`).

## 3. Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `BTC_Monitor.py` | **Ponto de entrada.** Busca do 1º preço, log, posição (na área livre do monitor), tamanho e modo da janela (`.ini`), perfil do WebView2, `ExposedApi` (API chamada pelo JS, inclusive `iniciar_arraste`), servidor local, criação da janela (`easy_drag=False`) e correção do tamanho inicial (`registrar_ajuste_de_tamanho`). A medição é opcional (`MEDICAO_ATIVA`) |
| `primeiro_preco.py` | `BuscaPrimeiroPreco`: pede os tickers à Binance numa thread (`urllib`, importado dentro da thread, timeout de 5 s) e entrega o resultado **uma vez só** (`resultado(espera_s)`), descartando-o após 15 s |
| `servidor_local.py` | Aplicativo WSGI (bottle) que o pywebview serve na porta 42001: `/` (HTML com o preload ajustado, a classe `compacto` no `<html>` se a janela estiver no modo compacto e o 1º preço embutido), `/preco-inicial` e a lista fechada de arquivos da página, com tipos fixos |
| `alertas_store.py` | Validação (`validar_alertas`) e persistência atômica e com trava (`RepositorioAlertas`) dos alertas. Sem dependências de GUI |
| `topo_janela.py` | Fixar/desafixar no topo via Win32 com `ctypes` (ver §8); `encontrar_janela` (título + PID) também serve ao arraste |
| `bordas_janela.py` | Arraste da janela com bordas magnéticas e área livre dos monitores: `Retangulo`, `encaixar`/`encaixar_eixo` (lógica pura), `area_livre` (a partir de `webview.screens`), `acompanhar_arraste` (laço com as funções do sistema recebidas por parâmetro), `Arrastador` (thread + trava) e `SistemaWin32` (ctypes). Sem dependências de GUI |
| `metricas.py` | Registro de métricas em `metricas.jsonl` (`RegistroMetricas`, `validar_relatorio_js`, `estatisticas`). **Fica fora do `.exe` de produção** |
| `index.html` | Estrutura, CSP, pré-conexões, preload da fonte, `#conteudo` com a classe `regiao-arraste` (onde se arrasta a janela), botões da barra (inclusive `#compacto-btn`), `#info-dolar` com duas partes (`#dolar-implicito` e `#dolar-comercial`), `#info-seta` já com ↔, `#info-faixa` (rodapé do modo compacto), `<div id="grafico" hidden>` (o atributo `hidden` define o padrão de abertura do gráfico: oculto), `<template id="grafico-modelo">` do TradingView, `<dialog>` de avisos (fora do `#conteudo`) |
| `metricas.js` | Coletor de métricas da página (`Metricas`) |
| `metricas_desligadas.js` | Substituto vazio do `metricas.js`, com a mesma interface. **É empacotado com o nome `metricas.js` no `.exe` de produção** |
| `regras.js` | Regras puras, sem DOM: alertas, `existeAlertaAtivo`, `validarEstadoSalvo`, `direcaoPreco`. Compartilhadas entre o navegador e os testes Node |
| `script.js` | Rede (preço inicial, REST e WebSocket), ciclos, exibição, estado salvo e esmaecimento, falhas, pausa/inatividade, WakeLock, ponte com o Python, pedido de arraste, gráfico, modo compacto, diálogo e alertas |
| `style.css` | Estilos; cores em variáveis CSS (`--laranja: #f7931a`, etc.); `.regiao-arraste` (layout do `#conteudo`: `position: fixed`, altura total); regras do modo compacto (`html.compacto`) |
| `Roboto.woff2` | Subconjunto "latin" da Roboto (24,6 KB; comando no `style.css` e na §9) |
| `alerta.mp3` | Som do alerta (MP3 mono, 22 kHz, 32 kbps, ~2,1 s, 8,6 KB) |
| `btc-logo.svg`, `btc-logo.ico` | Favicon e ícone do `.exe` |
| `BTC Monitor.spec` | **Única fonte da configuração do build** (produção × medição, exclusão do setuptools) |
| `criar_exe_btc.ps1` | Para se houver um `BTC Monitor.exe` aberto da pasta `dist`; roda os testes e gera o exe. `-SemTestes` pula os testes; `-ComMedicao` gera o build de teste |
| `runbtc.ps1` | Executa o app pelo Python do `.venv`, sem build (com medição) |
| `pytest.ini` | Marcador `desempenho`; esses testes ficam fora da execução padrão |
| `MEDICAO.md` | Guia dos instrumentos de medição |
| `tools/analisar_metricas.py` | Relatório do `metricas.jsonl`: abertura etapa a etapa (com cada arquivo da página e o marco `tamanho_ajustado`), thread ocupada (1b), funções/rede, contadores, janela minimizada |
| `tools/medir_abertura.py` | Abre o app N vezes e mede a abertura; `--comparar <recurso>` alterna aberturas com e sem um recurso (com `--exe`, exige o build `-ComMedicao`) |
| `tools/medir_websocket.py` | Compara as portas 9443 e 443 do stream da Binance (rede real) |
| `tests/test_alertas_store.py`, `tests/test_metricas.py` | Testes Python dos módulos |
| `tests/test_bordas_janela.py` | Encaixe (cada borda, cantos, limite de 20 px, empate, vários monitores, barra de tarefas em lados diferentes), `area_livre` (com e sem `frame`, `frame` incoerente), laço de arraste com um sistema falso, `Arrastador` (2º pedido ignorado, erros no log, trava liberada) e, só no Windows, o `SistemaWin32` real |
| `tests/test_janela.py` | Posição dentro do monitor e da área livre (barra de tarefas), centralizar pela altura do modo e na área livre, `.ini` (posição e modo), `definir_compacto` (topo fixo, correção de borda, falha), ajuste de tamanho no `shown`, `iniciar_arraste`, `create_window` com `easy_drag=False` (via `abrir_janela` com um pywebview falso) e o `index.html` sem `pywebview-drag-region`, com uma janela falsa (sem abrir janela) |
| `tests/test_producao.py` | O app sem o módulo de medição: nada medido nem gravado, variáveis `BTC_SEM_*` ignoradas |
| `tests/test_primeiro_preco.py` | Busca do 1º preço com um servidor HTTP local no lugar da Binance |
| `tests/test_servidor_local.py` | Rotas, lista fechada, tipos, `mimetypes` nunca iniciado, preload, preço no HTML, classe do modo compacto (`TAG_HTML`), marcos da medição |
| `tests/test_preconnect.py` | Dicas de pré-conexão × CSP e as funções do `medir_abertura.py`/`analisar_metricas.py` |
| `tests/regras.test.js`, `tests/metricas.test.js` | Testes Node (o segundo confere a interface do substituto vazio) |
| `tests/apoio_pagina.py` | Apoio aos testes com Playwright: `RedeSimulada` (REST, WebSocket e TradingView simulados), `ServidorDaPagina` (o `servidor_local` real numa porta livre, aceita as opções do `criar_aplicativo`, como `modo_compacto`), fixture `navegador`, timers acelerados |
| `tests/test_pagina_funcional.py` | Testes funcionais da página no Edge, por `file://` e pelo servidor local (rodam no `pytest tests`; pulados se faltar o Playwright ou o navegador). `com_grafico_ao_abrir(contexto)` abre a página com o gráfico visível; `contadores()`/`marcos_da_pagina()` juntam os valores atuais com os dos relatórios já entregues (ver §7). Cobre também modo compacto, seta, esmaecimento, falhas por fonte, inatividade após alarme e o pedido de arraste (só fora dos controles e das barras de rolagem; nunca fora do app) |
| `tests/desempenho/` | Suíte de desempenho (`-m desempenho`); grava `resultados/<data-hora>.json` e compara com a execução anterior. A abertura e os ciclos são medidos sem o gráfico (padrão); `test_grafico_e_tela_de_alertas` o abre pelo ⇄ |

Ordem no `<head>`: CSP → pré-conexões → preload de `Roboto.woff2` → `style.css` → `metricas.js` → `regras.js` → `script.js` (os três scripts com `defer`). Servido pelo app, o HTML ganha antes do `</head>` o bloco `<script type="application/json" id="preco-inicial">` quando o Python já tem o preço. A inicialização ocorre no `DOMContentLoaded`.

## 4. Arquitetura

### Python (`BTC_Monitor.py`)
- As primeiras linhas guardam `_INICIO_PERF`/`_INICIO_EPOCH`, antes de qualquer outro import. Depois: `main()` → `BUSCA_PRIMEIRO_PRECO.iniciar()` (antes de tudo) → `configurar_log()` → `abrir_janela()`.
- `import metricas` dentro de `try`. Se faltar (build de produção), `MEDICAO_ATIVA = False`, `METRICAS` vira `_SemMedicao` (marcar/medir vazios), a API usada é `ExposedApi`, e os eventos de métricas não são registrados.
- **Variáveis de medição `BTC_SEM_*`** (só valem com `MEDICAO_ATIVA`; `recurso_desligado_na_medicao`): `BTC_SEM_PRECONNECT`, `BTC_SEM_PRECO_PYTHON`, `BTC_SEM_AJUSTE_PRELOAD`, `BTC_SEM_TIPOS_FIXOS`, `BTC_SEM_PRECO_NO_HTML`. Cada uma desliga um recurso para o `medir_abertura.py --comparar`.
- Recursos lidos de `PASTA_RECURSOS` (`sys._MEIPASS` no exe; pasta do script em desenvolvimento).
- Dados do usuário em `%APPDATA%\btcstatus\`:
  - `Alertas.json`;
  - `BTC Monitor.ini`: `[Position]` com `x`/`y` e `[Janela]` com `compacto = 0|1`. É gravado inteiro ao fechar (`salvar_configuracao`). Sem a seção `[Janela]` ou com valor inválido, abre no modo completo;
  - `btcstatus.log` (rotativo, 512 KB × 3);
  - `webview\` (perfil persistente do WebView2);
  - `metricas.jsonl` (só com medição; rotaciona para `.1` acima de 5 MB).
- **Janela:** `webview.create_window(..., url=aplicativo_wsgi, http_port=42001, width=500, height=altura_da_janela(compacto), frameless=True, easy_drag=False)`. Com um aplicativo como `url`, o pywebview o serve em `http://127.0.0.1:42001/` (verificado no código do 6.2.1). A origem fixa mantém o `localStorage`. O arraste é do app (ver "Arraste da janela", abaixo).
- **Tamanhos:** `WINDOW_WIDTH` = 500; `WINDOW_HEIGHT` = 810 (completo); `WINDOW_HEIGHT_COMPACTA` = 388 (compacto: a margem abaixo do rodapé é igual à de cima dos botões, 12 px). `altura_da_janela(compacto)` escolhe.
- **Tamanho inicial corrigido no `shown`** (`registrar_ajuste_de_tamanho`): o pywebview cria a janela menor pela moldura (§8, armadilha 30). Um handler sem parâmetros chama `janela.resize(500, altura do modo)` no evento `shown` e marca `tamanho_ajustado`. A janela aparece (~475 ms) antes de a página começar (~615 ms), então a correção acontece com ela vazia. Falha vai para o log e não impede a abertura.
- **Perfil do WebView2:** `webview.start(user_agent="pywebview", **opcoes_de_armazenamento())`, com `private_mode=False` e `storage_path=PASTA_WEBVIEW`. Isso mantém o cache entre execuções e o `localStorage` (usado pelo estado salvo). Se a pasta não for gravável, o app cai no modo privado e registra no log.
- **Posição inicial:** a salva no `.ini`, se o canto superior esquerdo ainda estiver dentro de algum monitor (área total), deslocada o mínimo para a janela inteira (na altura do modo salvo) caber na **área livre** dele (`posicao_dentro_do_monitor`); senão, centralizada na área livre do monitor principal (o que tem origem em 0,0) com a altura do modo (`posicao_centralizada`). A posição e o modo são salvos ao fechar (`events.closing`).
- **Monitores** obtidos de `webview.screens` (lido em `abrir_janela`, `centralizar` e `definir_compacto`); a 1ª leitura inicializa o .NET (~300 ms).
  - O monitor que contém um ponto é escolhido pela área total (`monitor_no_ponto`).
  - Os limites para posicionar são a **área livre** (`bordas_janela.area_livre`): no Windows, o pywebview 6.2.1 guarda em `Screen.frame` o `Screen.WorkingArea` do WinForms (atributos `X`, `Y`, `Width`, `Height`), nas mesmas coordenadas de `x`/`y`/`width`/`height` (`Screen.Bounds`). Sem `frame`, ou com ele vazio ou fora do monitor, vale a área total.
  - **Essas coordenadas são os pixels lógicos do pywebview.** Só o laço de arraste usa as coordenadas do Win32 (ver abaixo).
- O pywebview executa **cada chamada da js_api numa thread nova**: as chamadas podem ser simultâneas. A ponte JS→Python usa as mensagens do WebView2 (`chrome.webview.postMessage`), não o servidor HTTP.

**Arraste da janela (`bordas_janela.py`):**
- O `script.js` pede `iniciar_arraste` ao pressionar o botão principal. O `Arrastador` abre uma thread (`arraste-janela`) e roda `acompanhar_arraste` até o botão ser solto. Uma trava (`acquire(blocking=False)`) ignora pedidos durante um arraste (duplo clique; armadilha 12). O handle vem de `ExposedApi._handle_janela` (título + PID; armadilha 2).
- O laço lê o cursor a cada `INTERVALO_ARRASTE_S` (1/120 s). O deslocamento cursor → canto da janela é lido na 1ª volta, não no clique, então a janela não pula se o mouse andou antes de a thread começar. Nova posição = cursor − deslocamento, encaixada (`encaixar`) na área de trabalho (`rcWork`) do monitor sob o cursor. Só move quando a posição muda; se o `SetWindowPos` falhar, para e registra no log.
- **Encaixe** (`DISTANCIA_IMA` = 20 px): vale dos dois lados da borda (a janela que passou até 20 px volta; mais longe, fica para fora, como no Windows). Com as duas bordas de um eixo ao alcance, vence a mais próxima; no empate, a do início (topo/esquerda, para os botões ficarem visíveis).
- `SistemaWin32` (ctypes, com `argtypes`/`restype` declarados; criado uma vez, no 1º arraste): `GetAsyncKeyState` (botão físico: com `SM_SWAPBUTTON`, o principal é o `VK_RBUTTON`), `GetCursorPos`, `GetWindowRect`, `MonitorFromPoint` + `GetMonitorInfoW` (`rcWork`) e `SetWindowPos` com `SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE` (não ativa a janela nem mexe na fixação no topo).
- **Coordenadas:** o laço usa só as do Win32 do próprio processo (o pywebview chama `SetProcessDPIAware`), sem converter para os pixels lógicos do pywebview. A posição lida depois (`janela.x`/`y`, `.ini`) vem do formulário real, então acompanha o arraste.

**Servidor local (`servidor_local.py`, `criar_aplicativo`):**

| Rota | Resposta |
|---|---|
| `/` e `/index.html` | O `index.html` com o preload da fonte ganhando `crossorigin` (`ajustar_preload_para_http`); com `modo_compacto()` verdadeiro, a linha exata `TAG_HTML` (`<html lang="pt-BR">`) vira `TAG_HTML_COMPACTO` (`marcar_compacto`); e, se a busca já tiver o preço (`resultado(0)`, sem esperar), o bloco `#preco-inicial` (`embutir_preco`, com `<` escapado como `<`) |
| `/preco-inicial` | Espera a busca até 1,5 s: 200 com os tickers (entrega única) ou 204 |
| `/<arquivo>` | Só os de `ARQUIVOS_DA_PAGINA` (nome → tipo); qualquer outro dá 404. `static_file(..., mimetype=tipo)` |

- `modo_compacto` é um callable (no app, `api._modo_compacto`) consultado **a cada pedido** de `/`: a abertura e o ↻ recebem o HTML no modo atual da janela.
- Todas as respostas levam `Cache-Control: no-cache, no-store, must-revalidate` (iguais às do servidor padrão do pywebview).
- Com medição, um envoltório registra `servidor_pedido:<arquivo>` e `servidor_fim:<arquivo>` (no `close()` da resposta) e `servidor_preco_no_html`.

**`ExposedApi`** — métodos disponíveis no JS via `window.pywebview.api` (o estado do modo fica em `_compacto` e o arrastador em `_arrastador`, não expostos):

| Método | Retorno | Observação |
|---|---|---|
| `fechar()` / `minimizar()` | — | |
| `centralizar()` | — | Na área livre do monitor que contém o centro da janela (ou do principal), com a altura do modo atual |
| `definir_compacto(ativo: bool)` | `bool` (redimensionou) | `janela.resize(500, 388 ou 810)` com o topo fixo; se a janela passar da borda da área livre do monitor (barra de tarefas inclusive), sobe/recua o necessário (`move`). Só muda `_compacto` se o `resize` der certo. O modo é gravado no `.ini` ao fechar |
| `iniciar_arraste()` | `bool` (começou) | Repassa ao `_arrastador` (`bordas_janela.Arrastador(self._handle_janela)`) e retorna na hora; `False` se já houver um arraste em andamento |
| `definir_topo(fixar: bool)` | `bool` (estado real) | Via `topo_janela`, nunca via `window.on_top` |
| `esta_no_topo()` | `bool` | Lê o estilo real da janela |
| `salvar_alerta(alertas)` | `bool` | Valida no Python; `False` se rejeitado ou se houver erro de disco |
| `carregar_alerta()` | `list` ou `None` | `[]` se o arquivo não existe; `None` se ilegível ou corrompido (o arquivo é preservado como `Alertas.<data-hora>.bak`) |
| `registrar_metricas(relatorio)` | `bool` | **Só em `ExposedApiComMedicao`** (medição ativa). Valida (objeto JSON simples, até 512 KB) e grava |

### JavaScript (`script.js`)

**Abertura** (`DOMContentLoaded`):
1. `capturarElementos()` (cache `ui`, inclusive os grupos de esmaecimento `ui.grupos`); `graficoVisivel = !ui.grafico.hidden` (padrão do gráfico vindo do HTML).
2. Modo compacto: no app, `compacto` = classe `compacto` do `<html>` (posta pelo servidor local); no navegador, lido do `localStorage['modoCompacto']` e aplicado ao `<html>`. A tela de carregamento cobre a troca. `atualizarBotaoCompacto()`.
3. `registrarEventos()` (inclusive o `mousedown` do arraste, só no app), `configurarBotoesJanela()`.
4. `restaurarEstadoSalvo()`: mostra o último estado (esmaecido) e tira a tela de carregamento.
5. Alertas: `sincronizarAlertas()` no app ou `carregarAlertasLocais()` no navegador.
6. `iniciarCiclos()`: a 1ª consulta de preço (`buscarTickers`) usa o preço do HTML, se houver.
7. Gráfico (se estiver configurado como visível e fora do modo compacto) e som só depois do `load` (`aposCarregarPagina`).

**1º preço no app** (`precoPythonPendente`: pywebview e página por `http:`; vale só para a 1ª consulta):
1. `lerPrecoNoHtml()`: lê e remove o bloco `#preco-inicial`. Se houver dados, são usados direto, sem nenhum pedido de rede (contador `primeiro_preco:html`).
2. Sem o bloco: `/preco-inicial` corre contra o REST (`Promise.any`); vale o primeiro com dados (`primeiro_preco:python` ou `primeiro_preco:rest`). Se os dois falharem, vale o erro do REST.
- Fora do app (navegador, `file://`) é sempre o REST.
- Se o Python não conseguir o preço em 5 s, o log registra "1º preço pelo Python falhou" (WARNING) e a página usa o REST. É ocasional (rede/Binance lenta) e não precisa de correção.

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
- **Falhas — mesma regra para todos os campos** (`CICLOS_ANTES_SEM_DADOS` = 3):
  - cada campo mantém o último valor na tela (salvo ou novo) por até 3 falhas **seguidas da sua fonte** e depois vira "Sem Dados" (preço, USDT, dólar) ou "—" (máx./mín., %, taxas, rodapé);
  - contadores: `falhasBRL`, `falhasUSD` (Binance REST), `falhasDolar` (AwesomeAPI), `falhasTaxas` (mempool.space); zerados na resposta válida e ao retomar;
  - sem nenhum valor na tela (1ª execução, sem estado salvo), a 1ª falha já mostra "Sem Dados"/"—";
  - o que está na tela fica em variáveis só de exibição: `precoBRLExibido`, `precoUSDExibido` (NaN em "Sem Dados"), `ultimaCotacaoDolar`, `taxasNaTela`. Os alarmes usam `ultimoPrecoBRL` (novo, nunca o salvo) e, desde a 1ª falha do BRL, NaN;
  - o **dólar implícito** é calculado com `precoBRLExibido / precoUSDExibido` (`exibirDolar`), então não some enquanto a Binance demora;
  - com `MAX_FALHAS` (10) falhas seguidas do BTC/BRL (REST), o monitoramento pausa como se fosse pausa manual **só se não houver nenhum alerta cadastrado** (`alertas.length === 0`). Com alertas (inclusive desativados), o ciclo segue tentando no intervalo normal, para os alertas voltarem a valer quando a internet voltar.
- **Seta:** compara o preço com o anterior (`direcaoPreco`). Se o preço se repete, a seta mantém a última direção. Começa como ↔ (`seta-neutra`) no HTML e no estado salvo; o 1º preço novo a mantém até o preço mudar. `SETA_POR_DIRECAO` = `↓`/`↔`/`↑` (sem espaços). O `#info-seta` tem largura fixa (`inline-block`, 1em), então trocar ou apagar a seta não desloca o percentual. A animação usa `element.animate` (sem reflow forçado) e só roda quando a seta muda.
- **Escrita no DOM** via `definirTexto` (só escreve se o texto mudou). `document.title` só é usado fora do app.
- **Pausa:**
  - `pausar(manual)` e `retomar({silenciar})`.
  - A pausa manual (botão ou falhas) só é desfeita com clique no overlay ou no botão.
  - A pausa por inatividade (~17 min, `LIMITE_INATIVIDADE`, sem atividade) é desfeita com qualquer movimento do mouse ou tecla (`registrarInteracao`). Clique (`pointerdown`) conta como atividade (`registrarAtividade`), mas não retoma.
  - A inatividade **não é verificada**: com a janela fixada no topo; com algum alerta **ativo** (`existeAlertaAtivo`); e depois de um alarme disparar, até haver nova atividade do usuário (`alarmeSemAtividade`). Os ~17 min contam a partir dessa atividade.
- **Arraste:** só no app (`isPyWebView`), um listener de `mousedown` (`aoPressionarParaArrastar`) chama `chamarApi('iniciar_arraste')` quando o botão principal (`button === 0`) é pressionado dentro de `.regiao-arraste`:
  - fora de `SELETOR_SEM_ARRASTE` (`button, input, select, textarea, a, label`), que têm ação própria;
  - fora de uma barra de rolagem (`cliqueNaBarraDeRolagem`: `offsetX`/`offsetY` além da área interna de um elemento que rola, como a `#listaAlertas`);
  - o `<dialog>` fica fora da região. O fundo das telas (preço, pausa, alertas) arrasta.
- **Gráfico:**
  - **Padrão de abertura: oculto.** Vem do atributo `hidden` de `#grafico` no `index.html`, lido uma vez no `DOMContentLoaded` (`graficoVisivel = !ui.grafico.hidden`); a variável começa `false`. Sem o atributo, o gráfico abre visível. A escolha pelo ⇄ não é salva entre execuções.
  - O widget fica no `<template id="grafico-modelo">` e só existe enquanto está visível, o monitoramento está ativo **e** fora do modo compacto (`atualizarGrafico`: `graficoVisivel && ativo && !compacto`). Pausar, ocultar com ⇄ ou compactar remove o iframe; mostrar clona o template de novo (`document.importNode`). O ⇄ existe no app e no navegador (oculto no modo compacto). Com o gráfico oculto, nada do TradingView é pedido.
  - `atualizarGrafico` define `style.display` (`flex`/`none`) e mantém o atributo `hidden` coerente com a tela. O CSS mantém `#grafico { display: none }`, então o quadro vazio nunca aparece antes da montagem.
  - Na abertura (se visível), é montado só depois do `load` e, no app, depois da ponte com o Python (ou do prazo de 5 s), via `requestIdleCallback`.
  - Widget com `"autosize": true`, `"width": "100%"`, `"height": "100%"`; o `#grafico` tem fundo preto opaco e o container do widget ocupa 100% dele.
  - **Posição** (`posicionarGrafico`, chamada ao montar e via `ResizeObserver` em `#conteudoMenosBotoes`): a borda de cima fica sobre a linha separadora (`.separator`) do topo da tabela de máximas/mínimas/taxas; largura = tabela + `SOBRA_GRAFICO` (2 px) de cada lado; altura = proporção 310/440 da largura, nunca antes do fim da tabela e nunca além do fim da janela. Na janela do app (500×810): `top` 449, `left` 24, 452×318 (os mesmos valores estão no CSS).
- **Modo compacto:**
  - Estado em `compacto`; layout pela classe `compacto` no `<html>` (`aplicarCompacto`). Botão `#compacto-btn`: ⊟ no modo completo ("Modo compacto"), ⊞ no compacto ("Modo completo"); no app em `right: 80px` (à esquerda do minimizar), no navegador em `right: 40px` (ao lado do ■).
  - `alternarCompacto()`: no app, pede `definir_compacto` ao Python numa **fila** (`filaCompacto`), na ordem dos cliques; no navegador, grava `localStorage['modoCompacto']` (`'1'`/`'0'`). O app ignora essa chave.
  - O CSS esconde logo, tabela e ⇄, mostra `#info-faixa` (máxima e mínima de 24 h em BRL numa linha, preenchidas junto com a tabela por `exibirMaximaMinimaBRL`) e reduz o ⏸ para 8rem.
  - A pausa, o fundo escuro e a tela de alertas ficam **presos ao bloco do conteúdo**: `#conteudo` passa a ter a altura do conteúdo (+10 px) e as sobreposições ficam `position: absolute` nele. Na tela de alertas, só a lista encolhe e rola. No app, o bloco ocupa a janela (4 alertas visíveis); no navegador com janela larga, o bloco é baixo e mostra 1–2 alertas.
  - O `<dialog>` de avisos continua no centro da janela.
- **Último estado salvo** (`localStorage['ultimoEstado']`, `{versao, salvoEm, brl, usdt, dolar, taxas}`, validado por `validarEstadoSalvo`):
  - Na abertura, preenche só os textos, com "atualizando… (salvo em …)" no horário. `ultimoPrecoBRL` continua NaN, então **nunca dispara alarme**. No app, o preço do HTML o substitui quase no mesmo instante.
  - **Esmaecimento por fonte** (`.desatualizado`, `marcarSalvo`/`marcarAtualizado`, conjunto `gruposSalvos`): cada grupo fica esmaecido enquanto mostra o valor salvo e volta ao normal quando a sua fonte responde ou quando vira "Sem Dados". Grupos: `brl` (preço, horário, % + seta, máx./mín. BRL e rodapé), `usdt`, `dolarImplicito` (sai quando BRL e USDT já são novos), `dolarComercial`, `taxas`.
  - É gravado no máximo a cada 30 s e também ao fechar, recarregar, ocultar a página ou sair dela (`pagehide`).
- **WakeLock:** pedido ao iniciar e em `visibilitychange`; liberado ao pausar.
- **Ponte com o Python:**
  - Sempre via `chamarApi(metodo, ...args)`, que nunca rejeita e retorna `undefined` fora do pywebview ou em falha.
  - `obterApi()` espera o `pywebviewready` (prazo de 5 s) só enquanto a API não está pronta.
  - A ponte só fica pronta depois do `load` da página, e a injeção dela ocupa a página por ~50 ms (ver §8).
- **Diálogo:** `<dialog id="dialogo">` nativo com fila (`mostrarDialogo`, `aviso(titulo, msg, autoFecharMs)`). O conteúdo é sempre texto. Com auto-fechamento, o botão mostra `OK (n)`. O diálogo de alarme não fecha sozinho.
- Formatadores `Intl` criados uma vez: `formatoBRL`, `formatoUSD`, `formatoTaxa`, `formatoData`, `formatoHora`.
- **Medição:**
  - `Metricas.marcar/registrar/contar/evento/medir` espalhados no `script.js`. No substituto de produção, todos são atalhos vazios. Evento `compacto` ao alternar o modo. Cada pedido de arraste aparece como `python:iniciar_arraste` (registrado pelo `chamarApi`).
  - Marcos do 1º preço: `preco_no_html`, `preco_inicial_pedido`, `preco_inicial_resposta`, `preco_inicial_dados`, `precos_continuacao`.
  - O `metricas.js` também registra: a 1ª requisição a cada servidor (`rede1:<host>`); cada arquivo da própria página (`recurso_inicio:`/`recurso:<arquivo>` e o contador `recurso_n:<arquivo>`); e, nos primeiros 2 s, os momentos em que a thread da página ficou ocupada por mais de 15 ms (`bloqueios`, por um timer encadeado). Antes de cada relatório, `takeRecords()` recolhe as entradas pendentes dos observadores.
  - `enviarMetricas(motivo)` sai cedo se `!Metricas.ATIVAS`.
  - Relatórios: abertura, periódico (5 min), recarga e encerramento (botão x).
  - **Relatório de abertura** (`enviarRelatorioAbertura`): sai depois do 1º preço, quando `aberturaConcluida()` for verdadeira, ou no máximo 15 s após o 1º preço:
    - gráfico visível e fora do modo compacto: quando ele carrega (`grafico_carregado`);
    - gráfico oculto (padrão) ou modo compacto, no app: quando `sincronizarAlertas()` termina, com ou sem sucesso (`sincronizacaoAlertasConcluida`, no `finally`). É o último passo da abertura, logo depois da ponte;
    - gráfico oculto ou modo compacto, no navegador: depois do `load` (`aposCarregarPagina`).
    - Com o gráfico oculto, o marco `grafico_carregado` não existe na abertura.
  - `Metricas.relatorio(motivo)` zera os contadores (e os `bloqueios`) **no momento em que monta o relatório**. Tudo o que for marcado ou contado depois da montagem só entra no relatório seguinte. No app, o envio passa por `chamarApi`, que espera a ponte; entre a montagem e a entrega, os contadores do período não estão nem na página nem no Python.

**Abertura medida** (`.exe` com medição, 10 aberturas, ms desde a criação do processo, medianas; a 1ª abertura, "fria", fica ~450 ms mais lenta; medida antes do modo compacto e da correção do tamanho no `shown`, cujo marco `tamanho_ajustado` ainda não foi medido):

| Etapa | Tempo |
|---|---|
| Imports concluídos / busca do 1º preço começa | ~90 |
| .NET iniciado (1º `webview.screens`) | ~395 |
| Janela exibida | ~475 |
| 1º preço recebido pelo Python | ~495 |
| Página começa a carregar | ~615 |
| Servidor entrega o HTML (com o preço) | ~625 |
| CSS e JS recebidos | ~645 |
| `DOMContentLoaded` | ~655 |
| **1º preço novo na tela** | **~660** |
| `load` da página | ~670 |
| Fonte carregada / 1º quadro | ~715 |
| Ponte JS→Python | ~720 |
| Alertas lidos do disco (fim da abertura: o relatório de abertura sai aqui) | ~725 |
| Gráfico (só com ele configurado como visível ao abrir; no padrão, não é montado) | ~800 (medição anterior) |

Thread da página ocupada na abertura (seção 1b do `analisar_metricas.py`): ~22 ms quando os scripts começam e ~45 ms logo no `load` (injeção da ponte do pywebview, §8 item 11). No lado da página, `python:carregar_alerta` leva ~65 ms porque é pedido no `DOMContentLoaded` e espera a ponte; no Python, o método leva ~0,3 ms.

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
- **Alertas e pausas automáticas:**
  - inatividade: suspensa com algum alerta ativo e, depois de um alarme, até a próxima atividade do usuário;
  - 10 falhas seguidas da Binance: não pausam com qualquer alerta cadastrado (inclusive desativado).
- **Tela de alertas:** só a lista (`#listaAlertas`) rola, e o campo e os botões ficam sempre visíveis. A tabela usa um único listener delegado (`data-acao` e `data-id`). Pressionar a barra de rolagem da lista não arrasta a janela.

## 6. Segurança

**CSP** no `<meta>` do `index.html`:
- `script-src 'self' file: 'unsafe-eval' https://s3.tradingview.com`. O `'unsafe-eval'` é **obrigatório**: o `api.js` do pywebview cria a ponte com `new Function`. O bloco `#preco-inicial` é `type="application/json"` (não é executado) e não precisa de exceção. Não há script inline (por isso o modo compacto do navegador é aplicado no `DOMContentLoaded`, sob a tela de carregamento).
- `style-src 'self' file: 'unsafe-inline'` (pywebview e TradingView injetam `<style>`).
- `font-src`, `img-src` e `media-src`: `'self' file:` (`img-src` também aceita `data:`).
- `connect-src`: `'self'` (para `/preco-inicial`), `https://api.binance.com`, `wss://stream.binance.com:9443`, `https://economia.awesomeapi.com.br`, `https://mempool.space`.
- `frame-src`: `https://*.tradingview.com`, `https://*.tradingview-widget.com`.
- O Chromium só segue uma dica de pré-conexão se alguma diretiva da CSP permitir o endereço (`tests/test_preconnect.py` confere).
- Ao trocar de API, porta ou widget, atualize a CSP e as pré-conexões.

**Outras regras:**
- Sem handlers inline (`onclick`). Todos os eventos são registrados em `registrarEventos()`.
- O Python valida todo dado vindo do JS (`validar_alertas`, `validar_relatorio_js`; `definir_compacto` converte para `bool`; `iniciar_arraste` não recebe argumentos).
- A `ExposedApi` expõe ao JS todo método **e todo objeto** público (o pywebview percorre atributos recursivamente). Estado interno fica em atributos ou métodos com `_` (ex.: `_compacto`, `_modo_compacto`, `_arrastador`). `tests/test_janela.py` confere.
- O servidor local só entrega os arquivos da lista fechada (o servidor padrão do pywebview entregava qualquer arquivo da pasta, inclusive os `.py`). Escuta só em `127.0.0.1`.
- O script do TradingView roda no contexto da página (com acesso à ponte) só enquanto o gráfico está montado. Com o padrão oculto, isso só acontece depois de o usuário clicar em ⇄.
- O `.exe` de produção não expõe `registrar_metricas`, não grava métricas e ignora as variáveis `BTC_SEM_*`.

## 7. Convenções

- **Python:** snake_case, type hints, `pathlib`, `logging` (nunca `print` no app; o exe não tem console), docstrings em português, 4 espaços.
- **JS:**
  - `'use strict'`, camelCase, `const`/`let`, indentação com **tab**, sem jQuery.
  - Sem `innerHTML` com dados: usar `textContent`/`replaceChildren`/`definirTexto`.
  - Constantes de tempo e URLs no topo do `script.js`.
- **Formatação pt-BR:** moeda via `Intl.NumberFormat('pt-BR')`, taxas com 2 casas e vírgula (`3,50 sat/vB`), data `dd/mm/aa - hh:mm:ss`. A variação percentual usa `toFixed(2)` (ponto decimal).
- **Campos com dados:** todo campo novo segue a regra de falhas (§4: valor mantido por `CICLOS_ANTES_SEM_DADOS` falhas da sua fonte) e, se vier do estado salvo, entra num grupo de `ui.grupos` (esmaecimento).
- **CSS:**
  - Cores em variáveis `:root`.
  - Botões de formulário, tabela e diálogo usam `.botao-padrao`; controles do topo usam `.btns` (ocultos por padrão; `configurarBotoesJanela()` exibe os que se aplicam: no navegador, ⏱ à esquerda, ⇄ ao lado, ⊟/⊞ e ■ à direita).
  - Regras do modo compacto ficam sob `html.compacto`, no fim do `style.css`. Para esconder um botão da barra no modo compacto, usar `!important` (o script os exibe com estilo inline).
  - Transições só nas propriedades que mudam (sem `all`).
- **Padrões de abertura configuráveis** ficam no `index.html` (ex.: `hidden` em `#grafico`) e são lidos pelo `script.js` no `DOMContentLoaded`, não fixados em variáveis do script. Escolhas do usuário lembradas entre execuções ficam no Python (`.ini`) no app e no `localStorage` no navegador (ex.: modo compacto).
- **Lógica pura nova** (alertas, estado salvo) vai para `regras.js`, com teste em `tests/regras.test.js`. No Python, a lógica da janela fica separada das chamadas ao sistema (ex.: `encaixar` × `SistemaWin32`), que entram por parâmetro para os testes usarem um sistema falso.
- **Posicionar a janela** usa a área livre (`area_livre(monitor)`), não `monitor.x`/`width` direto; escolher o monitor usa a área total (`monitor_no_ponto`).
- **Controle novo na região de arrasto** que tenha ação ao pressionar e não seja `button`/`input`/`select`/`textarea`/`a`/`label` precisa entrar em `SELETOR_SEM_ARRASTE`.
- **Arquivo novo usado pela página:** entra em `datas` no `.spec` **e** em `ARQUIVOS_DA_PAGINA` (com o tipo) no `servidor_local.py`. `tests/test_servidor_local.py` confere que todo arquivo citado no HTML está na lista.
- **Medição:**
  - Novos pontos de medida usam `Metricas.*`.
  - Ao mudar a interface de `metricas.js`, mude também `metricas_desligadas.js` (`tests/metricas.test.js` confere).
  - Novos marcos de abertura entram em `ETAPAS_ABERTURA` (`tools/analisar_metricas.py`). Marcos do Python e do JS não podem ter o mesmo nome (a linha do tempo junta os dois).
  - Recurso novo da abertura que se queira medir ganha uma variável `BTC_SEM_*` (só com medição) e uma entrada em `COMPARACOES` do `medir_abertura.py`.
  - Toda otimização entra com comparação A/B (`--comparar`); fica só se o ganho se repetir.
- **Testes:**
  - Comportamento de página novo ganha teste em `tests/test_pagina_funcional.py` (rede simulada, timers acelerados 50×). O que depende de `http://` usa `ServidorDaPagina`.
  - Teste que precisa do gráfico montado **na abertura** chama `com_grafico_ao_abrir(contexto)` antes do `goto` (init script que tira o `hidden` de `#grafico` no `DOMContentLoaded`, antes do listener do `script.js`). Teste que só precisa do gráfico depois de aberto clica em `#grafico-btn`.
  - Os init scripts `PYWEBVIEW_TARDIO` e `CAPTURAR_RELATORIOS` guardam os relatórios entregues em `window.__relatorios`. Contadores e marcos são lidos por `contadores(pagina)` e `marcos_da_pagina(pagina)`, que esperam o relatório de abertura ser entregue (`_esperar_relatorio_de_abertura`) e somam/juntam os relatórios com os valores atuais. Não ler `Metricas.resumo().contadores` direto depois do 1º preço.
  - Métodos novos da API no app simulado entram por um init script que os acrescenta no `pywebviewready` (ex.: `API_DEFINIR_COMPACTO`, `API_INICIAR_ARRASTE`), junto com `PYWEBVIEW_TARDIO` e o user agent com "pywebview".
  - Testes de inatividade usam `pagina.clock.install()` + `fast_forward`/`run_for`.
  - Código Python que mexe na janela é testado com uma janela falsa (`JanelaFalsa` em `tests/test_janela.py`) e `app.webview` trocado por um objeto com `screens` (ver armadilha 37); para a área livre, monitores com `frame` (`MONITOR_COM_BARRA`). O `abrir_janela` inteiro é testado com `create_window`/`start` falsos e `EventosFalsos`. O arraste é testado com `SistemaFalso` (cursor roteirizado) em `tests/test_bordas_janela.py`.
  - Um teste que corrige um defeito deve falhar com o código antigo (ou ter um caso de controle que mostre o defeito).
- **Scripts `.ps1`:** mensagens sem acentos (o PowerShell 5.1 lê UTF-8 sem BOM como ANSI) e finais de linha CRLF.

## 8. Armadilhas conhecidas (não reintroduzir)

1. **Não usar `window.on_top` do pywebview 6.2.1.** O setter altera a propriedade `TopMost` do WinForms pela thread da js_api via pythonnet, segurando o GIL, e trava o app. Usar `topo_janela.py` (ctypes libera o GIL). Pelo mesmo motivo, evitar em métodos da `ExposedApi` qualquer setter de propriedade .NET que não use `Invoke`. (`window.move` e `window.resize` são seguros: chamam `SetWindowPos` pelo ctypes.)
2. **Não fixar a janela com `GetForegroundWindow()`**: pode fixar a janela de outro programa. O handle é obtido por título **e** PID (`encontrar_janela`). O arraste usa o mesmo handle.
3. **Pixels lógicos:** o pywebview (`x`, `y`, `move`, `resize`, `screens`, inclusive `screen.frame`) usa pixels lógicos. Não misturar com bibliotecas que retornam pixels físicos. O laço de arraste (`bordas_janela.py`) é a exceção controlada: lê e escreve só coordenadas do Win32 (`GetCursorPos`, `GetWindowRect`, `rcWork`, `SetWindowPos`), sem nunca combiná-las com as do pywebview.
4. O pywebview **não** sincroniza o título nativo da janela com `document.title`. A janela sempre se chama "BTC Status", e `encontrar_janela` depende disso.
5. `element.style.display` vem vazio quando o valor vem só do CSS. Para ler o valor efetivo, usar `getComputedStyle`. A tela de alertas é aberta com `style.display = 'block'`, por isso o flex fica no `.modal-content`, não no `.modal`.
6. A **AwesomeAPI** sem chave mantém cache de 1 min e tem cota mensal de 100 mil requisições. Não consultar com menos de 60 s de intervalo.
7. Os dois endpoints de taxas da mempool.space (`recommended` e `precise`) têm os mesmos campos; o `precise` traz casas decimais.
8. Nunca reagendar ciclos com `setInterval` dentro de função `async`; usar a cadeia de `setTimeout` com `geracaoCiclo`.
9. O build deve sempre usar o `.spec`. Passar o `.py` com opções ao PyInstaller **sobrescreve** o `.spec`. Não incluir `python3xx.dll` à mão.
10. Arquivo novo usado pela página (JS, CSS, mídia) precisa entrar em `datas` no `.spec` **e** em `ARQUIVOS_DA_PAGINA` no `servidor_local.py` (senão dá 404 no app). Módulos Python importados entram automaticamente. O `metricas.js` é a exceção no `.spec`: entra pelo `a.datas +=` (coletor real ou substituto vazio).
11. **A ponte do pywebview só fica pronta no `load` da página e ocupa a página por ~50 ms.** Ela é injetada no `NavigationCompleted` do WebView2, que acompanha o `load`: o pywebview executa na página ~70 KB de JS dele (`polyfill.js`, `dom_json.js`, `api.js`...). O `load` espera iframes, fontes e mídia: nada pesado pode ser montado antes dele, e o gráfico entra depois da ponte. Tudo o que depender de um evento assíncrono logo depois do `load` (ex.: resposta de um `fetch`) espera essa injeção; por isso o 1º preço vem no HTML. Um arraste pedido antes da ponte espera por ela e, se o botão já tiver sido solto, não move nada.
12. **As chamadas da js_api rodam em threads paralelas.** Todo recurso compartilhado (como o `Alertas.json`) precisa de trava no Python, e a ordem das gravações é garantida pela fila no JS. O mesmo vale para o redimensionamento: `definir_compacto` passa pela fila `filaCompacto`; sem ela, dois cliques rápidos podem deixar a janela num tamanho e o layout no outro. E para o arraste: a trava do `Arrastador` impede dois laços movendo a janela ao mesmo tempo.
13. **Handlers de eventos do pywebview:**
    - um handler com parâmetros recebe os argumentos do evento (use funções sem parâmetros);
    - **retornar `False` cancela a ação** em `closing`, `initialized`, `before_show` e `before_load`;
    - os handlers rodam em threads.
14. **`private_mode=True` (padrão do pywebview)** apaga o perfil a cada execução (sem cache) e, ao fechar, espera até 3 s pelo processo do navegador. O app usa `private_mode=False` com `storage_path`.
15. **ctypes no Windows 64 bits:** sempre declarar `argtypes`/`restype` de funções que usam handles. Sem isso, o `HANDLE` volta truncado em 32 bits e a chamada falha (era o caso do `GetCurrentProcess`). Cada módulo cria o seu `ctypes.WinDLL("user32")`, para as declarações não se misturarem com as do `windll` usado pelo pywebview.
16. **Build sem setuptools:** o `cffi` só o usa para compilar, mas o runtime hook do PyInstaller o importaria em toda abertura (~100 ms). Excluir `setuptools`, `pkg_resources` e `_distutils_hack`. **Não** excluir `distutils`: quebra o build (o hook do PyInstaller o redireciona).
17. **Preload da fonte: `file://` SEM `crossorigin`, `http` COM.** Com a regra trocada, o Chromium descarta o preload e lê a fonte duas vezes. O `index.html` vem sem o atributo (navegador e testes por `file://`), e o `servidor_local.py` o acrescenta procurando a linha exata `PRELOAD_FONTE`: não mudar essa linha do HTML sem mudar a constante. Testes: `test_preload_da_fonte_e_aproveitado` (`file://`) e `test_preload_da_fonte_pelo_servidor_local` (`http`).
18. **O BTC/BRL fica em silêncio no WebSocket** por 5 a 16 s quando não há negociação: a Binance só envia o ticker que mudou. A vigia de silêncio precisa contar qualquer par (o USDT chega a cada ~1 s), senão gera quedas e reconexões falsas.
19. **Estrangulamento de timers do Chromium com a página oculta:** a página recebe `hidden` ao minimizar. Timers aninhados (nível ≥ 5) passam a rodar no máximo 1 vez por minuto. Os ciclos daqui reagendam depois de um `await fetch`, o que zera o aninhamento, e por isso só sofrem o alinhamento de ~1 s. Não reagendar ciclos críticos diretamente de dentro de um callback de timer. Mensagens do WebSocket não são estranguladas.
20. **Widget do TradingView:** o script `embed-widget-*.js` lê o JSON do próprio `<script>` via `currentScript`. Para recriá-lo, clonar o `<template>` (`document.importNode`). `innerHTML` não executa o script. Não fixar o tamanho do widget nem ampliá-lo com `transform: scale`: a proporção da tabela muda com a janela e sobra texto nas bordas; usar `autosize` dentro do quadro opaco posicionado sobre a tabela.
21. **Playwright (testes):**
    - no handler de `route_web_socket` (API síncrona), chamar `ws.close()` **trava**;
    - registrar `on_close` gera `KeyError: 'code'` na biblioteca. Fechar de fora do handler e com `code`;
    - um `Proxy` usado como `window.pywebview.api` não pode responder `then`, senão vira "thenable" e as Promises nunca resolvem;
    - no `nova_pagina`, a rota registrada por último tem precedência;
    - `add_init_script` roda em **todos os frames**, inclusive no iframe do TradingView. Init script que mexe em elementos da página precisa conferir se eles existem (ex.: `#grafico` não existe no iframe), senão gera `pageerror` e os testes falham em `assert not erros`;
    - com `pagina.clock.install()`, o evento `close` de um `<dialog>` chega numa tarefa à parte: depois de `dialogo.close()`, esperar o efeito em laço (`clock.run_for` + `wait_for_timeout`) antes de conferir, senão o teste falha às vezes;
    - o Chromium sem janela do Playwright esconde as barras de rolagem (largura 0), e o `::-webkit-scrollbar` não vale com o `scrollbar-color` do `style.css`. Para testar um clique na barra, simular o `mousedown` logo à direita da área interna do elemento.
22. **Medir o `.exe` exige o build `-ComMedicao`.** O `.exe` de produção não gera relatório, e o `medir_abertura.py --exe` avisa.
23. **Porta fixa 42001.** O `localStorage` (último estado salvo) pertence à origem `http://127.0.0.1:42001`: mudar a porta perde o estado salvo. O servidor do pywebview (wsgiref) abre a porta mesmo ocupada (no Windows, `SO_REUSEADDR`), e a página pode vir de **outra instância aberta** (ex.: o `.exe` de produção durante uma medição): sem medição, sem os arquivos novos, ou 404. O `medir_abertura.py` para se a porta estiver ocupada.
24. **O `servidor_local.py` depende de duas opções do `create_window` do pywebview 6.2.1:** um aplicativo WSGI como `url` (`is_app`) e `http_port`. Ao atualizar o pywebview, conferir no código dele (`window._initialize` e `http.BottleServer.start_server`) que continuam iguais; os testes da página não cobrem o servidor do pywebview.
25. **Nunca deixar o bottle adivinhar o tipo dos arquivos.** Sem `mimetype`, o `static_file` chama `mimetypes.guess_type`, e a 1ª chamada do processo lê a tabela de tipos do registro do Windows (~22 ms). Os pedidos simultâneos da abertura faziam isso cada um, em fila no GIL, e seguravam CSS e JS por ~60 ms. O registro também pode trazer tipos errados (ex.: `.js` como `text/plain`). `test_entregar_arquivos_nao_inicia_o_mimetypes` confere.
26. **`TCP_NODELAY` no servidor local não traz ganho** (medido): a demora dos arquivos era o `mimetypes`, não a rede local. Não reintroduzir, inclusive porque exige acessar o socket por um detalhe interno do wsgiref.
27. **O build falha se houver um `BTC Monitor.exe` aberto da pasta `dist`** (ele trava o `ClrLoader.dll`, e o PyInstaller não consegue apagar a pasta). O `criar_exe_btc.ps1` confere antes e para; não encerra o processo sozinho.
28. **Gráfico oculto ao abrir (atributo `hidden` de `#grafico`):**
    - o `hidden` só esconde porque o CSS também tem `#grafico { display: none }`; uma regra de autor com `display` em `#grafico` sem `:not([hidden])` anularia o atributo (mesmo problema da armadilha 5);
    - o `script.js` lê o atributo uma única vez, no `DOMContentLoaded`; mudar `graficoVisivel` direto no topo do script não altera o padrão;
    - o relatório de abertura não pode exigir `grafico_carregado` com o gráfico oculto ou no modo compacto, senão sempre espera os 15 s (`aberturaConcluida` só espera o gráfico se `graficoVisivel && !compacto`);
    - testes e ferramentas que dependem do gráfico na abertura (`grafico_carregado`, iframe do TradingView) precisam abri-lo de propósito (`com_grafico_ao_abrir` ou clique em ⇄); sem isso, esperam um gráfico que nunca é montado.
29. **Relatório de abertura: o momento da montagem decide o conteúdo.** `Metricas.relatorio` monta o relatório e zera os dados na hora da chamada; a entrega ao Python vem depois (espera a ponte).
    - **Não montar o relatório de abertura no 1º preço.** Ele perde todos os marcos posteriores (`nav_load`, `api_python_pronta`, `alertas_sincronizados`, fonte, 1º quadro, bloqueios do `load`). E o `medir_abertura.py` fecha o app assim que o relatório de abertura chega, então esses marcos nunca são gravados. O relatório sai quando `aberturaConcluida()` (§4). `test_relatorio_de_abertura_nao_espera_o_grafico_oculto` confere.
    - **Os contadores somem entre a montagem e a entrega.** Quem lê `Metricas.resumo().contadores` depois da montagem não acha os da abertura (ex.: `primeiro_preco:html`). Nos testes, usar `contadores()`/`marcos_da_pagina()` (§7). Nas ferramentas, somar todos os relatórios gravados no `metricas.jsonl` (o `analisar_metricas.py` já faz isso).
30. **A janela frameless nasce menor que o pedido.** O pywebview 6.2.1 (WinForms) define o tamanho (`self.Size`) com a moldura normal e só depois aplica `FormBorderStyle = None`; o WinForms mantém a área interna, e a janela perde a moldura (~16 px na largura e ~40 px na altura a 100%). Sem a correção, o modo compacto abria com o rodapé cortado e o completo com ~484×771. A correção é o `resize` no evento `shown` (`registrar_ajuste_de_tamanho`). Não compensar somando a moldura no `create_window` (depende do DPI e da ordem interna do pywebview). Ao atualizar o pywebview, conferir se a ordem mudou. Os testes da página não pegam isso (o navegador já tem o tamanho exato).
31. **Classe `compacto` no HTML: linha exata `TAG_HTML`.** O `servidor_local.py` troca `<html lang="pt-BR">` por `<html lang="pt-BR" class="compacto">`. Não mudar a linha do `<html>` no `index.html` sem mudar a constante (`test_tag_html_do_modo_compacto_existe_no_index` confere). O `index.html` sempre vem no modo completo.
32. **Modo compacto: o layout e a janela precisam concordar.** No app, o Python guarda o modo (`_compacto`, `.ini`) e o servidor o põe no HTML a cada pedido de `/`: o ↻ e a abertura respeitam o tamanho real da janela. Não guardar o modo do app no `localStorage` (a janela já nasceria num tamanho e a página leria outro). Não ler `localStorage['modoCompacto']` no app.
33. **Sobreposições no modo compacto são relativas ao `#conteudo`.** O `#conteudo` (fixo) tem a altura do conteúdo, e `.overlay`/`.modal` ficam `position: absolute` nele. Mover a pausa, o fundo escuro ou a tela de alertas para fora do `#conteudo`, ou voltar o `#conteudo` a `height: 100%` no modo compacto, faz tudo cobrir a janela inteira de novo no navegador. `test_pausa_e_alertas_ficam_no_bloco_compacto` confere.
34. **Estado salvo: exibição separada dos alarmes.** Os valores salvos ficam em `precoBRLExibido`/`precoUSDExibido` (e nos textos), nunca em `ultimoPrecoBRL`/`ultimoPrecoUSD`, que os alarmes usam. Calcular o dólar implícito com `ultimoPreco*` faz ele virar "Sem Dados" enquanto a Binance demora. Decidir a tolerância a falhas por `exibindoEstadoSalvo` (que é só do BRL) apagava o USDT salvo quando o BRL chegava primeiro: usar "há valor desse campo na tela".
35. **Seta com largura fixa.** O % e a seta são centralizados juntos; ↔, ↑ e ↓ têm larguras diferentes, e a seta vazia não ocupa espaço. Sem o `inline-block` de 1em em `#info-seta`, o número se desloca a cada troca. Os espaços entre o % e a seta vêm do HTML, não do texto da seta.
36. **Inatividade, cliques e alarmes.** `mousemove` e `keydown` não pegam um clique sem movimento (ex.: fechar o alarme com o ponteiro parado sobre o OK). Por isso o `pointerdown` registra atividade (sem retomar a pausa: retomar no `pointerdown` faria o clique seguinte cair no ⏸/■ e pausar de novo). Depois de um alarme, a pausa por inatividade só volta a contar depois de nova atividade (`alarmeSemAtividade`).
37. **`webview.screens` é uma propriedade de módulo (`module_property`)**: não dá para trocá-la com `monkeypatch.setattr(webview, "screens", ...)`. Nos testes, trocar `app.webview` inteiro por um objeto com `screens`.
38. **`window.resize` do pywebview ativa a janela e a traz para frente** (`SetWindowPos` com `SWP_SHOWWINDOW`, sem `SWP_NOACTIVATE`/`SWP_NOZORDER`). Com `HWND_TOP` a fixação no topo se manteve na verificação manual. Se for preciso redimensionar sem ativar, usar `SetWindowPos` próprio pelo ctypes (como em `topo_janela.py` e `bordas_janela.py`), convertendo para pixels físicos.
39. **Arraste: não usar o `easy_drag` nem a classe `pywebview-drag-region`.** O `easy_drag` (padrão `True`) move a janela pelo JS (`js/customize.js`: cada `mousemove` vira `window.move` numa thread da js_api), sem noção das bordas da tela, e as chamadas podem chegar fora de ordem. **E o pywebview sempre escuta o `DRAG_REGION_SELECTOR` (`.pywebview-drag-region`), mesmo com `easy_drag=False`**: um elemento com essa classe religa o arraste antigo por cima do do app. Por isso o `#conteudo` usa `regiao-arraste` (`test_index_nao_usa_a_regiao_de_arrasto_do_pywebview` e `test_janela_e_criada_sem_o_easy_drag` conferem). O CSS de `.regiao-arraste` (`position: fixed`, altura total) é layout: não apagar.
40. **O Snap do Windows (Aero Snap) não serve para esta janela.** O WebView2 do pywebview 6.2.1 (SDK 1.0.3856.49) aceita `app-region: drag` com `IsNonClientRegionSupportEnabled` (o pywebview não liga), o que daria arraste nativo. Mas o Snap maximizaria ou esticaria a janela, que tem layout fixo (500×810/388), e a janela sem moldura não tem `WS_THICKFRAME`. As bordas são do app (§4, "Arraste da janela").
41. **`GetAsyncKeyState` lê o botão físico.** Com os botões do mouse trocados (canhotos), o clique principal é o `VK_RBUTTON`; sem consultar `SM_SWAPBUTTON`, o arraste terminaria na hora.

## 9. Comandos

```powershell
# Dependências
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Executar sem build (com medição)
.\runbtc.ps1

# Testes (inclui os funcionais de página; os de desempenho ficam fora)
.venv\Scripts\python.exe -m pytest tests
node --test tests/regras.test.js tests/metricas.test.js

# Só o arraste e a janela
.venv\Scripts\python.exe -m pytest tests\test_bordas_janela.py tests\test_janela.py

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

# Frequência das falhas do 1º preço pelo Python
Select-String -Path "$env:APPDATA\btcstatus\btcstatus.log*" -Pattern "1º preço pelo Python falhou" | Select-Object -Last 20

# Regenerar a fonte reduzida (a partir da Roboto Regular completa; pip install fonttools brotli)
pyftsubset Roboto-original.woff2 --unicodes="U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD" --layout-features='*' --flavor=woff2 --output-file=Roboto.woff2
```
- Saída: `dist\BTC Monitor\BTC Monitor.exe`. Para distribuir, copiar a pasta `dist\BTC Monitor` inteira.
- No PowerShell, abrir um executável com espaço no caminho: `& ".\dist\BTC Monitor\BTC Monitor.exe"`.
- **Depuração:**
  - Erros do Python vão para `%APPDATA%\btcstatus\btcstatus.log` (inclui "1º preço pelo Python falhou", "Falha ao mudar o modo compacto"/"Falha ao ajustar o tamanho inicial da janela" e, no arraste, "Arraste: janela não encontrada"/"Falha ao mover a janela durante o arraste"/"Falha no arraste da janela"). Erros da página não vão para o log.
  - Para ver os erros da página, acrescentar temporariamente `debug=True` ao `webview.start(...)` em `abrir_janela()`, o que abre o DevTools.
  - No navegador, `Metricas.resumo()` no console mostra as medidas do período.
  - Para ajustar o ímã das bordas, mudar `DISTANCIA_IMA` no topo do `bordas_janela.py` (e o teste `test_encaixar_usa_20_px_por_padrao`).
  - Para testar a inatividade sem esperar 17 min, mudar `LIMITE_INATIVIDADE` no topo do `script.js` para `60 * 1000` só durante o teste.

## 10. Verificação manual após mudanças

- [ ] A tela abre já com o preço novo; os campos do estado salvo aparecem esmaecidos e voltam ao normal conforme cada fonte responde, sem "Sem Dados" na abertura. Sem internet, todos mostram o último estado salvo e depois viram "Sem Dados"/"—" (preço em ~10–20 s; dólar comercial e taxas em ~3 min)
- [ ] O preço muda a cada ~1 s (WebSocket); o % já abre com a seta ↔ e não se desloca quando a seta muda
- [ ] Criar, alternar tipo e apagar alerta; os alertas persistem após fechar e reabrir; com muitos alertas, só a lista rola
- [ ] Um alerta dispara (som + diálogo) e fica desativado após fechar o diálogo
- [ ] Pausar/retomar: o overlay aparece, o gráfico some (se estava aberto), a rede para e tudo volta ao retomar
- [ ] Inatividade: sem alertas, pausa após ~17 min; com alerta ativo, não pausa; depois de um alarme, só pausa ~17 min após a próxima atividade
- [ ] Queda de internet: com alertas, não pausa e o preço volta sozinho; sem alertas, pausa após ~30–60 s
- [ ] Fixar/desafixar no topo; ↻ com a janela fixada desafixa e recarrega
- [ ] Centralizar (na área livre, fora da barra de tarefas), minimizar, fechar (a posição e o modo são restaurados ao reabrir) nos dois modos
- [ ] Arraste: a janela gruda a até 20 px de cada borda da tela e da barra de tarefas (também em outro monitor e com escala diferente de 100%) e solta ao afastar; arrastar não ativa a janela nem tira a fixação no topo; botões, campo do alerta e barra de rolagem da lista não arrastam; com os botões do mouse trocados, o arraste funciona
- [ ] Modo compacto: ⊟/⊞ alterna 500×810 ↔ 500×388 mantendo o topo; perto da borda de baixo ou da barra de tarefas, a janela sobe ao expandir até ficar acima dela; reabre no modo salvo com o rodapé inteiro visível; ↻ mantém o modo; a fixação no topo se mantém ao alternar; pausa e alertas cabem na janela
- [ ] No navegador, o modo compacto sobrevive ao F5, e a pausa e os alertas ficam dentro do bloco do conteúdo
- [ ] O gráfico abre oculto (a tabela de máximas/mínimas/taxas fica à mostra); ⇄ o mostra cobrindo a tabela inteira, com a borda de cima sobre a linha separadora, e o oculta de novo; no navegador, idem em vários tamanhos de janela; no modo compacto, o gráfico some e volta ao expandir
- [ ] A fonte Roboto aparece normalmente
- [ ] O `.exe` de produção abre e não cria nem altera o `%APPDATA%\btcstatus\metricas.jsonl`

### Em aberto (próximos passos)

Referência: a tabela "Abertura medida" na §4. O 1º preço já aparece logo depois do `DOMContentLoaded`; o que sobra depende de a página começar mais cedo ou mexe só na ponte e no WebSocket (o gráfico não entra mais na abertura padrão).

1. **Medir de novo a abertura** com o build `-ComMedicao`, incluindo o marco `tamanho_ajustado` (deve ficar antes de "Página começa a carregar") e o modo compacto.
2. **Cache dos arquivos da página.** O servidor local envia `no-store`. Trocar por `no-cache` com validação pela data do arquivo (304) permitiria ao WebView2 guardar o `script.js` já compilado entre aberturas. Ganho estimado pequeno (5–20 ms na execução dos scripts); medir com `--comparar`.
3. **Rodar `tools\medir_websocket.py`** e decidir a porta (9443 × 443). O WebSocket conecta só em ~1,5–2 s e é o que traz o 2º preço em diante.
4. **Imports do Python** (~40 ms entre o bootloader e os imports): medir com `python -X importtime` antes de propor algo.
5. **Injeção da ponte pelo pywebview** (~50 ms de JS na página depois do `load`): só reduzível alterando o comportamento interno do pywebview (ex.: não injetar o `polyfill.js`). Afeta a ponte, não o preço. Alto risco em atualizações.
6. **Medir a latência dos domínios públicos da Binance** (`data-api.binance.vision` / `data-stream.binance.vision`). Hoje só afetaria o REST de reserva e os ciclos seguintes. Verificar antes se os domínios existem e estão em uso.
7. **Medir CPU e memória do widget do TradingView** (o processo `msedgewebview2` dele) quando aberto. Se for alto, avaliar trocá-lo por um gráfico próprio com os candles da Binance.
8. *(Estrutural)* A subida do .NET (~305 ms) e do WebView2 (~220 ms até a página começar) é o que hoje segura a página e o 1º preço. Só cai trocando o pywebview por um hospedeiro de WebView2 sem .NET.
