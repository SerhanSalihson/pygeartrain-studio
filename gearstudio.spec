# PyInstaller spec for pyGearTrain Studio.
#   pyinstaller gearstudio.spec            -> dist/pyGearTrainStudio/ (portable folder, fast start)
#   set GS_ONEFILE=1 && pyinstaller ...    -> dist/pyGearTrainStudio.exe (single file)
import os
import re

ROOT = os.path.abspath(SPECPATH)
ONEFILE = os.environ.get('GS_ONEFILE') == '1'

# Qt pieces the app never uses. PyInstaller's QML hook would otherwise bundle every QML module,
# including the 190 MB Chromium-based WebEngine.
UNUSED_QT = ['webengine', 'pdf', 'charts', 'graphs', 'datavisualization', '3d', 'location', 'multimedia',
             'spatialaudio', 'sensors', 'texttospeech', 'remoteobjects', 'scxml', 'statemachine', 'positioning',
             'webchannel', 'webview', 'websockets', 'bluetooth', 'nfc', 'serialport', 'serialbus',
             'virtualkeyboard', 'designer', 'help', 'httpserver', 'test', '5compat', 'quicktimeline']
# never prune ShaderTools: Qt Quick 3D compiles its shaders with it at run time
_dll = re.compile(r'qt6(%s)' % '|'.join(UNUSED_QT))
_qml = re.compile(r'pyside6[\\/]qml[\\/]qt(%s)[\\/]' % '|'.join(UNUSED_QT))
_other = re.compile(r'(qtwebengine|translations[\\/]qtwebengine_locales|resources[\\/]qtwebengine)')


def keep(entry):
    name = entry[0].lower()
    if _qml.search(name) or _other.search(name):
        return False
    base = os.path.basename(name)
    return not (base.startswith('qt6') and _dll.match(base) and not base.startswith('qt6quick3d'))


a = Analysis(
    [os.path.join(ROOT, 'run_gearstudio.py')],
    pathex=[ROOT, os.path.join(ROOT, 'vendor', 'pyGearTrain')],
    datas=[(os.path.join(ROOT, 'gearstudio', 'ui', 'view3d.qml'), 'gearstudio/ui'),
           (os.path.join(ROOT, 'gearstudio', 'ui', 'fonts'), 'gearstudio/ui/fonts')],
    hiddenimports=['pygeartrain.' + m for m in
                   ('planetary', 'compound_planetary', 'cycloid', 'compound_cycloid', 'nabtesco', 'simple')],
    excludes=['tkinter', 'IPython', 'jax', 'jaxlib', 'torch', 'pytest', 'vispy', 'pandas', 'einops', 'PyQt5',
              'PyQt6', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
              'PySide6.Qt3DCore', 'PySide6.QtCharts', 'PySide6.QtMultimedia', 'PySide6.QtPdf'],
    noarchive=False,
)
a.binaries = [e for e in a.binaries if keep(e)]
a.datas = [e for e in a.datas if keep(e)]
pyz = PYZ(a.pure)
icon = os.path.join(ROOT, 'build_assets', 'gear.ico')

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='pyGearTrainStudio', console=False, icon=icon,
              upx=False)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='pyGearTrainStudio', console=False, icon=icon,
              upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name='pyGearTrainStudio', upx=False)
