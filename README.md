# BTC Status

Monitor de preço do Bitcoin para Windows: uma janela pequena, sem moldura, que mostra em tempo real o preço do BTC em reais e em dólares, as taxas da rede e um gráfico, com alertas de preço sonoros.

## Funcionalidades

- **Preço do Bitcoin em BRL e USDT** (Binance), atualizado a cada ~1 s pelo WebSocket, com máxima e mínima de 24 h, variação percentual e seta de direção.
- **Dólar implícito** (BTC/BRL ÷ BTC/USDT) e **dólar comercial** (AwesomeAPI).
- **Taxas da rede Bitcoin** (mempool.space), em sat/vB.
- **Gráfico de candles BTC/BRL** (widget do TradingView), que pode ser mostrado ou ocultado.
- **Alertas de preço** "maior que" e "menor que", com som e aviso. Cada alerta dispara uma vez e fica desativado.
- **Abertura rápida:** o 1º preço novo aparece em ~0,7 s após abrir o app. Antes disso, a tela já mostra os últimos valores salvos.
- **Janela prática:** pode ficar fixa no topo, ser centralizada no monitor e lembra a posição ao reabrir.
- **Economia de recursos:** pausa sozinha após ~17 min sem uso (exceto com alertas ativos ou com a janela fixada) e pode ser pausada manualmente.

## Requisitos

- Windows 10 ou 11, com o [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (já vem no Windows 11).
- Para rodar pelo código-fonte ou gerar o executável: Python 3.14.
- Para os testes: Node.js e o Microsoft Edge (testes de página com Playwright).

## Instalação (pelo código-fonte)

```powershell
git clone <url-do-repositorio> btcstatus
cd btcstatus
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Para desenvolvimento (build e testes):

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Os testes de página usam o Microsoft Edge já instalado no Windows.

## Uso

Executar pelo código-fonte:

```powershell
.\runbtc.ps1
```

### Controles da janela

| Botão | Ação |
|---|---|
| ⏱ | Abre a tela de alertas |
| ⇄ | Mostra ou oculta o gráfico |
| ■ | Pausa ou retoma o monitoramento |
| △ | Fixa ou solta a janela no topo |
| ▣ | Centraliza a janela no monitor |
| ↻ | Recarrega a página |
| _ / x | Minimiza / fecha |

A janela pode ser arrastada por qualquer área livre.

### Alertas

Na tela de alertas, digite um valor em reais e adicione. O botão de tipo de cada alerta alterna entre **Maior** (dispara quando o preço fica igual ou acima do valor), **Menor** (igual ou abaixo) e **Desativado**. Quando um alerta dispara, toca o som, aparece um aviso e ele é desativado.

Os alertas ficam salvos em `%APPDATA%\btcstatus\Alertas.json`.

### No navegador

O `index.html` também abre direto num navegador comum, com funções reduzidas: alertas (salvos no próprio navegador), gráfico e pausa.

## Gerar o executável

```powershell
.\criar_exe_btc.ps1              # roda os testes e gera o executável de produção
.\criar_exe_btc.ps1 -SemTestes   # sem os testes
```

O resultado fica em `dist\BTC Monitor\`. Para distribuir, copie a pasta inteira; o programa é `BTC Monitor.exe`. Feche o app antes de gerar um novo build (o script avisa se houver um aberto).

## Testes

```powershell
.venv\Scripts\python.exe -m pytest tests
node --test tests/regras.test.js tests/metricas.test.js
```

Os testes de página rodam no Microsoft Edge com a rede simulada (Binance, WebSocket e TradingView falsos). A suíte de desempenho fica separada:

```powershell
.venv\Scripts\python.exe -m pytest tests\desempenho -m desempenho
```

## Medição de desempenho

O código-fonte e o build de teste (`.\criar_exe_btc.ps1 -ComMedicao`) registram tempos da abertura e do funcionamento em `%APPDATA%\btcstatus\metricas.jsonl`. O executável de produção não tem nenhuma medição.

```powershell
.venv\Scripts\python.exe tools\medir_abertura.py --vezes 10
.venv\Scripts\python.exe tools\analisar_metricas.py --ultimas 3
```

Os instrumentos, inclusive as comparações A/B (`--comparar`), estão descritos em [MEDICAO.md](MEDICAO.md).

## Como funciona

- O app é uma janela [pywebview](https://pywebview.flowrl.com/) (WebView2) que carrega uma página HTML/CSS/JavaScript servida por um servidor local do próprio app, em `http://127.0.0.1:42001/`.
- Ao abrir, o Python já pede o preço à Binance em paralelo com a subida da janela, e o servidor entrega esse preço dentro do HTML. Depois, a página recebe os preços pelo WebSocket da Binance, com consultas REST como reserva.
- A comunicação entre a página e o Python (alertas, janela no topo, centralizar) usa a ponte do pywebview.

## Estrutura

| Arquivo | Conteúdo |
|---|---|
| `BTC_Monitor.py` | Ponto de entrada: janela, posição, perfil do WebView2 e API chamada pela página |
| `servidor_local.py` | Servidor da página (HTML, arquivos e 1º preço) |
| `primeiro_preco.py` | Busca do 1º preço pelo Python durante a abertura |
| `alertas_store.py` | Validação e gravação dos alertas |
| `topo_janela.py` | Fixar a janela no topo (Win32) |
| `index.html`, `style.css`, `script.js`, `regras.js` | A página |
| `metricas.py`, `metricas.js`, `metricas_desligadas.js` | Medição de desempenho (fora do build de produção) |
| `BTC Monitor.spec`, `criar_exe_btc.ps1` | Build com o PyInstaller |
| `tools/` | Ferramentas de medição |
| `tests/` | Testes Python, JavaScript e de página |

## Dados do usuário

Ficam em `%APPDATA%\btcstatus\`:

| Arquivo | Conteúdo |
|---|---|
| `Alertas.json` | Alertas de preço |
| `BTC Monitor.ini` | Posição da janela |
| `btcstatus.log` | Log de erros (primeiro lugar a olhar se algo falhar) |
| `webview\` | Perfil do WebView2 (cache e último estado exibido) |

Para começar do zero, feche o app e apague a pasta.

## Fontes de dados

- [Binance](https://www.binance.com/): preços BTC/BRL e BTC/USDT (REST e WebSocket).
- [AwesomeAPI](https://docs.awesomeapi.com.br/): dólar comercial (consultado no máximo 1 vez por minuto).
- [mempool.space](https://mempool.space/): taxas da rede Bitcoin.
- [TradingView](https://www.tradingview.com/): widget do gráfico.

Os dados são apenas informativos e podem ter atraso ou falhas. Este programa não é recomendação de investimento e não tem vínculo com os serviços acima.
