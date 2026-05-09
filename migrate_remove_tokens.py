#!/usr/bin/env python3
"""Migration: Remove device_key and refresh_token columns from authorized_users table."""
import asyncio
import sys

async def main():
    try:
        from db.engine import get_session

        async with get_session() as db_session:
            # SQLite doesn't support DROP COLUMN directly
            # We need to recreate the table
            await db_session.execute("""
                CREATE TABLE IF NOT EXISTS authorized_users_new (
                    chat_id INTEGER NOT NULL PRIMARY KEY,
                    authorized_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Copy data from old table
            await db_session.execute("""
                INSERT INTO authorized_users_new (chat_id, authorized_at)
                SELECT chat_id, authorized_at FROM authorized_users
            """)

            # Drop old table
            await db_session.execute("DROP TABLE authorized_users")

            # Rename new table
            await db_session.execute("""
                ALTER TABLE authorized_users_new RENAME TO authorized_users
            """)

            await db_session.commit()

            print("✅ Migration completed successfully!")
            print("Removed device_key and refresh_token columns from authorized_users table")

    except Exception as exc:
        print(f"❌ Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
