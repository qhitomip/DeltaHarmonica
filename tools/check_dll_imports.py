from __future__ import annotations

import sys
from pathlib import Path

import pefile


def export_names(path: Path) -> set[str]:
    pe = pefile.PE(str(path), fast_load=False)
    directory = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
    if directory is None:
        return set()
    return {
        symbol.name.decode(errors="replace")
        for symbol in directory.symbols
        if symbol.name is not None
    }


def main() -> int:
    root = Path(sys.argv[1])
    target = root / sys.argv[2]
    pe = pefile.PE(str(target), fast_load=False)
    for dependency in pe.DIRECTORY_ENTRY_IMPORT:
        dll_name = dependency.dll.decode(errors="replace")
        dll_path = root / dll_name
        if not dll_path.exists():
            continue
        exports = export_names(dll_path)
        imported = {
            item.name.decode(errors="replace")
            for item in dependency.imports
            if item.name is not None
        }
        missing = sorted(imported - exports)
        print(f"{dll_name}: imports={len(imported)} exports={len(exports)} missing={missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
