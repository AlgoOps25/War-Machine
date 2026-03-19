#!/usr/bin/env python3
"""
fix_print_to_logger.py
======================
Scans every .py file under app/ and utils/ and:

  1. Finds ALL bare print() calls  (no emoji filter — handles flush=True banners,
     f-strings, plain strings, separator lines, etc.)
  2. Module-level prints (indent == '') are DROPPED entirely.
  3. Function-level prints (indented) are converted to logger.info / logger.debug.
  4. Ensures  import logging  and  logger = logging.getLogger(__name__)
     are present in every file that is modified.

Special cases:
  - print("=" * N)  separators                -> dropped (module-level) / logger.debug (fn)
  - print("[TAG] msg", flush=True)            -> logger.info("[TAG] msg")
  - print(f"[TAG] {var}", flush=True)         -> logger.info(f"[TAG] {var}")
  - print(get_eod_report())                   -> logger.info(get_eod_report())   (kept as-is inner expr)
  - print(learning_engine.generate_...())    -> logger.info(...)
  - traceback.print_exc()                     -> SKIPPED (not a bare print)

Run from repo root:
    python scripts/fix_print_to_logger.py [--dry-run] [--verbose]

Safety:
  - Only touches app/ and utils/
  - Backs up originals to .fix_print_backup/
  - Writes fix_print_report.txt summary
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).parent.parent
SCAN_DIRS   = [REPO_ROOT / "app", REPO_ROOT / "utils"]
BACKUP_DIR  = REPO_ROOT / ".fix_print_backup"
REPORT_FILE = REPO_ROOT / "fix_print_report.txt"

# Match any bare print(...) line — single-line only
# Captures: indent, and everything inside the outer print( )
PRINT_LINE_RE = re.compile(
    r'^(?P<indent>[ \t]*)print\((?P<args>.*)\)\s*$'
)

# These print calls should be SKIPPED (they are NOT bare print)
SKIP_PATTERNS = [
    re.compile(r'traceback\.print_exc'),
    re.compile(r'traceback\.print_tb'),
    re.compile(r'pprint\.'),
]

IMPORT_LOGGING   = "import logging\n"
LOGGER_GETLOGGER = "logger = logging.getLogger(__name__)\n"

ALREADY_HAS_LOGGER = re.compile(r'logger\s*=\s*logging\.getLogger')
ALREADY_HAS_IMPORT = re.compile(r'^import logging\s*$', re.MULTILINE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_py_files(dirs):
    for d in dirs:
        if not d.exists():
            continue
        for root, subdirs, files in os.walk(d):
            subdirs[:] = [s for s in subdirs if s != "__pycache__"]
            for f in files:
                if f.endswith(".py"):
                    yield Path(root) / f


def backup(path: Path):
    rel  = path.relative_to(REPO_ROOT)
    dest = BACKUP_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)


def insert_logging_header(lines: list) -> list:
    """Insert import logging + logger = ... after the last import block."""
    insert_at    = 0
    in_docstring = False
    ds_char      = None

    for i, line in enumerate(lines):
        s = line.strip()
        if not in_docstring:
            if s.startswith('"""') or s.startswith("'''"):
                ds_char = s[:3]
                in_docstring = True
                if s.count(ds_char) >= 2 and len(s) > 3:
                    in_docstring = False
                continue
        else:
            if ds_char in s:
                in_docstring = False
            continue

        if s.startswith("import ") or s.startswith("from "):
            insert_at = i + 1
        elif s and not s.startswith("#"):
            break

    result      = lines[:insert_at]
    has_import  = any(re.match(r'^import logging\s*$', l) for l in lines)
    has_logger  = any(ALREADY_HAS_LOGGER.search(l) for l in lines)

    if not has_import:
        result.append(IMPORT_LOGGING)
    if not has_logger:
        result.append(LOGGER_GETLOGGER)

    result.extend(lines[insert_at:])
    return result


def _should_skip(line: str) -> bool:
    for pat in SKIP_PATTERNS:
        if pat.search(line):
            return True
    return False


def _make_logger_call(indent: str, args: str) -> str:
    """
    Convert the inner args of a print() into a logger.info() call.
    Strips flush=True / flush=False keyword argument.
    """
    # Remove flush=True/False (common in scanner.py banners)
    args = re.sub(r',?\s*flush\s*=\s*(True|False)', '', args).strip()
    args = args.rstrip(',')

    # Separator lines like "=" * 60 or "-" * 50 -> logger.debug
    if re.fullmatch(r'["\']([=\-*#~])\1["\']\s*\*\s*\d+', args.strip()):
        return f'{indent}logger.debug({args})\n'

    # Everything else -> logger.info
    return f'{indent}logger.info({args})\n'


def convert_line(line: str, verbose: bool) -> tuple:
    """
    Returns (new_line_or_None, was_changed).
    None  -> delete the line (module-level print).
    str   -> replacement line.
    """
    if _should_skip(line):
        return line, False

    m = PRINT_LINE_RE.match(line)
    if not m:
        return line, False

    indent = m.group("indent")
    args   = m.group("args").strip()

    # Empty print() -> blank logger.info or blank line
    if args == "":
        if indent == "":
            if verbose:
                print(f"  DROP  (module-level empty): {line.rstrip()}")
            return None, True
        new = f'{indent}logger.info("")\n'
        if verbose:
            print(f"  CONV  {line.rstrip()} -> {new.rstrip()}")
        return new, True

    if indent == "":
        # Module-level: drop entirely
        if verbose:
            print(f"  DROP  (module-level): {line.rstrip()}")
        return None, True
    else:
        # Inside a function: convert
        new = _make_logger_call(indent, args)
        if verbose:
            print(f"  CONV  {line.rstrip()}")
            print(f"     -> {new.rstrip()}")
        return new, True


def process_file(path: Path, dry_run: bool, verbose: bool) -> dict:
    result = {
        "path":         str(path.relative_to(REPO_ROOT)),
        "changed":      False,
        "dropped":      0,
        "converted":    0,
        "logger_added": False,
    }

    original = path.read_text(encoding="utf-8")
    lines    = original.splitlines(keepends=True)

    # Quick check: any bare print( in this file?
    if not any(PRINT_LINE_RE.match(l) for l in lines):
        return result

    # Skip files where every print is in a skip pattern
    candidate_lines = [l for l in lines if PRINT_LINE_RE.match(l) and not _should_skip(l)]
    if not candidate_lines:
        return result

    if verbose:
        print(f"\n--- {result['path']}")

    new_lines   = []
    any_changed = False

    for line in lines:
        new_line, changed = convert_line(line, verbose)
        if changed:
            any_changed = True
            if new_line is None:
                result["dropped"] += 1
            else:
                result["converted"] += 1
                new_lines.append(new_line)
        else:
            new_lines.append(line)

    if not any_changed:
        return result

    # Inject logging header if needed
    joined = "".join(new_lines)
    needs_header = (
        not ALREADY_HAS_IMPORT.search(joined) or
        not ALREADY_HAS_LOGGER.search(joined)
    )
    if needs_header:
        new_lines = insert_logging_header(new_lines)
        result["logger_added"] = True

    result["changed"] = True
    new_content = "".join(new_lines)

    if not dry_run:
        backup(path)
        path.write_text(new_content, encoding="utf-8")

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Convert bare print() calls to logger.info()")
    parser.add_argument("--dry-run",  action="store_true", help="Preview only, no writes")
    parser.add_argument("--verbose",  action="store_true", help="Show each matched line")
    args = parser.parse_args()

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Scanning {[str(d) for d in SCAN_DIRS]} ...")
    print(f"Backup dir: {BACKUP_DIR}\n")

    results       = []
    total_files   = 0
    changed_files = 0

    for py_file in sorted(find_py_files(SCAN_DIRS)):
        total_files += 1
        r = process_file(py_file, dry_run=args.dry_run, verbose=args.verbose)
        results.append(r)
        if r["changed"]:
            changed_files += 1
            status = "[DRY]" if args.dry_run else "[FIXED]"
            print(
                f"{status} {r['path']:65s}  "
                f"dropped={r['dropped']}  converted={r['converted']}  "
                f"{'+ logger header' if r['logger_added'] else ''}"
            )

    # Write report
    lines = [
        f"fix_print_to_logger.py — Run at {datetime.now().isoformat()}",
        f"{'DRY RUN — no files written' if args.dry_run else 'FILES MODIFIED'}",
        "",
        f"Total .py files scanned : {total_files}",
        f"Files changed           : {changed_files}",
        "",
        "CHANGED FILES:",
    ]
    for r in results:
        if r["changed"]:
            lines.append(
                f"  {r['path']}  "
                f"(dropped={r['dropped']}, converted={r['converted']}, "
                f"logger_added={r['logger_added']})"
            )
    lines += ["", "SKIPPED (no bare print() found):"]
    for r in results:
        if not r["changed"]:
            lines.append(f"  {r['path']}")

    report = "\n".join(lines) + "\n"

    if not args.dry_run:
        REPORT_FILE.write_text(report, encoding="utf-8")
        print(f"\nReport  : {REPORT_FILE}")
        print(f"Backups : {BACKUP_DIR}/")
    else:
        print("\n--- REPORT (dry run) ---")
        print(report)

    print(f"\nDone. {changed_files}/{total_files} files {'would be' if args.dry_run else 'were'} modified.")


if __name__ == "__main__":
    main()
