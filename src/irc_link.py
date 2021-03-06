import eventbus
import asyncio
import irc.client_aio
import random
import util
import logging
import hashlib

def scramble(text):
    n = list(text)
    random.shuffle(n)
    return "".join(n)

def color_code(x):
    return f"\x03{x}"
def random_color(id): return color_code(hashlib.blake2b(str(id).encode("utf-8")).digest()[0] % 13 + 2)

async def initialize():
    joined = set()

    loop = asyncio.get_event_loop()
    reactor = irc.client_aio.AioReactor(loop=loop)
    conn = await reactor.server().connect(util.config["irc"]["server"], util.config["irc"]["port"], util.config["irc"]["nick"])

    def inuse(conn, event):
        conn.nick(scramble(conn.get_nickname()))

    def pubmsg(conn, event):
        msg = eventbus.Message(eventbus.AuthorInfo(event.source.nick, str(event.source), None), " ".join(event.arguments), (util.config["irc"]["name"], event.target), util.random_id())
        asyncio.create_task(eventbus.push(msg))

    async def on_bridge_message(channel_name, msg):
        if channel_name in util.config["irc"]["channels"]:
            if channel_name not in joined: conn.join(channel_name)
            line = msg.message.replace("\n", " ")
            # ping fix - zero width space embedded in messages
            line = f"<{random_color(msg.author.id)}{msg.author.name[0]}\u200B{msg.author.name[1:]}{color_code('')}> " + line.strip()[:400]
            conn.privmsg(channel_name, line)
        else:
            logging.warning("IRC channel %s not allowed", channel_name)

    def connect(conn, event):
        for channel in util.config["irc"]["channels"]:
            conn.join(channel)
            logging.info("connected to %s", channel)
            joined.add(channel)

    # TODO: do better thing
    conn.add_global_handler("welcome", connect)
    conn.add_global_handler("disconnect", lambda conn, event: logging.warn("disconnected from IRC, oh no"))
    conn.add_global_handler("nicknameinuse", inuse)
    conn.add_global_handler("pubmsg", pubmsg)

    eventbus.add_listener(util.config["irc"]["name"], on_bridge_message)