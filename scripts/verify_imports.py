"""Import hygiene: core/ is web/media-free, nothing imports the parent Arbitale repo."""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

from scripts.testkit import ROOT, Checker

T = Checker("verify_imports")
PARENT = ROOT.parent
CORE_FORBIDDEN = {"fastapi", "starlette", "uvicorn", "server", "media"}
SKIP_DIRS = {"web", "node_modules", ".git", "states", "cache", "logs", "__pycache__", ".venv"}


def python_files(base: Path) -> list[Path]:
    return [p for p in base.rglob("*.py") if not SKIP_DIRS & set(p.relative_to(ROOT).parts)]


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def parent_module_names() -> set[str]:
    """Top-level Arbitale modules/packages (excluding names Polytale legitimately owns)."""
    names = {p.stem for p in PARENT.glob("*.py")}
    names |= {p.name for p in PARENT.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    names |= {"dm_brain", "dm_prompt", "engine", "gemini_utils", "game_service", "shared_types",
              "web_api", "web_service", "arbitale_media", "arbitale_scenario"}
    own = {p.name for p in ROOT.iterdir() if p.is_dir()} | {p.stem for p in ROOT.glob("*.py")}
    return names - own


def test_core_modules_import() -> None:
    modules = sorted(f"core.{p.stem}" for p in (ROOT / "core").glob("*.py") if p.stem != "__init__")
    for name in modules:
        module = importlib.import_module(name)
        T.check(f"{name} imports from polytale/core",
                Path(module.__file__ or "").resolve().is_relative_to(ROOT / "core"))


def test_core_forbidden_imports() -> None:
    for path in python_files(ROOT / "core"):
        bad = imported_roots(path) & CORE_FORBIDDEN
        T.check(f"{path.relative_to(ROOT)} has no web/media imports", not bad, sorted(bad))
    code = (
        "import sys, importlib, pathlib\n"
        "for p in sorted(pathlib.Path('core').glob('*.py')):\n"
        "    importlib.import_module('core.' + p.stem) if p.stem != '__init__' else None\n"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {sorted(CORE_FORBIDDEN)!r})\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"})
    T.check("importing all of core loads no fastapi/server/media modules",
            out.returncode == 0 and out.stdout.strip() == "", out.stdout + out.stderr)


def test_no_parent_imports() -> None:
    forbidden = parent_module_names()
    T.check("parent module list is non-empty", {"dm_brain", "engine", "gemini_utils"} <= forbidden)
    for path in python_files(ROOT):
        bad = imported_roots(path) & forbidden
        T.check(f"{path.relative_to(ROOT)} imports nothing from Arbitale", not bad, sorted(bad))
    T.check("parent repo is not on sys.path",
            all(Path(p or ".").resolve() != PARENT for p in sys.path))


if __name__ == "__main__":
    T.run("core modules import", test_core_modules_import)
    T.run("core forbidden imports", test_core_forbidden_imports)
    T.run("no parent imports", test_no_parent_imports)
    T.finish()
