import asyncio
import argparse
import random
from numpy.random import default_rng
import re
import aiohttp
import subprocess
import discord.ext.commands as commands
import discord
from datetime import datetime
from pathlib import Path

import tio
import util

def render(dt: datetime):
    return f"{dt.hour:02}:{dt.minute:02}"

cleaner = commands.clean_content()
def clean(ctx, text):
    return cleaner.convert(ctx, text)

AUTOGOLLARK_MARKER = "\u200b"
AUTOGOLLARK_GOLLARK = "autogollark"

class Sentience(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

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
            if content == "wipe_memory":
                prompt = []
            if not content and message.embeds:
                content = message.embeds[0].title
            elif not content and message.attachments:
                content = "[attachments]"
            if not content:
                continue
            if message.author == self.bot.user:
                if message.content.startswith(AUTOGOLLARK_MARKER):
                    content = message.content.removeprefix(AUTOGOLLARK_MARKER)
                    display_name = AUTOGOLLARK_GOLLARK

                if content in seen: continue
                seen.add(content)
            prompt.append(f"[{render(message.created_at)}] {display_name}: {content}\n")
            if sum(len(x) for x in prompt) > util.config["ai"]["max_len"]:
                break
        prompt.reverse()
        return prompt

    @commands.command(help="Highly advanced AI Assistant.")
    async def ai(self, ctx, *, query=None):
        prompt = await self.serialize_history(ctx)
        prompt.append(f'[{render(datetime.utcnow())}] {util.config["ai"]["own_name"]}:')
        generation = await util.generate(self.session, util.config["ai"]["prompt_start"] + "".join(prompt))
        if generation.strip():
            await ctx.send(generation.strip())

    @commands.command(help="Emulated gollark instance.", aliases=["gollark", "ag"])
    async def autogollark(self, ctx):
        prompt = await self.serialize_history(ctx, n=50)
        prompt.append(f"[{render(datetime.utcnow())}] {AUTOGOLLARK_GOLLARK}:")
        conversation = "".join(prompt)
        # retrieve gollark data from backend
        gollark_chunks = []
        async with self.session.post(util.config["ai"]["autogollark_server"], json={"query": conversation}) as res:
            for chunk in (await res.json()):
                gollark_chunk = []
                if sum(len(y) for x in gollark_chunks for y in x) > util.config["ai"]["max_gollark_len"]: gollark_chunks.pop(0)
                for message in chunk:
                    dt = datetime.fromisoformat(message["timestamp"])
                    line = f"[{render(dt)}] {message['author'] or AUTOGOLLARK_GOLLARK}: {await clean(ctx, message['contents'])}\n"
                    gollark_chunk.append(line)
                    
                    # ugly hack to remove duplicates
                    ds = []
                    for chunk in gollark_chunks:
                        if line in chunk and line != "---\n": ds.append(chunk)
                    for d in ds:
                        print("delete chunk", d)
                        try:
                            gollark_chunks.remove(d)
                        except ValueError: pass

                gollark_chunk.append("---\n")
                gollark_chunks.append(gollark_chunk)

        gollark_data = "".join("".join(x) for x in gollark_chunks)

        print(gollark_data + conversation)

        # generate response
        generation = await util.generate(self.session, gollark_data + conversation, stop=["\n["])
        generation = generation.strip().strip("[\n ")
        if generation:
            await ctx.send(AUTOGOLLARK_MARKER + generation)

    @commands.Cog.listener("on_message")
    async def autogollark_listener(self, message):
        if message.channel.id in util.config["ai"]["autogollark_channels"] and not message.content.startswith(AUTOGOLLARK_MARKER):
            await self.autogollark(commands.Context(bot=self.bot, message=message, prefix="", view=None))

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

def setup(bot):
    bot.add_cog(Sentience(bot))
