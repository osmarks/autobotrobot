import aiosqlite
import logging

migrations = [
"""
CREATE TABLE deleted_items (
    id INTEGER PRIMARY KEY,
    timestamp INTEGER NOT NULL,
    item TEXT NOT NULL
);
""",
"""
CREATE INDEX deleted_items_timestamps ON deleted_items(timestamp);
""",
"""
CREATE TABLE reminders (
    id INTEGER PRIMARY KEY,
    remind_timestamp INTEGER NOT NULL,
    created_timestamp INTEGER NOT NULL,
    reminder TEXT NOT NULL,
    expired INTEGER NOT NULL,
    extra TEXT NOT NULL
);
"""
]

async def init(db_path):
    db = await aiosqlite.connect(db_path)

    version = (await (await db.execute("PRAGMA user_version")).fetchone())[0]
    for i in range(version, len(migrations)):
        await db.executescript(migrations[i])
        # Normally this would be a terrible idea because of SQL injection.
        # However, in this case there is not an obvious alternative (the parameter-based way apparently doesn't work)
        # and i + 1 will always be an integer anyway
        await db.execute(f"PRAGMA user_version = {i + 1}")
        await db.commit()
        logging.info(f"Migrated DB to schema {i + 1}")

    return db