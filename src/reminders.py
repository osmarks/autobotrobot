import json
import logging
from datetime import datetime, timezone
import discord.ext.tasks as tasks

import util

def setup(bot):
    @bot.command(brief="Set a reminder to be reminded about later.", rest_is_raw=True, help="""Sets a reminder which you will (probably) be reminded about at/after the specified time.
    All times are UTC.
    Reminders are checked every minute, so while precise times are not guaranteed, reminders should under normal conditions be received within 2 minutes of what you specify.""")
    async def remind(ctx, time, *, reminder):
        reminder = reminder.strip()
        if len(reminder) > 512:
            await ctx.send(embed=util.error_embed("Maximum reminder length is 512 characters", "Foolish user error"))
            return
        extra_data = {
            "author_id": ctx.author.id,
            "channel_id": ctx.message.channel.id,
            "message_id": ctx.message.id,
            "guild_id": ctx.message.guild and ctx.message.guild.id,
            "original_time_spec": time
        }
        try:
            now = datetime.now(tz=timezone.utc)
            time = util.parse_time(time)
        except:
            await ctx.send(embed=util.error_embed("Invalid time (wrong format/too large/non-integer months or years)"))
            return
        await bot.database.execute("INSERT INTO reminders (remind_timestamp, created_timestamp, reminder, expired, extra) VALUES (?, ?, ?, ?, ?)", 
            (time.timestamp(), now.timestamp(), reminder, 0, util.json_encode(extra_data)))
        await bot.database.commit()
        await ctx.send(f"Reminder scheduled for {util.format_time(time)} ({util.format_timedelta(now, time)}).")

    async def send_to_channel(info, text):
        channel = bot.get_channel(info["channel_id"])
        if not channel: raise Exception(f"channel {info['channel_id']} unavailable/nonexistent")
        await channel.send(text)

    async def send_by_dm(info, text):
        user = bot.get_user(info["author_id"])
        if not user: raise Exception(f"user {info['author_id']} unavailable/nonexistent")
        if not user.dm_channel: await user.create_dm()
        await user.dm_channel.send(text)

    async def send_to_guild(info, text):
        guild = bot.get_guild(info["guild_id"])
        member = guild.get_member(info["author_id"])
        self = guild.get_member(bot.user.id)
        # if member is here, find a channel they can read and the bot can send in
        if member:
            for chan in guild.text_channels:
                if chan.permissions_for(member).read_messages and chan.permissions_for(self).send_messages:
                    await chan.send(text)
                    return
        # if member not here or no channel they can read messages in, send to any available channel
        for chan in guild.text_channels:
            if chan.permissions_for(self).send_messages:
                await chan.send(text)
                return
        raise Exception(f"guild {info['author_id']} has no (valid) channels")

    remind_send_methods = [
        ("original channel", send_to_channel),
        ("direct message", send_by_dm),
        ("originating guild", send_to_guild)
    ]

    @tasks.loop(seconds=60)
    async def remind_worker():
        csr = bot.database.execute("SELECT * FROM reminders WHERE expired = 0 AND remind_timestamp < ?", (util.timestamp(),))
        to_expire = []
        async with csr as cursor:
            async for row in cursor:
                rid, remind_timestamp, created_timestamp, reminder_text, _, extra = row
                try:
                    remind_timestamp = datetime.utcfromtimestamp(remind_timestamp)
                    created_timestamp = datetime.utcfromtimestamp(created_timestamp)
                    extra = json.loads(extra)
                    uid = extra["author_id"]
                    text = f"<@{uid}> Reminder queued at {util.format_time(created_timestamp)}: {reminder_text}"

                    for method_name, func in remind_send_methods:
                        print("trying", method_name, rid)
                        try:
                            await func(extra, text)
                            to_expire.append(rid)
                            break
                        except Exception as e: logging.warning("failed to send %d to %s", rid, method_name, exc_info=e)
                except Exception as e:
                    logging.warning("Could not send reminder %d", rid, exc_info=e)
        for expiry_id in to_expire:
            logging.info("Expiring reminder %d", expiry_id)
            await bot.database.execute("UPDATE reminders SET expired = 1 WHERE id = ?", (expiry_id,))
        await bot.database.commit()

    @remind_worker.before_loop
    async def before_remind_worker():
        logging.info("Waiting for bot readiness...")
        await bot.wait_until_ready()
        logging.info("Remind worker starting")

    remind_worker.start()
    bot.remind_worker = remind_worker

def teardown(bot):
    bot.remind_worker.cancel()