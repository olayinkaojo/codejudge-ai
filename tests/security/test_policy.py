"""Guard the architectural boundary: control-plane modules cannot launch submission interpreters."""

import ast
from pathlib import Path

import pytest


def forbidden_calls(source):
    tree = ast.parse(source)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            )
            if any(name == "subprocess" for name in names):
                violations.append("subprocess")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "compile"}:
                violations.append(node.func.id)
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
                and node.func.attr in {"system", "popen", "fork", "execve", "execv", "spawnv"}
            ):
                violations.append("os." + node.func.attr)
    return violations


@pytest.mark.parametrize("path", ["app/main.py", "app/worker.py", "runner/service.py", "runner/isolation.py"])
def test_execution_only_belongs_to_the_isolated_guest(path):
    assert forbidden_calls(Path(path).read_text()) == []


def test_boundary_guard_detects_a_native_execution_regression():
    assert forbidden_calls("import subprocess\nexec(source)\nos.system(source)") == [
        "subprocess",
        "exec",
        "os.system",
    ]
