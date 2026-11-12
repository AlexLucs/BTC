# Medição de desempenho do BTC Status

## Produção × medição

A medição **não faz parte da versão de produção**:

| Onde | Medição |
|---|---|
| `.\criar_exe_btc.ps1` (padrão) | **Nenhuma.** O `metricas.py` fica fora do `.exe`, o `metricas.js` empacotado é o substituto vazio (`metricas_desligadas.js`) e nada é gravado em `metricas.jsonl` |
| `.\criar_exe_btc.ps1 -ComMedicao` | Build de teste, com o coletor real. É o que o `tools\medir_abertura.py --exe` precisa |
| Código-fonte (`.\runbtc.ps1`, testes) | Ativa (ambiente de desenvolvimento) |

`tests\test_producao.py` e o teste de página com o substituto vazio garantem que a produção funciona sem a medição.

Três instrumentos, do mais real ao mais controlado.

## 1. Métricas do app em uso (sempre ligadas)

O app grava em `%APPDATA%\btcstatus\metricas.jsonl`:

- abertura, do Python e da página;
- duração das funções, da rede e dos métodos Python;
- tarefas longas (> 50 ms);
- memória do JS;
- minimizar e restaurar, e a visibilidade da página.

A página envia um relatório na abertura, a cada 5 min, ao clicar em ↻ e ao fechar pelo **x**. Fechar por Alt+F4 ou pela barra de tarefas perde só o período em curso.

```powershell
.venv\Scripts\python.exe tools\analisar_metricas.py              # todas as sessões
.venv\Scripts\python.exe tools\analisar_metricas.py --ultimas 3
.venv\Scripts\python.exe tools\analisar_metricas.py --json resumo.json
```

Para responder à pergunta "a página percebe quando a janela é minimizada?":

1. Abra o app.
2. Minimize por 1 a 2 min e restaure.
3. Rode a análise e veja a seção 4.

Para desligar a coleta, mude `ATIVAS` para `false` em `metricas.js`.

Contadores do WebSocket na seção 3:

| Contador | O que conta |
|---|---|
| `ws:conexoes` | conexões abertas |
| `ws:queda:fechado` / `ws:queda:silencio` | quedas, por motivo |
| `ws:mensagens` | mensagens recebidas |

Na seção 2:

| Medida | O que mede |
|---|---|
| `ws:intervalo_brl` | tempo entre mensagens de BTC/BRL (~1000 ms) |
| `ws:idade_evento` | idade da mensagem ao chegar; inclui a diferença de relógio com a Binance |
| `ws:conexao` | tempo para conectar |

## 2. Abertura repetida (automática)

Com o app fechado:

```powershell
.venv\Scripts\python.exe tools\medir_abertura.py                                   # 5x pelo Python
.\criar_exe_btc.ps1 -ComMedicao                                                       # build de teste
.venv\Scripts\python.exe tools\medir_abertura.py --exe "dist\BTC Monitor\BTC Monitor.exe"
.\criar_exe_btc.ps1                                                                   # volta ao build de produção
```

A 1ª execução é a abertura "fria" e costuma ser mais lenta. O app é fechado à força, então a posição da janela não é salva nessas execuções.

## 2b. Portas do WebSocket da Binance (rede real)

```powershell
.venv\Scripts\python.exe tools\medir_websocket.py --vezes 10
```

Compara as portas 9443 e 443 do stream, alternando a ordem entre elas. Mostra o tempo de conexão e o tempo até a 1ª mensagem. Só vale trocar a porta (em `URL_WS_TICKERS` no `script.js` e no `connect-src` da CSP) se a diferença for grande e se repetir em outra execução.

## 2b'. Thread da página ocupada na abertura

A seção 1b do relatório lista, para cada abertura, os momentos dos primeiros 2 s em que a thread da página ficou ocupada por mais de 15 ms (início em ms desde a criação do processo e duração). O Long Tasks API só registra tarefas acima de 50 ms; aqui um timer encadeado do `metricas.js` mede o intervalo entre execuções. A seção 1 traz também as etapas do 1º preço vindo do Python: pedido a `/preco-inicial`, resposta, dados lidos e a volta do código do preço.

## 2c. Comparar um recurso da abertura (com × sem)

```powershell
.venv\Scripts\python.exe tools\medir_abertura.py --comparar preconnect --vezes 20
.venv\Scripts\python.exe tools\medir_abertura.py --comparar preco-python --vezes 20
```

Alterna aberturas com e sem o recurso (ordem com, sem, sem, com...). Só o app com a medição ativa obedece às variáveis que desligam cada um; a produção as ignora.

| Recurso | Variável | Nas aberturas "sem" |
|---|---|---|
| `preconnect` | `BTC_SEM_PRECONNECT=1` | o servidor local (`servidor_local.py`) entrega o `index.html` sem as dicas `<link rel="preconnect">` / `dns-prefetch` |
| `preco-python` | `BTC_SEM_PRECO_PYTHON=1` | o Python não busca o 1º preço (`/preco-inicial` responde 204); a página fica só com o REST |
| `preload-fonte` | `BTC_SEM_AJUSTE_PRELOAD=1` | o servidor local entrega o `index.html` sem acrescentar `crossorigin` ao preload da fonte (por http o preload é descartado e a fonte é lida duas vezes) |
| `tipos-fixos` | `BTC_SEM_TIPOS_FIXOS=1` | o servidor local deixa o bottle adivinhar o tipo de cada arquivo pelo `mimetypes`, que na 1ª vez lê o registro do Windows |
| `preco-no-html` | `BTC_SEM_PRECO_NO_HTML=1` | o 1º preço não vai dentro do HTML; a página o pede em `/preco-inicial` (correndo contra o REST) |

A tabela final mostra a mediana de cada metade e o ganho (sem − com) das etapas que dependem da rede, a duração da 1ª requisição a cada servidor (`rede1:<servidor>`, também na seção 2 do relatório comum) e de onde veio o 1º preço (`primeiro_preco:python` / `primeiro_preco:rest`). A tabela também mostra quando a fonte chegou e quantas vezes cada arquivo da página foi lido (`recurso_n:<arquivo>`; o ideal é 1). `--comparar-preconnect` continua valendo.

Na seção 1 do relatório comum aparecem, para cada arquivo da própria página (CSS, JS, fonte, ícone), o instante em que foi pedido e o instante em que chegou (`recurso_inicio:<arquivo>` / `recurso:<arquivo>`), junto das outras etapas: é por aí que se vê o que segura o `load`. Do lado do Python, o servidor local registra quando cada pedido chegou e quando terminou de enviar a resposta (`servidor_pedido:<arquivo>` / `servidor_fim:<arquivo>`). Aceita `--exe` com o build `-ComMedicao`.

## 3. Testes de desempenho (laboratório)

Ficam fora do `python -m pytest tests` e do `criar_exe_btc.ps1`.

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests\desempenho -m desempenho
```

- **Python:** validação, disco, métricas e custo dos imports da abertura.
- **JS (Node):** funções puras em µs.
- **Página (Playwright + Edge, rede simulada):**
  - marcos da abertura;
  - custo por ciclo com 100 alertas (layouts, estilo, script, heap e nós DOM);
  - animação da seta;
  - montagem do gráfico e tabela de alertas;
  - integração do relatório JS com o Python.

Cada execução grava `tests\desempenho\resultados\<data-hora>.json` e mostra a variação (Δ %) em relação à execução anterior.

Variáveis de ambiente:

| Variável | Efeito |
|---|---|
| `BTC_SEM_ORCAMENTO=1` | só mede, não falha por orçamento |
| `BTC_NAVEGADOR=msedge\|chrome\|chromium` | escolhe o navegador (padrão: Edge, depois Chrome) |
| `BTC_REDE_REAL=1` | usa a internet em vez da rede simulada |
| `BTC_DESEMPENHO_ABERTURAS=5`, `BTC_DESEMPENHO_CICLOS=200` | tamanho das amostras |

## Limitações

- No WebView2, `performance.now()` tem resolução de cerca de 0,1 ms. Medidas abaixo disso aparecem como 0 nas métricas da página. Para funções rápidas, use o benchmark JS (µs).
- Nos testes de página, as esperas de 1 s ou mais são aceleradas 50×. Por isso, contagens ligadas a animações por ciclo ficam distorcidas. O teste `test_animacao_da_seta` mede em tempo real.
- O teste de página usa o Edge, mas não o WebView2 dentro do pywebview. Os números absolutos do app vêm do instrumento 1.

## Testes funcionais da página

`tests\test_pagina_funcional.py` roda junto com `python -m pytest tests` (e no `criar_exe_btc.ps1`). Ele usa o mesmo Playwright, com a rede simulada, e verifica:

- o último estado salvo aparece antes da rede e nunca dispara alarmes;
- o estado salvo resiste a falhas e depois vira "Sem Dados";
- a pausa por inatividade não acontece com alerta ativo;
- o gráfico espera a ponte do Python;
- o preload da fonte é aproveitado (sem "crossorigin", por ser `file://`);
- o WebSocket da Binance:
  - atualiza o preço e para o polling REST;
  - quando cai ou fica em silêncio (nenhum par por 10 s), o app volta ao REST e reconecta;
  - o BTC/BRL calado com o USDT chegando não derruba a conexão;
  - pausar fecha a conexão;
  - o alarme dispara pelo preço do WebSocket.

O WebSocket simulado usa `route_web_socket`, que exige Playwright 1.48 ou mais recente.

Se o Playwright ou o navegador não estiverem disponíveis, esses testes são pulados.

