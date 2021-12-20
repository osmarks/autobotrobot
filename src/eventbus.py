import asyncio
import prometheus_client
import dataclasses
import typing
import collections
import logging
import discord

import util

@dataclasses.dataclass
class AuthorInfo:
    name: str
    id: any
    avatar_url: str = None
    deprioritize: bool = False

def unpack_dataclass_without(d, without):
    dct = dict([(field, getattr(d, field)) for field in type(d).__dataclass_fields__])
    del dct[without]
    return dct

@dataclasses.dataclass
class Message:
    author: AuthorInfo
    message: list[typing.Union[str, dict]]
    source: (str, any)
    id: int
    attachments: list[discord.Attachment]
    action: bool = False
    reply: (AuthorInfo, str) = None

evbus_messages = prometheus_client.Counter("abr_evbus_messages", "Messages processed by event bus", ["source_type"])
evbus_messages_dropped = prometheus_client.Counter("abr_evbus_messages_dropped", "Messages received by event bus but dropped by rate limits", ["source_type"])

# maps each bridge destination type (discord/APIONET/etc) to the listeners for it
listeners = collections.defaultdict(set)

# maintains a list of all the unidirectional links between channels - key is source, values are targets
links = collections.defaultdict(set)

def find_all_destinations(source):
    visited = set()
    targets = set(links[source])
    while len(targets) > 0:
        current = targets.pop()
        targets.update(adjacent for adjacent in links[current] if not adjacent in visited)
        visited.add(current)
    return visited

# 5 messages per 5 seconds from each input channel
RATE = 10.0
PER = 5000000.0 # µs

RLData = collections.namedtuple("RLData", ["allowance", "last_check"])
rate_limiting = collections.defaultdict(lambda: RLData(RATE, util.timestamp()))

async def push(msg: Message):
    destinations = find_all_destinations(msg.source)
    if len(destinations) > 0:
        # "token bucket" rate limiting algorithm - max 10 messages per 5 seconds (half that for bots)
        # TODO: maybe separate buckets for bot and unbot?
        current = util.timestamp_µs()
        time_passed = current - rate_limiting[msg.source].last_check
        allowance = rate_limiting[msg.source].allowance
        allowance += time_passed * (RATE / PER)
        if allowance > RATE:
            allowance = RATE
        rate_limiting[msg.source] = RLData(allowance, current)
        if allowance < 1:
            evbus_messages_dropped.labels(msg.source[0]).inc()
            return
        allowance -= 2.0 if msg.author.deprioritize else 1.0
        rate_limiting[msg.source] = RLData(allowance, current)

        evbus_messages.labels(msg.source[0]).inc()
        for dest in destinations:
            if dest == msg.source: continue
            dest_type, dest_channel = dest
            for listener in listeners[dest_type]:
                asyncio.ensure_future(listener(dest_channel, msg))

def add_listener(s, l):
    listeners[s].add(l)
    return lambda: listeners[s].remove(l)

async def add_bridge_link(db, c1, c2, cause=None, bidirectional=True):
    logging.info("Bridging %s and %s (bidirectional: %s)", repr(c1), repr(c2), bidirectional)
    links[c1].add(c2)
    if bidirectional: links[c2].add(c1)
    await db.execute("INSERT INTO links VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING", (c1[0], c1[1], c2[0], c2[1], util.timestamp(), cause))
    if bidirectional: await db.execute("INSERT INTO links VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING", (c2[0], c2[1], c1[0], c1[1], util.timestamp(), cause))
    await db.commit()

async def remove_bridge_link(db, c1, c2, bidirectional=True):
    logging.info("Unbridging %s and %s (bidirectional: %s)", repr(c1), repr(c2), bidirectional)
    links[c1].remove(c2)
    if bidirectional: links[c2].remove(c1)
    await db.execute("DELETE FROM links WHERE (to_type = ? AND to_id = ?) AND (from_type = ? AND from_id = ?)", (c1[0], c1[1], c2[0], c2[1]))
    if bidirectional: await db.execute("DELETE FROM links WHERE (to_type = ? AND to_id = ?) AND (from_type = ? AND from_id = ?)", (c2[0], c2[1], c1[0], c1[1]))
    await db.commit()

async def initial_load(db):
    rows = await db.execute_fetchall("SELECT * FROM links")
    for row in rows:
        links[(row["from_type"], row["from_id"])].add((row["to_type"], row["to_id"]))
    logging.info("Loaded %d links", len(rows))