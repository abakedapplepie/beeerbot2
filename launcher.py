import asyncio
import contextlib
import importlib
import logging
import sys

import click
from munch import munchify
import sqlalchemy
from sqlalchemy import create_engine
import yaml

from bot import beeerbot, initial_extensions
from util import database


@contextlib.contextmanager
def setup_logging():
    try:
        logging.getLogger('discord').setLevel(logging.INFO)
        logging.getLogger('discord.http').setLevel(logging.WARNING)

        log = logging.getLogger("beeerbot")
        log.setLevel(logging.INFO)
        filehandler = logging.FileHandler(filename='beeerbot.log', encoding='utf-8', mode='w')
        formatter = logging.Formatter(
            "[{asctime}] [{levelname:<7}][{filename}:{lineno:<4}] {name}: {message}",
            datefmt="%Y-%m-%d %H:%M:%S",
            style="{")
        filehandler.setFormatter(formatter)
        log.addHandler(filehandler)

        stdouthandler = logging.StreamHandler(sys.stdout)
        stdouthandler.setLevel(logging.DEBUG)
        stdouthandler.setFormatter(formatter)
        log.addHandler(stdouthandler)
        log.info("Launcher initialized")

        yield
    finally:
        handlers = log.handlers[:]
        for h in handlers:
            h.close()
            log.removeHandler(h)


def run_bot():
    bot = beeerbot()
    bot.run()


@click.group(invoke_without_command=True, options_metavar='[options]')
@click.pass_context
def main(ctx):
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
