import eventbus
import discord
import asyncio
import logging
import re
import discord.ext.commands as commands

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
                if member: out += f"<@{member.id}>"
                else: out += f"@{seg['name']}"
            elif kind == "channel_mention": # these appear to be clickable across servers/guilds
                out += f"<#{seg['id']}>"
            else: logging.warn("Unrecognized message seg %s", kind)
    return out

class DiscordLink(commands.Cog):
    def __init__(self, bot):
        self.webhooks = {}
        self.bot = bot
        self.unlisten = eventbus.add_listener("discord", self.on_bridge_message)

    async def initial_load_webhooks(self):
        rows = await self.bot.database.execute_fetchall("SELECT * FROM discord_webhooks")
        for row in rows:
            self.webhooks[row["channel_id"]] = row["webhook"]
        logging.info("Loaded %d webhooks", len(rows))

    async def on_bridge_message(self, channel_id, msg):
        channel = self.bot.get_channel(channel_id)
        if channel:
            webhook = self.webhooks.get(channel_id)
            if webhook:
                wh_obj = discord.Webhook.from_url(webhook, adapter=discord.AsyncWebhookAdapter(self.bot.http._HTTPClient__session))
                await wh_obj.send(
                    content=render_formatting(channel, msg.message)[:2000], username=msg.author.name, avatar_url=msg.author.avatar_url,
                    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False))
            else:
                text = f"<{msg.author.name}> {render_formatting(channel, msg.message)}"
                await channel.send(text[:2000], allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False))
        else:
            logging.warning("Channel %d not found", channel_id)

    @commands.Cog.listener("on_message")
    async def send_to_bridge(self, msg):
        # discard webhooks and bridge messages (hackily, admittedly, not sure how else to do this)
        if msg.content == "": return
        if (msg.author == self.bot.user and msg.content[0] == "<") or msg.author.discriminator == "0000": return
        channel_id = msg.channel.id
        msg = eventbus.Message(eventbus.AuthorInfo(msg.author.name, msg.author.id, str(msg.author.avatar_url), msg.author.bot), parse_formatting(self.bot, msg.content), ("discord", channel_id), msg.id)
        await eventbus.push(msg)

    def cog_unload(self):
        self.unlisten()

def setup(bot):
    cog = DiscordLink(bot)
    bot.add_cog(cog)
    asyncio.create_task(cog.initial_load_webhooks())