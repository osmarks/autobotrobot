import util
import random
import logging
import discord
import asyncio

import metrics

role_transfer_lock = asyncio.Lock()

def setup(bot):
	@bot.listen()
	async def on_message(message):
		if message.guild and message.guild.id == util.config["esoserver"]["id"]:
			async with role_transfer_lock: # prevent concurrency horrors - serialize accesses, probably
				for role in message.role_mentions:
					if role.id == util.config["esoserver"]["transfer_role"]: # transfer the role from sender to other pinged person
						if len(message.mentions) == 1:
							await message.author.remove_roles(role, reason="untransfer unrole")
							await message.mentions[0].add_roles(role, reason="transfer role")
							metrics.role_transfers.inc()
						return
				for user in message.mentions:
					for role in user.roles:
						if role.id == util.config["esoserver"]["transfer_role"]: # transfer from pingee to pinger
							await user.remove_roles(role, reason="untransfer unrole")
							await message.author.add_roles(role, reason="transfer role")
							metrics.role_transfers.inc()
							return