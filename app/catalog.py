from pathlib import Path

from contracts.evaluation import Suite

CATALOG = Path(__file__).resolve().parent.parent / "catalog"


def suites():
    # Operator-controlled, versioned files only; no request-derived filesystem paths.
    values = [Suite.model_validate_json(path.read_text()) for path in sorted(CATALOG.glob("*.json"))]
    if len({suite.id for suite in values}) != len(values):
        raise ValueError("duplicate suite IDs")
    return {suite.id: suite for suite in values}
