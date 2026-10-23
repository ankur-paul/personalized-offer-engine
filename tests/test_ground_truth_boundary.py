"""ADR 0002: the decision pipeline never reads Ground Truth.

Pipeline modules (PLAN "Assumed › Code layout") must not import `offer_engine.sim` or name a `sim_*` table.
"""

import ast
import re
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).parents[1] / "src" / "offer_engine"
PIPELINE_MODULES = (
    "customers",
    "budget",
    "rules",
    "validation",
    "caption_check",
    "pipeline",
    "choosers",
    "lift",
    "triggers",
    "daily_sweep",
    "offer_bot",
)
SIM_TABLE = re.compile(r"\bsim_\w+")
SIM_PACKAGE = "offer_engine.sim"


def module_name(path: Path, package_dir: Path) -> str:
    parts = path.relative_to(package_dir.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imported_modules(node: ast.AST, current: str, is_package: bool) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level:
            base = current.split(".")
            # A module's own package is its parent; a package's own package is itself.
            base = base[: len(base) - node.level + (1 if is_package else 0)]
            module = ".".join(base + ([node.module] if node.module else []))
        else:
            module = node.module or ""
        return [module] + [f"{module}.{alias.name}" for alias in node.names]
    return []


def violations(path: Path, package_dir: Path = PACKAGE_DIR) -> list[str]:
    current = module_name(path, package_dir)
    is_package = path.name == "__init__.py"
    found = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        for module in imported_modules(node, current, is_package):
            if module == SIM_PACKAGE or module.startswith(SIM_PACKAGE + "."):
                found.append(f"{path.name}:{node.lineno} imports {module}")
        is_string = isinstance(node, ast.Constant) and isinstance(node.value, str)
        if is_string and (SIM_TABLE.search(node.value) or SIM_PACKAGE in node.value):
            found.append(f"{path.name}:{node.lineno} names {node.value!r}")
    return found


def pipeline_files(package_dir: Path = PACKAGE_DIR) -> list[Path]:
    files = []
    for name in PIPELINE_MODULES:
        if (package_dir / f"{name}.py").is_file():
            files.append(package_dir / f"{name}.py")
        if (package_dir / name).is_dir():
            files.extend(sorted((package_dir / name).rglob("*.py")))
    return files


def test_pipeline_modules_never_touch_ground_truth():
    found = [v for path in pipeline_files() for v in violations(path)]
    assert not found, "pipeline modules read simulator data:\n" + "\n".join(found)


@pytest.fixture
def fake_package(tmp_path):
    package = tmp_path / "offer_engine"
    package.mkdir()
    (package / "__init__.py").write_text("")
    return package


def add_choosers(package: Path) -> Path:
    (package / "choosers").mkdir()
    (package / "choosers" / "__init__.py").write_text("")
    return package / "choosers"


@pytest.mark.parametrize(
    "source",
    [
        "import offer_engine.sim",
        "import offer_engine.sim.generate as gen",
        "from offer_engine.sim import ground_truth",
        "from offer_engine import sim",
        "from .sim import ground_truth",
        "from . import sim",
        "QUERY = 'SELECT * FROM sim_ground_truth'",
        "def f(conn):\n    return conn.execute(f'SELECT base FROM sim_customer_traits WHERE id = {1}')",
        "import importlib\nimportlib.import_module('offer_engine.sim')",
    ],
)
def test_detects_reads_of_simulator_data(fake_package, source):
    module = fake_package / "rules.py"
    module.write_text(source + "\n")
    assert pipeline_files(fake_package) == [module]
    assert violations(module, fake_package)


def test_detects_relative_import_from_subpackage(fake_package):
    module = add_choosers(fake_package) / "rules_chooser.py"
    module.write_text("from ..sim import ground_truth\n")
    assert module in pipeline_files(fake_package)
    assert violations(module, fake_package)


@pytest.mark.parametrize(
    "source",
    [
        "import offer_engine.simulation_report",
        "from offer_engine import similar",
        "NOTE = 'simulated time, not a table'",
        "from . import rules",
        "from ..domain import Offer",
    ],
)
def test_allows_unrelated_names(fake_package, source):
    module = add_choosers(fake_package) / "__init__.py"
    module.write_text(source + "\n")
    assert violations(module, fake_package) == []


def test_non_pipeline_modules_are_not_scanned(fake_package):
    (fake_package / "commands").mkdir()
    (fake_package / "commands" / "generate.py").write_text("import offer_engine.sim\n")
    assert pipeline_files(fake_package) == []
