import json
import logging
from datetime import datetime, timezone
import discord.ext.tasks as tasks
from discord.ext import commands
import asyncio

import util
import metrics

# https://github.com/python/cpython/blob/3.10/Lib/bisect.py (we need the 3.10 version)
def bisect_left(a, x, lo=0, hi=None, *, key=None):
    """Return the index where to insert item x in list a, assuming a is sorted.
    The return value i is such that all e in a[:i] have e < x, and all e in
    a[i:] have e >= x.  So if x already appears in the list, a.insert(i, x) will
    insert just before the leftmost x already there.
    Optional args lo (default 0) and hi (default len(a)) bound the
    slice of a to be searched.
    """

    if lo < 0:
        raise ValueError('lo must be non-negative')
    if hi is None:
        hi = len(a)
    # Note, the comparison uses "<" to match the
    # __lt__() logic in list.sort() and in heapq.
    if key is None:
        while lo < hi:
            mid = (lo + hi) // 2
            if a[mid] < x:
                lo = mid + 1
            else:
                hi = mid
    else:
        while lo < hi:
            mid = (lo + hi) // 2
            if key(a[mid]) < x:
                lo = mid + 1
            else:
                hi = mid
    return lo

class Reminders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminder_queue = []
        self.reminder_event = asyncio.Event()

    @commands.command(brief="Set a reminder to be reminded about later.", rest_is_raw=True, help="""Sets a reminder which you will (probably) be reminded about at/after the specified time.
    All times are UTC unless overridden.
    Thanks to new coding and algorithms, reminders are now not done at minute granularity. However, do not expect sub-5s granularity due to miscellaneous latency which has not been a significant target of optimization.
    Note that due to technical limitations reminders beyond the year 10000 CE or in the past cannot currently be handled.
    Note that reminder delivery is not guaranteed, due to possible issues including but not limited to: data loss, me eventually not caring, the failure of Discord (in this case message delivery will still be attempted manually on a case-by-case basis), the collapse of human civilization, or other existential risks.""")
    async def remind(self, ctx, time, *, reminder):
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
        tz = await util.get_user_timezone(ctx)
        try:
            now = datetime.now(tz=timezone.utc)
            time = util.parse_time(time, tz)
        except:
            await ctx.send(embed=util.error_embed("Invalid time (wrong format/too large months or years)"))
            return
        utc_time, local_time = util.in_timezone(time, tz)
        id = (await self.bot.database.execute_insert("INSERT INTO reminders (remind_timestamp, created_timestamp, reminder, expired, extra) VALUES (?, ?, ?, ?, ?)", 
            (utc_time.timestamp(), now.timestamp(), reminder, 0, util.json_encode(extra_data))))["last_insert_rowid()"]
        await self.bot.database.commit()
        await ctx.send(f"Reminder scheduled for {util.format_time(local_time)} ({util.format_timedelta(now, utc_time)}).")
        self.insert_reminder(id, utc_time.timestamp())

    def insert_reminder(self, id, time):
        pos = bisect_left(self.reminder_queue, time, key=lambda x: x[0])
        self.reminder_queue.insert(pos, (time, id))
        if pos == 0:
            self.reminder_event.set()

    async def send_to_channel(self, info, text):
        channel = self.bot.get_channel(info["channel_id"])
        if not channel: raise Exception(f"channel {info['channel_id']} unavailable/nonexistent")
        await channel.send(text)

    async def send_by_dm(self, info, text):
        user = self.bot.get_user(info["author_id"])
        if not user:
            user = await self.bot.fetch_user(info["author_id"])
        if not user: raise Exception(f"user {info['author_id']} unavailable/nonexistent")
        if not user.dm_channel: await user.create_dm()
        await user.dm_channel.send(text)

    async def send_to_guild(self, info, text):
        if not "guild_id" in info: raise Exception("Guild unknown")
        guild = self.bot.get_guild(info["guild_id"])
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

    async def fire_reminder(self, id):
        remind_send_methods = [
            ("original channel", self.send_to_channel),
            ("direct message", self.send_by_dm),
            ("originating guild", self.send_to_guild)
        ]
        row = await self.bot.database.execute_fetchone("SELECT * FROM reminders WHERE id = ?", (id,))
        to_expire = []
        rid, remind_timestamp, created_timestamp, reminder_text, _, extra = row
        try:
            remind_timestamp = datetime.utcfromtimestamp(remind_timestamp)
            created_timestamp = datetime.utcfromtimestamp(created_timestamp).replace(tzinfo=timezone.utc)
            extra = json.loads(extra)
            uid = extra["author_id"]
            tz = await util.get_user_timezone(util.AltCtx(util.IDWrapper(uid), util.IDWrapper(extra.get("guild_id")), self.bot))
            created_time = util.format_time(created_timestamp.astimezone(tz))
            text = f"<@{uid}> Reminder queued at {created_time}: {reminder_text}"

            for method_name, func in remind_send_methods:
                try:
                    await func(extra, text)
                    metrics.reminders_fired.inc()
                    to_expire.append((1, rid)) # 1 = expired normally
                    break
                except Exception as e: logging.warning("Failed to send %d to %s", rid, method_name, exc_info=e)
        except Exception as e:
            logging.warning("Could not send reminder %d", rid, exc_info=e)
            #to_expire.append((2, rid)) # 2 = errored
        for expiry_type, expiry_id in to_expire:
            logging.info("Expiring reminder %d", expiry_id)
            await self.bot.database.execute("UPDATE reminders SET expired = ? WHERE id = ?", (expiry_type, expiry_id))
        await self.bot.database.commit()

    async def init_reminders(self):
        ts = util.timestamp()
        # load future reminders
        reminders = await self.bot.database.execute_fetchall("SELECT * FROM reminders WHERE expired = 0 AND remind_timestamp > ?", (ts,))
        for reminder in reminders:
            self.insert_reminder(reminder["id"], reminder["remind_timestamp"])
        logging.info("Loaded %d reminders", len(reminders))
        self.rloop_task = await self.reminder_loop()
        # catch reminders which were not fired due to downtime or something
        reminders = await self.bot.database.execute_fetchall("SELECT * FROM reminders WHERE expired = 0 AND remind_timestamp <= ?", (ts,))
        logging.info("Firing %d late reminders", len(reminders))
        for reminder in reminders:
            await self.fire_reminder(reminder["id"])

    async def reminder_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                next_time, next_id = self.reminder_queue[0]
            except IndexError:
                await self.reminder_event.wait()
                self.reminder_event.clear()
            else:
                try:
                    await asyncio.wait_for(self.reminder_event.wait(), next_time - util.timestamp())
                    self.reminder_event.clear()
                except asyncio.TimeoutError:
                    self.reminder_event.clear()
                    self.reminder_queue.pop(0)
                    await self.fire_reminder(next_id)

async def setup(bot):
    cog = Reminders(bot)
    asyncio.create_task(cog.init_reminders())
    await bot.add_cog(cog)

def teardown(bot):
    bot.rloop_task.cancel()