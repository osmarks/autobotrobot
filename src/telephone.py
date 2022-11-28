from discord.ext import commands
import discord
import logging
import asyncio
import re
import hashlib
from datetime import datetime, timedelta
import os
import pydot
import tempfile
import collections
import aiohttp

import util
import eventbus

# Generate a "phone" address
# Not actually for phones
def generate_address(ctx):
    h = hashlib.blake2b(str(ctx.guild.id).encode("utf-8")).digest()
    words = open("wordlist-8192.txt").readlines()
    out = ""
    for i in range(3):
        out += words[int.from_bytes(h[i * 2:i * 2 + 3], "little") % 8192].strip().title()
    return out

def parse_formatting(bot, text):
    def parse_match(m):
        try:
            target = int(m.group(2))
        except ValueError: return m.string
        if m.group(1) == "@": # user ping
            user = bot.get_user(target)
            if user: return { "type": "user_mention", "name": user.name, "id": target }
            return f"@{target}"
        else: # channel "ping"
            channel = bot.get_channel(target)
            if channel: return { "type": "channel_mention", "name": channel.name, "id": target }
            return f"#{target}"
    remaining = text
    out = []
    while match := re.search(r"<([@#])!?([0-9]+)>", remaining):
        start, end = match.span()
        out.append(remaining[:start])
        out.append(parse_match(match))
        remaining = remaining[end:]
    out.append(remaining)
    return list(filter(lambda x: x != "", out))

def render_formatting(dest_channel, message):
    out = ""
    for seg in message:
        if isinstance(seg, str):
            out += seg
        else:
            kind = seg["type"]
            # TODO: use python 3.10 pattern matching
            if kind == "user_mention":
                member = dest_channel.guild.get_member(seg["id"])
                if member != None: out += f"<@{member.id}>"
                else: out += f"@{seg['name']}"
            elif kind == "channel_mention": # these appear to be clickable across servers/guilds
                out += f"<#{seg['id']}>"
            else: logging.warn("Unrecognized message seg %s", kind)
    return out

class Telephone(commands.Cog):
    # Discord event bus link

    def __init__(self, bot):
        self.webhooks = {}
        self.bot = bot
        self.unlisten = eventbus.add_listener("discord", self.on_bridge_message)
        self.webhook_queue = asyncio.Queue(50)
        self.webhook_queue_handler_task = asyncio.create_task(self.send_webhooks())

    async def send_webhooks(self):
        while True:
            webhook, content, username, avatar_url = await self.webhook_queue.get()
            wh_obj = discord.Webhook.from_url(webhook, session=self.bot.http._HTTPClient__session)
            try:
                await wh_obj.send(content=content, username=username, avatar_url=avatar_url, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False))
            except:
                logging.exception("Webhook send on %s failed")

    async def initial_load_webhooks(self):
        rows = await self.bot.database.execute_fetchall("SELECT * FROM discord_webhooks")
        for row in rows:
            self.webhooks[row["channel_id"]] = row["webhook"]
        logging.info("Loaded %d webhooks", len(rows))

    async def on_bridge_message(self, channel_id, msg: eventbus.Message):
        channel = self.bot.get_channel(channel_id)
        if channel:
            webhook = self.webhooks.get(channel_id)
            attachments_text = "\n".join(f"{at.filename}: {at.proxy_url}" for at in msg.attachments)
            async def send_raw(text):
                if webhook:
                    try:
                        self.webhook_queue.put_nowait((webhook, text, msg.author.name, msg.author.avatar_url))
                    except asyncio.QueueFull:
                        text = f"<{msg.author.name}> {text}"
                        await channel.send(text[:2000], allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False))
                else:
                    text = f"<{msg.author.name}> {text}"
                    await channel.send(text[:2000], allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False))
            await send_raw(render_formatting(channel, msg.message)[:2000])
            if attachments_text: await send_raw(attachments_text)
        else:
            logging.warning("Channel %d not found", channel_id)

    @commands.Cog.listener("on_message")
    async def send_to_bridge(self, msg):
        # discard webhooks and bridge messages (hackily, admittedly, not sure how else to do this)
        if msg.content == "" and len(msg.attachments) == 0: return
        if (msg.author == self.bot.user and (len(msg.content) > 0 and msg.content[0] == "<")) or msg.author.discriminator == "0000": return
        channel_id = msg.channel.id
        reply = None
        if msg.reference:
            if isinstance(msg.reference.resolved, discord.DeletedReferencedMessage):
                replying_to = None
            elif msg.reference.resolved:
                replying_to = msg.reference.resolved
            elif msg.reference.cached_message:
                replying_to = msg.reference.cached_message
            else:
                try:
                    replying_to = await self.bot.get_guild(msg.reference.guild_id).get_channel(msg.reference.channel_id).fetch_message(msg.reference.message_id)
                except (discord.HTTPException, AttributeError):
                    replying_to = None
            if replying_to:
                reply = (eventbus.AuthorInfo(replying_to.author.name, replying_to.author.id, str(replying_to.author.display_avatar.url), replying_to.author.bot), parse_formatting(self.bot, replying_to.content))
            else:
                reply = (None, None)
        msg = eventbus.Message(eventbus.AuthorInfo(msg.author.name, msg.author.id, str(msg.author.display_avatar.url), msg.author.bot), 
            parse_formatting(self.bot, msg.content), ("discord", channel_id), msg.id, [ at for at in msg.attachments if not at.is_spoiler() ], reply=reply)
        await eventbus.push(msg)

    def cog_unload(self):
        self.unlisten()
        self.webhook_queue_handler_task.cancel()

    # ++tel commands

    @commands.group(name="apiotelephone", aliases=["tel", "tele", "telephone", "apiotel"], brief="ApioTelephone lets you 'call' other servers.")
    async def telephone(self, ctx):
        """Call other (participating) servers with ApioTelephone! To configure a channel for telephony, use the setup command (requires Manage Channels).
It's recommended that you give the bot Manage Webhooks permissions in this channel so that it can use webhook calls mode.
To place a call, use dial [number] - the other end has to accept the call.
When you want to end a call, use hangup.
"""
        pass

    async def get_channel_config(self, channel):
        return await self.bot.database.execute_fetchone("SELECT * FROM telephone_config WHERE channel_id = ?", (channel,))

    async def get_addr_config(self, addr):
        return await self.bot.database.execute_fetchone("SELECT * FROM telephone_config WHERE id = ? COLLATE NOCASE", (addr,))

    @telephone.command(brief="Link to other channels", help="""Connect to another channel on Discord or any supported bridges.
    Virtual channels also exist.
    """)
    @commands.check(util.extpriv_check)
    async def link(self, ctx, target_type, target_id, bidirectional: bool = True):
        target_id = util.extract_codeblock(target_id)
        try:
            target_id = int(target_id)
        except ValueError: pass
        await eventbus.add_bridge_link(self.bot.database, ("discord", ctx.channel.id), (target_type, target_id), "manual", bidirectional)
        await ctx.send(f"Link established.")
        pass

    @telephone.command(brief="Undo link commands.")
    @commands.check(util.server_mod_check)
    async def unlink(self, ctx, target_type, target_id, bidirectional: bool = True):
        target_id = util.extract_codeblock(target_id)
        try:
            target_id = int(target_id)
        except ValueError: pass
        await eventbus.remove_bridge_link(self.bot.database, ("discord", ctx.channel.id), (target_type, target_id), bidirectional)
        await ctx.send(f"Successfully deleted.")
        pass


    async def find_recent(self, chs, query):
        one_week = timedelta(seconds=60*60*24*7)
        one_week_ago = datetime.now() - one_week

        for ch in chs:
            yield True, ch
            async for msg in ch.history(limit=None,after=one_week_ago):
                if query in msg.content.lower():
                    yield False, ch, msg

    @telephone.command(brief="Find recent messages in channels linked to this")
    @commands.check(util.extpriv_check)
    async def searchrecent(self, ctx, ch: discord.TextChannel, *, query):
        author = ctx.author
        chs = []
        for dest in eventbus.find_all_destinations(("discord",ch.id)):
            if dest[0] == "discord":
                chs.append(self.bot.get_channel(dest[1]))

        found = await self.find_recent(chs, query)

        out = ""
        async for ch,ms in found.items():
            out += f"{ch.mention} (`#{ch.name}` in `{ch.guild.name}`)\n"
            for m in ms:
                u = m.author.name if m.author else None
                w = "[WH]" if m.webhook_id else ""
                out += f"- {m.content[:20]} @{m.created_at} by {u} {w}\n"

        for c in util.chunks(out,2000):
            await author.send(c)

        return found

    @telephone.command(brief="Delete recent messages in channels linked to this")
    @commands.check(util.extpriv_check)
    async def delrecent(self, ctx, ch: discord.TextChannel, *, query):
        author = ctx.author
        found = await self.searchrecent(ctx,ch,query=query)

        await author.send("please say 'GO' to confirm or wait 10 seconds to not confirm")
        try:
            await self.bot.wait_for('message',check=lambda m:m.author == ctx.author and m.content == "GO" and m.channel == ctx.author.dm_channel,timeout=10)
        except asyncio.TimeoutError:
            await author.send("timed out")
            return

        async def try_delete(msg,session):
            if msg.webhook_id is not None:
                # note: assumes there is only one webhook we control per channel
                # i think that's the case
                wh_url = await self.bot.database.execute_fetchone("SELECT webhook FROM discord_webhooks WHERE channel_id = ?",(msg.channel.id,))
                if wh_url is None:
                    await author.send(f"no access to webhook: {msg.id} {msg.channel.mention} {msg.jump_url}")
                    return
                wh_url = wh_url['webhook']

                wh = discord.Webhook.from_url(wh_url,session=session)
                await wh.delete_message(msg.id)

            else:
                try:
                    await msg.delete()
                except discord.errors.Forbidden:
                    await author.send(f"!!! couldn't delete msg {msg.id} in {msg.channel.mention}")

        msgs = []
        for q in found.values():
            msgs.extend(q)

        async with aiohttp.ClientSession() as session:
            await asyncio.gather(*(try_delete(msg,session) for msg in msgs))

        await author.send("done")


    @telephone.command(brief="Generate a webhook")
    @commands.check(util.server_mod_check)
    async def init_webhook(self, ctx):
        webhook = (await ctx.channel.create_webhook(name="ABR webhook", reason=f"requested by {ctx.author.name}")).url
        await self.bot.database.execute("INSERT OR REPLACE INTO discord_webhooks VALUES (?, ?)", (ctx.channel.id, webhook))
        await self.bot.database.commit()
        self.webhooks[ctx.channel.id] = webhook
        await ctx.send("Done.")

    @telephone.command()
    @commands.check(util.server_mod_check)
    async def setup(self, ctx):
        num = generate_address(ctx)
        await ctx.send(f"Your address is {num}.")
        info = await self.get_addr_config(num)
        webhook = None
        if info: webhook = info["webhook"]
        if not info or not webhook:
            try:
                webhook = (await ctx.channel.create_webhook(name="incoming message display", reason="configure for apiotelephone")).url
                await self.bot.database.execute("INSERT OR REPLACE INTO discord_webhooks VALUES (?, ?)", (ctx.channel.id, webhook))
                await ctx.send("Created webhook.")
            except discord.Forbidden as f:
                logging.warn("Could not create webhook in #%s %s", ctx.channel.name, ctx.guild.name, exc_info=f)
                await ctx.send("Webhook creation failed - please ensure permissions are available. This is not necessary but is recommended.")
        await self.bot.database.execute("INSERT OR REPLACE INTO telephone_config VALUES (?, ?, ?, ?)", (num, ctx.guild.id, ctx.channel.id, webhook))
        await self.bot.database.commit()
        await ctx.send("Configured.")

    @telephone.command(aliases=["rcall"], brief="Dial another telephone channel.")
    async def rdial(self, ctx):
        # TODO: this is not very performant
        random = (await self.bot.database.execute_fetchone("SELECT id FROM telephone_config ORDER BY RANDOM()"))["id"]
        await self.dial(ctx, random)

    @telephone.command(aliases=["call"], brief="Dial another telephone channel.")
    async def dial(self, ctx, address):
        # basic checks - ensure this is a phone channel and has no other open calls
        channel_info = await self.get_channel_config(ctx.channel.id)
        if not channel_info: return await ctx.send(embed=util.error_embed("Not in a phone channel."))
        originating_address = channel_info["id"]
        if address == originating_address: return await ctx.send(embed=util.error_embed("A channel cannot dial itself. That means *you*, Gibson."))
        recv_info = await self.get_addr_config(address)
        if not recv_info: return await ctx.send(embed=util.error_embed("Destination address not found. Please check for typos and/or antimemes."))

        current_call = await self.bot.database.execute_fetchone("SELECT * FROM calls WHERE from_id = ?", (originating_address,))
        if current_call: return await ctx.send(embed=util.error_embed(f"A call is already open (to {current_call['to_id']}) from this channel. Currently, only one outgoing call is permitted at a time."))

        # post embed in the receiving channel prompting people to accept/decline call
        recv_channel = self.bot.get_channel(recv_info["channel_id"])
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

        def check(re, u): return (str(re.emoji) == "✅" or str(re.emoji) == "❎") and u != self.bot.user

        reaction = None
        # wait until someone clicks the reactions, or time out and say so
        try:
            reaction, user = await self.bot.wait_for("reaction_add", timeout=util.config["call_timeout"], check=check)
        except asyncio.TimeoutError:
            await asyncio.gather(
                ctx.send(embed=util.error_embed("Timed out", "Outgoing call timed out - the other end did not pick up.")),
                recv_channel.send(embed=util.error_embed("Timed out", "Call timed out - no response in time"))
            )

        await asyncio.gather(call_message.remove_reaction("✅", self.bot.user), call_message.remove_reaction("❎", self.bot.user))
        em = str(reaction.emoji) if reaction else "❎"
        if em == "✅": # accept call
            await self.bot.database.execute("INSERT INTO calls VALUES (?, ?, ?)", (originating_address, address, util.timestamp()))
            await self.bot.database.commit()
            await eventbus.add_bridge_link(self.bot.database, ("discord", ctx.channel.id), ("discord", recv_channel.id), "telephone")
            await asyncio.gather(
                ctx.send(embed=util.info_embed("Outgoing call", "Call accepted and connected.")),
                recv_channel.send(embed=util.info_embed("Incoming call", "Call accepted and connected."))
            )
        elif em == "❎": # drop call
            await ctx.send(embed=util.error_embed("Your call was declined.", "Call declined"))

    @telephone.command(aliases=["disconnect", "quit"], brief="Disconnect latest call.")
    async def hangup(self, ctx):
        channel_info = await self.get_channel_config(ctx.channel.id)
        addr = channel_info["id"]
        if not channel_info: return await ctx.send(embed=util.error_embed("Not in a phone channel."))
        from_here = await self.bot.database.execute_fetchone("SELECT * FROM calls WHERE from_id = ?", (addr,))
        to_here = await self.bot.database.execute_fetchone("SELECT * FROM calls WHERE to_id = ?", (addr,))
        if (not to_here) and (not from_here): return await ctx.send(embed=util.error_embed("No calls are active."))

        other = None
        if from_here:
            other = from_here["to_id"]
            await self.bot.database.execute("DELETE FROM calls WHERE from_id = ? AND to_id = ?", (addr, other))
        elif to_here:
            other = to_here["from_id"]
            await self.bot.database.execute("DELETE FROM calls WHERE to_id = ? AND from_id = ?", (addr, other))
        await self.bot.database.commit()
        other_channel = (await self.get_addr_config(other))["channel_id"]
        await eventbus.remove_bridge_link(self.bot.database, ("discord", other_channel), ("discord", ctx.channel.id))

        await asyncio.gather(
            ctx.send(embed=util.info_embed("Hung up", f"Call to {other} disconnected.")),
            self.bot.get_channel(other_channel).send(embed=util.info_embed("Hung up", f"Call to {addr} disconnected."))
        )

    @telephone.command(aliases=["status"], brief="List inbound/outbound calls.")
    async def info(self, ctx):
        channel_info = await self.get_channel_config(ctx.channel.id)
        if not channel_info: return await ctx.send(embed=util.info_embed("Phone status", "Not a phone channel"))
        addr = channel_info['id']
        title = f"{addr} status"

        fields = []

        now = datetime.utcnow()
        def delta(ts):
            return util.format_timedelta(datetime.utcfromtimestamp(ts), now)

        incoming = await self.bot.database.execute_fetchall("SELECT * FROM calls WHERE to_id = ?", (addr,))
        fields.extend(map(lambda x: ["Incoming call", f"From {x['from_id']} - for {delta(x['start_time'])}"], incoming))
        outgoing = await self.bot.database.execute_fetchall("SELECT * FROM calls WHERE from_id = ?", (addr,))
        fields.extend(map(lambda x: ["Outgoing call", f"To {x['to_id']} - for {delta(x['start_time'])}"], outgoing))
        await ctx.send(embed=util.info_embed(title, f"Connected: {len(incoming) + len(outgoing)}", fields))

    @telephone.command(brief="Dump links out of current channel.")
    async def graph(self, ctx):
        graph = pydot.Dot("linkgraph", ratio="fill")
        seen = set()
        seen_edges = set()
        def node_name(x):
            if x[0] == "discord":
                chan = self.bot.get_channel(x[1])
                if chan and getattr(chan, "name", False):
                    out = "#" + chan.name
                    if chan.guild:
                        out = chan.guild.name + "/" + out
                    return "discord/" + out
                else:
                    return f"{x[0]}/{x[1]}"
            return f"{x[0]}/{x[1]}"
        todo = [("discord", ctx.channel.id)]

        while todo:
            current = todo.pop(0)
            graph.add_node(pydot.Node(node_name(current), fontname="monospace"))
            for adjacent in eventbus.links[current]:
                if adjacent not in seen:
                    todo.append(adjacent)
                edge = (current, adjacent)
                if edge not in seen_edges:
                    graph.add_edge(pydot.Edge(node_name(current), node_name(adjacent)))
                    seen_edges.add(edge)
            seen.add(current)
        (handle, tmppath) = tempfile.mkstemp(".png", "graphviz")
        graph.write_png(tmppath)
        try:
            await ctx.send(file=discord.File(handle, filename="out.png"))
        finally:
            os.unlink(tmppath)

def setup(bot):
    cog = Telephone(bot)
    bot.add_cog(cog)
    asyncio.create_task(cog.initial_load_webhooks())
