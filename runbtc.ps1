# Executa o BTC Status usando o Python do venv ".venv", sem precisar ativar o ambiente.
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
