from __future__ import annotations

import argparse

from app.core.database import SessionLocal
from app.services.news_kg_service import backfill_news_to_kg


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill industry news into Neo4j knowledge graph")
    parser.add_argument("--limit", type=int, default=500, help="Max number of latest news rows to process")
    parser.add_argument("--source-name", type=str, default="", help="Optional source_name contains filter")
    parser.add_argument("--time-window", type=str, default="1m", help="1d|1w|1m|1q|1y|3y|5y|all")
    parser.add_argument("--force", action="store_true", help="Force re-extract even if same extract version already succeeded")
    parser.add_argument("--extract-version", type=str, default="", help="Override extract version marker")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        stats = backfill_news_to_kg(
            db,
            limit=args.limit,
            source_name=args.source_name or None,
            time_window=args.time_window,
            force=bool(args.force),
            extract_version=args.extract_version or "",
        )
        print(stats)
    finally:
        db.close()


if __name__ == "__main__":
    main()
