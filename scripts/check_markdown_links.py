#!/usr/bin/env python3
"""Validate local markdown links in project docs.

Checks markdown files in repository root and docs/ for broken relative links.
External URLs (http/https/mailto) and in-page anchors are ignored.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_GLOBS = ["*.md", "docs/**/*.md"]
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def iter_markdown_files() -> list[Path]:
    files: list[Path] = []
    for pattern in MARKDOWN_GLOBS:
        files.extend(ROOT.glob(pattern))
    return sorted({path.resolve() for path in files if path.is_file()})


def normalize_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and target.endswith(">") and len(target) >= 2:
        target = target[1:-1].strip()
    return target


def is_external(target: str) -> bool:
    lower = target.lower()
    return lower.startswith(("http://", "https://", "mailto:"))


def resolve_target(md_file: Path, target: str) -> Path:
    clean = target.split("#", 1)[0].strip()
    if clean.startswith("/"):
        return (ROOT / clean.lstrip("/")).resolve()
    return (md_file.parent / clean).resolve()


def main() -> int:
    broken: list[str] = []

    for md_file in iter_markdown_files():
        text = md_file.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            raw_target = normalize_target(match.group(1))
            if not raw_target or raw_target.startswith("#") or is_external(raw_target):
                continue

            target_path = resolve_target(md_file, raw_target)
            if not target_path.exists():
                rel_file = md_file.relative_to(ROOT).as_posix()
                broken.append(f"{rel_file}: {raw_target}")

    if broken:
        print("Broken markdown links found:")
        for item in broken:
            print(f"- {item}")
        return 1

    print("Markdown link check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
