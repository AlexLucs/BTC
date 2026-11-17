<#
.SYNOPSIS
    Prepara um pacote para a revisao de codigo do BTC Status: fontes, bibliotecas externas usadas,
    ambiente, resultados dos testes e verificacoes automaticas.

.DESCRIPTION
    Junta numa pasta com data e hora (e num .7z) tudo o que uma revisao detalhada precisa, sem
    alterar o codigo do projeto:

      fontes\      Copia dos arquivos do projeto (raiz, tools, tests), sem .venv, build, dist e
                   caches, mais os 2 resultados mais recentes de tests\desempenho\resultados.
      externos\    Arquivos do pywebview e do bottle instalados no .venv dos quais o app depende
                   (util.py, http.py, window.py, screen.py, edgechromium.py, winforms.py, js\*,
                   bottle.py), lista completa do pacote webview e versoes das DLLs, para conferir
                   o comportamento real das bibliotecas em vez de presumir.
      ambiente.md  Windows (build), PowerShell, Python, pip freeze, pip check, Node, Playwright,
                   WebView2 Runtime, 7-Zip e git (se houver).
      testes\      pytest (saida, JUnit XML, 30 testes mais lentos e reexecucao so das falhas,
                   para separar falha real de falha ocasional), node --test e, opcionais,
                   desempenho e cobertura.
      analise\     Verificacoes das armadilhas (secao 8 do context.md) e das convencoes (secao 7),
                   so no codigo (comentarios e docstrings que citam uma armadilha nao contam);
                   arquivos duplicados ou fora do lugar; codificacao e quebras de linha;
                   versoes das dependencias diferentes das conferidas (armadilhas a rever).
                   Opcionais: ruff, bandit, vulture, radon e pip-audit.
      build\       tools\conferir_build.py sobre dist\BTC Monitor, se existir um build, e os
                   avisos do PyInstaller (warn-BTC Monitor.txt).
      logs\        btcstatus.log* de %APPDATA%\btcstatus (so com -ComLogs).
      INDICE.md    Resumo de tudo, comando usado, SHA-256 deste script e manifesto dos
                   arquivos (linhas, bytes, SHA-256).

    No fim, compacta a pasta num .7z (7-Zip, compressao maxima). Sem o 7-Zip (7z no PATH ou em
    Arquivos de Programas\7-Zip), avisa no inicio e entrega so a pasta.

    Falhas de teste e achados dos analisadores nao interrompem o script: viram parte do pacote.
    Nada e instalado no .venv do projeto, exceto o coverage com -ComCobertura. Os analisadores
    ficam num venv proprio em %LOCALAPPDATA%\btcstatus-revisao\venv.

.PARAMETER Destino
    Pasta onde a pasta revisao_<data-hora> e o .7z sao criados. Padrao:
    %USERPROFILE%\Downloads\btcstatus_revisao (fora do projeto, para nao entrar nos testes nem no
    build).

.PARAMETER SemTestes
    Nao roda pytest nem node --test (so copia, ambiente, verificacoes e analisadores pedidos).

.PARAMETER ComDesempenho
    Roda tambem tests\desempenho (-m desempenho). Demora mais e grava em tests\desempenho\resultados.

.PARAMETER ComCobertura
    Roda o pytest sob o coverage (com ramos) e gera o relatorio por arquivo; no Node (20+), usa
    --experimental-test-coverage. Instala o coverage no .venv se faltar. Mede tambem o JS da
    pagina (script.js, regras.js, metricas.js) durante os testes de pagina, pelo Profiler do
    Chromium (variavel BTC_COBERTURA_JS, lida por tests\apoio_pagina.py), com relatorio pelo
    c8 (npx c8@10; exige Node e, na 1a vez, internet).

.PARAMETER ComAnalisadores
    Cria (na 1a vez) ou atualiza um venv separado com ruff, bandit, vulture, radon e pip-audit e
    roda todos. Exige internet (instalacao e base do pip-audit).

.PARAMETER ComLogs
    Inclui os btcstatus.log* do app (podem conter caminhos com o nome do usuario).

.PARAMETER SemCompactar
    Nao gera o .7z no fim (entrega so a pasta).

.EXAMPLE
    .\preparar_revisao.ps1
    Fontes, externos, ambiente, verificacoes e testes padrao.

.EXAMPLE
    .\preparar_revisao.ps1 -ComCobertura -ComAnalisadores
    Pacote completo para uma revisao detalhada (recomendado).

.EXAMPLE
    .\preparar_revisao.ps1 -SemTestes -Destino C:\Temp\revisao
    So arquivos, ambiente e verificacoes, numa pasta escolhida.
#>
[CmdletBinding()]
param(
    [string] $Destino = (Join-Path $env:USERPROFILE 'Downloads\btcstatus_revisao'),
    [switch] $SemTestes,
    [switch] $ComDesempenho,
    [switch] $ComCobertura,
    [switch] $ComAnalisadores,
    [switch] $ComLogs,
    [switch] $SemCompactar
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------------------------
$Raiz = $PSScriptRoot
$MeuNome = Split-Path -Leaf $PSCommandPath
# Para o INDICE: com que versao deste script e com que comando o pacote foi gerado.
$ComandoUsado = $MyInvocation.Line.Trim()
$ShaDoScript = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
$Python = Join-Path $Raiz '.venv\Scripts\python.exe'
$SitePackages = Join-Path $Raiz '.venv\Lib\site-packages'
$Invariante = [Globalization.CultureInfo]::InvariantCulture
$Utf8SemBom = New-Object System.Text.UTF8Encoding($false)
$Latin1 = [Text.Encoding]::GetEncoding(28591)
$BT = [string][char]96   # crase, para codigo em Markdown (no PowerShell a crase e escape)
$Etapas = New-Object System.Collections.Generic.List[object]
$script:Passo = 0

$PastasExcluidas = @('.venv', 'build', 'dist', '__pycache__', '.pytest_cache', '.ruff_cache',
    '.mypy_cache', 'node_modules', '.git', 'htmlcov', 'resultados', 'revisao')
$ExtensoesExcluidas = @('.pyc', '.pyo', '.log', '.jsonl', '.zip', '.7z', '.tmp', '.bak', '.exe',
    '.dll', '.coverage')
$ExtensoesDeTexto = @('.py', '.js', '.mjs', '.html', '.css', '.md', '.txt', '.ini', '.cfg',
    '.toml', '.json', '.spec', '.ps1', '.psm1', '.svg', '.yml', '.yaml', '.gitignore')
$ExtensoesDeCodigo = @('.py', '.js', '.html', '.css', '.ps1')

# Arquivos das bibliotecas externas que o app usa de forma nao documentada (context.md, sec. 4 e 8)
$ExternosFixos = @(
    'webview\__init__.py', 'webview\util.py', 'webview\http.py', 'webview\window.py',
    'webview\screen.py', 'webview\event.py', 'webview\errors.py', 'webview\menu.py',
    'webview\platforms\edgechromium.py', 'webview\platforms\winforms.py', 'bottle.py'
)

# Arquivos que precisam estar na raiz (armadilha 56) ou que o build exige
$ObrigatoriosNaRaiz = @('BTC_Monitor.py', 'index.html', 'script.js', 'regras.js', 'metricas.js',
    'metricas_desligadas.js', 'style.css', 'Roboto.woff2', 'alerta.mp3', 'btc-logo.svg',
    'btc-logo.ico', 'BTC Monitor.spec', 'requirements.txt', 'requirements-dev.txt', 'pytest.ini',
    'criar_exe_btc.ps1', 'runbtc.ps1')

# Versoes em que o context.md foi conferido. Outra versao instalada: rever estas armadilhas
# (comportamentos internos que o app usa; ver "Ao atualizar" nelas). Terminada em ".": prefixo.
$VersoesConferidas = @(
    @{ Pacote = 'pywebview'; Conferida = '6.2.1'; Armadilhas = '1, 13, 14, 24, 30, 39, 42, 45, 53, 68' }
    @{ Pacote = 'pyinstaller'; Conferida = '6.22.'; Armadilhas = '9, 16, 43, 44' }
)

# Regras do ruff que o projeto segue de proposito (nao sao achados):
#   PLC0415 import dentro da funcao (abertura rapida, armadilha 48); N806 nomes do Win32
#   (LONG_PTR...); RUF001/RUF002 travessao do portugues; E501 linha longa.
$RuffIgnorar = 'E501,PLC0415,N806,RUF001,RUF002'

# Nomes que podem repetir em pastas diferentes sem ser copia esquecida.
$NomesQuePodemRepetir = @('__init__.py', 'conftest.py', 'readme.md')

# Verificacoes por expressao regular. Escopos: app-py, app-js, app-html, app-web, py, codigo.
# Sao candidatos: cada ocorrencia precisa ser conferida no codigo. So no codigo: comentarios
# e docstrings ficam de fora (eles citam as armadilhas), exceto onde SoCodigo = $false.
$Regras = @(
    @{ Id = 'A1'; Escopo = 'app-py'; Padrao = '\.on_top\b'
       Descricao = 'window.on_top (armadilha 1: setter .NET pela thread da js_api trava o app)' }
    @{ Id = 'A8'; Escopo = 'app-js'; Padrao = '\bsetInterval\s*\('
       Descricao = 'setInterval (armadilha 8: ciclos por cadeia de setTimeout)' }
    @{ Id = 'A14'; Escopo = 'app-py'; Padrao = 'private_mode\s*=\s*True'
       Descricao = 'private_mode=True (armadilha 14)' }
    @{ Id = 'A15'; Escopo = 'app-py'; Padrao = '\bwindll\b'
       Descricao = 'windll compartilhado em vez de ctypes.WinDLL proprio (armadilha 15)' }
    @{ Id = 'A26'; Escopo = 'app-py'; Padrao = 'TCP_NODELAY'
       Descricao = 'TCP_NODELAY no servidor local (armadilha 26)' }
    @{ Id = 'A39'; Escopo = 'app-web'; Padrao = 'easy_drag\s*=\s*True|pywebview-drag-region'
       Descricao = 'easy_drag ou pywebview-drag-region (armadilha 39)' }
    @{ Id = 'A45'; Escopo = 'app-py'
       Padrao = 'ssl\s*=\s*True|^\s*(import|from)\s+(urllib\.request|http\.client|requests|ssl)\b'
       Descricao = 'TLS/HTTPS no Python do app (armadilha 45; o esperado e so em ssl_ausente.py)' }
    @{ Id = 'A63'; Escopo = 'app-py'; Padrao = 'ShowInTaskbar'
       Descricao = 'Form.ShowInTaskbar (armadilha 63)' }
    @{ Id = 'A66'; Escopo = 'app-py'; Padrao = '\bWM_TIMER\b|\bSetTimer\b'
       Descricao = 'WM_TIMER/SetTimer na vigia (armadilha 66)' }
    @{ Id = 'A67'; Escopo = 'app-py'; Padrao = 'EVENT_OBJECT_(SHOW|HIDE|DESTROY|LOCATIONCHANGE)\b'
       Descricao = 'Gancho global de alta frequencia (armadilha 67)' }
    @{ Id = 'C-print'; Escopo = 'app-py'; Padrao = '(?<![\w.])print\s*\('
       Descricao = 'print no app (convencao: logging; o exe nao tem console)' }
    @{ Id = 'C-except'; Escopo = 'py'; Padrao = '^\s*except\s*:'
       Descricao = 'except sem tipo' }
    @{ Id = 'C-pass'; Escopo = 'py'; Padrao = '^\s*except\b[^:]*:\s*pass\s*(#.*)?$'
       Descricao = 'except com pass na mesma linha (erro engolido sem log)' }
    @{ Id = 'C-html'; Escopo = 'app-js'
       Padrao = '\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML\s*\(|document\.write\s*\('
       Descricao = 'HTML montado por texto (convencao: textContent/replaceChildren)' }
    @{ Id = 'C-var'; Escopo = 'app-js'; Padrao = '^\s*var\s'
       Descricao = 'var (convencao: const/let)' }
    @{ Id = 'C-console'; Escopo = 'app-js'; Padrao = 'console\.(log|debug|trace)\s*\('
       Descricao = 'console.log/debug/trace esquecido' }
    @{ Id = 'S-eval'; Escopo = 'app-js'
       Padrao = '\beval\s*\(|new\s+Function\s*\(|set(Timeout|Interval)\s*\(\s*[''"]'
       Descricao = 'eval, new Function ou timer com texto' }
    @{ Id = 'S-inline'; Escopo = 'app-html'; Padrao = '\son[a-z]+\s*=\s*["'']'
       Descricao = 'Handler inline no HTML (secao 6)' }
    @{ Id = 'S-script'; Escopo = 'app-html'
       Padrao = '<script(?![^>]*\bsrc\s*=)(?![^>]*application/json)[^>]*>'
       Descricao = 'Script inline sem src (CSP sem unsafe-inline em script-src)' }
    @{ Id = 'C-todo'; Escopo = 'codigo'; Padrao = '\b(TODO|FIXME|XXX|HACK)\b'; SoCodigo = $false
       Descricao = 'TODO/FIXME/XXX/HACK (inclusive em comentarios)' }
)

# ---------------------------------------------------------------------------------------------
# Funcoes
# ---------------------------------------------------------------------------------------------
function Write-Passo([string] $Texto) {
    $script:Passo++
    Write-Host ('[{0}] {1}' -f $script:Passo, $Texto) -ForegroundColor Cyan
}

function Write-TextoUtf8([string] $Caminho, [string] $Texto) {
    $pasta = Split-Path -Parent $Caminho
    if (-not (Test-Path -LiteralPath $pasta)) { New-Item -ItemType Directory -Path $pasta -Force | Out-Null }
    [IO.File]::WriteAllText($Caminho, $Texto, $Utf8SemBom)
}

function Read-TextoUtf8([string] $Caminho) {
    if (-not (Test-Path -LiteralPath $Caminho)) { return '' }
    return [IO.File]::ReadAllText($Caminho, [Text.Encoding]::UTF8)
}

function ConvertTo-Argumento([string] $Valor) {
    if ($Valor -eq '') { return '""' }
    if ($Valor -notmatch '[\s"]') { return $Valor }
    return '"' + ($Valor -replace '"', '\"') + '"'
}

function ConvertTo-CelulaMd([string] $Texto) {
    return ($Texto -replace '\|', '\|' -replace '\r?\n', ' ')
}

function Get-Comando([string] $Nome) {
    $comando = Get-Command $Nome -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($comando) { return $comando.Source }
    return $null
}

function Get-Relativo([string] $Caminho) {
    return $Caminho.Substring($Raiz.Length).TrimStart('\')
}

function Invoke-Etapa {
    # Roda um programa externo com saida e erro em arquivos (sem o problema do 2>&1 no 5.1),
    # com prazo. Com -ArquivoSaida, grava o relatorio e registra a etapa no INDICE.
    param(
        [Parameter(Mandatory = $true)] [string] $Nome,
        [Parameter(Mandatory = $true)] [string] $Executavel,
        [string[]] $Argumentos = @(),
        [string] $ArquivoSaida = '',
        [int] $LimiteMin = 30
    )
    $linha = (@($Argumentos) | ForEach-Object { ConvertTo-Argumento $_ }) -join ' '
    $tmpSaida = [IO.Path]::GetTempFileName()
    $tmpErro = [IO.Path]::GetTempFileName()
    $inicio = Get-Date
    $codigo = $null
    try {
        $opcoes = @{
            FilePath               = $Executavel
            WorkingDirectory       = $Raiz
            NoNewWindow            = $true
            PassThru               = $true
            RedirectStandardOutput = $tmpSaida
            RedirectStandardError  = $tmpErro
        }
        if ($linha) { $opcoes['ArgumentList'] = $linha }
        $processo = Start-Process @opcoes
        $null = $processo.Handle   # sem isso o ExitCode pode vir vazio no PowerShell 5.1
        if ($processo.WaitForExit($LimiteMin * 60000)) {
            $processo.WaitForExit()
            $codigo = $processo.ExitCode
        } else {
            try {
                Start-Process -FilePath 'taskkill.exe' -ArgumentList ('/T /F /PID {0}' -f $processo.Id) `
                    -NoNewWindow -Wait | Out-Null
            } catch { }
            $codigo = 'tempo esgotado ({0} min)' -f $LimiteMin
        }
    } catch {
        $codigo = 'nao iniciou: ' + $_.Exception.Message
    }
    $duracao = [math]::Round(((Get-Date) - $inicio).TotalSeconds, 1)
    $textoSaida = Read-TextoUtf8 $tmpSaida
    $textoErro = Read-TextoUtf8 $tmpErro
    Remove-Item -LiteralPath $tmpSaida, $tmpErro -ErrorAction SilentlyContinue

    $resultado = [pscustomobject]@{
        Nome     = $Nome
        Comando  = ('{0} {1}' -f $Executavel, $linha).Trim()
        Codigo   = $codigo
        Duracao  = $duracao
        Saida    = $textoSaida
        Erro     = $textoErro
        Arquivo  = $ArquivoSaida
    }
    if ($ArquivoSaida) {
        $texto = @(
            ('# {0}' -f $Nome), '',
            ('Comando: {0}' -f $resultado.Comando),
            ('Pasta: {0}' -f $Raiz),
            ('Codigo de saida: {0}' -f $codigo),
            ('Duracao: {0} s' -f $duracao.ToString($Invariante)), '',
            '--- saida padrao ---', $textoSaida,
            '--- saida de erro ---', $textoErro
        ) -join "`r`n"
        Write-TextoUtf8 $ArquivoSaida $texto
        $Etapas.Add($resultado)
        $cor = 'Gray'
        if ($codigo -isnot [int]) { $cor = 'Yellow' }
        Write-Host ('      {0}: codigo {1}, {2} s' -f $Nome, $codigo, $duracao.ToString($Invariante)) -ForegroundColor $cor
    }
    return $resultado
}

function Get-ArquivosDoProjeto([string] $Pasta) {
    foreach ($item in (Get-ChildItem -LiteralPath $Pasta -Force)) {
        if ($item.PSIsContainer) {
            if ($PastasExcluidas -contains $item.Name -or $item.Name -like '.venv*') { continue }
            if ($item.FullName.TrimEnd('\') -eq $DestinoCompleto) { continue }
            Get-ArquivosDoProjeto $item.FullName
        } elseif ($ExtensoesExcluidas -notcontains $item.Extension.ToLowerInvariant()) {
            $item
        }
    }
}

function Get-LinhasDeCodigo([object] $Arquivo) {
    # Por linha, so o codigo: comentarios e docstrings viram '' (eles citam as armadilhas,
    # ex.: "Nao usar window.on_top", e nao sao defeitos). Aproximado de proposito: um "#"
    # ou "//" dentro de texto tambem corta a linha; para achar candidatos basta.
    $linhas = [IO.File]::ReadAllLines($Arquivo.Caminho, [Text.Encoding]::UTF8)
    $resultado = New-Object 'string[]' $linhas.Count
    $inicios = switch ($Arquivo.Ext) {
        '.py'   { @('"""', "'''") }
        '.html' { @('<!--') }
        '.js'   { @('/*') }
        '.css'  { @('/*') }
        default { @() }
    }
    $aberto = $null   # fim do bloco aberto: aspas triplas, '*/' ou '-->'
    for ($i = 0; $i -lt $linhas.Count; $i++) {
        $linha = $linhas[$i]
        $codigo = ''
        while ($true) {
            if ($aberto) {
                $fim = $linha.IndexOf($aberto)
                if ($fim -lt 0) { break }
                $linha = $linha.Substring($fim + $aberto.Length)
                $aberto = $null
                continue
            }
            $posicao = -1; $marca = $null
            foreach ($candidato in $inicios) {
                $p = $linha.IndexOf($candidato)
                if ($p -ge 0 -and ($posicao -lt 0 -or $p -lt $posicao)) { $posicao = $p; $marca = $candidato }
            }
            if ($posicao -lt 0) { $codigo += $linha; break }
            $codigo += $linha.Substring(0, $posicao)
            $linha = $linha.Substring($posicao + $marca.Length)
            if ($marca -eq '/*') { $aberto = '*/' }
            elseif ($marca -eq '<!--') { $aberto = '-->' }
            else { $aberto = $marca }
        }
        # Comentario de linha (inteiro ou no fim)
        if ($Arquivo.Ext -eq '.py') {
            $p = $codigo.IndexOf('#')
            if ($p -ge 0) { $codigo = $codigo.Substring(0, $p) }
        } elseif ($Arquivo.Ext -eq '.js') {
            if ($codigo.TrimStart().StartsWith('//')) { $codigo = '' }
            else {
                $p = $codigo.IndexOf(' //')
                if ($p -ge 0) { $codigo = $codigo.Substring(0, $p) }
            }
        }
        $resultado[$i] = $codigo
    }
    return ,$resultado
}

function Get-Escopo([string] $Nome) {
    $semEste = $Manifesto | Where-Object { $_.Rel -ne $MeuNome }
    switch ($Nome) {
        'app-py'   { $semEste | Where-Object { $_.NaRaiz -and $_.Ext -eq '.py' } }
        'app-js'   { $semEste | Where-Object { $_.NaRaiz -and $_.Ext -eq '.js' } }
        'app-html' { $semEste | Where-Object { $_.NaRaiz -and $_.Ext -eq '.html' } }
        'app-web'  { $semEste | Where-Object { $_.NaRaiz -and @('.py', '.js', '.html', '.css') -contains $_.Ext } }
        'py'       { $semEste | Where-Object { $_.Ext -eq '.py' } }
        'js'       { $semEste | Where-Object { $_.Ext -eq '.js' } }
        'codigo'   { $semEste | Where-Object { $ExtensoesDeCodigo -contains $_.Ext } }
        'ps1'      { $Manifesto | Where-Object { $_.Ext -eq '.ps1' } }
    }
}

function New-Verificacao([string] $Id, [string] $Descricao, $Detalhes) {
    $lista = @($Detalhes | Where-Object { $_ })
    return [pscustomobject]@{ Id = $Id; Descricao = $Descricao; Quantidade = $lista.Count; Detalhes = $lista }
}

function Get-ResumoJUnit([string] $Caminho) {
    if (-not (Test-Path -LiteralPath $Caminho)) { return $null }
    $xml = New-Object System.Xml.XmlDocument
    try { $xml.Load($Caminho) } catch { return $null }
    $total = 0; $falhas = 0; $erros = 0; $pulados = 0; $tempo = 0.0
    foreach ($suite in $xml.SelectNodes('//testsuite')) {
        $total += [int]$suite.GetAttribute('tests')
        $falhas += [int]$suite.GetAttribute('failures')
        $erros += [int]$suite.GetAttribute('errors')
        $pulados += [int]$suite.GetAttribute('skipped')
        $t = $suite.GetAttribute('time')
        if ($t) { $tempo += [double]::Parse($t, $Invariante) }
    }
    $falharam = @(foreach ($caso in $xml.SelectNodes('//testcase[failure or error]')) {
        '{0}::{1}' -f $caso.GetAttribute('classname'), $caso.GetAttribute('name')
    })
    $motivos = @{}
    foreach ($pulo in $xml.SelectNodes('//testcase/skipped')) {
        $motivo = $pulo.GetAttribute('message')
        if (-not $motivo) { $motivo = '(sem motivo)' }
        $motivos[$motivo] = 1 + [int]$motivos[$motivo]
    }
    return [pscustomobject]@{
        Total = $total; Falhas = $falhas; Erros = $erros; Pulados = $pulados
        Tempo = [math]::Round($tempo, 1); Falharam = $falharam; Motivos = $motivos
    }
}

function Get-ResumoNode([string] $Texto) {
    # Relator TAP ("# pass 10") ou spec ("i pass 10", com o simbolo de informacao U+2139)
    $resumo = [ordered]@{}
    $padrao = '(?m)^[#\u2139]\s*(tests|suites|pass|fail|cancelled|skipped|todo)\s+(\d+)'
    foreach ($m in [regex]::Matches($Texto, $padrao)) { $resumo[$m.Groups[1].Value] = [int]$m.Groups[2].Value }
    return $resumo
}

# ---------------------------------------------------------------------------------------------
# Inicio
# ---------------------------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host ('Python do projeto nao encontrado: {0}' -f $Python) -ForegroundColor Red
    Write-Host 'Crie o .venv e instale requirements-dev.txt (secao 9 do context.md).' -ForegroundColor Red
    exit 1
}

$seteZip = Get-Comando '7z'
if (-not $seteZip) {
    foreach ($pastaProgramas in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($pastaProgramas -and (Test-Path -LiteralPath (Join-Path $pastaProgramas '7-Zip\7z.exe'))) {
            $seteZip = Join-Path $pastaProgramas '7-Zip\7z.exe'
            break
        }
    }
}
if (-not $seteZip -and -not $SemCompactar) {
    Write-Warning '7-Zip nao encontrado (7z no PATH ou em Arquivos de Programas\7-Zip): o pacote fica so na pasta, sem .7z.'
}

$DestinoCompleto = [IO.Path]::GetFullPath($Destino).TrimEnd('\')
$Carimbo = Get-Date -Format 'yyyyMMdd_HHmmss'
$Saida = Join-Path $DestinoCompleto ('revisao_' + $Carimbo)
$PastaFontes = Join-Path $Saida 'fontes'
$PastaExternos = Join-Path $Saida 'externos'
$PastaTestes = Join-Path $Saida 'testes'
$PastaAnalise = Join-Path $Saida 'analise'
$PastaBuild = Join-Path $Saida 'build'
New-Item -ItemType Directory -Path $Saida -Force | Out-Null

if ($DestinoCompleto.StartsWith($Raiz + '\', [StringComparison]::OrdinalIgnoreCase)) {
    Write-Warning 'O destino fica dentro do projeto: ele e ignorado na copia, mas prefira uma pasta fora.'
}

$ioAnterior = $env:PYTHONIOENCODING
$coberturaJsAnterior = $env:BTC_COBERTURA_JS
# So a saida do Python em UTF-8. PYTHONUTF8 fica desligado de proposito: ligado, esconderia
# leituras/gravacoes sem encoding explicito, que sao justamente um ponto da revisao.
$env:PYTHONIOENCODING = 'utf-8'
$inicioGeral = Get-Date

try {
    Write-Host ('Pacote de revisao em {0}' -f $Saida) -ForegroundColor Green

    # -----------------------------------------------------------------------------------------
    Write-Passo 'Copiando os arquivos do projeto'
    $Fontes = @(Get-ArquivosDoProjeto $Raiz | Sort-Object FullName)
    $Manifesto = @(foreach ($arquivo in $Fontes) {
        $rel = Get-Relativo $arquivo.FullName
        $destinoArquivo = Join-Path $PastaFontes $rel
        New-Item -ItemType Directory -Path (Split-Path -Parent $destinoArquivo) -Force | Out-Null
        Copy-Item -LiteralPath $arquivo.FullName -Destination $destinoArquivo -Force
        $ext = $arquivo.Extension.ToLowerInvariant()
        $linhas = ''
        if ($ExtensoesDeTexto -contains $ext) { $linhas = [IO.File]::ReadAllLines($arquivo.FullName).Count }
        [pscustomobject]@{
            Rel     = $rel
            Ext     = $ext
            NaRaiz  = ($rel -notmatch '\\')
            Bytes   = $arquivo.Length
            Linhas  = $linhas
            Sha     = (Get-FileHash -LiteralPath $arquivo.FullName -Algorithm SHA256).Hash.Substring(0, 16).ToLowerInvariant()
            Caminho = $arquivo.FullName
        }
    })
    Write-Host ('      {0} arquivos' -f $Manifesto.Count) -ForegroundColor Gray

    # -----------------------------------------------------------------------------------------
    Write-Passo 'Copiando os arquivos das bibliotecas externas (.venv)'
    $ExternosCopiados = New-Object System.Collections.Generic.List[string]
    $ExternosAusentes = New-Object System.Collections.Generic.List[string]
    $pastaJs = Join-Path $SitePackages 'webview\js'
    $listaExternos = @($ExternosFixos)
    if (Test-Path -LiteralPath $pastaJs) {
        $listaExternos += @(Get-ChildItem -LiteralPath $pastaJs -File | ForEach-Object { 'webview\js\' + $_.Name })
    } else {
        $ExternosAusentes.Add('webview\js\')
    }
    foreach ($rel in $listaExternos) {
        $origem = Join-Path $SitePackages $rel
        if (Test-Path -LiteralPath $origem) {
            $destinoArquivo = Join-Path $PastaExternos $rel
            New-Item -ItemType Directory -Path (Split-Path -Parent $destinoArquivo) -Force | Out-Null
            Copy-Item -LiteralPath $origem -Destination $destinoArquivo -Force
            $ExternosCopiados.Add($rel)
        } else {
            $ExternosAusentes.Add($rel)
        }
    }
    $pastaWebview = Join-Path $SitePackages 'webview'
    if (Test-Path -LiteralPath $pastaWebview) {
        $listaPacote = Get-ChildItem -LiteralPath $pastaWebview -Recurse -File |
            Where-Object { $_.FullName -notmatch '\\__pycache__\\' } |
            ForEach-Object { '{0}  ({1} bytes)' -f $_.FullName.Substring($SitePackages.Length).TrimStart('\'), $_.Length }
        Write-TextoUtf8 (Join-Path $PastaExternos 'arquivos_do_pacote_webview.txt') (($listaPacote -join "`r`n") + "`r`n")

        $dlls = Get-ChildItem -LiteralPath $pastaWebview -Recurse -File -Filter '*.dll' | ForEach-Object {
            $versao = $_.VersionInfo.FileVersion
            if (-not $versao) { $versao = '(sem versao)' }
            '| {0} | {1} | {2} |' -f $_.FullName.Substring($SitePackages.Length).TrimStart('\'), $versao, $_.Length
        }
        $textoDlls = @('# DLLs do pacote webview', '', '| Arquivo | Versao | Bytes |', '|---|---|---|') + @($dlls)
        Write-TextoUtf8 (Join-Path $PastaExternos 'dlls_do_pywebview.md') (($textoDlls -join "`r`n") + "`r`n")
    }
    Write-Host ('      {0} copiados, {1} ausentes' -f $ExternosCopiados.Count, $ExternosAusentes.Count) -ForegroundColor Gray

    # -----------------------------------------------------------------------------------------
    Write-Passo 'Coletando o ambiente'
    $amb = New-Object System.Collections.Generic.List[string]
    $amb.Add('# Ambiente'); $amb.Add('')
    $amb.Add(('Gerado em: {0}' -f (Get-Date -Format 'dd/MM/yyyy HH:mm:ss'))); $amb.Add('')

    $amb.Add('## Windows')
    try {
        $nt = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
        $amb.Add(('- Produto: {0} (o registro diz "Windows 10" tambem no 11; vale o build)' -f $nt.ProductName))
        $amb.Add(('- Versao: {0}' -f $nt.DisplayVersion))
        $amb.Add(('- Build: {0}.{1}' -f $nt.CurrentBuild, $nt.UBR))
    } catch { $amb.Add('- (nao foi possivel ler o registro)') }
    $amb.Add(('- Arquitetura: {0}' -f $env:PROCESSOR_ARCHITECTURE))
    $amb.Add(('- PowerShell: {0} ({1})' -f $PSVersionTable.PSVersion, $PSVersionTable.PSEdition))
    $amb.Add('')

    $amb.Add('## WebView2 Runtime')
    $guid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    $chaves = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$guid",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$guid",
        "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$guid"
    )
    $achouWebView2 = $false
    foreach ($chave in $chaves) {
        try {
            $pv = (Get-ItemProperty -LiteralPath $chave -ErrorAction Stop).pv
            if ($pv) { $amb.Add(('- {0}: {1}' -f $chave, $pv)); $achouWebView2 = $true }
        } catch { }
    }
    if (-not $achouWebView2) { $amb.Add('- Nao encontrado no registro') }
    $amb.Add('')

    $amb.Add('## Python (.venv)')
    $r = Invoke-Etapa -Nome 'python' -Executavel $Python -Argumentos @('-c', 'import sys, platform; print(sys.version); print(platform.platform()); print(sys.executable)')
    $amb.Add('```'); $amb.Add($r.Saida.Trim()); $amb.Add('```')
    $freeze = Invoke-Etapa -Nome 'pip freeze' -Executavel $Python -Argumentos @('-m', 'pip', 'freeze', '--all', '--disable-pip-version-check')
    $ArquivoFreeze = Join-Path $Saida 'pip_freeze.txt'
    Write-TextoUtf8 $ArquivoFreeze $freeze.Saida
    $amb.Add(''); $amb.Add('### pip freeze --all'); $amb.Add('```'); $amb.Add($freeze.Saida.Trim()); $amb.Add('```')
    $check = Invoke-Etapa -Nome 'pip check' -Executavel $Python -Argumentos @('-m', 'pip', 'check', '--disable-pip-version-check')
    $amb.Add(''); $amb.Add(('### pip check (codigo {0})' -f $check.Codigo)); $amb.Add('```'); $amb.Add(($check.Saida + $check.Erro).Trim()); $amb.Add('```')
    $pw = Invoke-Etapa -Nome 'playwright' -Executavel $Python -Argumentos @('-m', 'playwright', '--version')
    $amb.Add(''); $amb.Add(('- Playwright: {0}' -f ($pw.Saida + $pw.Erro).Trim()))
    $amb.Add(('- BTC_NAVEGADOR: {0}' -f $(if ($env:BTC_NAVEGADOR) { $env:BTC_NAVEGADOR } else { '(nao definido)' })))
    $amb.Add('')

    $amb.Add('## Outras ferramentas')
    $Node = Get-Comando 'node'
    $NodeMaior = 0
    if ($Node) {
        $nv = (Invoke-Etapa -Nome 'node' -Executavel $Node -Argumentos @('--version')).Saida.Trim()
        if ($nv -match '^v(\d+)') { $NodeMaior = [int]$Matches[1] }
        $amb.Add(('- Node.js: {0} ({1})' -f $nv, $Node))
    } else {
        $amb.Add('- Node.js: nao encontrado no PATH')
    }
    $amb.Add(('- 7-Zip: {0}' -f $(if ($seteZip) { $seteZip } else { 'nao encontrado' })))
    $Git = Get-Comando 'git'
    if ($Git -and (Test-Path (Join-Path $Raiz '.git'))) {
        $amb.Add(''); $amb.Add('## git')
        foreach ($argsGit in @(@('status', '--short', '--branch'), @('log', '-20', '--oneline'), @('diff', '--stat'))) {
            $g = Invoke-Etapa -Nome 'git' -Executavel $Git -Argumentos $argsGit
            $amb.Add(('### git {0}' -f ($argsGit -join ' '))); $amb.Add('```'); $amb.Add($g.Saida.Trim()); $amb.Add('```')
        }
    } else {
        $amb.Add('- git: projeto sem repositorio (ou git ausente)')
    }
    Write-TextoUtf8 (Join-Path $Saida 'ambiente.md') (($amb -join "`r`n") + "`r`n")

    # -----------------------------------------------------------------------------------------
    Write-Passo 'Verificando armadilhas e convencoes'
    $Verificacoes = New-Object System.Collections.Generic.List[object]

    $codigoPorArquivo = @{}   # Rel -> linhas so com o codigo (Get-LinhasDeCodigo), calculadas uma vez
    foreach ($regra in $Regras) {
        $soCodigo = $regra.SoCodigo -ne $false
        $achados = New-Object System.Collections.Generic.List[string]
        foreach ($arquivo in @(Get-Escopo $regra.Escopo)) {
            $originais = [IO.File]::ReadAllLines($arquivo.Caminho, [Text.Encoding]::UTF8)
            $alvo = $originais
            if ($soCodigo) {
                if (-not $codigoPorArquivo.ContainsKey($arquivo.Rel)) {
                    $codigoPorArquivo[$arquivo.Rel] = Get-LinhasDeCodigo $arquivo
                }
                $alvo = $codigoPorArquivo[$arquivo.Rel]
            }
            for ($i = 0; $i -lt $alvo.Count; $i++) {
                if (-not [regex]::IsMatch($alvo[$i], $regra.Padrao)) { continue }
                $trecho = $originais[$i].Trim()
                if ($trecho.Length -gt 160) { $trecho = $trecho.Substring(0, 160) + '...' }
                $achados.Add(('{0}:{1}: {2}' -f $arquivo.Rel, ($i + 1), $trecho))
            }
        }
        $Verificacoes.Add((New-Verificacao $regra.Id ('{0} [{1}{2}{1}]' -f $regra.Descricao, $BT, $regra.Padrao) $achados))
    }

    # 'use strict' em todo .js
    $semStrict = @(Get-Escopo 'js' | Where-Object {
        -not (Select-String -LiteralPath $_.Caminho -Pattern '[''"]use strict[''"]' -Quiet)
    } | ForEach-Object { $_.Rel })
    $Verificacoes.Add((New-Verificacao 'C-strict' 'Arquivo .js sem use strict (convencao)' $semStrict))

    # Indentacao: JS com tab, Python com 4 espacos
    $indentacao = @()
    foreach ($a in @(Get-Escopo 'app-js')) {
        $n = @(Select-String -LiteralPath $a.Caminho -Pattern '^ {2,}\S' -CaseSensitive).Count
        if ($n) { $indentacao += ('{0}: {1} linhas indentadas com espacos (convencao JS: tab)' -f $a.Rel, $n) }
    }
    foreach ($a in @(Get-Escopo 'py')) {
        $n = @(Select-String -LiteralPath $a.Caminho -Pattern '^\t' -CaseSensitive).Count
        if ($n) { $indentacao += ('{0}: {1} linhas indentadas com tab (convencao Python: 4 espacos)' -f $a.Rel, $n) }
    }
    $Verificacoes.Add((New-Verificacao 'C-indent' 'Indentacao fora da convencao' $indentacao))

    # .ps1: sem acentos, CRLF, ajuda por comentario com um .PARAMETER por parametro, sem erro de sintaxe
    $problemasPs1 = @()
    foreach ($a in @(Get-Escopo 'ps1')) {
        $bruto = [IO.File]::ReadAllText($a.Caminho, $Latin1)
        $lfSozinho = [regex]::Matches($bruto, '(?<!\r)\n').Count
        if ($lfSozinho) { $problemasPs1 += ('{0}: {1} quebras LF sem CR (convencao: CRLF)' -f $a.Rel, $lfSozinho) }
        $linhasNaoAscii = @(Select-String -LiteralPath $a.Caminho -Pattern '[^\x00-\x7F]' -Encoding UTF8 | ForEach-Object { $_.LineNumber })
        if ($linhasNaoAscii.Count) {
            $problemasPs1 += ('{0}: caracteres fora do ASCII nas linhas {1} (armadilha: PS 5.1 le UTF-8 sem BOM como ANSI)' -f $a.Rel, (($linhasNaoAscii | Select-Object -First 15) -join ', '))
        }
        try {
            $tokens = $null; $errosSintaxe = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile($a.Caminho, [ref]$tokens, [ref]$errosSintaxe)
            foreach ($e in @($errosSintaxe)) {
                if ($e) { $problemasPs1 += ('{0}:{1}: erro de sintaxe: {2}' -f $a.Rel, $e.Extent.StartLineNumber, $e.Message) }
            }
            $ajuda = $ast.GetHelpContent()
            if (-not $ajuda -or -not $ajuda.Synopsis) {
                $problemasPs1 += ('{0}: sem ajuda por comentario (.SYNOPSIS) - armadilha 62' -f $a.Rel)
            } else {
                if (-not $ajuda.Description) { $problemasPs1 += ('{0}: ajuda sem .DESCRIPTION' -f $a.Rel) }
                if (@($ajuda.Examples).Count -eq 0) { $problemasPs1 += ('{0}: ajuda sem .EXAMPLE' -f $a.Rel) }
                if ($ast.ParamBlock) {
                    $documentados = @($ajuda.Parameters.Keys | ForEach-Object { $_.ToUpperInvariant() })
                    foreach ($p in $ast.ParamBlock.Parameters) {
                        $nomeParam = $p.Name.VariablePath.UserPath
                        if ($documentados -notcontains $nomeParam.ToUpperInvariant()) {
                            $problemasPs1 += ('{0}: parametro -{1} sem .PARAMETER' -f $a.Rel, $nomeParam)
                        }
                    }
                }
            }
        } catch {
            $problemasPs1 += ('{0}: nao foi possivel analisar ({1})' -f $a.Rel, $_.Exception.Message)
        }
    }
    $Verificacoes.Add((New-Verificacao 'C-ps1' 'Scripts .ps1 fora da convencao (secao 7)' $problemasPs1))

    # Armadilhas 54 e 56: arquivos no lugar certo
    $copiaEmTools = @()
    if (Test-Path -LiteralPath (Join-Path $Raiz 'tools\argumentos_webview2.py')) { $copiaEmTools += 'tools\argumentos_webview2.py existe' }
    $Verificacoes.Add((New-Verificacao 'A54' 'Copia de argumentos_webview2.py em tools (armadilha 54)' $copiaEmTools))
    $faltando = @($ObrigatoriosNaRaiz | Where-Object { -not (Test-Path -LiteralPath (Join-Path $Raiz $_)) } |
        ForEach-Object { '{0} ausente na raiz' -f $_ })
    $Verificacoes.Add((New-Verificacao 'A56' 'Arquivos obrigatorios na raiz (armadilha 56)' $faltando))

    # Arquivos duplicados ou fora do lugar (ex.: uma copia esquecida de um teste na raiz,
    # mais nova que a de tests\ e que nunca roda)
    $mesmoNome = @($Manifesto |
        Group-Object { ($_.Rel -split '\\')[-1].ToLowerInvariant() } |
        Where-Object { $_.Count -gt 1 -and $NomesQuePodemRepetir -notcontains $_.Name } |
        ForEach-Object { 'mesmo nome: {0}' -f (($_.Group | ForEach-Object { $_.Rel }) -join ', ') })
    $mesmoConteudo = @($Manifesto | Where-Object { $_.Bytes -gt 0 } | Group-Object Sha |
        Where-Object { $_.Count -gt 1 } |
        ForEach-Object { 'mesmo conteudo: {0}' -f (($_.Group | ForEach-Object { $_.Rel }) -join ', ') })
    $testesFora = @($Manifesto | Where-Object {
            $_.Rel -notlike 'tests\*' -and ($_.Rel -split '\\')[-1] -match '(\.test\.js|^test_.*\.py)$'
        } | ForEach-Object { 'teste fora de tests\: {0} (nunca roda)' -f $_.Rel })
    $Verificacoes.Add((New-Verificacao 'C-arquivos' 'Arquivos duplicados ou fora do lugar' ($mesmoNome + $mesmoConteudo + $testesFora)))

    # Codificacao e quebras de linha (os .ps1 tem a verificacao propria, C-ps1)
    $problemasTexto = @()
    $utf8Estrito = New-Object System.Text.UTF8Encoding($false, $true)
    foreach ($a in @($Manifesto | Where-Object { @('.py', '.js', '.html', '.css', '.md', '.json', '.txt', '.ini', '.spec') -contains $_.Ext })) {
        $bytes = [IO.File]::ReadAllBytes($a.Caminho)
        if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
            $problemasTexto += ('{0}: comeca com BOM' -f $a.Rel)
        }
        try { $null = $utf8Estrito.GetString($bytes) } catch { $problemasTexto += ('{0}: nao e UTF-8 valido' -f $a.Rel) }
        $bruto = $Latin1.GetString($bytes)
        $crlf = [regex]::Matches($bruto, '\r\n').Count
        $lfSozinho = [regex]::Matches($bruto, '(?<!\r)\n').Count
        if ($crlf -gt 0 -and $lfSozinho -gt 0) {
            $problemasTexto += ('{0}: quebras misturadas ({1} CRLF, {2} LF)' -f $a.Rel, $crlf, $lfSozinho)
        }
    }
    $Verificacoes.Add((New-Verificacao 'C-codificacao' 'Codificacao (UTF-8 sem BOM) e quebras de linha uniformes' $problemasTexto))

    # Versoes diferentes das conferidas no context.md: armadilhas a rever
    $instalados = @{}
    foreach ($linhaFreeze in ($freeze.Saida -split '\r?\n')) {
        if ($linhaFreeze -match '^\s*([A-Za-z0-9_.\-]+)==(\S+)') { $instalados[$Matches[1].ToLowerInvariant()] = $Matches[2] }
    }
    $ResumoVersoes = New-Object System.Collections.Generic.List[object]
    $versoesARever = @()
    foreach ($item in $VersoesConferidas) {
        $instalada = $instalados[$item.Pacote]
        if ($item.Conferida.EndsWith('.')) { $confere = $instalada -and $instalada.StartsWith($item.Conferida) }
        else { $confere = $instalada -eq $item.Conferida }
        $ResumoVersoes.Add([pscustomobject]@{ Pacote = $item.Pacote; Instalada = $instalada; Conferida = $item.Conferida; Confere = [bool]$confere; Armadilhas = $item.Armadilhas })
        if (-not $confere) {
            $versoesARever += ('{0} {1} (conferido em {2}): rever as armadilhas {3}' -f $item.Pacote, $(if ($instalada) { $instalada } else { 'ausente' }), $item.Conferida, $item.Armadilhas)
        }
    }
    $Verificacoes.Add((New-Verificacao 'V-versoes' 'Dependencias em versao diferente da conferida no context.md' $versoesARever))

    $ContextoNoDisco = @($Manifesto | Where-Object { $_.Rel -match '(^|\\)context\.md$' } | ForEach-Object { $_.Rel })

    $ver = New-Object System.Collections.Generic.List[string]
    $ver.Add('# Verificacoes automaticas'); $ver.Add('')
    $ver.Add('Ocorrencias sao candidatas: cada uma precisa ser conferida no codigo (ex.: A45 encontra o import de ssl esperado em ssl_ausente.py; C-print vale so para o app, nao para tools). As regras por expressao olham so o codigo: comentarios e docstrings (que citam as armadilhas) ficam de fora, exceto em C-todo.')
    $ver.Add('')
    foreach ($v in $Verificacoes) {
        $ver.Add(('## {0} - {1}' -f $v.Id, $v.Descricao)); $ver.Add('')
        if ($v.Quantidade -eq 0) { $ver.Add('Nenhuma ocorrencia.') }
        else {
            $ver.Add(('{0} ocorrencia(s):' -f $v.Quantidade)); $ver.Add('')
            foreach ($d in ($v.Detalhes | Select-Object -First 60)) { $ver.Add(('- {0}{1}{0}' -f $BT, ($d -replace $BT, "'"))) }
            if ($v.Quantidade -gt 60) { $ver.Add(('- ... e mais {0}' -f ($v.Quantidade - 60))) }
        }
        $ver.Add('')
    }
    Write-TextoUtf8 (Join-Path $PastaAnalise 'verificacoes.md') (($ver -join "`r`n") + "`r`n")
    $totalAchados = ($Verificacoes | Measure-Object -Property Quantidade -Sum).Sum
    Write-Host ('      {0} verificacoes, {1} ocorrencias' -f $Verificacoes.Count, $totalAchados) -ForegroundColor Gray

    # -----------------------------------------------------------------------------------------
    $ResumoPytest = $null; $ResumoReexecucao = $null; $ResumoDesempenho = $null; $ResumoNode = $null
    if ($SemTestes) {
        Write-Passo 'Testes pulados (-SemTestes)'
    } else {
        Write-Passo 'Rodando o pytest (pode levar alguns minutos)'
        $xmlPytest = Join-Path $PastaTestes 'pytest.xml'
        $argsPytest = @('-m', 'pytest', 'tests', '-rA', '--durations=30', ('--junitxml=' + $xmlPytest))
        $dadosCobertura = Join-Path $PastaTestes '.coverage'
        if ($ComCobertura) {
            $temCoverage = Invoke-Etapa -Nome 'coverage instalado' -Executavel $Python -Argumentos @('-c', 'import coverage')
            if ($temCoverage.Codigo -ne 0) {
                Write-Warning 'coverage ausente: instalando no .venv do projeto (pedido por -ComCobertura).'
                Invoke-Etapa -Nome 'Instalar coverage' -Executavel $Python `
                    -Argumentos @('-m', 'pip', 'install', '--disable-pip-version-check', 'coverage') `
                    -ArquivoSaida (Join-Path $PastaTestes 'instalar_coverage.txt') | Out-Null
            }
            $argsPytest = @('-m', 'coverage', 'run', '--branch', ('--data-file=' + $dadosCobertura), '--source=.',
                '--omit=*/tests/*,*/tools/*,*/.venv/*') + $argsPytest
            # JS da pagina: tests\apoio_pagina.py grava a cobertura do V8 de cada pagina aqui.
            $PastaCoberturaJs = Join-Path $PastaTestes 'cobertura_js_v8'
            New-Item -ItemType Directory -Path $PastaCoberturaJs -Force | Out-Null
            $env:BTC_COBERTURA_JS = $PastaCoberturaJs
        }
        $pytest = Invoke-Etapa -Nome 'pytest' -Executavel $Python -Argumentos $argsPytest `
            -ArquivoSaida (Join-Path $PastaTestes 'pytest.txt') -LimiteMin 60
        $ResumoPytest = Get-ResumoJUnit $xmlPytest

        if ($ComCobertura -and (Test-Path -LiteralPath $dadosCobertura)) {
            Invoke-Etapa -Nome 'Cobertura (Python)' -Executavel $Python `
                -Argumentos @('-m', 'coverage', 'report', '-m', ('--data-file=' + $dadosCobertura)) `
                -ArquivoSaida (Join-Path $PastaTestes 'cobertura_python.txt') | Out-Null
            Remove-Item -LiteralPath $dadosCobertura -Force -ErrorAction SilentlyContinue
        }
        if ($ComCobertura) {
            $env:BTC_COBERTURA_JS = $coberturaJsAnterior
            $medicoesJs = @(Get-ChildItem -LiteralPath $PastaCoberturaJs -Filter '*.json' -File -ErrorAction SilentlyContinue)
            # npx.cmd, e nao npx: no PowerShell 7 o "npx" acha antes o npx.ps1, que o Start-Process nao executa.
            $Npx = Get-Comando 'npx.cmd'
            if ($medicoesJs.Count -eq 0) {
                Write-Warning 'Nenhuma medicao de cobertura do JS da pagina (testes de pagina pulados?).'
            } elseif (-not $Npx) {
                Write-Warning 'npx nao encontrado: sem relatorio de cobertura do JS da pagina.'
            } else {
                Invoke-Etapa -Nome 'Cobertura (JS da pagina, c8)' -Executavel $Npx `
                    -Argumentos @('--yes', 'c8@10', 'report', '--temp-directory', $PastaCoberturaJs, '--reporter=text') `
                    -ArquivoSaida (Join-Path $PastaTestes 'cobertura_js_pagina.txt') -LimiteMin 10 | Out-Null
            }
            # As medicoes brutas sao grandes (uma por teste de pagina): ficam so no relatorio.
            Remove-Item -LiteralPath $PastaCoberturaJs -Recurse -Force -ErrorAction SilentlyContinue
        }

        if ($pytest.Codigo -eq 1) {
            Write-Passo 'Reexecutando so as falhas (separa falha real de ocasional, ex.: armadilha 73)'
            $xmlReexecucao = Join-Path $PastaTestes 'pytest_reexecucao.xml'
            Invoke-Etapa -Nome 'pytest (reexecucao das falhas)' -Executavel $Python `
                -Argumentos @('-m', 'pytest', 'tests', '--lf', '--lfnf=none', '-rA', ('--junitxml=' + $xmlReexecucao)) `
                -ArquivoSaida (Join-Path $PastaTestes 'pytest_reexecucao.txt') -LimiteMin 30 | Out-Null
            $ResumoReexecucao = Get-ResumoJUnit $xmlReexecucao
        }

        if ($Node) {
            Write-Passo 'Rodando os testes do Node'
            $testesJs = @(Get-ChildItem -LiteralPath (Join-Path $Raiz 'tests') -Filter '*.test.js' -File |
                Sort-Object Name | ForEach-Object { 'tests/' + $_.Name })
            $argsNode = @('--test')
            if ($ComCobertura -and $NodeMaior -ge 20) { $argsNode += '--experimental-test-coverage' }
            $argsNode += $testesJs
            $execucaoNode = Invoke-Etapa -Nome 'node --test' -Executavel $Node -Argumentos $argsNode `
                -ArquivoSaida (Join-Path $PastaTestes 'node.txt') -LimiteMin 10
            $ResumoNode = Get-ResumoNode ($execucaoNode.Saida + "`n" + $execucaoNode.Erro)
        } else {
            Write-Warning 'Node.js nao encontrado: testes .js nao rodados.'
        }

        if ($ComDesempenho) {
            Write-Passo 'Rodando os testes de desempenho'
            $xmlDesempenho = Join-Path $PastaTestes 'desempenho.xml'
            Invoke-Etapa -Nome 'pytest -m desempenho' -Executavel $Python `
                -Argumentos @('-m', 'pytest', 'tests\desempenho', '-m', 'desempenho', '-rA', ('--junitxml=' + $xmlDesempenho)) `
                -ArquivoSaida (Join-Path $PastaTestes 'desempenho.txt') -LimiteMin 60 | Out-Null
            $ResumoDesempenho = Get-ResumoJUnit $xmlDesempenho
        }
    }

    # Resultados de desempenho mais recentes (depois dos testes, para pegar o novo)
    $pastaResultados = Join-Path $Raiz 'tests\desempenho\resultados'
    if (Test-Path -LiteralPath $pastaResultados) {
        $destinoResultados = Join-Path $PastaFontes 'tests\desempenho\resultados'
        New-Item -ItemType Directory -Path $destinoResultados -Force | Out-Null
        Get-ChildItem -LiteralPath $pastaResultados -Filter '*.json' -File |
            Sort-Object LastWriteTime -Descending | Select-Object -First 2 |
            ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $destinoResultados -Force }
    }

    # -----------------------------------------------------------------------------------------
    if ($ComAnalisadores) {
        Write-Passo 'Preparando os analisadores (venv separado)'
        $venvAnalise = Join-Path $env:LOCALAPPDATA 'btcstatus-revisao\venv'
        $pyAnalise = Join-Path $venvAnalise 'Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $pyAnalise)) {
            Invoke-Etapa -Nome 'Criar venv dos analisadores' -Executavel $Python -Argumentos @('-m', 'venv', $venvAnalise) `
                -ArquivoSaida (Join-Path $PastaAnalise '_criar_venv.txt') | Out-Null
        }
        if (Test-Path -LiteralPath $pyAnalise) {
            Invoke-Etapa -Nome 'Instalar analisadores' -Executavel $pyAnalise `
                -Argumentos @('-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check', 'ruff', 'bandit', 'vulture', 'radon', 'pip-audit') `
                -ArquivoSaida (Join-Path $PastaAnalise '_instalar.txt') -LimiteMin 15 | Out-Null

            Write-Passo 'Rodando os analisadores'
            $pyApp = @($Manifesto | Where-Object { $_.Ext -eq '.py' -and ($_.NaRaiz -or $_.Rel -like 'tools\*') } | ForEach-Object { $_.Rel })
            $pyTestes = @($Manifesto | Where-Object { $_.Ext -eq '.py' -and $_.Rel -like 'tests\*' } | ForEach-Object { $_.Rel })
            $regrasRuff = 'E,W,F,B,S,N,UP,C4,PIE,RET,SIM,PTH,ARG,BLE,PL,RUF'

            Invoke-Etapa -Nome 'ruff (app e tools)' -Executavel $pyAnalise `
                -Argumentos (@('-m', 'ruff', 'check', '--no-cache', '--output-format', 'concise', '--select', $regrasRuff, '--ignore', $RuffIgnorar) + $pyApp) `
                -ArquivoSaida (Join-Path $PastaAnalise 'ruff_app.txt') | Out-Null
            Invoke-Etapa -Nome 'ruff (estatisticas)' -Executavel $pyAnalise `
                -Argumentos (@('-m', 'ruff', 'check', '--no-cache', '--statistics', '--select', $regrasRuff, '--ignore', $RuffIgnorar) + $pyApp) `
                -ArquivoSaida (Join-Path $PastaAnalise 'ruff_estatisticas.txt') | Out-Null
            if ($pyTestes.Count) {
                Invoke-Etapa -Nome 'ruff (testes)' -Executavel $pyAnalise `
                    -Argumentos (@('-m', 'ruff', 'check', '--no-cache', '--output-format', 'concise', '--select', 'F,E9,B') + $pyTestes) `
                    -ArquivoSaida (Join-Path $PastaAnalise 'ruff_testes.txt') | Out-Null
            }
            Invoke-Etapa -Nome 'bandit' -Executavel $pyAnalise -Argumentos (@('-m', 'bandit', '-f', 'txt') + $pyApp) `
                -ArquivoSaida (Join-Path $PastaAnalise 'bandit.txt') | Out-Null
            Invoke-Etapa -Nome 'vulture' -Executavel $pyAnalise -Argumentos (@('-m', 'vulture', '--min-confidence', '60') + $pyApp) `
                -ArquivoSaida (Join-Path $PastaAnalise 'vulture.txt') | Out-Null
            Invoke-Etapa -Nome 'radon cc' -Executavel $pyAnalise -Argumentos (@('-m', 'radon', 'cc', '-s', '-a', '-nc') + $pyApp) `
                -ArquivoSaida (Join-Path $PastaAnalise 'radon_complexidade.txt') | Out-Null
            Invoke-Etapa -Nome 'radon mi' -Executavel $pyAnalise -Argumentos (@('-m', 'radon', 'mi', '-s') + $pyApp) `
                -ArquivoSaida (Join-Path $PastaAnalise 'radon_manutenibilidade.txt') | Out-Null
            Invoke-Etapa -Nome 'pip-audit' -Executavel $pyAnalise `
                -Argumentos @('-m', 'pip_audit', '-r', $ArquivoFreeze, '--no-deps', '--disable-pip', '--progress-spinner', 'off') `
                -ArquivoSaida (Join-Path $PastaAnalise 'pip_audit.txt') -LimiteMin 10 | Out-Null
        } else {
            Write-Warning 'Nao foi possivel criar o venv dos analisadores (ver analise\_criar_venv.txt).'
        }
    }

    # -----------------------------------------------------------------------------------------
    $AvisosPyInstaller = $null
    $warn = Join-Path $Raiz 'build\BTC Monitor\warn-BTC Monitor.txt'
    if (Test-Path -LiteralPath $warn) {
        New-Item -ItemType Directory -Path $PastaBuild -Force | Out-Null
        Copy-Item -LiteralPath $warn -Destination $PastaBuild -Force
        $AvisosPyInstaller = @(Select-String -LiteralPath $warn -Pattern '^missing module').Count
    }
    $InfoBuild = $null
    $pastaDist = Join-Path $Raiz 'dist\BTC Monitor'
    $exe = Join-Path $pastaDist 'BTC Monitor.exe'
    if (Test-Path -LiteralPath $exe) {
        Write-Passo 'Conferindo o build em dist'
        $argsBuild = @('tools\conferir_build.py', $pastaDist)
        $pastaTrabalho = Join-Path $Raiz 'build\BTC Monitor'
        if (Test-Path -LiteralPath $pastaTrabalho) { $argsBuild += @('--trabalho', $pastaTrabalho) }
        Invoke-Etapa -Nome 'conferir_build' -Executavel $Python -Argumentos $argsBuild `
            -ArquivoSaida (Join-Path $PastaBuild 'conferir_build.txt') | Out-Null
        $arquivosDist = @(Get-ChildItem -LiteralPath $pastaDist -Recurse -File)
        $InfoBuild = [pscustomobject]@{
            Data     = (Get-Item -LiteralPath $exe).LastWriteTime.ToString('dd/MM/yyyy HH:mm')
            Arquivos = $arquivosDist.Count
            Mb       = [math]::Round((($arquivosDist | Measure-Object -Property Length -Sum).Sum / 1MB), 1)
        }
    } else {
        Write-Passo 'Sem build em dist (conferencia do build pulada)'
    }

    # -----------------------------------------------------------------------------------------
    $LogsCopiados = 0
    if ($ComLogs) {
        Write-Passo 'Copiando os logs do app'
        $pastaDados = Join-Path $env:APPDATA 'btcstatus'
        if (Test-Path -LiteralPath $pastaDados) {
            $logs = @(Get-ChildItem -LiteralPath $pastaDados -Filter 'btcstatus.log*' -File)
            if ($logs.Count) {
                $pastaLogs = Join-Path $Saida 'logs'
                New-Item -ItemType Directory -Path $pastaLogs -Force | Out-Null
                foreach ($log in $logs) { Copy-Item -LiteralPath $log.FullName -Destination $pastaLogs -Force }
                $LogsCopiados = $logs.Count
            }
        }
    }

    # -----------------------------------------------------------------------------------------
    Write-Passo 'Gerando o INDICE.md'
    $L = New-Object System.Collections.Generic.List[string]
    $opcoesUsadas = @()
    foreach ($nome in @('SemTestes', 'ComDesempenho', 'ComCobertura', 'ComAnalisadores', 'ComLogs', 'SemCompactar')) {
        if ((Get-Variable -Name $nome -ValueOnly).IsPresent) { $opcoesUsadas += ('-' + $nome) }
    }
    if (-not $opcoesUsadas) { $opcoesUsadas = @('(padrao)') }

    $L.Add('# Pacote de revisao - BTC Status'); $L.Add('')
    $L.Add(('- Gerado em: {0} (duracao {1} min)' -f (Get-Date -Format 'dd/MM/yyyy HH:mm:ss'), [math]::Round(((Get-Date) - $inicioGeral).TotalMinutes, 1).ToString($Invariante)))
    $L.Add(('- Projeto: {0}{1}{0}' -f $BT, $Raiz))
    $L.Add(('- Opcoes: {0}' -f ($opcoesUsadas -join ' ')))
    $L.Add(('- Comando: {0}{1}{0}' -f $BT, $ComandoUsado))
    $L.Add(('- Script: {0} (SHA-256 {1})' -f $MeuNome, $ShaDoScript))
    if ($ContextoNoDisco.Count) { $L.Add(('- context.md no disco: {0}' -f ($ContextoNoDisco -join ', '))) }
    else { $L.Add('- context.md: nao esta na pasta do projeto (fica nos documentos do Projeto no claude.ai)') }
    $L.Add('')

    $L.Add('## Conteudo'); $L.Add('')
    $L.Add('| Pasta/arquivo | O que tem |'); $L.Add('|---|---|')
    $L.Add(('| fontes\ | {0} arquivos do projeto (manifesto no fim) |' -f $Manifesto.Count))
    $L.Add(('| externos\ | {0} arquivos do pywebview/bottle do .venv, lista do pacote webview e DLLs |' -f $ExternosCopiados.Count))
    $L.Add('| ambiente.md, pip_freeze.txt | Windows, WebView2, Python, dependencias, Node, Playwright |')
    $L.Add('| testes\ | Saidas do pytest e do node (e cobertura/desempenho, se pedidos) |')
    $L.Add('| analise\ | verificacoes.md (armadilhas e convencoes) e analisadores, se pedidos |')
    if ($InfoBuild) { $L.Add('| build\ | conferir_build.py |') }
    if ($LogsCopiados) { $L.Add(('| logs\ | {0} arquivo(s) btcstatus.log* |' -f $LogsCopiados)) }
    $L.Add('')

    $L.Add('## Testes'); $L.Add('')
    if ($SemTestes) { $L.Add('Nao rodados (-SemTestes).') }
    else {
        foreach ($par in @(@('pytest', $ResumoPytest), @('pytest - reexecucao das falhas', $ResumoReexecucao), @('desempenho', $ResumoDesempenho))) {
            $resumo = $par[1]
            if (-not $resumo) { continue }
            $L.Add(('### {0}' -f $par[0])); $L.Add('')
            $L.Add(('- {0} testes, {1} falhas, {2} erros, {3} pulados, {4} s' -f $resumo.Total, $resumo.Falhas, $resumo.Erros, $resumo.Pulados, $resumo.Tempo.ToString($Invariante)))
            if ($resumo.Falharam.Count) {
                $L.Add('- Falharam:')
                foreach ($f in $resumo.Falharam) { $L.Add(('  - {0}{1}{0}' -f $BT, $f)) }
            }
            if ($resumo.Motivos.Count) {
                $L.Add('- Pulados por motivo:')
                foreach ($k in ($resumo.Motivos.Keys | Sort-Object)) { $L.Add(('  - {0}x {1}' -f $resumo.Motivos[$k], (ConvertTo-CelulaMd $k))) }
            }
            $L.Add('')
        }
        if (-not $ResumoPytest) { $L.Add('- pytest: sem JUnit XML (ver testes\pytest.txt)'); $L.Add('') }
        if ($ResumoNode -and $ResumoNode.Count) {
            $L.Add('### node --test'); $L.Add('')
            $L.Add(('- ' + (($ResumoNode.Keys | ForEach-Object { '{0} {1}' -f $_, $ResumoNode[$_] }) -join ', ')))
            $L.Add('')
        }
    }

    $L.Add('## Verificacoes automaticas (detalhes em analise\verificacoes.md)'); $L.Add('')
    $L.Add('| Id | Verificacao | Ocorrencias |'); $L.Add('|---|---|---|')
    foreach ($v in $Verificacoes) { $L.Add(('| {0} | {1} | {2} |' -f $v.Id, (ConvertTo-CelulaMd $v.Descricao), $v.Quantidade)) }
    $L.Add('')

    $L.Add('## Etapas executadas'); $L.Add('')
    $L.Add('| Etapa | Codigo de saida | Duracao (s) | Arquivo |'); $L.Add('|---|---|---|---|')
    foreach ($e in $Etapas) {
        $L.Add(('| {0} | {1} | {2} | {3} |' -f $e.Nome, (ConvertTo-CelulaMd ([string]$e.Codigo)), $e.Duracao.ToString($Invariante), $e.Arquivo.Substring($Saida.Length).TrimStart('\')))
    }
    $L.Add('')
    $L.Add('Codigos: pytest 0 = tudo passou, 1 = falhas, 5 = nenhum teste; ruff/bandit/vulture 1 (ou 3) = ha achados, nao erro.')
    $L.Add('')

    if ($InfoBuild) {
        $L.Add('## Build em dist'); $L.Add('')
        $L.Add(('- BTC Monitor.exe de {0}; {1} arquivos; {2} MB' -f $InfoBuild.Data, $InfoBuild.Arquivos, $InfoBuild.Mb.ToString($Invariante)))
        $L.Add('')
    }

    $L.Add('## Versoes conferidas no context.md'); $L.Add('')
    $L.Add('| Pacote | Instalada | Conferida | Situacao | Armadilhas a rever se mudou |'); $L.Add('|---|---|---|---|---|')
    foreach ($r in $ResumoVersoes) {
        $situacao = if ($r.Confere) { 'igual' } else { '**DIFERENTE**' }
        $instaladaTexto = if ($r.Instalada) { $r.Instalada } else { 'ausente' }
        $L.Add(('| {0} | {1} | {2} | {3} | {4} |' -f $r.Pacote, $instaladaTexto, $r.Conferida, $situacao, $r.Armadilhas))
    }
    $L.Add('')
    if ($null -ne $AvisosPyInstaller) {
        $L.Add(('- Avisos do PyInstaller: build\warn-BTC Monitor.txt ({0} linhas "missing module"; a maioria e de plataformas que o app nao usa).' -f $AvisosPyInstaller))
        $L.Add('')
    }

    $L.Add('## Bibliotecas externas'); $L.Add('')
    $L.Add(('- Copiados: {0}' -f (($ExternosCopiados | ForEach-Object { $BT + $_ + $BT }) -join ', ')))
    if ($ExternosAusentes.Count) {
        $L.Add(('- **Ausentes no .venv** (versao diferente da esperada?): {0}' -f (($ExternosAusentes | ForEach-Object { $BT + $_ + $BT }) -join ', ')))
    }
    $L.Add('- Demais arquivos do pacote: externos\arquivos_do_pacote_webview.txt')
    $L.Add('')

    $L.Add('## Observacoes para quem revisa'); $L.Add('')
    $L.Add('- Ocorrencias das verificacoes sao candidatas, nao defeitos confirmados.')
    $L.Add('- O vulture aponta como sem uso os metodos da ExposedApi (chamados pelo JS) e os handlers do pywebview: falso positivo esperado.')
    $L.Add('- Testes com Win32 real so rodam no Windows; os de pagina sao pulados sem Playwright/navegador (ver "Pulados por motivo").')
    $L.Add('- PYTHONIOENCODING=utf-8 so na saida do Python; PYTHONUTF8 ficou desligado para nao esconder leituras/gravacoes sem encoding.')
    $L.Add('- Binarios (Roboto.woff2, alerta.mp3, btc-logo.ico) vao copiados, mas sem contagem de linhas.')
    $L.Add(('- As regras por expressao olham so o codigo (comentarios e docstrings ficam de fora, exceto em C-todo). O ruff ignora {0}{1}{0}, que o projeto segue de proposito.' -f $BT, $RuffIgnorar))
    $L.Add('')

    $L.Add('## Manifesto (fontes\)'); $L.Add('')
    $L.Add('| Arquivo | Linhas | Bytes | SHA-256 (16) |'); $L.Add('|---|---:|---:|---|')
    foreach ($m in $Manifesto) { $L.Add(('| {0} | {1} | {2} | {3} |' -f (ConvertTo-CelulaMd $m.Rel), $m.Linhas, $m.Bytes, $m.Sha)) }
    $totalLinhas = ($Manifesto | Where-Object { $_.Linhas -ne '' } | Measure-Object -Property Linhas -Sum).Sum
    $L.Add(('| **Total** | {0} | {1} | |' -f $totalLinhas, ($Manifesto | Measure-Object -Property Bytes -Sum).Sum))
    Write-TextoUtf8 (Join-Path $Saida 'INDICE.md') (($L -join "`r`n") + "`r`n")

    # -----------------------------------------------------------------------------------------
    $Compactado = $null
    if (-not $SemCompactar -and $seteZip) {
        Write-Passo 'Compactando com o 7-Zip'
        $arquivo7z = $Saida + '.7z'
        if (Test-Path -LiteralPath $arquivo7z) { Remove-Item -LiteralPath $arquivo7z -Force }
        # a = adicionar; -mx=9 = compressao maxima; -bsp0 = sem barra de progresso na saida
        $execucao7z = Invoke-Etapa -Nome '7z' -Executavel $seteZip `
            -Argumentos @('a', '-t7z', '-mx=9', '-bsp0', $arquivo7z, (Join-Path $Saida '*')) -LimiteMin 10
        # 7z: 0 = ok, 1 = aviso (ex.: arquivo em uso), 2 ou mais = erro
        if (($execucao7z.Codigo -eq 0 -or $execucao7z.Codigo -eq 1) -and (Test-Path -LiteralPath $arquivo7z)) {
            $Compactado = $arquivo7z
            if ($execucao7z.Codigo -eq 1) { Write-Warning ('7z terminou com aviso: {0}' -f $execucao7z.Erro.Trim()) }
        } else {
            Write-Warning ('7z falhou (codigo {0}): {1}' -f $execucao7z.Codigo, ($execucao7z.Erro + $execucao7z.Saida).Trim())
        }
    }

    # -----------------------------------------------------------------------------------------
    Write-Host ''
    Write-Host 'Pacote pronto.' -ForegroundColor Green
    Write-Host ('  Pasta: {0}' -f $Saida)
    if ($Compactado) { Write-Host ('  7z:    {0} ({1} KB)' -f $Compactado, [math]::Round((Get-Item -LiteralPath $Compactado).Length / 1KB)) }
    if ($ResumoPytest) {
        $cor = 'Green'
        if ($ResumoPytest.Falhas -or $ResumoPytest.Erros) { $cor = 'Yellow' }
        Write-Host ('  pytest: {0} testes, {1} falhas, {2} erros, {3} pulados' -f $ResumoPytest.Total, $ResumoPytest.Falhas, $ResumoPytest.Erros, $ResumoPytest.Pulados) -ForegroundColor $cor
    }
    Write-Host ('  Verificacoes: {0} ocorrencias (analise\verificacoes.md)' -f $totalAchados)
    if ($Compactado) { Write-Host '  Envie o .7z junto com o pedido de revisao (resumo em INDICE.md).' }
    else { Write-Host '  Envie a pasta junto com o pedido de revisao (resumo em INDICE.md).' }
} finally {
    $env:PYTHONIOENCODING = $ioAnterior
    $env:BTC_COBERTURA_JS = $coberturaJsAnterior
}
