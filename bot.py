import os
import sys
from collections import Counter, deque, defaultdict
import asyncio
import json
import random
from random import shuffle
import base64
import requests
import aiohttp
import datetime
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.schema import MetaData

import logging
import discord
from discord.ext import commands

import yaml
from munch import munchify

from cogs.utils import context
from cogs.utils.config import Config
from util import database

log = logging.getLogger("beeerbot")

description = """
beeeeer
"""

initial_extensions = {
    'cogs.comic', 'cogs.factoids', 'cogs.lenny'
}


def _prefix_callable(bot, msg):
    user_id = bot.user.id
    base = [f'<@!{user_id}> ', f'<@{user_id} ']
    if msg.guild is None:
        base.append('!')
    else:
        base.extend(bot.prefixes.get(msg.guild.id, ['!']))
    return base

class beeerbot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=_prefix_callable,
                         description=description,
                         pm_help=None,
                         help_attrs=dict(hidden=True),
                         fetch_offine_members=None,
                         heartbeat_timeout=150.0)

        self.config = munchify(yaml.safe_load(open("config.yml")))

        self.session = aiohttp.ClientSession(loop=self.loop)

        self._prev_events = deque(maxlen=10)

        self.prefixes = Config('prefixes.json')
        self.blacklist = Config('blacklist.json')

        self.spam_control = commands.CooldownMapping.from_cooldown(10, 12.0, commands.BucketType.user)

        self._auto_spam_count = Counter()

        # setup db
        db_path = self.config.bot_options.get('database', 'sqlite:///cloudbot.db')
        self.db_engine = create_engine(db_path, future=True)
        database.configure(self.db_engine, future=True)

        self.log = logging.getLogger("beeerbot")
        log.info("Bot initialized")

        for ext in initial_extensions:
            try:
                self.load_extension(ext)
                log.info('Extension %s loaded', ext)
            except Exception:
                self.log.error('Failed to load extension %s.', ext, exc_info=1)

    async def on_socket_response(self, msg):
        self._prev_events.append(msg)

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.author.send('This command cannot be used in private messages.')
        elif isinstance(error, commands.DisabledCommand):
            await ctx.author.send('This command has been disabled.')
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            if not isinstance(original, discord.HTTPException):
                log.error(f'In {ctx.command.qualified_name}:', exc_info=1)
                log.error(f'{original.__class__.__name__}: {original}', exc_info=1)
        elif isinstance(error, commands.ArgumentParsingError):
            await ctx.send(error)
        elif isinstance(error, commands.CheckFailure):
            log.error(error)

    def get_guild_prefixes(self, guild, *, local_inject=_prefix_callable):
        proxy_msg = discord.Object(id=None)
        proxy_msg.guild = guild
        return local_inject(self, proxy_msg)

    def get_raw_guild_prefixes(self, guild_id):
        return self.prefixes.get(guild_id, ['?', '!'])

    async def set_guild_prefixes(self, guild, prefixes):
        if len(prefixes) == 0:
            await self.prefixes.put(guild.id, [])
        elif len(prefixes) > 10:
            raise RuntimeError('Cannot have more than 10 prefixes.')
        else:
            await self.prefixes.put(guild.id, sorted(set(prefixes), reverse=True))

    async def add_to_blacklist(self, object_id):
        await self.blacklist.put(object_id, True)

    async def remove_from_blacklist(self, object_id):
        try:
            await self.blacklist.remove(object_id)
        except KeyError:
            pass

    async def on_ready(self):
        log.info('Ready: %s (ID: %s)', self.user, self.user.id)
        await self.change_presence(activity=discord.Game(name="bite my shiny metal ass"))

    def log_spammer(self, ctx, message, retry_after, *, autoblock=False):
        guild_name = getattr(ctx.guild, 'name', 'No Guild (DMs)')
        guild_id = getattr(ctx.guild, 'id', None)
        fmt = 'User %s (ID %s) in guid %r (ID %s) spamming, retry after: %.2fs'
        log.warning(fmt, message.author, message.author.id, guild_name, guild_id, retry_after)
        if not autoblock:
            return

    async def process_commands(self, message):
        ctx = await self.get_context(message, cls=context.Context)

        if ctx.command is None:
            return

        if ctx.author.id in self.blacklist:
            return

        if ctx.guild is not None and ctx.guild.id in self.blacklist:
            return

        bucket = self.spam_control.get_bucket(message)
        current = message.created_at.replace(tzinfo=datetime.timezone.utc).timestamp()
        retry_after = bucket.update_rate_limit(current)
        author_id = message.author.id
        if retry_after and author_id != self.owner_id:
            self._auto_spam_count[author_id] += 1
            if self._auto_spam_count[author_id] >= 5:
                await self.add_to_blacklist(author_id)
                del self._auto_spam_count[author_id]
                await self.log_spammer(ctx, message, retry_after, autoblock=True)
            else:
                self.log_spammer(ctx, message, retry_after)
            return
        else:
            self._auto_spam_count.pop(author_id, None)

        await self.invoke(ctx)

    async def on_message(self, message):
        if message.author.bot:
            return
        await self.process_commands(message)

    async def close(self):
        await super().close()
        await self.session.close()

    def run(self):
        try:
            super().run(self.config.discord.token, reconnect=True)
        finally:
            with open('prev_events.log', 'w', encoding='utf-8') as f:
                for data in self._prev_events:
                    try:
                        x = json.dumps(data, ensure_ascii=True, indent=4)
                    except:
                        f.write(f'{data}\n')
                    else:
                        f.write(f'{x}\n')
