# Reproducible Windows one-file build. Resolve DLLs before sealing the archive.
from pathlib import Path
import hashlib
import json
import os
import sys
import runpy
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct,
)

root = Path(SPECPATH).parent
packages = root / '.packages'
version = runpy.run_path(str(root / 'src/delta_harmonica/__init__.py'))['__version__']
version_numbers = tuple(int(part) for part in version.split('.')) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_numbers, prodvers=version_numbers,
                      mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('080404b0', [
        StringStruct('CompanyName', '沙拉Sarada'),
        StringStruct('FileDescription', 'Delta Harmonica 正式版'),
        StringStruct('FileVersion', version),
        StringStruct('ProductName', 'Delta Harmonica'),
        StringStruct('ProductVersion', version),
        StringStruct('OriginalFilename', 'DeltaHarmonica.exe'),
    ])]), VarFileInfo([VarStruct('Translation', [2052, 1200])])],
)
a = Analysis(
    [str(root / 'launcher.py')],
    pathex=[str(root / 'src'), str(packages)],
    binaries=[],
    datas=[(str(root / 'src/delta_harmonica/assets'), 'delta_harmonica/assets'),
           (str(root / 'licenses'), 'licenses'),
           (str(root / 'THIRD_PARTY_NOTICES.md'), '.'), (str(root / 'README.md'), '.')],
    hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['numpy', 'onnxruntime', 'miniaudio', '_miniaudio', '_cffi_backend', 'cffi', 'scipy', 'sympy'], noarchive=False,
    optimize=0,
)

system32 = Path(os.environ['WINDIR']) / 'System32'
runtime_names = ('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
                 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll',
                 'msvcp140_codecvt_ids.dll')
replacements = {name: system32 / name for name in runtime_names}
python_dlls = Path(sys.base_prefix) / 'DLLs'
for name in ('libssl-3-x64.dll', 'libcrypto-3-x64.dll'):
    replacements[name] = python_dlls / name
for name, source in replacements.items():
    if not source.is_file():
        raise SystemExit(f'Missing required build dependency: {source}')

# Qt uses the Windows ICU library. Do not collect unrelated Poppler ICU files.
excluded = {'icuuc.dll', 'icudt78.dll'} | replacements.keys()
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in excluded]
a.binaries += [(name, str(source), 'BINARY') for name, source in replacements.items()]
manifest = {name: hashlib.sha256(source.read_bytes()).hexdigest()
            for name, source in replacements.items()}
manifest_path = Path(workpath) / 'runtime-manifest.json'
manifest_path.parent.mkdir(parents=True, exist_ok=True)
manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
a.datas.append(('runtime-manifest.json', str(manifest_path), 'DATA'))

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name='DeltaHarmonica', icon=str(root / 'src/delta_harmonica/assets/app.ico'),
          version=version_info, console=False, debug=False, strip=False, upx=False,
          runtime_tmpdir=None, bootloader_ignore_signals=False,
          disable_windowed_traceback=False)
