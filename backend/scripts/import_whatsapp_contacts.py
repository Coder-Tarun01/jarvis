"""Bulk-import WhatsApp name -> number aliases into ``data/whatsapp_aliases.json``.

    cd backend
    python scripts/import_whatsapp_contacts.py --contacts            # Google contacts cache
    python scripts/import_whatsapp_contacts.py --file contacts.csv
    python scripts/import_whatsapp_contacts.py --file - < list.txt   # stdin
    python scripts/import_whatsapp_contacts.py --file list.txt --dry-run

Understands ``Name=+91 98765 43210``, ``Name,+91…``, ``Name<TAB>+91…``,
``Name: +91…``, ``+91… Name``, vCard (``FN``/``TEL``) and JSON.

Nothing is overwritten unless ``--overwrite`` is passed: a name that already
resolves to a different number is reported as a conflict and left untouched, so
the aliases you maintain by hand survive every bulk run.

WhatsApp's own stores cannot be read (the local ``*.db`` files are
SQLCipher-encrypted and the Windows People store is usually empty), which is why
the sources here are the Google contacts cache and exported/pasted lists.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# backend/scripts/import_whatsapp_contacts.py -> backend/  (so `app` imports work)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.errors import ToolError  # noqa: E402
from app.services import whatsapp_import  # noqa: E402


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).expanduser().read_text(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--file",
        "-f",
        action="append",
        default=[],
        metavar="PATH",
        help="list to import ('-' reads stdin); repeatable",
    )
    parser.add_argument("--text", default="", help="inline 'Name=+number' lines")
    parser.add_argument(
        "--contacts",
        action="store_true",
        help="import every contact with a phone number from the Google contacts cache",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace differing numbers")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--limit", type=int, default=0, help="stop after N contacts (0 = all)")
    parser.add_argument("--json", action="store_true", help="machine-readable summary")
    args = parser.parse_args()

    settings = get_settings()
    chunks = [_read(path) for path in args.file]
    if args.text:
        chunks.append(args.text)
    text = "\n".join(chunk for chunk in chunks if chunk.strip())

    if not text.strip() and not args.contacts:
        parser.error("nothing to import — pass --contacts, --file PATH or --text 'Name=+number'")
    if not text.strip() and args.file:
        print("those files held no text", file=sys.stderr)
        return 1

    try:
        summary = whatsapp_import.run(
            settings,
            text=text,
            source="auto" if text.strip() else "contacts",
            overwrite=args.overwrite,
            dry_run=args.dry_run,
            limit=args.limit,
        )
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary["path"] = str(settings.whatsapp_aliases_path)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0

    print(summary["message"])
    print(f"  alias file : {summary['path']}")
    print(f"  parsed     : {summary['parsed']} pair(s) from {summary['source']}")
    print(
        f"  added      : {summary['added']}   updated: {summary['updated']}   "
        f"unchanged: {summary['unchanged']}   total: {summary['total']}"
    )
    for sample in summary["samples"]:
        print(f"  + {sample['name']} -> {sample['number']}")
    for conflict in summary["conflicts"]:
        print(
            f"  ! {conflict['name']}: kept {conflict['kept']}, ignored {conflict['ignored']}",
            file=sys.stderr,
        )
    for bad in summary["invalid"]:
        print(f"  ! skipped {bad.get('name', '?')}: {bad.get('reason', 'unusable')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
