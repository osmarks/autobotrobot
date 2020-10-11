import util
import asyncio
import traceback
from discord.ext import commands

def setup(bot):
    async def admin_check(ctx):
        return await bot.is_owner(ctx.author)

    @bot.group()
    @commands.check(admin_check)
    async def magic(ctx):
        if ctx.invoked_subcommand == None:
            return await ctx.send("Invalid magic command.")

    @magic.command(rest_is_raw=True)
    async def py(ctx, *, code):
        code = util.extract_codeblock(code)
        try:
            loc = {
                **locals(),
                "bot": bot,
                "ctx": ctx,
                "db": bot.database
            }
            result = await asyncio.wait_for(util.async_exec(code, loc, globals()), timeout=5.0)
            if result != None:
                if isinstance(result, str):
                    await ctx.send(result[:1999])
                else:
                    await ctx.send(util.gen_codeblock(repr(result)))
        except TimeoutError:
            await ctx.send(embed=util.error_embed("Timed out."))
        except BaseException as e:
            await ctx.send(embed=util.error_embed(util.gen_codeblock(traceback.format_exc())))

    @magic.command(rest_is_raw=True)
    async def sql(ctx, *, code):
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