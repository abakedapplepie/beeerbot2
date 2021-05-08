import discord
from discord.ext import commands
import string
from sqlalchemy import Table, Column, String, PrimaryKeyConstraint
from collections import defaultdict
import logging
import re

class Factoids(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("beeerbot")
        self.config = bot.config

        self.table = Table(
            "factoids",
            bot.db_metadata,
            Column("word", String(25)),
            Column("data", String(500)),
            Column("nick", String(25)),
            Column("chan", String(65)),
            PrimaryKeyConstraint('word', 'chan')
        )
        self.db = bot.db_session
        self.load_cache()
        self.log.info("Factoids initialized")

    async def cog_command_error(self, ctx, error):
        return

    def load_cache(self):
        """
        :type db: sqlalchemy.orm.Session
        """

        self.factoid_cache = defaultdict(lambda: {"beeerbot": "is the best"})
        for row in self.db.execute(self.table.select().order_by("word")):
            # assign variables
            chan = row["chan"]
            word = row["word"]
            data = row["data"]

            if chan not in self.factoid_cache:
                self.factoid_cache.update({chan:{word:data}})
            elif word not in self.factoid_cache[chan]:
                self.factoid_cache[chan].update({word:data})
            else:
                self.factoid_cache[chan][word] = data

    def add_factoid(self, word, chan, data, nick):
        """
        :type db: sqlalchemy.orm.Session
        :type word: str
        :type data: str
        :type nick: str
        """

        if word in self.factoid_cache[chan]:
            # if we have a set value, update
            self.db.execute(self.table.update().values(data=data, nick=nick, chan=chan).where(self.table.c.chan == chan).where(self.table.c.word == word))
            self.db.commit()
        else:
            # otherwise, insert
            self.db.execute(self.table.insert().values(word=word, data=data, nick=nick, chan=chan))
            self.db.commit()
        self.load_cache()

    def del_factoid(self, chan, word):
        """
        :type db: sqlalchemy.orm.Session
        :type word: str
        """
        self.db.execute(self.table.delete().where(self.table.c.word == word).where(self.table.c.chan == chan))
        self.db.commit()
        self.load_cache()

    @commands.command(aliases=["r"])
    async def remember(self, ctx, word, *data):
        """<word> [+]<data> - remembers <data> with <word> - add + to <data> to append. If the input starts with <act> the message will be sent as an action. If <user> in in the message it will be replaced by input arguments when command is called."""

        try:
            word = word.lower()
            data = str(" ".join(data))
            guild_id = str(getattr(ctx.guild, 'id', None))
            nick = str(getattr(ctx.author, 'name', None))

            try:
                old_data = self.factoid_cache[guild_id].get(word)
            except:
                old_data = ""
                pass

            if data.startswith('+') and old_data:
                # remove + symbol
                new_data = data[1:]
                # append new_data to the old_data
                if len(new_data) > 1 and new_data[1] in (string.punctuation + ' '):
                    data = old_data + new_data
                else:
                    data = old_data + ' ' + new_data
                await ctx.send("Appending **{}** to **{}**".format(new_data, old_data))
            else:
                await ctx.send('Remembering **{0}** for *{1}*. Type `?{1}` to see it.'.format(data, word))
                if old_data:
                    await ctx.send('Previous data was **{}**'.format(old_data))

            self.add_factoid(word, guild_id, data, nick)
        except Exception as e:
            self.log.error('Exception', exc_info=True)
        return


    @commands.command(aliases=["f"])
    async def forget(self, ctx, word) :
        """<word> - forgets previously remembered <word>"""
        guild_id = str(getattr(ctx.guild, 'id', None))
        data = self.factoid_cache[guild_id][word.lower()]

        if data:
            self.del_factoid(guild_id, word)
            return await ctx.send('"{}" has been forgotten.'.format(data))
        else:
            return await ctx.send("I don't know about that.")

    @commands.command()
    async def info(self, ctx, text):
        """<factoid> - shows the source of a factoid"""

        guild_id = str(getattr(ctx.guild, 'id', None))
        text = text.strip().lower()

        if text in self.factoid_cache[guild_id]:
            return await ctx.send(self.factoid_cache[guild_id][text])
        else:
            return await ctx.send("Unknown Factoid.")

    @commands.Cog.listener('on_message')
    async def factoid(self, message):
        """<word> - shows what data is associated with <word>"""

        if message.author.bot:
            return

        guild_id = str(getattr(message.guild, 'id', None))
        content = message.content
        if message.content[0] == '?':
            content = message.content[1:]
            arg1 = ""
            if len(content.split()) >= 2:
                arg1 = content.split()[1]
            # split up the input
            split = content.strip().split(" ")
            factoid_text = split[0].lower()

            if factoid_text in self.factoid_cache[guild_id]:
                result = self.factoid_cache[guild_id][factoid_text]

                # factoid post-processors
                # result = colors.parse(result)
                if arg1:
                    result = result.replace("<user>", arg1)
                if result.startswith("<act>"):
                    result = result[5:].strip()
                    return await message.channel.send("*{}*".format(result))
                else:
                    return await message.channel.send(result)
        else: 
            return

    @commands.command()
    async def listfacts(self, ctx):
        """- lists all available factoids"""
        
        guild_id = str(getattr(ctx.guild, 'id', None))
        reply_text = []
        reply_text_length = 0
        for word in self.factoid_cache[guild_id].keys():
            added_length = len(word) + 2
            if reply_text_length + added_length > 400:
                await ctx.send(", ".join(reply_text))
                reply_text = []
                reply_text_length = 0
            else:
                reply_text.append(word)
                reply_text_length += added_length
        return await ctx.send(", ".join(reply_text))

def setup(bot):
    bot.add_cog(Factoids(bot))
