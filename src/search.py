import aiohttp
import discord
import asyncio
import logging
import discord.ext.commands as commands
import html.parser
import collections
import util
import io
import concurrent.futures

def pool_load_model(model):
    from transformers import pipeline
    qa_pipeline = pipeline("question-answering", model)
    globals()["qa_pipeline"] = qa_pipeline

def pool_operate(question, context):
    qa_pipeline = globals()["qa_pipeline"] 
    return qa_pipeline(question=question, context=context)

class Parser(html.parser.HTMLParser):
    def __init__(self):
        self.links = []
        super().__init__()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("class") == "result__a" and "https://duckduckgo.com/y.js?ad_provider" not in attrs["href"]:
            self.links.append(attrs["href"])
    
class Search(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.wp_cache = collections.OrderedDict()
        self.wp_search_cache = collections.OrderedDict()
        self.pool = None

    def ensure_pool(self):
        if self.pool is not None: return
        self.pool = concurrent.futures.ProcessPoolExecutor(max_workers=1, initializer=pool_load_model, initargs=(util.config["ir"]["model"],))

    @commands.command()
    async def search(self, ctx, *, query):
        "Search using DuckDuckGo. Returns the first result as a link."
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
    
    async def wp_search(self, query):
        async with self.session.get("https://en.wikipedia.org/w/api.php",
            params={ "action": "query", "list": "search", "srsearch": query, "utf8": "1", "format": "json", "srlimit": 1 }) as resp:
            data = (await resp.json())["query"]["search"]
        if len(data) > 0: return data[0]["title"]
        else: return None

    async def wp_fetch(self, page, *, fallback=True):
        async def fallback_to_search():
            if fallback:
                new_page = await self.wp_search(page)
                if len(self.wp_search_cache) > util.config["ir"]["cache_size"]:
                    self.wp_search_cache.popitem(last=False)
                self.wp_search_cache[page] = new_page
                if new_page is None: return None
                return await self.wp_fetch(new_page, fallback=False)

        if page in self.wp_cache: return self.wp_cache[page]
        if page in self.wp_search_cache: 
            if self.wp_search_cache[page] is None: return None
            return await self.wp_fetch(self.wp_search_cache[page], fallback=False)
        async with self.session.get("https://en.wikipedia.org/w/api.php", 
            params={ "action": "query", "format": "json", "titles": page, "prop": "extracts", "exintro": 1, "explaintext": 1 }) as resp:
            data = (await resp.json())["query"]
        if "-1" in data["pages"]:
            return await fallback_to_search()
        else:
            content = next(iter(data["pages"].values()))["extract"]
            if not content: return await fallback_to_search()
            if len(self.wp_cache) > util.config["ir"]["cache_size"]:
                self.wp_cache.popitem(last=False)
            self.wp_cache[page] = content
            return content

    @commands.command(aliases=["wp"])
    async def wikipedia(self, ctx, *, page):
        "Have you ever wanted the first section of a Wikipedia page? Obviously, yes. This gets that."
        content = await self.wp_fetch(page)
        if content is None:
            await ctx.send("Not found.")
        else:
            f = io.BytesIO(content.encode("utf-8"))
            file = discord.File(f, "content.txt")
            await ctx.send(file=file)

    @commands.command()
    async def experimental_qa(self, ctx, page, *, query):
        "Answer questions from the first part of a Wikipedia page, using a finetuned ALBERT model."
        self.ensure_pool()
        loop = asyncio.get_running_loop()
        async with ctx.typing():
            content = await self.wp_fetch(page)
            result = await loop.run_in_executor(self.pool, pool_operate, query, content)
            await ctx.send("%s (%f)" % (result["answer"].strip(), result["score"]))

    def cog_unload(self):
        asyncio.create_task(self.session.close())
        if self.pool is not None:
            self.pool.shutdown()

def setup(bot):
    cog = Search(bot)
    bot.add_cog(cog)