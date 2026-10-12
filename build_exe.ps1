# Builds dist\pyGearTrainStudio.exe, a single-file portable exe. Run setup_env.ps1 first.
param([string]$Venv = '.venv')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$root = $PSScriptRoot
$py = Join-Path $Venv 'Scripts\python.exe'
$modules = 'planetary', 'compound_planetary', 'cycloid', 'compound_cycloid', 'nabtesco', 'simple'
$excludes = 'jax', 'jaxlib', 'torch', 'pytest', 'vispy', 'IPython', 'PyQt5', 'PySide6', 'pandas', 'einops'
# PyInstaller resolves relative paths against --specpath, so pass absolute ones
$pyiArgs = @('--noconfirm', '--clean', '--onefile', '--windowed', '--name', 'pyGearTrainStudio',
             '--icon', (Join-Path $root 'build_assets\gear.ico'),
             '--add-data', ((Join-Path $root 'build_assets\gear.ico') + ';build_assets'),
             '--paths', (Join-Path $root 'vendor\pyGearTrain'),
             '--workpath', (Join-Path $root 'build'),
             '--specpath', (Join-Path $root 'build'),
             '--distpath', (Join-Path $root 'dist'))
$pyiArgs += $modules | ForEach-Object { '--hidden-import', "pygeartrain.$_" }
$pyiArgs += $excludes | ForEach-Object { '--exclude-module', $_ }
& $py -m PyInstaller @pyiArgs (Join-Path $root 'geartrain_gui.py')
