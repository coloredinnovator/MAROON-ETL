#!/usr/bin/env python3
"""
Build the rotation register for MAROON-ETL.

"Rotate from the lake": credential-bearing files are ingested like anything
else. This scan does not block them — it reads what landed and produces the
worklist of credentials to rotate, so the lake itself tells you what needs
rotating and where to rotate it.

Reads the `rotation_register` section of ingest_rules.yaml and writes
manifest/rotation-register.json.

Exit code is 0 on findings — a credential found is a work item, not a failure.
Exits non-zero only on a real error (bad rules file, unwritable output).

Usage:
    python tools/build_rotation_register.py                 # scan lake/
    python tools/build_rotation_register.py path [path ...]
    python tools/build_rotation_register.py --print         # show worklist
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES = REPO_ROOT / "ingest_rules.yaml"


def load_rules(path: Path) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def compile_detectors(cfg: dict) -> list[tuple[str, re.Pattern, str]]:
    """(name, compiled regex, where-to-rotate) for each configured detector."""
    out = []
    for entry in cfg.get("detect", []) or []:
        out.append((
            entry["name"],
            re.compile(entry["regex"]),
            entry.get("rotate_at", ""),
        ))
    return out


def is_known_credential_file(path: Path, cfg: dict) -> bool:
    for glob in cfg.get("known_credential_files", []) or []:
        if fnmatch.fnmatch(path.name, glob):
            return True
    return False


def iter_files(targets: list[Path]):
    for target in targets:
        if target.is_file():
            yield target
        elif target.is_dir():
            for path in sorted(target.rglob("*")):
                if path.is_file():
                    yield path


def scan(targets: list[Path], cfg: dict) -> tuple[list[dict], int]:
    detectors = compile_detectors(cfg)
    record_location = cfg.get("record_location", True)
    entries: list[dict] = []
    scanned = 0

    for path in iter_files(targets):
        scanned += 1
        try:
            rel = str(path.relative_to(REPO_ROOT))
        except ValueError:
            rel = str(path)

        if is_known_credential_file(path, cfg):
            entries.append({
                "file": rel,
                "credential": "known_credential_file",
                "rotate_at": "Identify each credential inside, then rotate at its provider",
                "priority": "high",
                "status": "pending",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for name, pattern, rotate_at in detectors:
            for match in pattern.finditer(text):
                entry = {
                    "file": rel,
                    "credential": name,
                    "rotate_at": rotate_at,
                    "priority": "high",
                    "status": "pending",
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                }
                if record_location:
                    entry["line"] = text.count("\n", 0, match.start()) + 1
                entries.append(entry)

    return entries, scanned


def seed_known_vault_credentials(cfg: dict) -> list[dict]:
    """Seed the worklist with vault locations known to carry credentials.

    These may not be ingested yet, but they are known rotation work — the
    register is the worklist, so it should name them from the start rather
    than only once the object lands.
    """
    seeded = []
    for path_glob in cfg.get("known_credential_paths", []) or []:
        seeded.append({
            "file": path_glob,
            "credential": "known_credential_location",
            "rotate_at": "Identify each credential inside, then rotate at its provider",
            "priority": "high",
            "status": "pending",
            "source": "vault_known",
            "note": (
                "Drive vault location known to carry live credentials "
                "(.env, kiro_oauth_config.json). Folder is link-shared."
            ),
            "detected_at": datetime.now(timezone.utc).isoformat(),
        })
    return seeded


def merge_existing(entries: list[dict], register_path: Path) -> list[dict]:
    """Carry forward status on entries already marked rotated."""
    if not register_path.exists():
        return entries
    try:
        prev = json.load(open(register_path)).get("entries", [])
    except (json.JSONDecodeError, OSError):
        return entries

    done = {
        (e.get("file"), e.get("credential"), e.get("line"))
        for e in prev
        if e.get("status") == "rotated"
    }
    for e in entries:
        if (e.get("file"), e.get("credential"), e.get("line")) in done:
            e["status"] = "rotated"
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="files or directories (default: lake/)")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--print", dest="show", action="store_true",
                        help="print the worklist instead of only writing it")
    args = parser.parse_args()

    rules = load_rules(args.rules)
    cfg = rules.get("rotation_register") or {}
    if not cfg.get("enabled", True):
        print("rotation_register disabled in ingest_rules.yaml")
        return 0

    targets = [Path(p) for p in args.paths] if args.paths else [REPO_ROOT / "lake"]
    targets = [t for t in targets if t.exists()]
    if not targets:
        print("build_rotation_register: nothing to scan", file=sys.stderr)
        return 0

    entries, scanned = scan(targets, cfg)
    entries = seed_known_vault_credentials(cfg) + entries

    register_path = REPO_ROOT / cfg.get("path", "manifest/rotation-register.json")
    register_path.parent.mkdir(parents=True, exist_ok=True)
    entries = merge_existing(entries, register_path)

    pending = [e for e in entries if e["status"] == "pending"]
    register = {
        "register_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "rotate_from_lake",
        "note": (
            "Credential-bearing files are ingested normally. This register is "
            "the rotation worklist derived from what landed in the lake. "
            "Rotate each entry at its provider, then set status to 'rotated'."
        ),
        "files_scanned": scanned,
        "total_entries": len(entries),
        "pending": len(pending),
        "rotated": len(entries) - len(pending),
        "entries": entries,
    }
    with open(register_path, "w") as fh:
        json.dump(register, fh, indent=2)

    print(f"rotation register: {len(entries)} entr{'y' if len(entries)==1 else 'ies'}, "
          f"{len(pending)} pending  ({scanned} files scanned)")
    print(f"  -> {register_path.relative_to(REPO_ROOT)}")

    if args.show and pending:
        print("\nWorklist:")
        for e in pending:
            loc = f":{e['line']}" if "line" in e else ""
            print(f"  [{e['priority']}] {e['file']}{loc}")
            print(f"      {e['credential']} — rotate at: {e['rotate_at']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
