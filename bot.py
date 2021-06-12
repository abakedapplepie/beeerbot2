import os
import sys
from collections import Counter, deque, defaultdict
import asyncio
import json
from pathlib import Path
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
import traceback

import logging
import discord
from discord.ext import commands

import yaml
from munch import munchify

from cogs.utils import context
from cogs.utils.config import Config
from util import database

log = logging.getLogger(__name__)

description = """
beeeeer
"""

initial_extensions = (
    'cogs.comic',
    'cogs.factoids',
    'cogs.lenny',
    'cogs.duckhunt',
    'cogs.cardsagainsthumanity',
    'cogs.stats',
    'cogs.botops'
)


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
        allowed_mentions = discord.AllowedMentions(roles=False, everyone=False, users=True)
        intents = discord.Intents(
            guilds=True,
            members=True,
            bans=True,
            emojis=True,
            voice_states=True,
            messages=True,
            reactions=True,
        )
        super().__init__(command_prefix=_prefix_callable, description=description,
                         pm_help=None, help_attrs=dict(hidden=True),
                         fetch_offline_members=False, heartbeat_timeout=150.0,
                         allowed_mentions=allowed_mentions, intents=intents)

        self.config = munchify(yaml.safe_load(open("config.yml")))

        self.session = aiohttp.ClientSession(loop=self.loop)

        self._prev_events = deque(maxlen=10)

        # shows the last attempted IDENTIFYs and RESUMEs
        self.resumes = defaultdict(list)
        self.identifies = defaultdict(list)

        # guild_id: list
        self.prefixes = Config('prefixes.json')

        # guild_id and user_id mapped to True
        # these are users and guilds globally blacklisted
        # from using the bot
        self.blacklist = Config('blacklist.json')

        # in case of even further spam, add a cooldown mapping
        # for people who excessively spam commands
        self.spam_control = commands.CooldownMapping.from_cooldown(10, 12.0, commands.BucketType.user)

        # A counter to auto-ban frequent spammers
        # Triggering the rate limit 5 times in a row will auto-ban the user from the bot.
        self._auto_spam_count = Counter()

        # setup db
        db_path = self.config.bot_options.get('database', 'sqlite:///cloudbot.db')
        self.db_engine = create_engine(db_path, future=True)
        database.configure(self.db_engine, future=True)

        # Set data path
        self.base_dir = Path().resolve()
        self.data_path = self.config.bot_options.get('data_dir', self.base_dir / "data")

        self.log = logging.getLogger(__name__)
        log.info("Bot initialized")

        for extension in initial_extensions:
            try:
                self.load_extension(extension)
                log.info('Extension %s loaded', extension)
            except Exception as e:
                print(f'Failed to load extension {extension}.', file=sys.stderr)
                traceback.print_exc()

    async def on_socket_response(self, msg):
        self._prev_events.append(msg)

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.author.send('This command cannot be used in private messages.')
        elif isinstance(error, commands.DisabledCommand):
            await ctx.author.send('Sorry. This command is disabled and cannot be used.')
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            if not isinstance(original, discord.HTTPException):
                print(f'In {ctx.command.qualified_name}:', file=sys.stderr)
                traceback.print_tb(original.__traceback__)
                print(f'{original.__class__.__name__}: {original}', file=sys.stderr)
        elif isinstance(error, commands.ArgumentParsingError):
            await ctx.send(error)
        elif isinstance(error, commands.CheckFailure):
            log.error(error)

    async def add_to_blacklist(self, object_id):
        await self.blacklist.put(object_id, True)

    async def remove_from_blacklist(self, object_id):
        try:
            await self.blacklist.remove(object_id)
        except KeyError:
            pass

    async def get_or_fetch_member(self, guild, member_id):
        """Looks up a member in cache or fetches if not found.
        Parameters
        -----------
        guild: Guild
            The guild to look in.
        member_id: int
            The member ID to search for.
        Returns
        ---------
        Optional[Member]
            The member or None if not found.
        """

        member = guild.get_member(member_id)
        if member is not None:
            return member

        members = await guild.query_members(limit=1, user_ids=[member_id], cache=True)
        if not members:
            return None
        return members[0]

    async def on_ready(self):
        if not hasattr(self, 'uptime'):
            self.uptime = datetime.datetime.utcnow()

        ready_msg = f'Ready: {self.user} (ID: {self.user.id})'
        print(ready_msg)
        wh = self.stats_webhook
        await wh.send(ready_msg)
        await self.change_presence(activity=discord.Game(name="bite my shiny metal ass"))

    @discord.utils.cached_property
    def stats_webhook(self):
        wh_id = self.config.discord.webhook_id
        wh_token = self.config.discord.webhook_token
        hook = discord.Webhook.partial(id=wh_id, token=wh_token, adapter=discord.AsyncWebhookAdapter(self.session))
        return hook

    def log_spammer(self, ctx, message, retry_after, *, autoblock=False):
        guild_name = getattr(ctx.guild, 'name', 'No Guild (DMs)')
        guild_id = getattr(ctx.guild, 'id', None)
        fmt = 'User %s (ID %s) in guid %r (ID %s) spamming, retry after: %.2fs'
        log.warning(fmt, message.author, message.author.id, guild_name, guild_id, retry_after)
        if not autoblock:
            return

        wh = self.stats_webhook
        embed = discord.Embed(title='Auto-blocked Member', colour=0xDDA453)
        embed.add_field(name='Member', value=f'{message.author} (ID: {message.author.id})', inline=False)
        embed.add_field(name='Guild Info', value=f'{guild_name} (ID: {guild_id})', inline=False)
        embed.add_field(name='Channel Info', value=f'{message.channel} (ID: {message.channel.id}', inline=False)
        embed.timestamp = datetime.datetime.utcnow()
        return wh.send(embed=embed)

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
        close_msg = f'Bot shutting down...'
        print(close_msg)
        wh = self.stats_webhook
        await wh.send(close_msg)
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
