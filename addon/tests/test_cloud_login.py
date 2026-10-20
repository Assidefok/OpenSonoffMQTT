"""Regression test for the eWeLink cloud ``login`` signature.

The Home Assistant config entry carries ``mqtt_*`` wizard fields, so
``XRegistryCloud.login`` must swallow unknown keyword arguments (``**_extra``)
instead of raising::

    TypeError: XRegistryCloud.login() got an unexpected keyword argument 'mqtt_enabled'

The check is done without network access and without requiring the optional
``aiohttp`` dependency: an AST check always runs, and a functional check
(``inspect.signature().bind``) runs when the module can be loaded.
"""

import ast
import importlib.util
import inspect
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Both copies of the registry: the HA integration and the add-on bridge.
CLOUD_FILES = {
    "integration": REPO / "custom_components/sonoff/core/ewelink/cloud.py",
    "addon": REPO / "addon/app/ewelink/cloud.py",
}

# Fields the config entry passes to login() that are not login arguments.
EXTRA_LOGIN_KWARGS = {
    "mqtt_enabled": True,
    "mqtt_host": "broker.local",
    "mqtt_port": 1883,
}


def _login_function(path: Path) -> ast.AsyncFunctionDef:
    """Return the ``login`` AST node of ``XRegistryCloud`` in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "XRegistryCloud":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "login":
                    return item
    pytest.fail(f"{path} does not declare XRegistryCloud.login()")


@pytest.mark.parametrize("copy", CLOUD_FILES, ids=list(CLOUD_FILES))
def test_login_has_var_keyword_ast(copy: str) -> None:
    """``login`` must accept ``**kwargs`` so mqtt_* config fields are ignored."""
    path = CLOUD_FILES[copy]
    login = _login_function(path)

    assert login.args.kwarg is not None, (
        f"{copy} copy ({path}): XRegistryCloud.login() has no **kwargs. "
        "The HA config entry passes mqtt_* fields, so add `**_extra` to the "
        "signature or it fails with 'unexpected keyword argument'."
    )


def _load_cloud(path: Path, alias: str):
    """Import ``cloud.py`` as a package submodule, isolated from the real ones."""
    package = types.ModuleType(alias)
    package.__path__ = [str(path.parent)]
    sys.modules[alias] = package
    spec = importlib.util.spec_from_file_location(f"{alias}.cloud", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
        sys.modules.pop(alias, None)
    return module


@pytest.mark.parametrize("copy", CLOUD_FILES, ids=list(CLOUD_FILES))
def test_login_binds_mqtt_kwargs(copy: str) -> None:
    """The real signature must accept mqtt_* kwargs (the old code raised)."""
    path = CLOUD_FILES[copy]
    try:
        module = _load_cloud(path, f"_login_probe_{copy}")
    except ImportError as ex:  # aiohttp is optional in a bare dev env
        pytest.skip(f"cannot import {path}: {ex}")

    login = module.XRegistryCloud.login
    signature = inspect.signature(login)

    assert any(
        param.kind is inspect.Parameter.VAR_KEYWORD
        for param in signature.parameters.values()
    ), f"{copy} copy ({path}): XRegistryCloud.login{signature} lacks **kwargs"

    try:
        signature.bind(None, "user@example.com", "secret", **EXTRA_LOGIN_KWARGS)
    except TypeError as ex:
        pytest.fail(
            f"{copy} copy ({path}): login{signature} rejects the config entry "
            f"mqtt_* fields: {ex}"
        )
