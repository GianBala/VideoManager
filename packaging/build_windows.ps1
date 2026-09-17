# Gera o pacote para Windows em dist\VideoManager\.
#
# Precisa rodar no Windows: o PyInstaller não faz compilação cruzada, então o
# pacote de Linux tem de ser gerado no Linux, com build_linux.sh.
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

$venv = if ($env:VENV) { $env:VENV } else { ".venv" }
$py = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Error "venv nao encontrado em $venv. Crie com: python -m venv $venv"
}

Write-Host "==> instalando dependencias"
& $py -m pip install -q --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar pip" }
& $py -m pip install -q -e ".[dev]" pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependencias" }

Write-Host "==> testes (um pacote nao deve ser gerado sobre suite vermelha)"
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Error "testes falharam" }

if ($env:VM_BUNDLE_FFMPEG -ne "0") {
    Write-Host "==> baixando ffmpeg para embutir"
    $env:PYTHONPATH = "src"
    & $py packaging\fetch_binaries.py
    if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar ffmpeg" }
}

Write-Host "==> empacotando"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
# Depois da limpeza: o .ico vive em build\ e o spec só o usa se existir.
& $py packaging\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o icone" }
& $py -m PyInstaller --noconfirm --clean packaging\videomanager.spec
if ($LASTEXITCODE -ne 0) { throw "Falha no empacotamento" }

& (Join-Path $PSScriptRoot "smoke_windows.ps1") -Executable ".\dist\VideoManager\VideoManager.exe" -Icon ".\build\videomanager.ico"

Write-Host ""
Write-Host "pronto: dist\VideoManager\VideoManager.exe"
