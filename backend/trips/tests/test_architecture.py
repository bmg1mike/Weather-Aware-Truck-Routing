"""Architectural invariants of spec section 10, enforced statically."""

import ast
from pathlib import Path

import pytest

TRIPS_DIR = Path(__file__).resolve().parent.parent

# Modules that must stay pure: no Django, no network, no filesystem/environment access.
PURE_MODULES = [
    TRIPS_DIR / "domain.py",
    TRIPS_DIR / "services" / "risk.py",
    TRIPS_DIR / "services" / "scoring.py",
    TRIPS_DIR / "services" / "sampling.py",
    TRIPS_DIR / "services" / "geometry.py",
]
# trips.api / trips.errors are listed because importing them pulls in Django transitively.
FORBIDDEN_IMPORTS = {
    "django",
    "rest_framework",
    "httpx",
    "requests",
    "redis",
    "urllib",
    "socket",
    "os",
    "pathlib",
    "trips.api",
    "trips.errors",
}


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _is_forbidden(module: str) -> bool:
    return any(module == banned or module.startswith(f"{banned}.") for banned in FORBIDDEN_IMPORTS)


@pytest.mark.parametrize("path", PURE_MODULES, ids=lambda p: p.name)
def test_pure_modules_have_no_io_or_django_imports(path):
    offending = sorted(m for m in _imported_modules(path) if _is_forbidden(m))
    assert not offending, f"{path.name} must stay pure but imports {offending}"


def test_guard_catches_transitive_django_import(tmp_path):
    impure = tmp_path / "impure.py"
    impure.write_text("from trips.errors import ApiError\nimport os.path\n")
    assert sorted(m for m in _imported_modules(impure) if _is_forbidden(m)) == [
        "os.path",
        "trips.errors",
    ]
