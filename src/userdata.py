import util

def setup(bot):
    @bot.group(name="userdata", aliases=["data"], brief="Store guild/user-localized data AND retrieve it later!")
    async def userdata(ctx): pass

    async def get_userdata(db, user, guild, key):
        return (await db.execute_fetchone("SELECT * FROM user_data WHERE user_id = ? AND guild_id = ? AND key = ?", (user, guild, key))
            or await db.execute_fetchone("SELECT * FROM user_data WHERE user_id = ? AND guild_id IS NULL AND key = ?", (user, key)))
    async def set_userdata(db, user, guild, key, value):
        await db.execute("INSERT OR REPLACE INTO user_data VALUES (?, ?, ?, ?)", (user, guild, key, value))
        await bot.database.commit()

    @userdata.command(help="Get a userdata key. Checks guild first, then global.")
    async def get(ctx, *, key):
        no_header = False
        if key.startswith("noheader "):
            key = key[9:]
            no_header = True
        row = await get_userdata(bot.database, ctx.author.id, ctx.guild.id, key)
        if not row:
            raise ValueError("No such key")
        if no_header:
            await ctx.send(row["value"])
        else:
            await ctx.send(f"**{key}**: {row['value']}")

    @userdata.command(name="list", brief="List userdata keys in a given scope matching a query.")
    async def list_cmd(ctx, query="%", scope="guild", show_values: bool = False):
        "Lsit userdata keys in a given scope (guild/global) matching your query (LIKE syntax). Can also show the associated values."
        if scope == "global":
            rows = await bot.database.execute_fetchall("SELECT * FROM user_data WHERE user_id = ? AND guild_id IS NULL AND key LIKE ?", (ctx.author.id, query))
        else:
            rows = await bot.database.execute_fetchall("SELECT * FROM user_data WHERE user_id = ? AND guild_id = ? AND key LIKE ?", (ctx.author.id, ctx.guild.id, query))
        out = []
        for row in rows:
            if show_values:
                out.append(f"**{row['key']}**: {row['value']}")
            else:
                out.append(row["key"])
        if len(out) == 0: return await ctx.send("No data")
        await ctx.send(("\n" if show_values else " ").join(out)[:2000]) # TODO: split better

    def check_key(key):
        if len(key) > 128: raise ValueError("Key too long")

    def preprocess_value(value):
        value = value.replace("\n", "").strip()
        if len(value) > 256: raise ValueError("Value too long")
        return value

    @userdata.command(name="set", help="Set a userdata key in the guild scope.")
    async def set_cmd(ctx, key, *, value):
        check_key(key)
        value = preprocess_value(value)
        await set_userdata(bot.database, ctx.author.id, ctx.guild.id, key, value)
        await ctx.send(f"**{key}** set (scope guild)")

    @userdata.command(help="Set a userdata key in the global scope.")
    async def set_global(ctx, key, *, value):
        check_key(key)
        value = preprocess_value(value)
        await set_userdata(bot.database, ctx.author.id, None, key, value)
        await ctx.send(f"**{key}** set (scope global)")

    @userdata.command()
    async def inc(ctx, key, by: int = 1):
        "Increase the integer value of a userdata key."
        check_key(key)
        row = await get_userdata(bot.database, ctx.author.id, ctx.guild.id, key)
        if not row:
            value = 0
            guild = ctx.guild.id
        else:
            value = int(row["value"])
            guild = row["guild_id"]
        new_value = value + by
        await set_userdata(bot.database, ctx.author.id, guild, key, str(new_value))
        await ctx.send(f"**{key}** set to {new_value}")

    @userdata.command()
    async def delete(ctx, *keys):
        "Delete the specified keys (smallest scope first)."
        for key in keys:
            row = await get_userdata(bot.database, ctx.author.id, ctx.guild.id, key)
            if not row:
                return await ctx.send(embed=util.error_embed(f"No such key {key}"))
            await bot.database.execute("DELETE FROM user_data WHERE user_id = ? AND guild_id = ? AND key = ?", (ctx.author.id, row["guild_id"], key))
            await bot.database.commit()
            await ctx.send(f"**{key}** deleted")