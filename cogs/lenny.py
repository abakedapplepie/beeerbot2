import json
import random
from pathlib import Path
import discord
from discord.ext import commands
import logging



class Lenny(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("beeerbot")
        self.log.info("Lenny initialized")
        self.config = bot.config
        
        self.lenny_data = {}

    async def cog_command_error(self, ctx, error):
        return

    #hook to !comic
    @commands.command()
    async def load_faces(self, ctx):
        try:
            self.lenny_data.clear()
            data_file = Path(self.config.bot_options.data_files) / "lenny.json"
            with data_file.open(encoding='utf-8') as f:
                self.lenny_data.update(json.load(f))
                self.log.info(lenny_data)
        except Exception as e:
            self.log.error('Exception', exc_info=True)

    @commands.command()
    async def lenny(self, ctx):
        """why the shit not lennyface"""
        try:
            return await ctx.send(random.choice(self.lenny_data['lenny']))
        except Exception as e:
            self.log.error('Exception', exc_info=True)

    @commands.command()
    async def flenny(self, ctx):
        """flenny is watching."""
        try:
            return await ctx.send(random.choice(lenny_data['flenny']))
        except Exception as e:
            self.log.error('Exception', exc_info=True)

def setup(bot):
    bot.add_cog(Lenny(bot))
