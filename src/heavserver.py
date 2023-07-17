import util
import random
import logging
import discord

import metrics

async def setup(bot):
	@bot.listen()
	async def on_member_join(member):
		if member.guild and member.guild.id == util.config["heavserver"]["id"]:
			logging.info("%s (%d) joined heavserver", member.display_name, member.id)
			if member.bot:
				await member.add_roles(discord.utils.get(member.guild.roles, id=util.config["heavserver"]["quarantine_role"]))
			await member.add_roles(discord.utils.get(member.guild.roles, id=random.choice(util.config["heavserver"]["moderator_roles"][:])))