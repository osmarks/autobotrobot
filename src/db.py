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
""",
"""
CREATE TABLE telephone_config (
    id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL UNIQUE,
    webhook TEXT
);
""",
"""
CREATE TABLE calls (
    from_id TEXT NOT NULL REFERENCES telephone_config(id) UNIQUE,
    to_id TEXT NOT NULL REFERENCES telephone_config(id),
    start_time INTEGER NOT NULL
);
""",
"""
CREATE TABLE guild_config (
    id INTEGER PRIMARY KEY,
    achievement_messages INTEGER
);

CREATE TABLE user_config (
    id INTEGER PRIMARY KEY,
    achievement_tracking_enabled INTEGER
);

CREATE TABLE stats (
    user_id INTEGER NOT NULL REFERENCES user_config (id),
    stat TEXT NOT NULL COLLATE NOCASE,
    value BLOB NOT NULL,
    UNIQUE (user_id, stat)
);

CREATE TABLE achievements (
    user_id INTEGER NOT NULL REFERENCES user_config (id),
    achievement TEXT NOT NULL,
    achieved_time INTEGER NOT NULL,
    UNIQUE (user_id, achievement)
);
""",
"""
CREATE TABLE assets (
    identifier TEXT PRIMARY KEY,
    url TEXT NOT NULL
);
""",
"""
CREATE TABLE user_data (
    user_id INTEGER NOT NULL,
    guild_id INTEGER,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    UNIQUE (user_id, guild_id, key)
);
"""
]

async def execute_fetchone(self, sql, params=None):
    if params == None: params = ()
    return await self._execute(self._fetchone, sql, params)

def _fetchone(self, sql, params):
    cursor = self._conn.execute(sql, params)
    return cursor.fetchone()

async def init(db_path):
    db = await aiosqlite.connect(db_path)
    await db.execute("PRAGMA foreign_keys = ON")

    db.row_factory = aiosqlite.Row
    aiosqlite.Connection._fetchone = _fetchone
    aiosqlite.Connection.execute_fetchone = execute_fetchone

    version = (await (await db.execute("PRAGMA user_version")).fetchone())[0]
    for i in range(version, len(migrations)):
        await db.executescript(migrations[i])
        # Normally interpolating like this would be a terrible idea because of SQL injection.
        # However, in this case there is not an obvious alternative (the parameter-based way apparently doesn't work)
        # and i + 1 will always be an integer anyway
        await db.execute(f"PRAGMA user_version = {i + 1}")
        await db.commit()
        logging.info(f"Migrated DB to schema {i + 1}")

    return db