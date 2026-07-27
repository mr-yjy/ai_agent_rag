from pathlib import Path

project_root = Path(SPECPATH).parent
backend_root = project_root / "backend"
package_data = backend_root / "scholarpilot" / "data"

analysis = Analysis(
    [str(backend_root / "run.py")],
    pathex=[str(backend_root)],
    binaries=[],
    datas=[(str(package_data), "scholarpilot/data")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["fastapi", "numpy", "openai", "uvicorn"],
    noarchive=False,
    optimize=1,
)
python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="ScholarPilotBackend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
