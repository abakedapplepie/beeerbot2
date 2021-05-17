import json
import random
import os
import codecs
import discord
from discord.ext import commands
import logging
import re

class CardsAgainstHumanity(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("beeerbot")
        self.log.info("CAH initialized")
        self.config = bot.config
        
        self.card_data = {}
        try:
            self.card_data.clear()
            with codecs.open(os.path.join(self.config.bot_options.data_files, "gnomecards.json"), encoding="utf-8") as f:
                self.card_data.update(json.load(f))
        except Exception as e:
            self.log.error('Exception', exc_info=True)

    async def cog_command_error(self, ctx, error):
        return

    @commands.command(aliases=["cah"])
    async def CAHwhitecard(self, ctx, word):
        '''Submit text to be used as a CAH whitecard'''
        return await ctx.send(random.choice(self.card_data['black']).format(word))

    @commands.command(aliases=["cahb"])
    async def CAHblackcard(self, ctx, *, text):
        '''Submit text with _ for the bot to fill in the rest. You can submit text with multiple _'''

        def blankfiller(matchobj):
            return random.choice(self.card_data['white'])

        out = re.sub(r'\b_\b', blankfiller, text)
        return await ctx.send(out)

def setup(bot):
    bot.add_cog(CardsAgainstHumanity(bot))
