#!/usr/bin/env python3
"""
Secret scanner for the MAROON-ETL lake.

Enforces the `scan` and `deny` sections of ingest_rules.yaml against files
staged for the lake. Exits non-zero on any hit so it can gate CI or a
pre-commit hook.

The Directive 8 SECURITY.md guardrail is "zero secrets in GitHub". Git history
makes a leaked credential effectively permanent, so this runs before content
lands rather than after.

Usage:
    python tools/scan_secrets.py [path ...]      # defaults to lake/
    python tools/scan_secrets.py --rules custom_rules.yaml
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES = REPO_ROOT / "ingest_rules.yaml"


def load_rules(rules_path: Path) -> dict:
    with open(rules_path) as fh:
        return yaml.safe_load(fh)


def compile_patterns(rules: dict) -> list[tuple[str, re.Pattern]]:
    scan = rules.get("scan", {})
    if not scan.get("enabled", True):
        return []
    compiled = []
    for entry in scan.get("patterns", []):
        compiled.append((entry["name"], re.compile(entry["regex"])))
    return compiled


def denied_globs(rules: dict) -> list[tuple[str, str]]:
    """Flatten deny.* filename globs into (glob, category) pairs."""
    out = []
    for category, spec in rules.get("deny", {}).items():
        for glob in spec.get("match_filenames", []) or []:
            out.append((glob, category))
    return out


def iter_files(targets: list[Path]):
    for target in targets:
        if target.is_file():
            yield target
        elif target.is_dir():
            for path in sorted(target.rglob("*")):
                if path.is_file():
                    yield path


def scan(targets: list[Path], rules: dict) -> list[str]:
    patterns = compile_patterns(rules)
    globs = denied_globs(rules)
    findings: list[str] = []

    for path in iter_files(targets):
        rel = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path

        # Filename-level denials
        for glob, category in globs:
            if fnmatch.fnmatch(path.name, glob):
                findings.append(f"{rel}: denied filename matches {glob!r} (deny.{category})")

        # Content-level scanning; skip anything that is not decodable text
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for name, pattern in patterns:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                findings.append(f"{rel}:{line_no}: possible {name}")

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=None,
                        help="files or directories to scan (default: lake/)")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES,
                        help="path to ingest_rules.yaml")
    args = parser.parse_args()

    targets = [Path(p) for p in args.paths] if args.paths else [REPO_ROOT / "lake"]
    targets = [t for t in targets if t.exists()]
    if not targets:
        print("scan_secrets: nothing to scan", file=sys.stderr)
        return 0

    rules = load_rules(args.rules)
    findings = scan(targets, rules)

    if findings:
        print(f"scan_secrets: {len(findings)} finding(s)\n", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        if rules.get("scan", {}).get("fail_run_on_hit", True):
            print("\nRun failed. Nothing was ingested.", file=sys.stderr)
            return 1

    print(f"scan_secrets: clean ({sum(1 for _ in iter_files(targets))} files scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
