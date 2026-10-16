# Build with: python -m PyInstaller --noconfirm iphone_joystick.spec
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

datas = collect_data_files('pymobiledevice3')
datas += copy_metadata('pymobiledevice3', recursive=True)
hiddenimports = collect_submodules('pmd_pytcp')
binaries = collect_dynamic_libs('pytun_pmd3')

a = Analysis(
    ['iphone_joystick.py'], pathex=[SPECPATH], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['IPython', 'matplotlib', 'numpy', 'pandas', 'scipy', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='iPhoneGPSJoystick',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='iPhoneGPSJoystick')
