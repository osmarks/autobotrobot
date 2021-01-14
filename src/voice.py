import util
import discord
from discord.oggparse import OggStream
# requests is for synchronous HTTP. This would be quite awful to use in the rest of the code, but is probably okay since voice code is in a separate thread
# This should, arguably, run in a separate process given python's GIL etc. but this would involve significant effort probably
import requests
import io
from discord.ext import commands


class HTTPSource(discord.AudioSource):
    def __init__(self, url):
        self.url = url
    async def start(self):
        bytestream = requests.get(self.url, stream=True).raw
        self.packets = OggStream(io.BufferedReader(bytestream, buffer_size=2**10)).iter_packets()
    def read(self): return next(self.packets, b"")
    def is_opus(self): return True

def setup(bot):
    # experimental, thus limit to me only
    @bot.group()
    @commands.check(util.admin_check)
    async def radio(ctx): pass

    @radio.command()
    async def connect(ctx, thing="main"):
        voice = ctx.author.voice
        if not voice: return await ctx.send(embed=util.error_embed("You are not in a voice channel."))
        if voice.mute: return await ctx.send(embed=util.error_embed("You are muted."))
        thing_url = util.config["radio_urls"].get(thing, None)
        if thing_url == None: return await ctx.send(embed=util.error_embed("No such radio thing."))
        existing = ctx.guild.voice_client
        if existing: await existing.disconnect()
        vc = await voice.channel.connect()
        src = HTTPSource(thing_url)
        await src.start()
        vc.play(src)

    @radio.command()
    async def disconnect(ctx):
        if ctx.guild.voice_client: 
            ctx.guild.voice_client.stop()
            await ctx.guild.voice_client.disconnect()

def teardown(bot):
    for guild in bot.guilds:
        if guild.voice_client:
            guild.voice_client.stop()