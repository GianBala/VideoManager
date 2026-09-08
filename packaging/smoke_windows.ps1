# O diagnóstico precisa terminar com sucesso; abrir a janela não basta.
param(
    [Parameter(Mandatory=$true)][string]$Executable,
    [int]$TimeoutSeconds = 60
)
$ErrorActionPreference = "Stop"
$process = Start-Process -FilePath $Executable -ArgumentList '--smoke-test' -PassThru
try {
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $process.Kill()
        $process.WaitForExit()
        throw "Diagnostico do pacote excedeu $TimeoutSeconds segundos."
    }
    if ($process.ExitCode -ne 0) {
        throw "Falha no diagnostico do pacote: codigo $($process.ExitCode)."
    }
    Write-Host 'VM_SMOKE_OK: janela, fontes, previa e exportacao verificadas'
} finally {
    $process.Dispose()
}
