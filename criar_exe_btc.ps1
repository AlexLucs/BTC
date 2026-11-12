<#
.SYNOPSIS
    Gera o executavel do BTC Status a partir do "BTC Monitor.spec".
.DESCRIPTION
    Usa o Python do venv ".venv" (sem ativar o ambiente), roda os testes e
    chama o PyInstaller com o .spec, que e a unica fonte da configuracao do build.
    Deve ficar na pasta raiz do projeto, junto do .spec.
.PARAMETER SemTestes
    Pula os testes antes do build.
.PARAMETER ComMedicao
    Inclui a medicao de desempenho (metricas.py e o coletor real do metricas.js),
    para usar com tools\medir_abertura.py --exe. Sem esta opcao o build e o de
    producao, sem nenhuma medicao.
.NOTES
    Para antes de tudo se houver um BTC Monitor.exe aberto a partir da pasta dist
    (ele trava os arquivos que o build precisa apagar).
.EXAMPLE
    .\criar_exe_btc.ps1
    .\criar_exe_btc.ps1 -SemTestes
    .\criar_exe_btc.ps1 -ComMedicao
#>
param(
    [switch]$SemTestes,
    [switch]$ComMedicao
)

$ErrorActionPreference = "Stop"

$raiz   = $PSScriptRoot
$python = Join-Path $raiz ".venv\Scripts\python.exe"
$spec   = Join-Path $raiz "BTC Monitor.spec"
$exe    = Join-Path $raiz "dist\BTC Monitor\BTC Monitor.exe"

foreach ($arquivo in @($python, $spec)) {
    if (-not (Test-Path $arquivo)) {
        Write-Host "Erro: arquivo nao encontrado: $arquivo" -ForegroundColor Red
        exit 1
    }
}

# Um BTC Monitor.exe aberto a partir da pasta dist trava os arquivos dela (ex.: ClrLoader.dll)
# e o PyInstaller falha ao apaga-la, no fim do build. Avisa antes e nao encerra nada sozinho.
$pastaDist = Split-Path $exe
$abertos = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and $_.Path.StartsWith($pastaDist + "\", [System.StringComparison]::OrdinalIgnoreCase)
})
if ($abertos.Count -gt 0) {
    Write-Host "Erro: feche o BTC Monitor antes de gerar o executavel. Processos abertos da pasta dist:" -ForegroundColor Red
    $abertos | ForEach-Object { Write-Host ("  PID {0}  {1}" -f $_.Id, $_.Path) -ForegroundColor Red }
    Write-Host "Para encerrar todos:" -ForegroundColor Yellow
    Write-Host "  Get-Process | Where-Object { `$_.Path -like ""*\dist\BTC Monitor\*"" } | Stop-Process -Force" -ForegroundColor Yellow
    exit 1
}

Push-Location $raiz
try {
    if (-not $SemTestes) {
        Write-Host "Rodando testes Python..." -ForegroundColor Cyan
        & $python -m pytest -q tests
        if ($LASTEXITCODE -ne 0) { throw "Testes Python falharam." }

        if (Get-Command node -ErrorAction SilentlyContinue) {
            Write-Host "Rodando testes JavaScript..." -ForegroundColor Cyan
            & node --test tests/regras.test.js tests/metricas.test.js
            if ($LASTEXITCODE -ne 0) { throw "Testes JavaScript falharam." }
        } else {
            Write-Host "Node.js nao encontrado: testes JavaScript ignorados." -ForegroundColor Yellow
        }
    }

    if ($ComMedicao) {
        Write-Host "Gerando executavel COM medicao (build de teste)..." -ForegroundColor Yellow
        $env:BTC_BUILD_MEDICAO = "1"
    } else {
        Write-Host "Gerando executavel de producao (sem medicao)..." -ForegroundColor Cyan
        Remove-Item Env:BTC_BUILD_MEDICAO -ErrorAction SilentlyContinue
    }
    # --clean evita reaproveitar no cache arquivos que ja foram removidos do projeto.
    & $python -m PyInstaller $spec --noconfirm --clean
    $codigo = $LASTEXITCODE
    Remove-Item Env:BTC_BUILD_MEDICAO -ErrorAction SilentlyContinue
    if ($codigo -ne 0) { throw "PyInstaller falhou (codigo $codigo)." }

    Write-Host "Executavel gerado: $exe" -ForegroundColor Green
    Write-Host "Para distribuir, copie a pasta inteira: $(Split-Path $exe)"
}
catch {
    Write-Host "Erro: $_" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
