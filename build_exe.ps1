# Builds the Windows downloads from gearstudio.spec. Run setup_env.ps1 first.
#   dist\pyGearTrainStudio\                         portable folder (fast start)
#   dist\pyGearTrainStudio-<version>-win64.zip      that folder, zipped
#   dist\pyGearTrainStudio.exe                      single file (slower start: unpacks itself)
param([string]$Venv = '.venv')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$py = Join-Path $Venv 'Scripts\python.exe'
$version = & $py -c "import gearstudio; print(gearstudio.__version__)"
$work = Join-Path $PSScriptRoot 'build'

& $py -m pytest -q tests
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; not building.' }

$env:GS_ONEFILE = '0'
& $py -m PyInstaller --noconfirm --clean --workpath $work --distpath dist gearstudio.spec
$env:GS_ONEFILE = '1'
& $py -m PyInstaller --noconfirm --workpath $work --distpath dist gearstudio.spec
Remove-Item Env:GS_ONEFILE

$zip = "dist\pyGearTrainStudio-$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path dist\pyGearTrainStudio -DestinationPath $zip
Get-ChildItem dist | Select-Object Name, @{n = 'MB'; e = { [math]::Round($_.Length / 1MB, 1) } }
