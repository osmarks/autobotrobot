import eventbus
import asyncio
import irc.client_aio
import random
import util
import logging
import hashlib
import discord.ext.commands as commands
from jaraco.stream import buffer

def scramble(text):
    n = list(text)
    random.shuffle(n)
    return "".join(n)

def color_code(x):
    return f"\x03{x}"
def random_color(id): return color_code(hashlib.blake2b(str(id).encode("utf-8")).digest()[0] % 13 + 2)

def render_formatting(message):
    out = ""
    for seg in message:
        if isinstance(seg, str):
            out += seg.replace("\n", " ")
        else:
            kind = seg["type"]
            #  TODO: check if user exists on both ends, and possibly drop if so
            if kind == "user_mention":
                out += f"@{random_color(seg['id'])}{seg['name']}{color_code('')}"
            elif kind == "channel_mention": # these appear to be clickable across servers/guilds
                out += f"#{seg['name']}"
            else: logging.warn("Unrecognized message seg %s", kind)
    return out.strip()

global_conn = None
unlisten = None

async def initialize():
    logging.info("Initializing IRC link")

    joined = set()

    loop = asyncio.get_event_loop()
    irc.client.ServerConnection.buffer_class = buffer.LenientDecodingLineBuffer # should not crash in the face of invalid UTF-8
    reactor = irc.client_aio.AioReactor(loop=loop)
    conn = await reactor.server().connect(util.config["irc"]["server"], util.config["irc"]["port"], util.config["irc"]["nick"])
    global global_conn
    global_conn = conn

    def inuse(conn, event):
        conn.nick(scramble(conn.get_nickname()))

    def pubmsg(conn, event):
        msg = eventbus.Message(eventbus.AuthorInfo(event.source.nick, str(event.source), None), [" ".join(event.arguments)], (util.config["irc"]["name"], event.target), util.random_id(), [])
        asyncio.create_task(eventbus.push(msg))

    async def on_bridge_message(channel_name, msg):
        if channel_name in util.config["irc"]["channels"]:
            if channel_name not in joined: conn.join(channel_name)
            # ping fix - zero width space embedded in messages
            line = f"<{random_color(msg.author.id)}{msg.author.name[0]}\u200B{msg.author.name[1:]}{color_code('')}> " + render_formatting(msg.message)[:400]
            conn.privmsg(channel_name, line)
            for at in msg.attachments:
                conn.privmsg(channel_name, f"-> {at.filename}: {at.proxy_url}")
        else:
            logging.warning("IRC channel %s not allowed", channel_name)

    def connect(conn, event):
        for channel in util.config["irc"]["channels"]:
            conn.join(channel, key=util.config["irc"]["channel_keys"].get(channel, ""))
            logging.info("Connected to %s on IRC", channel)
            joined.add(channel)

    def disconnect(conn, event):
        logging.warn("Disconnected from IRC, reinitializing")
        teardown()
        asyncio.create_task(initialize)

    # TODO: do better thing
    conn.add_global_handler("welcome", connect)
    conn.add_global_handler("disconnect", disconnect)
    conn.add_global_handler("nicknameinuse", inuse)
    conn.add_global_handler("pubmsg", pubmsg)

    global unlisten
    unlisten = eventbus.add_listener(util.config["irc"]["name"], on_bridge_message)

def setup(bot):
    asyncio.create_task(initialize())

def teardown(bot):
    if global_conn: global_conn.disconnect()
    if unlisten: unlisten()
