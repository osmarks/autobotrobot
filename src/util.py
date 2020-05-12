import re
import datetime
import parsedatetime
from dateutil.relativedelta import relativedelta

# from here: https://github.com/Rapptz/RoboDanny/blob/18b92ae2f53927aedebc25fb5eca02c8f6d7a874/cogs/utils/time.py
short_timedelta_regex = re.compile("""
(?:(?P<years>[0-9])(?:years?|y))?             # e.g. 2y
(?:(?P<months>[0-9]{1,2})(?:months?|mo))?     # e.g. 2months
(?:(?P<weeks>[0-9]{1,4})(?:weeks?|w))?        # e.g. 10w
(?:(?P<days>[0-9]{1,5})(?:days?|d))?          # e.g. 14d
(?:(?P<hours>[0-9]{1,5})(?:hours?|h))?        # e.g. 12h
(?:(?P<minutes>[0-9]{1,6})(?:minutes?|m))?    # e.g. 10m
(?:(?P<seconds>[0-9]{1,7})(?:seconds?|s))?    # e.g. 15s """, re.VERBOSE)

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