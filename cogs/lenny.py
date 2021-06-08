import json
import logging
import random
from typing import Dict, List

from discord.ext import commands


class Lenny(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("beeerbot")
        self.log.info("Lenny initialized")
        self.config = bot.config
        self.lenny_data: Dict[str, List[str]] = {}
        self.load_faces()

    async def cog_command_error(self, ctx, error):
        return

    def load_faces(self):
        try:
            self.lenny_data.clear()
            data_file = self.bot.data_path / "lenny.json"
            with data_file.open(encoding="utf-8") as f:
                self.lenny_data.update(json.load(f))
        except Exception as e:
            self.log.error('Exception', exc_info=True)

    @commands.command()
    async def lenny(self, ctx):
        """why the shit not lennyface"""
        try:
            return await ctx.send(random.choice(self.lenny_data['lenny']))
        except Exception as e:
            self.log.error('Exception', exc_info=True)

    @commands.command(aliases=["fle"])
    async def flenny(self, ctx):
        """flenny is watching."""
        try:
            return await ctx.send(random.choice(self.lenny_data['flenny']))
        except Exception as e:
            self.log.error('Exception', exc_info=True)

def setup(bot):
    bot.add_cog(Lenny(bot))
