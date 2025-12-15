
import random
import aiohttp
from collections import defaultdict, deque
import discord.ext.commands as commands
import discord
from datetime import datetime, timedelta, timezone
from pathlib import Path
import asyncio
import logging
import re

import util

cleaner = commands.clean_content()
def clean(ctx, text):
    return cleaner.convert(ctx, text)

class Sentience(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.timeouts = {}
        self.session = aiohttp.ClientSession()
        self.autopraise_spontaneous_times = {}
        self.autopraise_triggered_times = {}
        self.praise_context_buffers = defaultdict(deque)

    async def serialize_history(self, ctx, n=20):
        PREFIXES = [ ctx.prefix + "ai", ctx.prefix + "ag", ctx.prefix + "autogollark", ctx.prefix + "gollark" ]

        prompt = []
        seen = set()
        async for message in ctx.channel.history(limit=n):
            display_name = message.author.display_name
            if message.author == self.bot.user:
                display_name = util.config["ai"]["own_name"]
            content = message.content
            for prefix in PREFIXES:
                if content.startswith(prefix):
                    content = content.removeprefix(prefix).lstrip()
            if not content and message.embeds:
                content = message.embeds[0].title
            elif not content and message.attachments:
                content = "[attachments]"
            if not content:
                continue
            if message.author == self.bot.user:
                if content in seen: continue
                seen.add(content)
            prompt.append(f"[{util.render_time(message.created_at)}] {display_name}: {content}\n")
            if sum(len(x) for x in prompt) > util.config["ai"]["max_len"]:
                break
        prompt.reverse()
        return prompt

    @commands.command(help="Highly advanced AI Assistant.")
    async def ai(self, ctx, *, query=None):
        if timeout := self.timeouts.get(ctx.channel.id):
            if timeout > datetime.now():
                return
        prompt = await self.serialize_history(ctx)
        prompt.append(f'[{util.render_time(datetime.now(timezone.utc))}] {util.config["ai"]["own_name"]}:')
        generation = await util.generate(self.session, util.config["ai"]["prompt_start"] + "".join(prompt))
        assert generation, "backend failed"
        generation = generation.strip()
        if generation:
            await ctx.send(generation)

            reminders_cog = self.bot.get_cog("Reminders")
            if reminders_cog:
                reminder_timestamp = re.search(r"scheduled for (\d+-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", generation)
                if reminder_timestamp:
                    await reminders_cog.remind(ctx, time=reminder_timestamp.group(1), reminder=query or generation, notify=False)

        if generation.endswith("/quit"):
            await ctx.send("Disconnecting AI as requested.")
            self.timeouts[ctx.channel.id] = datetime.now() + timedelta(seconds=1200)

    @commands.command(help="Search meme library.", aliases=["memes"])
    async def meme(self, ctx, *, query=None):
        search_many = ctx.invoked_with == "memes"
        raw_memes = await util.user_config_lookup(ctx, "enable_raw_memes") == "true"
        async with self.session.post(util.config["memetics"]["meme_search_backend"], json={
            "terms": [{"text": query, "weight": 1}],
            "k": 200
        }) as res:
            results = await res.json()
            mat = results["matches"][:(4 if search_many else 1)]
        if raw_memes:
            o_files = [ discord.File(Path(util.config["memetics"]["memes_local"]) / Path(util.config["memetics"]["meme_base"]) / m[1]) for m in mat ]
        else:
            o_files = [ discord.File(Path(util.config["memetics"]["memes_local"]) / util.meme_thumbnail(results, m)) for m in mat ]
        await ctx.send(files=o_files)

    async def spontaneous_praise(self, target, delay):
        await asyncio.sleep(delay)
        del self.autopraise_spontaneous_times[target["user"]]
        await self.praise(target, target["spontaneous_channel"], util.config["autopraise"]["spontaneous_prompt"])

    async def praise(self, target, channel, prompt):
        chan = self.bot.get_channel(channel)
        if chan:
            context = "\n".join(self.praise_context_buffers[target["user"]])
            praise_message = await util.generate_raw_chatcompletion(self.session, util.config["ai"]["chat_completions"], prompt + "\n" + context)
            praise_message = praise_message.strip()
            if praise_message and praise_message != util.config["autopraise"]["no_praise"]:
                await chan.send(praise_message)
                self.praise_context_buffers[target["user"]].append(f"{util.config["ai"]["own_name"]}: {msg.content.strip()}")
            else:
                # if no praise occurred, reset the timer
                del self.autopraise_triggered_times[target["user"]]

    @commands.Cog.listener("on_message")
    async def auto_praise(self, msg):
        now = util.timestamp()
        # if anyone uses this, rearrange to dict users → spec, for efficiency
        for target in util.config["autopraise"]["targets"]:
            if target["guild"] == msg.guild.id and target["user"] == msg.author.id:
                if msg.channel.id in target["channels"]:
                    if msg.content and msg.content.strip(): self.praise_context_buffers[msg.author.id].append(f"{msg.author.name}: {msg.content.strip()}")
                    if len(self.praise_context_buffers[msg.author.id]) >= target["context_length"]:
                        self.praise_context_buffers[msg.author.id].popleft()

                    # no spontaneous praise event within window: dispatch
                    if msg.author.id not in self.autopraise_spontaneous_times:
                        spontaneous_praise_delay = random.expovariate(target["spontaneous_interval"] / 2) + target["spontaneous_interval"] / 2
                        logging.info("Scheduling spontaneous praise for %d delay %f", msg.author.id, spontaneous_praise_delay)
                        self.autopraise_spontaneous_times[msg.author.id] = now + spontaneous_praise_delay
                        asyncio.create_task(self.spontaneous_praise(target, spontaneous_praise_delay))

                    may_praise_at = self.autopraise_triggered_times.get(msg.author.id)
                    if may_praise_at is None or may_praise_at < now:
                        logging.info("Triggered praise event for %d", msg.author.id)
                        self.autopraise_triggered_times[msg.author.id] = now + target["triggered_interval"]
                        await self.praise(target, msg.channel.id, util.config["autopraise"]["triggered_prompt"])

async def setup(bot):
    await bot.add_cog(Sentience(bot))
