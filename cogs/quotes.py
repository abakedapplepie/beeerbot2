import random
import re
import time

from sqlalchemy import select
from sqlalchemy import Table, Column, String, PrimaryKeyConstraint
from sqlalchemy.types import REAL
from sqlalchemy.exc import IntegrityError 
import logging
import discord
from discord.ext import commands

class Quotes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("beeerbot")
        self.config = bot.config

        self.table = Table(
            'quote',
            bot.db_metadata,
            Column('chan', String(25)),
            Column('nick', String(25)),
            Column('add_nick', String(25)),
            Column('msg', String(500)),
            Column('time', REAL),
            Column('deleted', String(5), default=0),
            PrimaryKeyConstraint('chan', 'nick', 'time')
        )
        self.db = bot.db_session
        self.log.info("Quotes initialized")

    async def cog_command_error(self, ctx, error):
        return

    @commands.command(aliases=["q"])
    async def quote(self, ctx, author_name=None, num=None): 
        """reply to a message with `!q[uote]` to add it to the db, use `!q[uote] nickname [N]` to retrieve the Nth quote for nickname. defaults to random"""
        try:
            if ctx.message.reference and author_name == None and num == None:
                try:
                    quoted_msg = await ctx.fetch_message(ctx.message.reference.message_id)
                    return await ctx.send(self.add_quote(ctx.guild.id, quoted_msg.author.name, ctx.author.name, quoted_msg.content))
                except:
                    return self.log.error('failed to fetch reply source', exc_info=1)
            else:
                return self.get_quote_by_author(ctx.guild.id, author_name, num)
        except: 
            return self.log.error('failed to generate quote', exc_info=1)
            


    def format_quote(self, nick, msg, quote_num, quote_total):
        """Returns a formatted string of a quote"""
        return "[{}/{}] <{}> {}".format(quote_num, quote_total,
                                                nick, msg)


    def add_quote(self, chan, target, sender, message):
        """Adds a quote to a nick, returns message string"""
        try:
            query = self.table.insert().values(
                chan=chan,
                nick=target.lower(),
                add_nick=sender.lower(),
                msg=message,
                time=time.time()
            )
            self.db.execute(query)
            self.db.commit()
        except IntegrityError:
            return "Message already stored, doing nothing."
        return "Quote added."


    # def del_quote(self, db, nick, msg):
        # """Deletes a quote from a nick"""
        # query = self.table.update() \
            # .where(self.table.c.chan == 1) \
            # .where(self.table.c.nick == nick.lower()) \
            # .where(self.table.c.msg == msg) \
            # .values(deleted=1)
        # self.db.execute(query)
        # self.db.commit()


    def get_quote_num(num, count, name):
        """Returns the quote number to fetch from the DB"""
        if num:  # Make sure num is a number if it isn't false
            num = int(num)
        if count == 0:  # Error on no quotes
            raise Exception("No quotes found for {}.".format(name))
        if num and num < 0:  # Count back if possible
            num = count + num + 1 if num + count > -1 else count + 1
        if num and num > count:  # If there are not enough quotes, raise an error
            raise Exception("I only have {} quote{} for {}.".format(count, ('s', '')[count == 1], name))
        if num and num == 0:  # If the number is zero, set it to one
            num = 1
        if not num:  # If a number is not given, select a random one
            num = random.randint(1, count)
        return num


    def get_quote_by_author(self, guild_id, author_name, num=False):
        """Returns a formatted quote from a nick, random or selected by number"""

        self.log.info("quote guild_id: {} quote author: {}".format(guild_id, author_name))
        try: 
            count_query = select([self.table]) \
                .where(self.table.c.deleted != 1) \
                .where(self.table.c.chan == guild_id) \
                .where(self.table.c.nick == author_name) \
                .count()
            count = db.execute(count_query).fetchall()[0][0]
            self.log.info("quote count: {} quote guild_id: {} quote author: {}".format(count, guild_id, author_name))
        except AttributeError:
            self.log.info("no quotes", exc_info=1) 
            return
        try:
            num = get_quote_num(num, count, author_name)
        except Exception as error_message:
            return error_message

        query = select([self.table.c.time, self.table.c.nick, self.table.c.msg]) \
            .where(self.table.c.deleted != 1) \
            .where(self.table.c.chan == guild_id) \
            .where(self.table.c.nick == author_name) \
            .order_by(self.table.c.time)\
            .limit(1) \
            .offset((num - 1))
        data = self.db.execute(query).fetchall()[0]
        return format_quote(data, num, count)
        

def setup(bot):
    bot.add_cog(Quotes(bot))
