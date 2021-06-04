import asyncio
import contextlib
import importlib
import logging
from logging.handlers import RotatingFileHandler
import sys
import traceback

import click
from munch import munchify
import sqlalchemy
from sqlalchemy import create_engine
import yaml

from bot import beeerbot, initial_extensions
from util import database


try:
    import uvloop
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


class RemoveNoise(logging.Filter):
    def __init__(self):
        super().__init__(name='discord.state')

    def filter(self, record):
        if record.levelname == 'WARNING' and 'referencing an unknown' in record.msg:
            return False
        return True


@contextlib.contextmanager
def setup_logging():
    try:
        # __enter__
        max_bytes = 32 * 1024 * 1024 # 32 MiB
        logging.getLogger('discord').setLevel(logging.INFO)
        logging.getLogger('discord.http').setLevel(logging.WARNING)
        logging.getLogger('discord.state').addFilter(RemoveNoise())

        log = logging.getLogger()
        log.setLevel(logging.INFO)
        handler = RotatingFileHandler(filename='beeerbot.log', encoding='utf-8', mode='w', maxBytes=max_bytes, backupCount=5)
        dt_fmt = '%Y-%m-%d %H:%M:%S'
        fmt = logging.Formatter('[{asctime}] [{levelname:<7}][{filename}:{lineno:<4}] {name}: {message}', dt_fmt, style='{')
        handler.setFormatter(fmt)
        log.addHandler(handler)
        log.info("Launcher initialized")

        yield
    finally:
        # __exit__
        handlers = log.handlers[:]
        for hdlr in handlers:
            hdlr.close()
            log.removeHandler(hdlr)


def run_bot():
    bot = beeerbot()
    bot.run()


@click.group(invoke_without_command=True, options_metavar='[options]')
@click.pass_context
def main(ctx):
    """Launches the bot."""
    if ctx.invoked_subcommand is None:
        loop = asyncio.get_event_loop()
        with setup_logging():
            run_bot()

@main.group(short_help='database stuff', options_metavar='[options]')
def db():
    pass

@db.command(short_help='init the db', options_metavar='[options]')
@click.option('-q', '--quiet', help='less verbose output', is_flag=True)
def init(quiet):
    """Manage database creation"""
    config = munchify(yaml.safe_load(open("config.yml")))
    db_path = config.bot_options.get('database', 'sqlite:///cloudbot.db')
    db_engine = create_engine(db_path, future=True)

    try:
        database.configure(db_engine, future=True)
    except Exception:
        click.echo(f'Could not create SQLite connection.\n{traceback.format_exc()}', err=True)

    cogs = initial_extensions

    for ext in cogs:
        try:
            importlib.import_module(ext)
        except Exception:
            click.echo(f'Could not load {ext}.\n{traceback.format_exc()}', err=True)
            return

    database.base.metadata.create_all(db_engine)


if __name__ == '__main__':
    main()
