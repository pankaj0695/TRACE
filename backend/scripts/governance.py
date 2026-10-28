"""Data-governance operations without starting the server.

Usage (from backend/):
    python -m scripts.governance quality                 # dataset quality + catalogue coverage (exit 1 on failure)
    python -m scripts.governance retention [--execute]   # apply retention periods (dry-run by default)
    python -m scripts.governance export  --user-id ID --reference TICKET
    python -m scripts.governance erase   --user-id ID --reference TICKET [--execute]
Run `python -m scripts.build_dataset` afterwards to rebuild from raw dumps; erased subjects stay suppressed.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.container import DatasetMissing, _missing_message  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.data.database import Database  # noqa: E402
from app.governance.services import GovernanceServices  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["quality", "retention", "export", "erase"])
    ap.add_argument("--user-id")
    ap.add_argument("--reference")
    ap.add_argument("--execute", action="store_true", help="apply changes (otherwise dry-run)")
    args = ap.parse_args()
    settings = get_settings()
    if not settings.db_path.is_file():
        raise DatasetMissing(_missing_message(settings))
    db = Database(settings.db_path)
    db.init_schema()
    gov = GovernanceServices(settings, db)

    if args.command == "quality":
        report = gov.quality.report()
        print(json.dumps(report, indent=2, default=str))
        return 1 if report["overall"] == "fail" else 0
    if args.command == "retention":
        print(json.dumps(gov.retention.purge(dry_run=not args.execute), indent=2))
        return 0
    if not (args.user_id and args.reference):
        ap.error("--user-id and --reference are required")
    if args.command == "export":
        print(json.dumps(gov.rights.export(args.user_id), indent=2, default=str))
    else:
        print(json.dumps(gov.rights.erase(args.user_id, args.reference, "cli", dry_run=not args.execute), indent=2))
        if args.execute:
            print("NOTE: restart the API so the in-memory graph and text index drop this subject.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
