from discord.ext import commands
import discord
import logging
import asyncio
import discord
from datetime import datetime
import re
import collections

import util

Achievement = collections.namedtuple("Achievement", ["name", "condition", "description"])

achievements = {
    "spectre_of_communism": Achievement("Containment Efforts Ongoing", "Refer to the 'spectre of communism' in a message.", "A spectre is haunting Europe. The spectre of communism. Containment efforts are ongoing and full containment is projected by 2036."),
    "test": Achievement("Test", "Test achievement. Obtained for testing.", "Congratulations, you ran the test command!"),
    "spam": Achievement("beesbeesbeesbeesbeesbeesbeesbeesbees", "Send a long message containing the same thing repeatedly.", "You should probably not do this, nobody* likes spam!"),
    "unicode_abuse": Achievement("Anomalous Unicode", "Send a high proportion of weird Unicode characters in a message.", "h̵͖̻̮̗̹̆͛͆̎ͮͤͫ͛ͦ̓̅ͤ́͢é͒ͧ̌̀ͪ̈͂̈́̉ͣ̅̿̄̌̋̿̽̚͏̛͏͚̯͉̟͇̼̹͎ͅa̠̹̘͎̫̜̞̩͖̟̟͍͇͈͍̝͕͛ͥ͊̾̈́ͩͯͩͭ̆̋͐͗̉͋̓̀͝v͎͖̜͎͔̞͚͉̺̞̘̥͖̝͚̺̍ͤ̌͂ͨ̃̅ͫ̿͛ͯ̓̉̆̎͊̀̚̕͟s̪̠̟̣̝̹̭̻̈́ͤ͗̏ͮ̂ͯ̈́̊ͩ̓̆̌̆͌̽̓̈́̚͢͞e̛̞̙̜̗̰͕͕͎̺͍̭̲̟̭̲̫̬͓ͯ̅̓̆̂̔̃͟r̷̛̮̮͇̳̳̾ͯͮͩ̏͂ͤ̿̽ͧ͒͋́̕ͅͅv̴̠͉̼̮̭̘ͪͯͦ͌́ͯ̒̃̀́̃͜͝ͅe̵̷̢͕̣̻̥̲͓̼͍̱͕̮̯̱̤̹̱̝̎̓̈́̿ͤ̔̍ͭͭ͐ͅŗ̔ͮͯ͂́͏̻͈̱ͅ ̣͇̼͊̄ͫ̆̍̄̀̀̓͊͐͋̌͘͠į̱͔̰̭̫̱̫̊ͪ̅ͥ̈́ͥ̐͌̅ͪ̅ͨ̎̀͘͝s̍͑̌̋̅͌͂ͨͬͯ̇͊҉̛̱̺͕̰͓̗̖̬͡͡ ̥̤̺̖̪̪́ͯͣ̏̅̈ͣ̿̀͠͠͞i̢̛̭̰̻͈̦̣̮̞̤̩̊̌̾͛ͭͦ̆ͮ̃̎ͪ̔ͬ͊̆͂ͫͅn̸̖͚̣̪̩̏ͥ̈́̅ͯ̔͆́ͦ͗͛͒̃̃ͫ͟͜͝͠ȩ̸͎̟̣̞͉̫̗̙̻̯͍̰̣̌ͪͨ͛̆̕͡v̙͙̲͕͔̦̣̺͔̖͉̜̲̩̈̿ͥ̎͊̈́̊ͯͯ͒ͭ̊̀͢i̪͈̣̱̞̥̰̟̣̩̼̻̪̳̤͇̻̹͉͗ͭ͆̆̎̀͑͑̆͋̏̏͊ͣͦ͆ͣ̈́̓͟͢ţ̵̘̫̯͓̻̗͕̘͙̯̞̪̪̲̤̬̜͕ͫ̄̌̓̎͌ͧ̔͟͢ͅa̸̧̭̲̯̳̔́͋̐͂̇ͪ̔̐́̚͢b͐̅̔ͭ͗̊̂̾̀̓ͭͭ͑ͤ̏̐̃ͩͬ҉̞̼̮̤̝̲̳͓̗̤̫̭̝̹̙͘͟͝ļ̷͈̭̖͓̜̬͔̻͔̀̎ͯ͗̐̽̏ͦ̊͗ͧ́͘ͅe̢͍̦̗̬̝̠͔̳̣̯̮̣̹͍͙̞̜ͣ̉͆̊̀̎ͦ͌̂̋̊ͨ͛́")
}

async def achieve(bot: commands.Bot, message: discord.Message, achievement):
    guild_conf = await bot.database.execute_fetchone("SELECT achievement_messages FROM guild_config WHERE id = ?", (message.guild.id,))
    if guild_conf and guild_conf["achievement_messages"] == 0: return

    uid = message.author.id
    # ensure the user doesn't have achievements off
    conf = await bot.database.execute_fetchone("SELECT * FROM user_config")
    if conf and conf["achievement_tracking_enabled"] == 0: return
    if not conf:
        await bot.database.execute("INSERT INTO user_config VALUES (?, NULL)", (uid,))
        await bot.database.commit()
    # detect if achievement already earned
    if await bot.database.execute_fetchone("SELECT 1 FROM achievements WHERE user_id = ? AND achievement = ?", (uid, achievement)):
        return
    achievement_info = achievements[achievement]
    description = f"Congratulations! You achieved the achievement __{achievement_info.name}__.\n\n{achievement_info.description}\n*{achievement_info.condition}*"
    e = util.make_embed(description=description, title="Achievement achieved!", color=util.hashbow(achievement))
    e.set_thumbnail(url=await util.get_asset(bot, f"achievements/{achievement}.png"))
    await message.channel.send(embed=e)
    await bot.database.execute("INSERT INTO achievements VALUES (?, ?, ?)", (uid, achievement, util.timestamp()))
    await bot.database.commit()
    logging.info("awarded achievement %s to %s", message.author.name, achievement)

def setup(bot):
    @bot.group(name="achievements", aliases=["ach", "achieve", "achievement"], brief="Achieve a wide variety of fun achievements!", help=f"""
    Do things and get arbitrary achievements for them!
    Note that due to reasons messages for achievements will not be shown except in opted-in servers, although achievements will be gained regardless.
    """)
    async def achievements(ctx): pass

    @achievements.command(help="Enable/disable achievement messages on this guild.")
    @commands.check(util.server_mod_check(bot))
    async def set_enabled(ctx, on: bool):
        await bot.database.execute("INSERT OR REPLACE INTO guild_config VALUES (?, ?)", (ctx.guild.id, int(on)))
        await bot.database.commit()
        await ctx.send(f"Achievement messages set to: {on}")

    @achievements.command(help="Obtain a test achievement")
    async def test(ctx):
        await achieve(ctx.bot, ctx.message, "test")

    @bot.listen("on_message")
    async def message_listener(msg: discord.Message):
        content = msg.content
        content_len = len(msg.content)
        if re.match("spect(re|er).{,20}(communism|☭)", content): await achieve(bot, msg, "spectre_of_communism")
        if re.match(r"^(.+)\1+$", content) and len(content) >= 1950: await achieve(bot, msg, "spam")
        if content_len > 30 and (len(re.findall("[\u0300-\u036f\U00040000-\U0010FFFF]", content)) / content_len) > 0.35: await achieve(bot, msg, "unicode_abuse")