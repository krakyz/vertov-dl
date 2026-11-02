"""Export a clean local source repository without runtime data or dependencies."""

import shutil
import sys
from pathlib import Path

source = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else source.parent / "vertov-dl"
if (
    target.exists()
    or target == source
    or source.is_relative_to(target)
    or target.is_relative_to(source)
):
    raise SystemExit("Destination must be a new directory outside the source repository")
files = [
    ".dockerignore",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "CHANGELOG.md",
    "Dockerfile",
    "README.md",
    "LICENSE",
    "NOTICE.md",
    "THIRD_PARTY_NOTICES.md",
    "compose.yaml",
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "requirements.lock",
]
folders = [".github", "apps/api", "apps/web", "docs", "scripts", "tests", "LICENSES"]
skipped = {
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".data",
    "secrets",
}
target.mkdir(parents=True)
for name in files:
    shutil.copyfile(source / name, target / name)
for name in folders:
    for path in (source / name).rglob("*"):
        relative = path.relative_to(source)
        if (
            path.is_symlink()
            or not path.is_file()
            or any(part in skipped or part.endswith(".egg-info") for part in relative.parts)
        ):
            continue
        if (
            path.suffix in {".pyc", ".png", ".sqlite3", ".part"}
            or path.name.startswith(".env")
            or path.name.endswith(".cookies.txt")
        ):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
name = "deploy/compose.home.example.yaml"
(target / "deploy").mkdir(exist_ok=True)
shutil.copyfile(source / name, target / name)
print(f"Prepared {target}")
