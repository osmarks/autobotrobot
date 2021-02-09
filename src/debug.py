import util
import asyncio
import traceback
import re
from discord.ext import commands
import util

def setup(bot):
    @bot.group(help="Debug/random messing around utilities. Owner-only.")
    @commands.check(util.admin_check)
    async def magic(ctx):
        if ctx.invoked_subcommand == None:
            return await ctx.send("Invalid magic command.")

    @magic.command(rest_is_raw=True, brief="Execute Python.")
    async def py(ctx, *, code):
        "Executes Python. You may supply a codeblock. Comments in the form #timeout:([0-9]+) will be used as a timeout specifier. React with :x: to stop, probably."
        timeout = 5.0
        timeout_match = re.search("#timeout:([0-9]+)", code, re.IGNORECASE)
        if timeout_match:
            timeout = int(timeout_match.group(1))
            if timeout == 0: timeout = None
        code = util.extract_codeblock(code)
        try:
            loc = {
                **locals(),
                "bot": bot,
                "ctx": ctx,
                "db": bot.database
            }

            def check(re, u): return str(re.emoji) == "❌" and u == ctx.author

            result = None
            async def run():
                nonlocal result
                result = await util.async_exec(code, loc, globals())
            halt_task = asyncio.create_task(bot.wait_for("reaction_add", check=check))
            exec_task = asyncio.create_task(run())
            done, pending = await asyncio.wait((exec_task, halt_task), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            for task in done: task.result() # get exceptions
            for task in pending: task.cancel()
            if result != None:
                if isinstance(result, str):
                    await ctx.send(result[:2000])
                else:
                    await ctx.send(util.gen_codeblock(repr(result)))
        except (TimeoutError, asyncio.CancelledError):
            await ctx.send(embed=util.error_embed("Timed out."))
        except BaseException as e:
            await ctx.send(embed=util.error_embed(util.gen_codeblock(traceback.format_exc())))

    @magic.command(rest_is_raw=True, help="Execute SQL code against the database.")
    async def sql(ctx, *, code):
        "Executes SQL (and commits). You may use a codeblock, similarly to with py."
        code = util.extract_codeblock(code)
        try:
            csr = bot.database.execute(code)
            out = ""
            async with csr as cursor:
                async for row in cursor:
                    out += " ".join(map(repr, row)) + "\n"
            await ctx.send(util.gen_codeblock(out))
            await bot.database.commit()
        except Exception as e:
            await ctx.send(embed=util.error_embed(util.gen_codeblock(traceback.format_exc())))

    @magic.command(help="Reload configuration file.")
    async def reload_config(ctx):
        util.load_config()
        ctx.send("Done!")

    @magic.command(help="Reload extensions (all or the specified one).")
    async def reload_ext(ctx, ext="all"):
        if ext == "all":
            for ext in util.extensions: bot.reload_extension(ext)
        else: bot.reload_extension(ext)
        await ctx.send("Done!")