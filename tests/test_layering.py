from __future__ import annotations

import ast
from pathlib import Path


def test_inner_layers_do_not_import_external_parser_or_database_sdks() -> None:
    source_root = Path(__file__).parents[1] / "src" / "stratweb"
    violations: list[str] = []

    for layer in ("domain", "application", "analytics", "temporal"):
        for path in (source_root / layer).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                forbidden_roots = ("demoparser2", "duckdb")
                if any(
                    module == root or module.startswith(f"{root}.")
                    for module in modules
                    for root in forbidden_roots
                ):
                    violations.append(str(path))

    assert not violations, f"External SDK leaked into inner layers: {violations}"
