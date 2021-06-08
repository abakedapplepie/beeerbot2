import json
import logging
import random
import re
from typing import Dict, List

from discord.ext import commands


class CardsAgainstHumanity(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger()
        self.config = bot.config
        self.card_data: Dict[str, List[str]] = {}
        self.load_cards()
        self.log.info("CAH initialized")

    async def cog_command_error(self, ctx, error):
        return

    def load_cards(self):
        try:
            self.card_data.clear()
            data_file = self.bot.data_path / "gnomecards.json"
            with data_file.open(encoding="utf-8") as f:
                self.card_data.update(json.load(f))
        except Exception as e:
            self.log.error('Exception', exc_info=True)

    @commands.command(aliases=["cah"])
    async def CAHwhitecard(self, ctx, *, text):
        """<text> - Submit text to be used as a CAH whitecard"""
        return await ctx.send(random.choice(self.card_data['black']).format(text))

    @commands.command(aliases=["cahb"])
    async def CAHblackcard(self, ctx, *, text):
        """<text> - Submit text with _ for the bot to fill in the rest. You can submit text with multiple _"""
        CardText = text.strip()

        def blankfiller(matchobj):
            return random.choice(self.card_data['white'])

        out = re.sub(r"\b_\b", blankfiller, CardText)
        return await ctx.send(out)

def setup(bot):
    bot.add_cog(CardsAgainstHumanity(bot))
