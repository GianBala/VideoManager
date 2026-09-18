# O diagnóstico precisa terminar com sucesso; abrir a janela não basta.
param(
    [Parameter(Mandatory=$true)][string]$Executable,
    # O arquivo unico extrai tudo para uma pasta temporaria antes de abrir: cerca
    # de 8 s numa maquina rapida (o pacote em pasta leva 2 s), e uma de CI e mais lenta.
    [int]$TimeoutSeconds = 120,
    # .ico usado no build; quando informado, o ícone do .exe precisa ser ele.
    [string]$Icon = "",
    # Python com PyInstaller, usado para listar o conteudo do arquivo unico.
    [string]$Python = "python"
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

# Conferencias de arquivo que o diagnostico em execucao nao alcanca. O pacote em
# pasta (VM_ONEFILE=0) as tem em _internal; o arquivo unico, dentro do proprio
# .exe, e ai a lista de entradas vem do PyInstaller.
$package = Split-Path -Parent (Resolve-Path $Executable).Path
$internal = Join-Path $package "_internal"
$onefile = -not (Test-Path $internal)
$solverEntry = "yt_dlp\extractor\youtube\jsc\_builtin\vendor\yt.solver.core.js"
$denoEntry = "vendor\win64\deno.exe"
if ($onefile) {
    $entries = & $Python -c "import sys; from PyInstaller.archive.readers import CArchiveReader; print('\n'.join(CArchiveReader(sys.argv[1]).toc))" (Resolve-Path $Executable).Path
    if ($LASTEXITCODE -ne 0) {
        throw "Nao foi possivel listar o conteudo do arquivo unico (PyInstaller disponivel em '$Python'?)."
    }
    $hasSolver = $entries -contains $solverEntry
    $hasDeno = $entries -contains $denoEntry
} else {
    $hasSolver = Test-Path (Join-Path $internal $solverEntry)
    $hasDeno = Test-Path (Join-Path $internal $denoEntry)
}
if (-not $hasSolver) {
    throw "Scripts do solver JavaScript do yt-dlp ausentes do pacote."
}
if ($env:VM_BUNDLE_DENO -ne "0" -and -not $hasDeno) {
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
# Pacote em pasta: o .ico tambem solto ao lado do executavel, para onde um atalho
# feito a mao pode apontar quando o Windows guardou o icone antigo daquele caminho.
# O arquivo unico nao tem "ao lado": e um .exe sozinho, com o icone embutido.
if (-not $onefile) {
    $icoNoPacote = Join-Path $package 'videomanager.ico'
    if (-not (Test-Path $icoNoPacote)) {
        throw "O pacote nao traz videomanager.ico ao lado do executavel."
    }
}
Write-Host 'VM_SMOKE_BUNDLE_OK: solver JavaScript e Deno conferidos'
