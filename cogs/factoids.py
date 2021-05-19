from collections import defaultdict
import logging
import string
from typing import Dict, List
import discord
from discord import utils
from discord.ext import commands, menus
from sqlalchemy import Column, String, insert, delete, select, update, and_

from util import database
from cogs.utils.formatting import get_text_list
from cogs.utils import checks
from cogs.utils.paginator import RoboPages, SimplePages, TextPageSource


# below is the default factoid in every channel you can modify it however you like
default_dict = {"beeerbot": "is the best"}

class FactoidsTable(database.base):
    __tablename__ = "factoids"
    word = Column(String(25), primary_key=True)
    data = Column(String(500))
    nick = Column(String(25))
    chan = Column(String(65), primary_key=True)


class Factoids(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.log = logging.getLogger("beeerbot")
        self.db = database.Session
        self.table = FactoidsTable
        self.factoid_char = bot.config.bot_options.get('factoid_char', '?')
        self.factoid_cache: Dict[str, Dict[str, str]] = defaultdict(default_dict.copy)
        self.load_cache()
        self.log.info("Factoids initialized")

    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.BadArgument):
            await ctx.send(error)
        if isinstance(error, commands.TooManyArguments):
            await ctx.send(f'You called the {ctx.command.name} command with too many arguments.')

    def load_cache(self):
        new_cache = self.factoid_cache.copy()
        new_cache.clear()
        for row in self.db.execute(select(self.table)).scalars().all():
            # assign variables
            chan = row.chan
            word = row.word
            data = row.data
            new_cache[chan][word] = data

        self.factoid_cache.clear()
        self.factoid_cache.update(new_cache)

    def add_factoid(self, word, chan, data, nick):
        """
        :type word: str
        :type chan: str
        :type data: str
        :type nick: str
        """
        if word in self.factoid_cache[chan]:
            # if we have a set value, update
            self.db.execute(
                update(self.table)
                .where(self.table.chan == chan, self.table.word == word)
                .values(data=data, nick=nick, chan=chan)
            )
            self.db.commit()
        else:
            # otherwise, insert
            self.db.execute(insert(self.table).values(word=word, data=data, nick=nick, chan=chan))
            self.db.commit()
        self.load_cache()

    def del_factoid(self, chan, word=None):
        """
        :type chan: str
        :type word: str
        """
        clause = self.table.chan == chan

        if word is not None:
            clause = and_(clause, self.table.word.in_(word))

        self.db.execute(delete(self.table).where(clause))
        self.db.commit()
        self.load_cache()

    @commands.command(aliases=["r"])
    async def remember(self, ctx, word, *data):
        """
        <word> [+]<data> - remembers <data> with <word> - add + to <data> to append.
        If the input starts with <act> the message will be sent as an action.
        If <user> in in the message it will be replaced by input arguments when command is called.
        """
        try:
            word = word.lower()
            data = str(" ".join(data))
            guild_id = str(getattr(ctx.guild, 'id', None))
            nick = str(getattr(ctx.author, 'name', None))

            try:
                old_data = self.factoid_cache[guild_id][word]
            except LookupError:
                old_data = None

            if data.startswith('+') and old_data:
                # remove + symbol
                new_data = data[1:]
                # append new_data to the old_data
                puncts = string.punctuation + " "
                if len(new_data) > 1 and new_data[1] in puncts:
                    data = old_data + new_data
                else:
                    data = old_data + ' ' + new_data
                await ctx.send(allowed_mentions=discord.AllowedMentions.none(), content=f"Appending  **{new_data}** to **{old_data}**")
            else:
                if not data:
                    return await ctx.send("Cannot save empty facts.")
                await ctx.send(
                    allowed_mentions=discord.AllowedMentions.none(), 
                    content=f"Remembering **{data}** for *{word}*. Type `{self.factoid_char}{word}` to see it."
                )
                if old_data:
                    await ctx.send(allowed_mentions=discord.AllowedMentions.none(), content=f"Previous data was **{old_data}**")

            self.add_factoid(word, guild_id, data, nick)
        except Exception as e:
            await ctx.send("Error adding factoid!")
            self.log.error('Exception', exc_info=True)
        return

    def get_max_size(self, facts):
        as_lengths = (utils._string_width(self.factoid_char + fact[0]) for fact in sorted(facts.items()))
        return max(as_lengths, default=0)

    def shorten_text(self, text, width):
        if len(text) > width:
            return text[:width - 3].rstrip() + '...'
        return text

    async def paste_facts(
        self,
        ctx,
        facts,
        *,
        width=80,
        heading=None,
        max_size=None,
        text=False,
        dm=True
    ):
        if not facts:
            return

        max_size = max_size or self.get_max_size(facts)
        get_width = utils._string_width

        entries = []
        for fact in sorted(facts.items()):
            name = self.factoid_char + fact[0]
            max_width = max_size - (get_width(name) - len(name))
            entry = f'{name:<{max_width}} {fact[1]}'
            entries.append(self.shorten_text(entry, width))

        if dm:
            dm_channel = await ctx.author.create_dm()
        else:
            dm_channel = None

        if text:
            input_text = '\n'.join(entries)
            pages = RoboPages(TextPageSource(input_text, heading=heading))
            try:
                await pages.start(ctx, channel=dm_channel)
            except menus.MenuError as e:
                await ctx.send(str(e))
        else:
            pages = SimplePages(entries=entries, per_page=25)
            try:
                await pages.start(ctx, channel=dm_channel)
            except menus.MenuError as e:
                await ctx.send(str(e))

    async def remove_fact(self, ctx, guild_id, names):
        found = {}
        missing = []
        for name in names:
            data = self.factoid_cache[guild_id].get(name.lower())
            if data:
                found[name] = data
            else:
                missing.append(name)

        if missing:
            return await ctx.send(
                "Unknown factoids: {}".format(
                    get_text_list([repr(s) for s in missing], "and")
                )
            )

        if found:
            await self.paste_facts(ctx, found, heading="Removed facts:", text=True, dm=False)
            self.del_factoid(guild_id, list(found.keys()))

    @commands.command(aliases=["f"])
    async def forget(self, ctx, *, word) :
        """<word> - forgets previously remembered <word>"""
        guild_id = str(getattr(ctx.guild, 'id', None))
        return await self.remove_fact(ctx, guild_id, word.split())

    @commands.command(aliases=["forgetall", "clearfacts"])
    @checks.is_mod()
    async def forget_all(self, ctx):
        guild_id = str(getattr(ctx.guild, 'id', None))
        await self.paste_facts(ctx, self.factoid_cache[guild_id], width=500, heading="Removed facts:", text=True)
        self.del_factoid(guild_id)
        return await ctx.send("Facts cleared.")

    @commands.command()
    async def factinfo(self, ctx, text):
        """<factoid> - shows the source of a factoid"""
        guild_id = str(getattr(ctx.guild, 'id', None))
        text = text.strip().lower()
        query = select(self.table).where(self.table.chan == guild_id, self.table.word == text)
        res = self.db.execute(query).scalars().all()

        if res:
            for row in res:
                await ctx.send(allowed_mentions=discord.AllowedMentions.none(), content=f"Fact: `{row.word}`; Data: `{row.data}`; Person responsible: `{row.nick}`")
        else:
            await ctx.send("Unknown factoid.")

    @commands.Cog.listener('on_message')
    async def factoid(self, message):
        """<word> - shows what data is associated with <word>"""
        if message.author.bot:
            return

        guild_id = str(getattr(message.guild, 'id', None))
        content = str(getattr(message, 'content'))
        if len(content) > 0:
            if content[0] == self.factoid_char:
                content = content[1:]
                arg1 = ""
                if len(content.split()) >= 2:
                    arg1 = content.split()[1]
                # split up the input
                split = content.strip().split(" ")
                factoid_text = split[0].lower()

                if factoid_text in self.factoid_cache[guild_id]:
                    result = self.factoid_cache[guild_id][factoid_text]

                    # factoid post-processors
                    if arg1:
                        result = result.replace("<user>", arg1)
                    if result.startswith("<act>"):
                        result = result[5:].strip()
                        return await message.channel.send(allowed_mentions=discord.AllowedMentions.none(), content=f"*{result}*")
                    else:
                        return await message.channel.send(allowed_mentions=discord.AllowedMentions.none(), content=result)
            else:
                return
        else: 
            return

    @commands.command(aliases=['listfactoids'])
    async def listfacts(self, ctx):
        """- lists all available factoids"""

        guild_id = str(getattr(ctx.guild, 'id', None))
        reply_text: List[str] = []
        reply_text_length = 0
        for word in sorted(self.factoid_cache[guild_id].keys()):
            reply_text.append(word)

        pages = SimplePages(entries=reply_text, per_page=25)
        try:
            dm = await ctx.author.create_dm()
            await pages.start(ctx, channel=dm)
        except menus.MenuError as e:
            await ctx.send(str(e))

    @commands.command(aliases=['listdetailedfacts'])
    async def listdetailedfactoids(self, ctx):
        guild_id = str(getattr(ctx.guild, 'id', None))
        return await self.paste_facts(ctx, self.factoid_cache[guild_id])

def setup(bot):
    bot.add_cog(Factoids(bot))
