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

#intents = discord.Intents.default()
#intents.members = True

bot = commands.Bot(command_prefix=config["prefix"], description="AutoBotRobot, the most useless bot in the known universe." + util.config.get("description_suffix", ""), 
    case_insensitive=True, allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=True))
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
    if isinstance(err, commands.CommandInvokeError) and isinstance(err.original, ValueError): return await ctx.send(embed=util.error_embed(str(err.original)))
    # TODO: really should find a way to detect ALL user errors here?
    if isinstance(err, (commands.UserInputError)): return await ctx.send(embed=util.error_embed(str(err)))
    try:
        command_errors.inc()
        trace = re.sub("\n\n+", "\n", "\n".join(traceback.format_exception(err, err, err.__traceback__)))
        logging.error("command error occured (in %s)", ctx.invoked_with, exc_info=err)
        await ctx.send(embed=util.error_embed(util.gen_codeblock(trace), title="Internal error"))
        await achievement.achieve(ctx.bot, ctx.message, "error")
    except Exception as e: print("meta-error:", e)

@bot.check
async def andrew_bad(ctx):
    return ctx.message.author.id != 543131534685765673

@bot.event
async def on_ready():
    logging.info("Connected as " + bot.user.name)
    await bot.change_presence(status=discord.Status.online, 
        activity=discord.Activity(name=f"{bot.command_prefix}help", type=discord.ActivityType.listening))

webhooks = {}

async def initial_load_webhooks(db):
    for row in await db.execute_fetchall("SELECT * FROM discord_webhooks"):
        webhooks[row["channel_id"]] = row["webhook"]

@bot.listen("on_message")
async def send_to_bridge(msg):
    # discard webhooks and bridge messages (hackily, admittedly, not sure how else to do this)
    if (msg.author == bot.user and msg.content[0] == "<") or msg.author.discriminator == "0000": return
    if msg.content == "": return
    channel_id = msg.channel.id
    msg = eventbus.Message(eventbus.AuthorInfo(msg.author.name, msg.author.id, str(msg.author.avatar_url), msg.author.bot), msg.content, ("discord", channel_id), msg.id)
    await eventbus.push(msg)

async def on_bridge_message(channel_id, msg):
    channel = bot.get_channel(channel_id)
    if channel:
        webhook = webhooks.get(channel_id)
        if webhook:
            wh_obj = discord.Webhook.from_url(webhook, adapter=discord.AsyncWebhookAdapter(bot.http._HTTPClient__session))
            await wh_obj.send(
                content=msg.message, username=msg.author.name, avatar_url=msg.author.avatar_url,
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False))
        else:
            text = f"<{msg.author.name}> {msg.message}"
            await channel.send(text[:2000], allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False))
    else:
        logging.warning("channel %d not found", channel_id)

eventbus.add_listener("discord", on_bridge_message)

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
    await initial_load_webhooks(bot.database)
    for ext in util.extensions:
        logging.info("loaded %s", ext)
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
