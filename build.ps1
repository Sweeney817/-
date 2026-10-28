$ErrorActionPreference = 'Stop'

$Python = if ($env:ORANGE_CAT_PYTHON) { $env:ORANGE_CAT_PYTHON } else { 'python' }
$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceAsset = Join-Path $Project 'assets\liuliu-source.png'
$Asset = Join-Path $Project 'assets\spritesheet.png'
$Icon = Join-Path $Project 'assets\orange-cat.ico'
$Dist = Join-Path $Project 'dist'

if (-not (Test-Path -LiteralPath $Asset)) {
    throw "Missing sprite atlas: $Asset"
}

& $Python -m pip install --disable-pip-version-check pillow pyinstaller rapidocr_onnxruntime
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name 'OrangeCatDesktopPet' `
    --icon $Icon `
    --collect-all rapidocr_onnxruntime `
    --add-data "$Asset;assets" `
    --distpath $Dist `
    --workpath (Join-Path $Project 'build') `
    --specpath $Project `
    (Join-Path $Project 'app.py')
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }

Write-Output (Join-Path $Dist 'OrangeCatDesktopPet.exe')
