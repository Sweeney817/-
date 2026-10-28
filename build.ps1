$ErrorActionPreference = 'Stop'

$Python = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceAsset = Join-Path $Project 'assets\liuliu-source.png'
$Asset = Join-Path $Project 'assets\spritesheet.png'
$Icon = Join-Path $Project 'assets\orange-cat.ico'
$Dist = Join-Path $Project 'dist'

if (-not (Test-Path -LiteralPath $SourceAsset)) {
    throw "Missing sprite atlas: $SourceAsset"
}

& $Python -m pip install --disable-pip-version-check pyinstaller rapidocr_onnxruntime
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& node (Join-Path $Project 'prepare_assets.cjs')
if ($LASTEXITCODE -ne 0) { throw 'Asset preparation failed' }

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
