import discord
import logging
import asyncio
import aiohttp
import random
import prometheus_client
from datetime import datetime
import discord.ext.commands as commands

import util

config = util.config

intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.message_content = True

bot = discord.Client(allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=True), intents=intents)

cleaner = commands.clean_content()
def clean(ctx, text):
    return cleaner.convert(ctx, text)

AUTOGOLLARK_MARKER = "\u200b"

async def serialize_history(ctx, n=20):
    prompt = []
    seen = set()
    async for message in ctx.channel.history(limit=n):
        display_name = message.author.display_name
        content = message.content
        if not content and message.embeds:
            content = message.embeds[0].title
        elif not content and message.attachments:
            content = "[attachments]"
        if not content:
            continue
        if message.content.startswith(AUTOGOLLARK_MARKER):
            content = message.content.removeprefix(AUTOGOLLARK_MARKER)
        if message.author == bot.user:
            display_name = config["autogollark"]["name"]

            if content in seen: continue
            seen.add(content)
        prompt.append(f"[{util.render_time(message.created_at)}] {display_name}: {content}\n")
        if sum(len(x) for x in prompt) > util.config["ai"]["max_len"]:
            break
    prompt.reverse()
    return prompt

async def autogollark(ctx, session):
    display_name = config["autogollark"]["name"]
    prompt = await serialize_history(ctx, n=20)
    prompt.append(f"[{util.render_time(datetime.utcnow())}] {display_name}:")
    conversation = "".join(prompt)
    # retrieve gollark data from backend
    gollark_chunks = []
    async with session.post(util.config["autogollark"]["api"], json={"query": conversation}) as res:
        for chunk in (await res.json()):
            gollark_chunk = []
            if sum(len(y) for x in gollark_chunks for y in x) > util.config["autogollark"]["max_context_chars"]: gollark_chunks.pop(0)
            for message in chunk:
                dt = datetime.fromisoformat(message["timestamp"])
                line = f"[{util.render_time(dt)}] {message['author'] or display_name}: {await clean(ctx, message['contents'])}\n"
                gollark_chunk.append(line)

                # ugly hack to remove duplicates
                ds = []
                for chunk in gollark_chunks:
                    if line in chunk and line != "---\n": ds.append(chunk)
                for d in ds:
                    try:
                        gollark_chunks.remove(d)
                    except ValueError: pass

            gollark_chunk.append("---\n")
            gollark_chunks.append(gollark_chunk)

    gollark_data = "".join("".join(x) for x in gollark_chunks)

    print(gollark_data + conversation)

    # generate response
    generation = await util.generate(session, gollark_data + conversation, stop=["\n["])
    while True:
        new_generation = generation.strip().strip("[\n ")
        new_generation = new_generation.removesuffix("---")
        if new_generation == generation:
            break
        generation = new_generation
    if generation:
        await ctx.send(generation)

@bot.event
async def on_message(message):
    if message.channel.id in util.config["autogollark"]["channels"] and not message.author == bot.user:
        await autogollark(commands.Context(bot=bot, message=message, prefix="", view=None), bot.session)

async def run_bot():
    bot.session = aiohttp.ClientSession()
    logging.info("Autogollark starting")
    await bot.start(config["autogollark"]["token"])
