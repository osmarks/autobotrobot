import discord
import toml
import logging
import discord.ext.commands as commands
import discord.ext.tasks as tasks
import re
import asyncio
import json
import traceback
import random
import collections
import prometheus_client
import prometheus_async.aio
import typing
import sys

import tio
import db
import util
import eventbus
import irc_link
import achievement

config = util.config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(asctime)s %(message)s", datefmt="%H:%M:%S %d/%m/%Y")

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix=commands.when_mentioned_or(config["prefix"]), description="AutoBotRobot, the most useless bot in the known universe." + util.config.get("description_suffix", ""), 
    case_insensitive=True, allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=True), intents=intents)
bot._skip_check = lambda x, y: False

messages = prometheus_client.Counter("abr_messages", "Messages seen/handled by bot")
command_invocations = prometheus_client.Counter("abr_command_invocations", "Total commands invoked (includes failed)")
@bot.event
async def on_message(message):
    messages.inc()
    words = message.content.split(" ")
    if len(words) == 10 and message.author.id == 435756251205468160:
        await message.channel.send(util.unlyric(message.content))
    else:
        if message.author == bot.user or message.author.discriminator == "0000": return
        ctx = await bot.get_context(message)
        if not ctx.valid: return
        command_invocations.inc()
        await bot.invoke(ctx)

command_errors = prometheus_client.Counter("abr_errors", "Count of errors encountered in executing commands.")
@bot.event
async def on_command_error(ctx, err):
    if isinstance(err, (commands.CommandNotFound, commands.CheckFailure)): return
    if isinstance(err, commands.CommandInvokeError) and isinstance(err.original, ValueError):
        return await ctx.send(embed=util.error_embed(str(err.original), title=f"Error in {ctx.invoked_with}"))
    # TODO: really should find a way to detect ALL user errors here?
    if isinstance(err, (commands.UserInputError)):
        return await ctx.send(embed=util.error_embed(str(err), title=f"Error in {ctx.invoked_with}"))
    try:
        command_errors.inc()
        trace = re.sub("\n\n+", "\n", "\n".join(traceback.format_exception(err, err, err.__traceback__)))
        logging.error("Command error occured (in %s)", ctx.invoked_with, exc_info=err)
        await ctx.send(embed=util.error_embed(util.gen_codeblock(trace), title=f"Internal error in {ctx.invoked_with}"))
        await achievement.achieve(ctx.bot, ctx.message, "error")
    except Exception as e: print("meta-error:", e)

@bot.check
async def andrew_bad(ctx):
    return ctx.message.author.id != 543131534685765673

@bot.event
async def on_ready():
    logging.info("Connected as " + bot.user.name)
    await bot.change_presence(status=discord.Status.online, 
        activity=discord.Activity(name=f"{config['prefix']}help", type=discord.ActivityType.listening))

visible_users = prometheus_client.Gauge("abr_visible_users", "Users the bot can see")
def get_visible_users():
    return len(bot.users)
visible_users.set_function(get_visible_users)

heavserver_members = prometheus_client.Gauge("abr_heavserver_members", "Current member count of heavserver")
heavserver_bots = prometheus_client.Gauge("abr_heavserver_bots", "Current bot count of heavserver")
def get_heavserver_members():
    if not bot.get_guild(util.config["heavserver"]["id"]): return 0
    return len(bot.get_guild(util.config["heavserver"]["id"]).members)
def get_heavserver_bots():
    if not bot.get_guild(util.config["heavserver"]["id"]): return 0
    return len([ None for member in bot.get_guild(util.config["heavserver"]["id"]).members if member.bot ])
heavserver_members.set_function(get_heavserver_members)
heavserver_bots.set_function(get_heavserver_bots)

guild_count = prometheus_client.Gauge("abr_guilds", "Guilds the bot is in")
def get_guild_count():
    return len(bot.guilds)
guild_count.set_function(get_guild_count)

async def run_bot():
    bot.database = await db.init(config["database"])
    await eventbus.initial_load(bot.database)
    for ext in util.extensions:
        logging.info("Loaded %s", ext)
        bot.load_extension(ext)
    await bot.start(config["token"])

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(prometheus_async.aio.web.start_http_server(port=config["metrics_port"]))
    try:
        loop.run_until_complete(run_bot())
    except KeyboardInterrupt:
        loop.run_until_complete(bot.logout())
        sys.exit(0)
    finally:
        loop.close()
