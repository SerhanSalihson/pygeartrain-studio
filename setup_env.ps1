# Recreates the Python environment for pyGearTrain Studio (Windows, no C compiler needed).
# Use a python.org Python 3.12 (not Anaconda: its _ctypes depends on a libffi DLL PyInstaller misses).
# pygeartrain itself is vendored in .\vendor\pyGearTrain.
param([string]$Python = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", [string]$Venv = '.venv')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& $Python -m venv $Venv
$py = Join-Path $Venv 'Scripts\python.exe'
& $py -m pip install --upgrade pip
# old numga requires numpy 1.x, so pin a matching scipy / matplotlib
& $py -m pip install "numpy==1.26.4" "scipy==1.13.1" "matplotlib==3.8.4" "contourpy<1.4" "shapely>=2.1,<2.3" `
    sympy pillow cached_property numpy_indexed funcsigs pyinstaller
# pygeartrain targets the pre-2.0 numga API (numga.backend.numpy.context); pin the last commit before the rewrite
& $py -m pip install --no-deps "git+https://github.com/eelcohoogendoorn/numga.git@fe9f0ff69fdf8fc3430544eb76431729d2cdbcb3"
# pycomplex wants fastcache and pycosat, which need MSVC to build; neither is used for 2D gear profiles
& $py -m pip install --no-deps "git+https://github.com/eelcohoogendoorn/pycomplex.git"
$site = & $py -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
Set-Content -Path (Join-Path $site 'fastcache.py') -Value 'from functools import lru_cache as clru_cache' -Encoding ascii
Set-Content -Path (Join-Path $site 'pycosat.py') -Encoding ascii -Value @'
def solve(*args, **kwargs):
    raise NotImplementedError("pycosat is stubbed out in this build")
'@
Write-Host "Done. Run the app with: $py geartrain_gui.py   (or build the exe with build_exe.ps1)"
