<#
.SYNOPSIS
    Executa o BTC Status pelo codigo-fonte, com o Python do venv ".venv".
.DESCRIPTION
    Roda BTC_Monitor.py com .venv\Scripts\python.exe, sem precisar ativar o
    ambiente e sem gerar o executavel. Pelo codigo-fonte a medicao de desempenho
    fica ligada (metricas.jsonl em %APPDATA%\btcstatus).
    Deve ficar na pasta raiz do projeto, junto do BTC_Monitor.py.
.NOTES
    Se o app terminar com erro, o codigo de saida e repassado e os detalhes
    ficam em %APPDATA%\btcstatus\btcstatus.log.
.EXAMPLE
    .\runbtc.ps1
#>
$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "BTC_Monitor.py"

foreach ($arquivo in @($python, $script)) {
    if (-not (Test-Path $arquivo)) {
        Write-Host "Erro: arquivo nao encontrado: $arquivo"
        exit 1
    }
}

& $python $script
if ($LASTEXITCODE -ne 0) {
    Write-Host "Erro: o BTC Status terminou com codigo $LASTEXITCODE. Veja %APPDATA%\btcstatus\btcstatus.log"
}
exit $LASTEXITCODE
