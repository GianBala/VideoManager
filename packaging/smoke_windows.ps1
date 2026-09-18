# O diagnóstico precisa terminar com sucesso; abrir a janela não basta.
param(
    [Parameter(Mandatory=$true)][string]$Executable,
    [int]$TimeoutSeconds = 60,
    # .ico usado no build; quando informado, o ícone do .exe precisa ser ele.
    [string]$Icon = ""
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

# Conferencias de arquivo que o diagnostico em execucao nao alcanca.
$internal = Join-Path (Split-Path -Parent $Executable) "_internal"
$solver = Join-Path $internal "yt_dlp\extractor\youtube\jsc\_builtin\vendor\yt.solver.core.js"
if (-not (Test-Path $solver)) {
    throw "Scripts do solver JavaScript do yt-dlp ausentes do pacote."
}
if ($env:VM_BUNDLE_DENO -ne "0" -and -not (Test-Path (Join-Path $internal "vendor\win64\deno.exe"))) {
    throw "deno.exe ausente do pacote (use VM_BUNDLE_DENO=0 para dispensar)."
}
if ($Icon) {
    # Sem icon= no spec o .exe sai com o icone padrao do PyInstaller, e nada
    # falha: so o Explorer mostra o desenho errado.
    Add-Type -AssemblyName System.Drawing
    $fromExe = [System.Drawing.Icon]::ExtractAssociatedIcon((Resolve-Path $Executable).Path).ToBitmap()
    $expected = (New-Object System.Drawing.Icon((Resolve-Path $Icon).Path, $fromExe.Width, $fromExe.Height)).ToBitmap()
    $different = 0
    for ($x = 0; $x -lt $fromExe.Width; $x += 3) {
        for ($y = 0; $y -lt $fromExe.Height; $y += 3) {
            if ($fromExe.GetPixel($x, $y).ToArgb() -ne $expected.GetPixel($x, $y).ToArgb()) { $different++ }
        }
    }
    if ($different -gt 0) {
        throw "O icone do executavel nao e o do aplicativo ($different pixels diferentes)."
    }
    Write-Host 'VM_SMOKE_ICON_OK'
}
# O .ico tambem solto ao lado do executavel: e para onde um atalho feito a mao
# pode apontar quando o Windows guardou o icone antigo daquele caminho.
$icoNoPacote = Join-Path (Split-Path -Parent (Resolve-Path $Executable).Path) 'videomanager.ico'
if (-not (Test-Path $icoNoPacote)) {
    throw "O pacote nao traz videomanager.ico ao lado do executavel."
}
Write-Host 'VM_SMOKE_BUNDLE_OK: solver JavaScript, Deno e icone conferidos'
