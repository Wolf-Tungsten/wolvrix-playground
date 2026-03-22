from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_wolvrix():
    module = sys.modules.get("wolvrix")
    if module is not None:
        return module

    repo_root = Path(__file__).resolve().parents[1]
    build_pkg_dir = repo_root / "wolvrix" / "build" / "python" / "wolvrix"
    build_init = build_pkg_dir / "__init__.py"
    build_native = build_pkg_dir / "_wolvrix.so"
    if build_init.exists() and build_native.exists():
        spec = importlib.util.spec_from_file_location(
            "wolvrix",
            build_init,
            submodule_search_locations=[str(build_pkg_dir)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"failed to load wolvrix module spec from {build_init}")
        module = importlib.util.module_from_spec(spec)
        sys.modules["wolvrix"] = module
        spec.loader.exec_module(module)
        return module

    import wolvrix as installed_wolvrix

    return installed_wolvrix
