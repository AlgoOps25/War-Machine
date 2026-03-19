#!/usr/bin/env python3
"""
fix_print_to_logger.py
======================
Scans every .py file under app/ and utils/ and:

  1. Finds all bare  print("[TAG] ✅ ...")  lines (module-level startup prints).
  2. Removes them (they become logger.info calls, or are simply dropped if
     they are pure banner/init messages that already appear in logger.info).
  3. Converts any remaining  print("[TAG] ✅ ...")  *inside functions* to
       logger.info("[TAG] ...")   (strips the ✅ emoji).
  4. Ensures  import logging  and  logger = logging.getLogger(__name__)
     appear near the top of every file that was modified.

Run from the repo root:
    python scripts/fix_print_to_logger.py

Flags:
    --dry-run   Print what would change without writing files.
    --verbose   Show every matched line.

Safety:
    - Only touches files in app/ and utils/.
    - Skips __pycache__, .pyc, and files already fully migrated.
    - Creates a  .fix_print_backup/  folder with originals before modifying.
    - Writes a  fix_print_report.txt  summary after running.
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

# Matches:  print("[SOME-TAG] ✅ any text")   (full-line, any indentation)
# Also matches f-string variant but those are handled separately below.
PRINT_CHECKMARK_RE = re.compile(
    r'^(?P<indent>[ \t]*)print\(\s*(?P<q>["\'])(?P<tag>\[[\w\-]+\])\s*✅\s*(?P<msg>[^"\']*)\3\s*\)\s*$'
)

# Matches f-string variant:  print(f"[TAG] ✅ {var} ...")
PRINT_FSTRING_RE = re.compile(
    r'^(?P<indent>[ \t]*)print\(\s*f(?P<q>["\'])(?P<tag>\[[\w\-]+\])\s*✅\s*(?P<msg>[^"\']*)\3\s*\)\s*$'
)

IMPORT_LOGGING      = "import logging\n"
LOGGER_GETLOGGER    = "logger = logging.getLogger(__name__)\n"

# Already-handled signal: if file already has getLogger it's done
ALREADY_HAS_LOGGER  = re.compile(r'logger\s*=\s*logging\.getLogger')
ALREADY_HAS_IMPORT  = re.compile(r'^import logging\s*$', re.MULTILINE)


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
    rel     = path.relative_to(REPO_ROOT)
    dest    = BACKUP_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)


def insert_logging_header(lines: list[str]) -> list[str]:
    """
    Insert  import logging  and  logger = logging.getLogger(__name__)
    after the last top-level import block, but before the first
    non-import, non-blank, non-comment, non-docstring line.
    """
    # Find insertion point: after last contiguous import line
    insert_at = 0
    in_docstring = False
    docstring_char = None

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track triple-quoted docstrings at top of file
        if not in_docstring and (stripped.startswith('"""') or stripped.startswith("'''")):
            in_docstring = True
            docstring_char = stripped[:3]
            if stripped.count(docstring_char) >= 2 and len(stripped) > 3:
                in_docstring = False  # single-line docstring
            continue
        if in_docstring:
            if docstring_char in stripped:
                in_docstring = False
            continue

        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_at = i + 1
        elif stripped == "" or stripped.startswith("#"):
            continue
        else:
            break  # hit real code

    result = lines[:insert_at]

    # Add import logging if not present
    has_import = any(re.match(r'^import logging\s*$', l) for l in lines)
    has_logger = any(ALREADY_HAS_LOGGER.search(l) for l in lines)

    if not has_import:
        result.append(IMPORT_LOGGING)
    if not has_logger:
        result.append(LOGGER_GETLOGGER)

    result.extend(lines[insert_at:])
    return result


def convert_line(line: str, verbose: bool) -> tuple[str | None, bool]:
    """
    Returns (new_line_or_None, was_changed).
    None means delete the line entirely (module-level init print).
    """
    # Plain string version
    m = PRINT_CHECKMARK_RE.match(line)
    if m:
        indent = m.group("indent")
        tag    = m.group("tag")
        msg    = m.group("msg").strip()
        # Module-level (no indent) → drop entirely
        if indent == "":
            if verbose:
                print(f"  DROP (module-level): {line.rstrip()}")
            return None, True
        # Inside function → convert to logger.info
        new = f'{indent}logger.info("{tag} {msg}")\n'
        if verbose:
            print(f"  CONVERT: {line.rstrip()}")
            print(f"       TO: {new.rstrip()}")
        return new, True

    # f-string version
    m = PRINT_FSTRING_RE.match(line)
    if m:
        indent = m.group("indent")
        tag    = m.group("tag")
        msg    = m.group("msg").strip()
        if indent == "":
            if verbose:
                print(f"  DROP (module-level fstr): {line.rstrip()}")
            return None, True
        new = f'{indent}logger.info(f"{tag} {msg}")\n'
        if verbose:
            print(f"  CONVERT: {line.rstrip()}")
            print(f"       TO: {new.rstrip()}")
        return new, True

    return line, False


def process_file(path: Path, dry_run: bool, verbose: bool) -> dict:
    result = {
        "path":     str(path.relative_to(REPO_ROOT)),
        "changed":  False,
        "dropped":  0,
        "converted": 0,
        "logger_added": False,
    }

    original = path.read_text(encoding="utf-8")
    lines    = original.splitlines(keepends=True)

    # Quick pre-check: does this file have any ✅ prints?
    if "✅" not in original:
        return result

    if verbose:
        print(f"\n--- {result['path']}")

    new_lines = []
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
    needs_header = (
        not ALREADY_HAS_IMPORT.search("".join(new_lines)) or
        not ALREADY_HAS_LOGGER.search("".join(new_lines))
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
    parser = argparse.ArgumentParser(description="Convert ✅ print() calls to logger.info()")
    parser.add_argument("--dry-run",  action="store_true", help="Preview changes, don't write")
    parser.add_argument("--verbose",  action="store_true", help="Show each matched line")
    args = parser.parse_args()

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Scanning {[str(d) for d in SCAN_DIRS]} ...")
    print(f"Backup dir: {BACKUP_DIR}\n")

    results   = []
    total_files  = 0
    changed_files = 0

    for py_file in sorted(find_py_files(SCAN_DIRS)):
        total_files += 1
        r = process_file(py_file, dry_run=args.dry_run, verbose=args.verbose)
        results.append(r)
        if r["changed"]:
            changed_files += 1
            status = "[DRY]" if args.dry_run else "[FIXED]"
            print(
                f"{status} {r['path']:60s}  "
                f"dropped={r['dropped']}  converted={r['converted']}  "
                f"{'+ logger header' if r['logger_added'] else ''}"
            )

    # Write report
    report_lines = [
        f"fix_print_to_logger.py — Run at {datetime.now().isoformat()}",
        f"{'DRY RUN — no files written' if args.dry_run else 'FILES MODIFIED'}",
        f"",
        f"Total .py files scanned : {total_files}",
        f"Files changed           : {changed_files}",
        f"",
        "CHANGED FILES:",
    ]
    for r in results:
        if r["changed"]:
            report_lines.append(
                f"  {r['path']}  "
                f"(dropped={r['dropped']}, converted={r['converted']}, "
                f"logger_added={r['logger_added']})"
            )
    report_lines.append("")
    report_lines.append("SKIPPED (no ✅ prints found):")
    for r in results:
        if not r["changed"]:
            report_lines.append(f"  {r['path']}")

    report_text = "\n".join(report_lines) + "\n"

    if not args.dry_run:
        REPORT_FILE.write_text(report_text, encoding="utf-8")
        print(f"\nReport written to: {REPORT_FILE}")
        print(f"Originals backed up to: {BACKUP_DIR}/")
    else:
        print("\n--- REPORT (dry run, not written to disk) ---")
        print(report_text)

    print(f"\nDone. {changed_files}/{total_files} files {'would be' if args.dry_run else 'were'} modified.")


if __name__ == "__main__":
    main()
