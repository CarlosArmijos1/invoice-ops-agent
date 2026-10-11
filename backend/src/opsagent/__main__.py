"""Operator CLI.

python -m opsagent seed                    # load vendors, POs and payments
python -m opsagent ingest ../data/synthetic/invoices --copy
python -m opsagent run                     # process everything pending, once
python -m opsagent report --date 2026-10-10
"""

import argparse
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path

from opsagent.container import build_container
from opsagent.infra.seed import load_catalog, seed_catalog
from opsagent.services.ingestion import ingest_folder
from opsagent.services.reporting import generate_daily_report
from opsagent.settings import REPO_ROOT

DEFAULT_CATALOG = REPO_ROOT / "data" / "synthetic" / "catalog.json"


def main() -> None:
    parser = argparse.ArgumentParser(prog="opsagent", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="load the synthetic catalog")
    seed.add_argument("catalog", type=Path, nargs="?", default=DEFAULT_CATALOG)

    ingest = sub.add_parser("ingest", help="ingest every invoice file in a folder")
    ingest.add_argument("folder", type=Path)
    ingest.add_argument(
        "--copy", action="store_true", help="work on a copy and leave the folder untouched"
    )

    run = sub.add_parser("run", help="process pending invoices once")
    run.add_argument("--limit", type=int, default=500)

    report = sub.add_parser("report", help="generate (or refresh) the daily report")
    report.add_argument("--date", type=date.fromisoformat, default=None)

    args = parser.parse_args()
    container = build_container(checkpoints=args.command == "run")
    try:
        if args.command == "seed":
            with container.session_factory() as session, session.begin():
                print(json.dumps(seed_catalog(session, load_catalog(args.catalog))))
        elif args.command == "ingest":
            folder = args.folder
            if args.copy:
                folder = Path(tempfile.mkdtemp(prefix="opsagent-inbox-"))
                for path in args.folder.iterdir():
                    if path.is_file():
                        shutil.copy2(path, folder / path.name)
            results = ingest_folder(container.session_factory, folder)
            print(json.dumps({"received": len(results), "new": sum(r.created for r in results)}))
        elif args.command == "run":
            summary = container.processor.process_pending(trigger="cli", limit=args.limit)
            print(json.dumps(summary.as_dict(), indent=2))
        elif args.command == "report":
            with container.session_factory() as session, session.begin():
                print(generate_daily_report(session, args.date).markdown)
    finally:
        container.close()


if __name__ == "__main__":
    main()
