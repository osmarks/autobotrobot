import re
import datetime
import parsedatetime
import ast
import copy
import random
from dateutil.relativedelta import relativedelta
import json
import discord
import toml
import os.path
from discord.ext import commands
import hashlib
import time
import math
import pytz
import collections
import aiohttp
import string
from pathlib import Path

config = {}

# update in place for runtime config reload
def load_config():
    for k, v in toml.load(open(os.path.join(os.path.dirname(__file__), "../config.toml"), "r")).items(): config[k] = v

load_config()

def timestamp(): return int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
def timestamp_µs(): return int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp() * 1e6)

prefixes = {
    # big SI prefixes
    "Y": 24, "Z": 21, "E": 18, "P": 15, "T": 12, "G": 9, "M": 6, "k": 3, "h": 2, "da": 1,
    # small SI prefixes
    "d": -1, "c": -2, "m": -3, "µ": -6, "μ": -6, "u": -6, "n": -9, "p": -12, "f": -15, "a": -18, "z": -21, "y": -24,
    # highly dubiously useful unofficial prefixes
    "R": 27, "r": -27, "Q": 30, "q": -30, "X": 27, "x": -27, "W": 30, "w": -30
}
number = "(-?[0-9]+(?:\\.[0-9]+)?)(" + "|".join(prefixes.keys()) + ")?"

time_units = (
    ("galacticyears", "cosmicyears", "gy", "[Cc]y"),
    ("years", "y"),
    ("beelifespans", "🐝", "bees?"),
    ("months", "mo"),
    ("semesters",),
    ("fortnights", "ft?n?"),
    ("weeks", "w"),
    ("days", "d"),
    ("hours", "h"),
    # Wikipedia tells me this is a traditional Chinese timekeeping unit
    ("ke",),
    ("minutes", "m"),
    ("seconds", "s"),
    ("helloboiseconds", "hbseconds", "hbs")
)

tu_mappings = {
    # dateutil dislikes fractional years, but this is 250My
    "galacticyears": (7.8892315e15, "seconds"),
    # apparently the average lifespan of a Western honey bee - I'm not very sure whether this is workers/drones/queens or what so TODO
    "beelifespans": lambda: (random.randint(122, 152), "days"),
    "semesters": (18, "weeks"),
    "fortnights": (2, "weeks"),
    "ke": (864, "seconds"),
    "helloboiseconds": (1800, "seconds")
}

fractional_tu_mappings = {
    "years": (365.25, "days"), # Julian year
    "months": (30.4375, "days") # average month length
}

def rpartfor(u):
    if u[0][-1] == "s": 
        l = [u[0] + "?"]
        l.extend(u[1:])
    else: l = u
    return f"(?:(?P<{u[0]}>{number})(?:{'|'.join(l)}))?[\t\n\r ]*"

short_timedelta_regex = re.compile("\n".join(map(rpartfor, time_units)), re.VERBOSE)

def parse_prefixed(s):
    match = re.match(number, s)
    if not match: raise ValueError("does not match metric-prefixed integer format - ensure prefix is valid")
    num = float(match.group(1))
    prefix = match.group(2)
    if prefix: num *= (10 ** prefixes[prefix])
    return num

def parse_short_timedelta(text):
    match = short_timedelta_regex.fullmatch(text)
    if match is None or not match.group(0): raise ValueError("parse failed")
    data = { k: parse_prefixed(v) if v else 0 for k, v in match.groupdict().items() }
    for tu, mapping in tu_mappings.items():
        if callable(mapping): mapping = mapping()
        qty, resunit = mapping
        data[resunit] += qty * data[tu]
        del data[tu]
    for tu, (qty, unit) in fractional_tu_mappings.items():
        if tu in data and math.floor(data[tu]) != data[tu]:
            whole = math.floor(data[tu])
            fractional = data[tu] - whole
            data[tu] = whole
            data[unit] += fractional * qty
    return datetime.datetime.now(tz=datetime.timezone.utc) + relativedelta(**data)

cal = parsedatetime.Calendar()
def parse_humantime(text, tz):
    dt_tuple = cal.parseDT(text, tzinfo=tz)
    if dt_tuple: return dt_tuple[0]
    else: raise ValueError("parse failed")

def parse_time(text, tz):
    try: return datetime.datetime.strptime(text, "%Y-%m-%d")
    except: pass
    try: return parse_short_timedelta(text)
    except: pass
    try: return parse_humantime(text, tz)
    except: pass
    raise ValueError("time matches no available format")

def format_time(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")

timeparts = (
    ("y", "years"),
    ("mo", "months"),
    ("d", "days"),
    ("h", "hours"),
    ("m", "minutes"),
    ("s", "seconds")
)

def format_timedelta(from_, to):
    d = relativedelta(to, from_)
    out = ""
    for short, attr in timeparts:
        x = getattr(d, attr)
        if x != 0: out += str(x) + short
    return "0s" if out == "" else out

CODEBLOCK_REGEX = "^[^`]*```[a-zA-Z0-9_\\-+]*\n(.+)```$"
CODELINE_REGEX = "^[^`]*`(.*)`$"
def extract_codeblock(s):
    match1 = re.match(CODEBLOCK_REGEX, s, flags=re.DOTALL)
    match2 = re.match(CODELINE_REGEX, s, flags=re.DOTALL)
    if match1: return match1.group(1)
    elif match2: return match2.group(1)
    else: return s.strip()

# from https://github.com/Gorialis/jishaku/blob/master/jishaku/repl/compilation.py
CORO_CODE = """
async def repl_coroutine():
    import asyncio
    import aiohttp
    import discord
    from discord.ext import commands
"""
async def async_exec(code, loc, glob):
    user_code = ast.parse(code, mode='exec')
    wrapper = ast.parse(CORO_CODE, mode='exec')
    funcdef = wrapper.body[-1]
    funcdef.body.extend(user_code.body)
    last_expr = funcdef.body[-1]

    if isinstance(last_expr, ast.Expr):
        funcdef.body.pop()
        funcdef.body.append(ast.Return(last_expr.value))
    ast.fix_missing_locations(wrapper)

    exec(compile(wrapper, "<repl>", "exec"), loc, glob)
    return await (loc.get("repl_coroutine") or glob.get("repl_coroutine"))()

def make_embed(*, fields=(), footer_text=None, **kwargs):
    embed = discord.Embed(**kwargs)
    for field in fields:
        if len(field) > 2:
            embed.add_field(name=field[0], value=field[1], inline=field[2])
        else:
            embed.add_field(name=field[0], value=field[1], inline=False)
    if footer_text:
        embed.set_footer(text=footer_text)
    return embed

def error_embed(msg, title="Error"): return make_embed(color=config["colors"]["error"], description=msg, title=title)
def info_embed(title, msg, fields=()): return make_embed(color=config["colors"]["info"], description=msg, title=title, fields=fields)

# https://github.com/LyricLy/Esobot/blob/bcc9e548c84ea9b23fc832d0b0aaa8288de64886/cogs/general.py
lyrictable_raw = {
            "a": "а",
            "c": "с",
            "e": "е",
            "s": "ѕ",
            "i": "і",
            "j": "ј",
            "o": "о",
            "p": "р",
            "y": "у",
            "x": "х"
        }
lyrictable = str.maketrans({v: k for k, v in lyrictable_raw.items()})

apioinfixes = ["cryo", "pyro", "chrono", "meta", "anarcho", "arachno", "aqua", "accelero", "hydro", "radio", "xeno", "morto", "thanato", "memeto", 
    "contra", "umbra", "macrono", "acantho", "acousto", "aceto", "acro", "aeolo", "hexa", "aero", "aesthio", "agro", "ferro", "alumino",
    "ammonio", "anti", "ankylo", "aniso", "annulo", "apo", "abio", "archeo", "argento", "arseno", "arithmo", "astro", "atlo", "auto", "axo",
    "azido", "bacillo", "bario", "balneo", "baryo", "basi", "benzo", "bismuto", "boreo", "biblio", "spatio", "boro", "bromo", "brachio",
    "bryo", "bronto", "calci", "caco", "carbo", "cardio", "cata", "iso", "centi", "ceno", "centro", "cero", "chalco", "chemo", "chloro",
    "chiono", "choano", "choro", "chromato", "chromo", "chryso", "chylo", "cine", "circum", "cirro", "climo", "cobalti", "coeno", "conico",
    "cono", "cortico", "cosmo", "crypto", "crano", "crystallo", "cyano", "cyber", "cyclo", "deca", "dendro", "cyno", "dactylo", "poly", "deutero",
    "dia", "digi", "diplo", "docosa", "disto", "dromo", "duo", "dynamo", "econo", "ecclesio", "echino", "eco", "ecto", "electro", "eigen", "eka",
    "elasto", "eicosa", "enviro", "enantio", "endo", "exo", "oeno", "femto", "ergato", "ergo", "etho", "euryo", "extro", "fluoro", "fructo",
    "galacto", "galvano", "glacio", "gibi", "glosso", "gluco", "glyco", "grammatico", "grapho", "gravi", "gyro", "hadro", "halo", "hapto", "hecto",
    "heli", "helio", "helico", "historio", "holo", "hella", "hemi", "hepta", "herpeto", "hiero", "hippo", "homo", "hoplo", "horo", "hyalo", "hyeto",
    "hygro", "hylo", "hypho", "hypno", "hypso", "iatro", "icthyo", "ichno", "icosa", "ideo", "idio", "imido", "info", "infra", "insta", "inter",
    "intro", "iodo", "iono", "irid", "iri", "iridio", "kilo", "diago", "juxta", "juridico", "bureaucrato", "entropo", "karyo", "kineto", "klepto",
    "konio", "kymo", "lamino", "leipdo", "lepto", "levo", "dextro", "lexico", "cognito", "ligno", "limno", "lipo", "litho", "logo", "magneto",
    "magnesio", "mega", "mento", "mercurio", "metallo", "mechano", "meco", "medio", "melo", "mero", "meso", "meteoro", "metro", "micto",
    "mono", "miso", "mnemo", "morpho", "myco", "myo", "myria", "mytho", "nano", "necro", "neo", "neutro", "neuro", "nitro", "nycto", "nucleo",
    "narco", "noto", "octo", "ochlo", "odonto", "oculo", "oligo", "opto", "organo", "ornitho", "osmio", "oneiro", "onto", "oxalo", "pachy",
    "paleo", "pali", "pallado", "pano", "para", "penta", "per", "patho", "pebi", "peloro", "pene", "petro", "pharma", "pheno", "philo", "pico",
    "piezo", "phono", "photo", "phospho", "physio", "physico", "phyto", "post", "pisci", "placo", "platy", "pleo", "plumbo", "pluto",
    "pneumato", "politico", "proto", "potassio", "proteo", "pseudo", "psycho", "ptero", "pykno", "quasi", "quadri", "recti", "retino", "retro",
    "rheo", "rhino", "rhizo", "rhodo", "roto", "rutheno", "saccharo", "sapo", "sauro", "seismo", "seleno", "septa", "silico", "scoto", "semanto",
    "sialo", "socio", "sodio", "skeleto", "somato", "somno", "sono", "spectro", "speleo", "sphero", "spino", "spiro", "sporo", "stanno", "stato",
    "steno", "stereo", "stegano", "strato", "hyper", "sulpho", "telluro", "stygo", "tachy", "tauto", "taxo", "techno", "tecto", "tele", "teleo",
    "temporo", "tera", "tetra", "thalasso", "thaumato", "thermo", "tephro", "tessera", "thio", "titano", "tomo", "topo", "tono", "tungsto",
    "turbo", "tyranno", "ultra", "undeca", "tribo", "trito", "tropho", "tropo", "uni", "urano", "video", "viro", "visuo", "xantho", "xenna",
    "xeri", "xipho", "xylo", "xyro", "yocto", "yttro", "zepto", "zetta", "zinco", "zirco", "zoo", "zono", "zygo", "templateo", "rustaceo", "mnesto",
    "amnesto", "cetaceo", "anthropo", "ioctlo", "crustaceo", "citrono", "apeiro", "Ægypto", "equi", "anglo", "atto", "ortho", "macro", "micro", "auro", 
    "Australo", "dys", "eu", "giga", "Inver", "omni", "semi", "Scando", "sub", "super", "trans", "ur-", "un", "mid", "mis", "ante", "intra"]
apiosuffixes = ["hazard", "form"]

def apioform():
    out = ""
    if random.randint(0, 3) == 0:
        out += random.choice(apioinfixes)
    out += "apio"
    i = 1
    while True:
        out += random.choice(apioinfixes)
        if random.randint(0, i) > 0: break
        i += 1
    out += random.choice(apiosuffixes)
    return out

def unlyric(text):
    return text.translate(lyrictable).replace("\u200b", "")

def gen_codeblock(content):
    return "```\n" + content.replace("```", "\\`\\`\\`")[:1900] + "\n```"

def json_encode(x): return json.dumps(x, separators=(',', ':'))

async def server_mod_check(ctx):
    return ctx.channel.permissions_for(ctx.author).manage_channels or (await extpriv_check(ctx))

async def admin_check(ctx):
    return await ctx.bot.is_owner(ctx.author)

async def extpriv_check(ctx):
    return await ctx.bot.is_owner(ctx.author) or ctx.author.id in config["extpriv_users"]

async def get_asset(bot: commands.Bot, identifier):
    safe_ident = re.sub("[^A-Za-z0-9_.-]", "_", identifier)
    x = await bot.database.execute_fetchone("SELECT * FROM assets WHERE identifier = ?", (safe_ident,))
    if x:
        return x["url"]
    file = discord.File(os.path.join("./assets", identifier), filename=safe_ident)
    message = await (bot.get_channel(config["image_upload_channel"])).send(identifier, file=file)
    url = message.attachments[0].url
    await bot.database.execute("INSERT INTO assets VALUES (?, ?)", (safe_ident, url))
    return url

def hashbow(thing):
    return int.from_bytes(hashlib.blake2b(thing.encode("utf-8")).digest()[:3], "little")

IDWrapper = collections.namedtuple("IDWrapper", ["id"])
AltCtx = collections.namedtuple("AltCtx", ["author", "guild", "bot"])

async def user_config_lookup(ctx, cfg):
    userdata = ctx.bot.get_cog("Userdata")
    if userdata is None: return
    row = await userdata.get_userdata(ctx.author.id, ctx.guild and ctx.guild.id, cfg)
    if row is None: return
    return row["value"]

async def get_user_timezone(ctx):
    tzname = await user_config_lookup(ctx, "tz")
    if tzname:
        try:
            return pytz.timezone(tzname)
        except pytz.UnknownTimeZoneError:
            raise commands.UserInputError(f"Invalid time zone {tzname}")
    else:
        return pytz.utc
def in_timezone(dt, tz):
    # we already have an aware datetime, so return that and localized version
    if dt.tzinfo is not None: return dt, dt.astimezone(tz)
    else:
        aware = tz.localize(dt)
        return aware, aware.astimezone(pytz.utc)

extensions = (
    "reminders",
    "debug",
    "telephone",
    "achievement",
    "heavserver",
    "voice",
    "commands",
    "userdata",
    "irc_link",
    "search",
    "esoserver",
    "sentience"
)

# https://github.com/SawdustSoftware/simpleflake/blob/master/simpleflake/simpleflake.py

SIMPLEFLAKE_EPOCH = 946702800
#field lengths in bits
SIMPLEFLAKE_TIMESTAMP_LENGTH = 43
SIMPLEFLAKE_RANDOM_LENGTH = 21
#left shift amounts
SIMPLEFLAKE_RANDOM_SHIFT = 0
SIMPLEFLAKE_TIMESTAMP_SHIFT = 21

def random_id():
    second_time = time.time()
    second_time -= SIMPLEFLAKE_EPOCH
    millisecond_time = int(second_time * 1000)
    randomness = random.getrandbits(SIMPLEFLAKE_RANDOM_LENGTH)
    return (millisecond_time << SIMPLEFLAKE_TIMESTAMP_SHIFT) + randomness

def chunks(source, length):
    for i in range(0, len(source), length):
        yield source[i : i+length]

async def generate(sess: aiohttp.ClientSession, prompt, stop=["\n"]):
    async with sess.post(config["ai"]["llm_backend"], json={
        "prompt": prompt,
        "max_tokens": 200,
        "stop": stop,
        "client": "abr",
        **config["ai"].get("params", {})
    }, headers=config["ai"].get("headers", {})) as res:
        data = await res.json()
        return data["choices"][0]["text"]

filesafe_charset = string.ascii_letters + string.digits + "-"

TARGET_FORMAT = "jpegh"
def meme_thumbnail(results, result):
    try:
        format_id = results["formats"].index(TARGET_FORMAT)
    except ValueError:
        format_id = None

    if not format_id:
        return Path(config["memetics"]["meme_base"]) / result[1]
    else:
        format_id = 1 << format_id
        if result[3] & format_id != 0:
            return Path(config["memetics"]["thumb_base"]) / f"{result[2]}{TARGET_FORMAT}.{results['extensions'][TARGET_FORMAT]}"
        else:
            return Path(config["memetics"]["meme_base"]) / result[1]