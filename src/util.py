import re
import datetime
import parsedatetime
import ast
import copy
import random
from dateutil.relativedelta import relativedelta

# from here: https://github.com/Rapptz/RoboDanny/blob/18b92ae2f53927aedebc25fb5eca02c8f6d7a874/cogs/utils/time.py
short_timedelta_regex = re.compile("""
(?:(?P<years>[0-9]{1,12})(?:years?|y))?        # e.g. 2y
(?:(?P<months>[0-9]{1,12})(?:months?|mo))?     # e.g. 2months
(?:(?P<weeks>[0-9]{1,12})(?:weeks?|w))?        # e.g. 10w
(?:(?P<days>[0-9]{1,12})(?:days?|d))?          # e.g. 14d
(?:(?P<hours>[0-9]{1,12})(?:hours?|h))?        # e.g. 12h
(?:(?P<minutes>[0-9]{1,12})(?:minutes?|m))?    # e.g. 10m
(?:(?P<seconds>[0-9]{1,12})(?:seconds?|s))?    # e.g. 15s """, re.VERBOSE)

def parse_short_timedelta(text):
    match = short_timedelta_regex.fullmatch(text)
    if match is None or not match.group(0): raise ValueError("parse failed")
    data = { k: int(v) for k, v in match.groupdict(default=0).items() }
    return datetime.datetime.utcnow() + relativedelta(**data)

cal = parsedatetime.Calendar()
def parse_humantime(text):
    time_struct, parse_status = cal.parse(text)
    if parse_status == 1: return datetime.datetime(*time_struct[:6])
    else: raise ValueError("parse failed")

def parse_time(text):
    try: return datetime.datetime.strptime(text, "%d/%m/%Y")
    except: pass
    try: return parse_short_timedelta(text)
    except: pass
    try: return parse_humantime(text)
    except: pass
    raise ValueError("could not parse time")

def format_time(dt):
    return dt.strftime("%H:%M:%S %d/%m/%Y")

CODEBLOCK_REGEX = "^[^`]*```[a-zA-Z0-9_\-+]*\n(.+)```$"
CODELINE_REGEX = "^[^`]*`(.*)`$"
def extract_codeblock(s):
    match1 = re.match(CODEBLOCK_REGEX, s, flags=re.DOTALL)
    match2 = re.match(CODELINE_REGEX, s, flags=re.DOTALL)
    if match1: return match1.group(1)
    elif match2: return match2.group(1)
    else:
        return s.strip()

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

apioprefixes = ["cryo", "meta", "chrono", "contra", "ortho", "macro", "micro"]
apioinfixes = ["cryo", "pyro", "chrono", "meta", "anarcho", "arachno", "aqua", 
    "hydro", "radio", "xeno", "morto", "thanato", "memeto", "contra", "umbra", "macrono"]
apiosuffixes = ["hazard", "form"]

def apioform():
    out = ""
    if random.randint(0, 4) == 0:
        out += random.choice(apioprefixes)
    out += "apio"
    while True:
        out += random.choice(apioinfixes)
        if random.randint(0, 1) == 0: break
    out += random.choice(apiosuffixes)
    return out

def unlyric(text):
    return text.translate(lyrictable).replace("\u200b", "")