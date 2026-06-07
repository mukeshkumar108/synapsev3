from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import asyncpg

from core.config import get_settings


ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "schema.sql"
EXPECTED_TABLES = (
    "outbox",
    "source_archive",
    "message_buffer",
    "session_summaries",
    "candidates",
    "confirmed_facts",
    "timeline_events",
    "entities",
    "entity_aliases",
    "entity_mentions",
    "entity_links",
    "retrieval_embeddings",
)


def render_schema_sql() -> str:
    dimension = int(os.environ.get("EMBEDDING_DIMENSION", "8"))
    return SCHEMA_PATH.read_text().replace("__EMBEDDING_DIMENSION__", str(dimension))


async def apply_schema() -> None:
    conn = await asyncpg.connect(get_settings().get_database_url())
    try:
        schema_sql = render_schema_sql()
        async with conn.transaction():
            await conn.execute(schema_sql)
    finally:
        await conn.close()


async def verify_tables() -> list[str]:
    conn = await asyncpg.connect(get_settings().get_database_url())
    try:
        rows = await conn.fetch(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
            """
        )
    finally:
        await conn.close()

    existing = {row["table_name"] for row in rows}
    missing = [table for table in EXPECTED_TABLES if table not in existing]
    if missing:
        raise RuntimeError(f"Missing expected tables: {', '.join(missing)}")
    extension = await asyncpg.connect(get_settings().get_database_url())
    try:
        vector_installed = await extension.fetchval(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        )
    finally:
        await extension.close()
    if not vector_installed:
        raise RuntimeError("Missing expected extension: vector")
    return sorted(existing)


async def main(verify_only: bool) -> None:
    if not verify_only:
        await apply_schema()

    tables = await verify_tables()
    print("Schema verification passed.")
    print(f"Tables present: {', '.join(tables)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply Synapse V3 schema.")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip applying schema.sql and only verify expected tables.",
    )
    args = parser.parse_args()
    asyncio.run(main(verify_only=args.verify_only))
