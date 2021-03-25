import aiohttp
import discord
import asyncio
import logging
import discord.ext.commands as commands
import html.parser

class Parser(html.parser.HTMLParser):
    def __init__(self):
        self.links = []
        super().__init__()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("class") == "result__a" and "https://duckduckgo.com/y.js?ad_provider" not in attrs["href"]:
            self.links.append(attrs["href"])
    
class DuckDuckGo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    @commands.command()
    async def search(self, ctx, *, query):
        async with ctx.typing():
            async with self.session.post("https://html.duckduckgo.com/html/", data={ "q": query, "d": "" }) as resp:
                if resp.history:
                    await ctx.send(resp.url, reference=ctx.message)
                else:
                    p = Parser()
                    txt = await resp.text()
                    p.feed(txt)
                    p.close()
                    try:
                        return await ctx.send(p.links[0], reference=ctx.message)
                    except IndexError:
                        return await ctx.send("No results.", reference=ctx.message)

    def cog_unload(self):
        asyncio.create_task(self.session.close())

def setup(bot):
    cog = DuckDuckGo(bot)
    bot.add_cog(cog)