import asyncio
import contextlib
import logging
import sys

import click

from bot import beeerbot


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


if __name__ == '__main__':
    main()
