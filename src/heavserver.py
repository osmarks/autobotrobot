import util
import random
import logging
import discord

def setup(bot):
	@bot.listen()
	async def on_member_join(member):
		if member.guild.id == util.config["heavserver"]["id"]:
			logging.info("%s (%d) joined heavserver", member.name, member.id)
			if member.bot:
				print(member.guild, member.guild.roles)
				await member.add_roles(discord.utils.get(member.guild.roles, id=util.config["heavserver"]["quarantine_role"]))
			mod_roles = set()
			can_add = util.config["heavserver"]["moderator_roles"][:]
			while True:
				x = random.choice(can_add)
				role = discord.utils.get(member.guild.roles, id=x)
				mod_roles.add(role)
				can_add.remove(x)
				if random.randint(0, 3) != 0 or len(can_add) == 0: break
			await member.add_roles(*mod_roles)