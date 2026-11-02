"""Deployment guards: everything dashboard.py imports must ship in the image.

The root Dockerfile once lacked analytics/, so the backtest tab failed only in
production. These tests fail at commit time instead.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILES = ["Dockerfile", "embedded_deployment/Dockerfile"]
APP_MODULES = ["dashboard.py", "scheduler.py", "db_manager.py", "macro_index.py", "data_fetcher.py"]
THIRD_PARTY = {
    "streamlit": "streamlit", "streamlit_javascript": "streamlit-javascript", "pandas": "pandas",
    "numpy": "pandas", "plotly": "plotly", "requests": "requests", "dateutil": "python-dateutil",
    "apscheduler": "APScheduler",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


def _first_party_packages() -> set[str]:
    found: set[str] = set()
    for module in APP_MODULES:
        found |= _imports(ROOT / module)
    for package in ("analytics", "ui", "fetchers"):
        for file in (ROOT / package).glob("*.py"):
            found |= _imports(file)
    return {name for name in found if (ROOT / name / "__init__.py").exists()}


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
class TestDockerfiles:
    def test_every_first_party_package_is_copied(self, dockerfile):
        text = (ROOT / dockerfile).read_text(encoding="utf-8")
        for package in _first_party_packages():
            assert re.search(rf"^COPY {package}/ {package}/", text, re.M), package

    def test_every_top_level_module_is_copied(self, dockerfile):
        text = (ROOT / dockerfile).read_text(encoding="utf-8")
        for module in APP_MODULES:
            assert module in text, module

    def test_theme_config_ships_with_the_app(self, dockerfile):
        assert "COPY .streamlit/ .streamlit/" in (ROOT / dockerfile).read_text(encoding="utf-8")

    def test_does_not_overwrite_the_app_config(self, dockerfile):
        assert "/root/.streamlit" not in (ROOT / dockerfile).read_text(encoding="utf-8")


def test_post_deploy_purge_list_is_not_read_by_the_app():
    """Everything the migration deletes must really be unused."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("post_deploy", ROOT / "tools" / "post_deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = (ROOT / "dashboard.py").read_text(encoding="utf-8")
    for key in module.LEGACY_BLOBS:
        assert f'db_manager.read("{key}")' not in source
        assert f"R('{key}')" not in source


def test_dockerignore_keeps_the_runtime_files():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for name in ("ui/", "analytics/", ".streamlit/", "*.toml"):
        assert name not in ignored


def test_requirements_declare_every_third_party_import():
    declared = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    used: set[str] = set()
    for module in APP_MODULES:
        used |= _imports(ROOT / module)
    for name in used & set(THIRD_PARTY):
        assert THIRD_PARTY[name].lower() in declared, name


def test_streamlit_version_supports_lazy_tabs():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    major, minor = re.search(r"streamlit>=(\d+)\.(\d+)", text).groups()
    assert (int(major), int(minor)) >= (1, 57)
