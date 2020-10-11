from discord.ext import commands
import discord
import logging
import asyncio
import hashlib
from datetime import datetime

import util

# Generate a "phone" address
# Not actually for phones
def generate_address(ctx):
    h = hashlib.blake2b(str(ctx.guild.id).encode("utf-8")).digest()
    words = open("wordlist-8192.txt").readlines()
    out = ""
    for i in range(3):
        out += words[int.from_bytes(h[i * 2:i * 2 + 3], "little") % 8192].strip().title()
    return out

channel_calls_cache = {}

def setup(bot):
    async def server_mod_check(ctx):
        return ctx.author.permissions_in(ctx.channel).manage_channels or (await bot.is_owner(ctx.author))

    @bot.group(name="apiotelephone", aliases=["tel", "tele", "telephone", "apiotel"], brief="ApioTelephone lets you 'call' other servers.", help=f"""
    Call other (participating) servers with ApioTelephone! To configure a channel for telephony, do `{bot.command_prefix}tel setup` (requires Manage Channels).
    It's recommended that you give the bot Manage Webhooks permissions in this channel so that it can use webhook calls mode.
    To place a call, do `{bot.command_prefix}tel dial [number]` - the other end has to accept the call.
    When you want to end a call, do {bot.command_prefix}tel disconnect.
    """)
    async def telephone(ctx): pass

    async def get_channel_config(channel):
        return await bot.database.execute_fetchone("SELECT * FROM telephone_config WHERE channel_id = ?", (channel,))

    async def get_addr_config(addr):
        return await bot.database.execute_fetchone("SELECT * FROM telephone_config WHERE id = ?", (addr,))

    def cache_call(chan, other, other_wh):
        x = channel_calls_cache.get(chan)
        if not x: 
            x = []
            channel_calls_cache[chan] = x
        # append other end and associated webhook
        x.append((other, other_wh))

    def uncache_call(chan, other):
        # remove other end
        l = channel_calls_cache[chan]
        for i, (c, _) in enumerate(l):
            if c == other: l.pop(i)

    async def populate_cache(db):
        for row in await db.execute_fetchall("""SELECT tcf.channel_id AS from_channel, tct.channel_id AS to_channel, tcf.webhook AS from_webhook, tct.webhook AS to_webhook FROM calls
            JOIN telephone_config AS tcf ON tcf.id = calls.from_id JOIN telephone_config AS tct ON tct.id = calls.to_id"""):
            cache_call(row["from_channel"], row["to_channel"], row["to_webhook"])
            cache_call(row["to_channel"], row["from_channel"], row["from_webhook"])

    bot.loop.create_task(populate_cache(bot.database))

    @bot.listen("on_message")
    async def forward_call_messages(message):
        calls = channel_calls_cache.get(message.channel.id, None)
        if not calls: return
        if (message.author.discriminator == "0000" and message.author.bot) or message.author == bot.user or message.content == "": # check if webhook, from itself, or only has embeds
            return
        async def send_to(call):
            other_channel, other_webhook = call
            if other_webhook:
                await discord.Webhook.from_url(other_webhook, adapter=discord.AsyncWebhookAdapter(bot.http._HTTPClient__session)).send(
                    content=message.content, username=message.author.name, avatar_url=message.author.avatar_url,
                    allowed_mentions=discord.AllowedMentions(everyone=False))
            else:
                m = f"**{message.author.name}**: "
                m += message.content[:2000 - len(m)]
                await bot.get_channel(other_channel).send(m)
        await asyncio.gather(*map(send_to, calls))

    @telephone.command()
    @commands.check(server_mod_check)
    async def setup(ctx):
        await ctx.send("Configuring...")
        num = generate_address(ctx)
        await ctx.send(f"Your address is {num}.")
        info = await get_addr_config(num)
        webhook = None
        if info: webhook = info["webhook"]
        if not info or not webhook:
            try:
                webhook = (await ctx.channel.create_webhook(name="incoming message display", reason="configure for apiotelephone")).url
                await ctx.send("Created webhook.")
            except discord.Forbidden as f:
                logging.warn("could not create webhook in #%s %s", ctx.channel.name, ctx.guild.name, exc_info=f)
                await ctx.send("Webhook creation failed - please ensure permissions are available. This is not necessary but is recommended.")
        await bot.database.execute("INSERT OR REPLACE INTO telephone_config VALUES (?, ?, ?, ?)", (num, ctx.guild.id, ctx.channel.id, webhook))
        await bot.database.commit()
        await ctx.send("Configured.")

    @telephone.command(aliases=["call"])
    async def dial(ctx, address):
        # basic checks - ensure this is a phone channel and has no other open calls
        channel_info = await get_channel_config(ctx.channel.id)
        if not channel_info: return await ctx.send(embed=util.error_embed("Not in a phone channel."))
        originating_address = channel_info["id"]
        if address == originating_address: return await ctx.send(embed=util.error_embed("A channel cannot dial itself. That means *you*, Gibson."))
        recv_info = await get_addr_config(address)
        if not recv_info: return await ctx.send(embed=util.error_embed("Destination address not found. Please check for typos and/or antimemes."))
        
        current_call = await bot.database.execute_fetchone("SELECT * FROM calls WHERE from_id = ?", (originating_address,))
        if current_call: return await ctx.send(embed=util.error_embed(f"A call is already open (to {current_call['to_id']}) from this channel. Currently, only one outgoing call is permitted at a time."))

        # post embed in the receiving channel prompting people to accept/decline call
        recv_channel = bot.get_channel(recv_info["channel_id"])
        _, call_message = await asyncio.gather(
            ctx.send(embed=util.info_embed("Outgoing call", f"Dialing {address}...")),
            recv_channel.send(embed=util.info_embed("Incoming call", 
                f"Call from {originating_address}. Click :white_check_mark: to accept or :negative_squared_cross_mark: to decline."))
        )
        # add clickable reactions to it
        await asyncio.gather(
            call_message.add_reaction("✅"),
            call_message.add_reaction("❎")
        )

        def check(re, u): return (str(re.emoji) == "✅" or str(re.emoji) == "❎") and u != bot.user

        # wait until someone clicks the reactions, or time out and say so
        try:
            reaction, user = await bot.wait_for("reaction_add", timeout=util.config["call_timeout"], check=check)
        except asyncio.TimeoutError:
            await asyncio.gather(
                ctx.send(embed=util.error_embed("Timed out", "Outgoing call timed out - the other end did not pick up.")),
                recv_channel.send(embed=util.error_embed("Timed out", "Call timed out - no response in time"))
            )

        await asyncio.gather(call_message.remove_reaction("✅", bot.user), call_message.remove_reaction("❎", bot.user))
        em = str(reaction.emoji)
        if em == "✅": # accept call
            await bot.database.execute("INSERT INTO calls VALUES (?, ?, ?)", (originating_address, address, util.timestamp()))
            await bot.database.commit()
            await asyncio.gather(
                ctx.send(embed=util.info_embed("Outgoing call", "Call accepted and connected.")),
                recv_channel.send(embed=util.info_embed("Incoming call", "Call accepted and connected."))
            )
            cache_call(ctx.channel.id, recv_channel.id, recv_info["webhook"])
            cache_call(recv_channel.id, ctx.channel.id, channel_info["webhook"])
        elif em == "❎": # drop call
            await ctx.send(embed=util.error_embed("Your call was declined.", "Call declined"))

    async def get_calls(addr):
        pass

    @telephone.command(aliases=["disconnect", "quit"])
    async def hangup(ctx):
        channel_info = await get_channel_config(ctx.channel.id)
        addr = channel_info["id"]
        if not channel_info: return await ctx.send(embed=util.error_embed("Not in a phone channel."))
        from_here = await bot.database.execute_fetchone("SELECT * FROM calls WHERE from_id = ?", (addr,))
        to_here = await bot.database.execute_fetchone("SELECT * FROM calls WHERE to_id = ?", (addr,))
        if (not to_here) and (not from_here): return await ctx.send(embed=util.error_embed("No calls are active."))

        other = None
        if from_here:
            other = from_here["to_id"]
            await bot.database.execute("DELETE FROM calls WHERE from_id = ? AND to_id = ?", (addr, other))
        elif to_here:
            other = to_here["from_id"]
            await bot.database.execute("DELETE FROM calls WHERE to_id = ? AND from_id = ?", (addr, other))
        await bot.database.commit()
        other_channel = (await get_addr_config(other))["channel_id"]

        uncache_call(ctx.channel.id, other_channel)
        uncache_call(other_channel, ctx.channel.id)

        await asyncio.gather(
            ctx.send(embed=util.info_embed("Hung up", f"Call to {other} disconnected.")),
            bot.get_channel(other_channel).send(embed=util.info_embed("Hung up", f"Call to {addr} disconnected."))
        )

    @telephone.command(aliases=["status"])
    async def info(ctx):
        channel_info = await get_channel_config(ctx.channel.id)
        if not channel_info: return await ctx.send(embed=util.info_embed("Phone status", "Not a phone channel"))
        addr = channel_info['id']
        title = f"{addr} status"

        fields = []

        now = datetime.utcnow()
        def delta(ts):
            return util.format_timedelta(datetime.utcfromtimestamp(ts), now)

        incoming = await bot.database.execute_fetchall("SELECT * FROM calls WHERE to_id = ?", (addr,))
        fields.extend(map(lambda x: ["Incoming call", f"From {x['from_id']} - for {delta(x['start_time'])}"], incoming))
        outgoing = await bot.database.execute_fetchall("SELECT * FROM calls WHERE from_id = ?", (addr,))
        fields.extend(map(lambda x: ["Outgoing call", f"To {x['to_id']} - for {delta(x['start_time'])}"], outgoing))
        await ctx.send(embed=util.info_embed(title, f"Connected: {len(incoming) + len(outgoing)}", fields))