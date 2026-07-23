from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema.validators import validator_for
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".stage0",
    ".venv",
    "__pycache__",
}
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
PROHIBITED_DEPENDENCIES = {"playwright", "selenium"}


def repository_files() -> set[str]:
    files: set[str] = set()
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        if path.name == ".env":
            continue
        files.add(path.relative_to(ROOT).as_posix())
    return files


def load_data(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        if path.suffix == ".json":
            return json.load(stream)
        return yaml.safe_load(stream)


def validate_structured_files(errors: list[str]) -> None:
    for relative in sorted(repository_files()):
        path = ROOT / relative
        if path.suffix not in {".json", ".yaml", ".yml"}:
            continue
        try:
            document = load_data(path)
        except Exception as exc:  # noqa: BLE001 - aggregate validator diagnostics
            errors.append(f"{relative}: parse failed: {exc}")
            continue
        if relative.startswith("specs/events/") and relative.endswith(".schema.json"):
            try:
                validator_for(document).check_schema(document)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{relative}: invalid JSON Schema: {exc}")
        if relative == "specs/openapi.yaml":
            try:
                validate(document)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{relative}: invalid OpenAPI: {exc}")


def validate_markdown_links(errors: list[str]) -> None:
    for relative in sorted(repository_files()):
        if not relative.endswith(".md"):
            continue
        path = ROOT / relative
        content = path.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(content):
            target = target.strip().strip("<>")
            if (
                not target
                or target.startswith(("#", "http://", "https://", "mailto:"))
                or "://" in target
            ):
                continue
            path_part = target.split("#", 1)[0]
            if not (path.parent / path_part).resolve().exists():
                errors.append(f"{relative}: broken link: {target}")


def validate_manifest(errors: list[str]) -> None:
    manifest = load_data(ROOT / "manifest.json")
    listed = set(manifest["files"])
    actual = repository_files()
    missing = listed - actual
    unlisted = actual - listed
    if missing:
        errors.append(f"manifest lists missing files: {sorted(missing)}")
    if unlisted:
        errors.append(f"manifest omits files: {sorted(unlisted)}")


def validate_dependencies(errors: list[str]) -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    for dependency in PROHIBITED_DEPENDENCIES:
        if re.search(rf'["\']{re.escape(dependency)}(?:[<>=~!\[]|["\'])', pyproject):
            errors.append(f"prohibited dependency declared: {dependency}")


def main() -> int:
    errors: list[str] = []
    validate_structured_files(errors)
    validate_markdown_links(errors)
    validate_manifest(errors)
    validate_dependencies(errors)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Repository validation passed: JSON/YAML/OpenAPI/schemas/links/manifest/dependencies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
