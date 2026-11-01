"""仓库自洽性检查：配置项、版本号、插件必需文件。

这些内容分布在四个文件里（schema、插件默认值、pyproject、metadata），
任何一处漏改都会造成“面板里有、代码里没有”这类问题，因此用测试守住。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "astrbot_plugin_pcrjjc"


def _schema() -> dict:
    return json.loads((PLUGIN / "_conf_schema.json").read_text(encoding="utf-8"))


def _defaults() -> dict:
    """从 main.py 里取出 DEFAULT_CONFIG（允许引用模块级常量）。"""

    source = (PLUGIN / "main.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    node = None
    for item in tree.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            if item.target.id == "DEFAULT_CONFIG" and item.value is not None:
                node = item.value
                break
        if isinstance(item, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "DEFAULT_CONFIG" for t in item.targets):
                node = item.value
                break
    assert node is not None, "DEFAULT_CONFIG not found"

    namespace = {"DEFAULT_ICON_SOURCE": "https://redive.estertion.win/icon/unit/"}
    code = compile(ast.Expression(node), "<DEFAULT_CONFIG>", "eval")
    return eval(code, {"__builtins__": {}}, namespace)  # noqa: S307 - 输入是本仓库源码


def test_schema_and_defaults_share_the_same_keys():
    schema_keys = set(_schema())
    default_keys = set(_defaults())
    assert schema_keys == default_keys, (
        f"只在 schema 中: {sorted(schema_keys - default_keys)}; "
        f"只在默认值中: {sorted(default_keys - schema_keys)}"
    )


def test_schema_defaults_match_plugin_defaults():
    schema = _schema()
    defaults = _defaults()
    mismatched = {
        key: (spec.get("default"), defaults.get(key))
        for key, spec in schema.items()
        if "default" in spec and spec["default"] != defaults.get(key)
    }
    assert not mismatched, f"默认值不一致: {mismatched}"


def test_versions_are_consistent():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package = (PLUGIN / "pcrjjc" / "__init__.py").read_text(encoding="utf-8")
    metadata = (PLUGIN / "metadata.yaml").read_text(encoding="utf-8")

    package_version = re.search(r'__version__ = "([^"]+)"', package).group(1)
    metadata_version = re.search(r"^version:\s*v?([0-9][^\s]*)", metadata, re.M).group(1)
    assert package_version == metadata_version, (package_version, metadata_version)

    if "dynamic = [\"version\"]" in pyproject:
        assert "path = \"astrbot_plugin_pcrjjc/pcrjjc/__init__.py\"" in pyproject
    else:
        pyproject_version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
        assert pyproject_version == package_version, (pyproject_version, package_version)


def test_plugin_package_contains_required_files():
    for name in ("main.py", "metadata.yaml", "_conf_schema.json", "requirements.txt",
                 "README.md", "CHANGELOG.md", "logo.png"):
        assert (PLUGIN / name).is_file(), f"缺少 {name}"


def test_character_table_is_valid():
    payload = json.loads((PLUGIN / "pcrjjc" / "data" / "characters.json").read_text(encoding="utf-8"))
    chars = payload["characters"]
    assert len(chars) > 300
    ids = [c["id"] for c in chars]
    assert len(set(ids)) == len(ids)
    assert all(100000 <= i <= 999999 for i in ids)
    assert sum(1 for c in chars if c.get("name_lang") == "zh") > 300
