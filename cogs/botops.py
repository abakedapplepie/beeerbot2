import datetime
import logging

import discord
from discord.ext import commands


class BotOps(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger(__name__)

    async def cog_command_error(self, ctx, error):
        return

    @commands.command(hidden=True)
    @commands.is_owner()
    async def restart(self, ctx):
        """restarts the bots"""
        embed = discord.Embed(
            title = f"{self.bot.user.name} restarting!",
            colour = 0xcc3366,
            timestamp = datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_author(
            name = ctx.author.name,
            icon_url = ctx.author.avatar_url
        )
        await self.bot.stats_webhook.send(embed=embed)

        await ctx.message.add_reaction('✅')
        await self.bot.close()

def setup(bot):
    bot.add_cog(BotOps(bot))
