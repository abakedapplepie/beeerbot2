import asyncio
from collections import defaultdict
from datetime import datetime
import logging
import operator
import random
from threading import Lock
from time import sleep, time
from typing import Dict, List, NamedTuple, TypeVar, Union

import discord
from discord.ext import tasks, commands
from munch import munchify
import yaml

from sqlalchemy import Column, String, Boolean, Integer, insert, delete, select, update, desc, and_
from util import database

from cogs.utils.formatting import pluralize_auto
from cogs.utils.func_utils import call_with_args
from cogs.utils import checks
from cogs.utils.paginator import SimplePages


class ScoreEntry(NamedTuple):
    network: str
    name: str
    chan: str
    shot: int = 0
    befriend: int = 0


class ScoreType:
    def __init__(self, name, column_name, noun, verb):
        self.name = name
        self.column_name = column_name
        self.noun = noun
        self.verb = verb


#TODO: stats are not correctly notifying when no results (friends/killers)
class DuckHuntTable(database.base):
    __tablename__ = "duck_hunt"
    network = Column(String(), primary_key=True)
    name = Column(String(), primary_key=True)
    shot = Column(Integer())
    befriend = Column(Integer())
    chan = Column(String(), primary_key=True)


class NoHuntTable(database.base):
    __tablename__ = "nohunt"
    network = Column(String(), primary_key=True)
    chan = Column(String(), primary_key=True)


class StatusTable(database.base):
    __tablename__ = "duck_status"
    network = Column(String(), primary_key=True)
    chan = Column(String(), primary_key=True)
    active = Column(Boolean())
    duck_kick = Column(Boolean())


class ChannelState:
    """
    Represents the state of the hunt in a single channel
    """

    def __init__(self):
        self.masks = []
        self.messages = 0
        self.game_on = False
        self.no_duck_kick = False
        self.duck_status = 0
        self.next_duck_time = 0
        self.duck_time = 0
        self.shoot_time = 0
        self.duck_msg_id = 0
        self.config = munchify(yaml.safe_load(open("config.yml")))

    def clear_messages(self):
        self.messages = 0
        self.masks.clear()

    def should_deploy(self, chan):
        """Should we deploy a duck?"""
        msg_delay = self.config.duckhunt_options.get("min_lines", 10)
        mask_req = self.config.duckhunt_options.get("min_users", 5)
        test_chan = int(self.config.duckhunt_options.get("test_channel", 0))

        return (
            self.game_on
            and self.duck_status == 0
            and self.next_duck_time <= time()
            and (self.messages >= msg_delay or int(chan) == test_chan)
            and (len(self.masks) >= mask_req or int(chan) == test_chan)
        )

    def handle_message(self, author_id):
        if self.game_on and self.duck_status == 0:
            self.messages += 1
            if author_id not in self.masks:
                self.masks.append(author_id)


class Duckhunt(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("beeerbot")
        self.config = bot.config
        self.db = database.Session
        self.table = DuckHuntTable
        self.status_table = StatusTable
        self.nohunt_table = NoHuntTable

        self.delete_source_msg = False

        # Grab config options
        self.min_ducktime = int(self.config.duckhunt_options.get("min_ducktime", 480))
        self.max_ducktime = int(self.config.duckhunt_options.get("max_ducktime", 3600))
        self.test_channel_id = int(self.config.duckhunt_options.get("test_channel", 0))

        # Set up duck parts
        self.duck_tail = "・゜゜・。。・゜゜"
        self.duck = [
            "\\_o< ",
            "\\_O< ",
            "\\_0< ",
            "\\_\u00f6< ",
            "\\_\u00f8< ",
            "\\_\u00f3< ",
        ]
        self.duck_noise = ["QUACK!", "FLAP FLAP!", "quack!"]

        # Set up score bits
        self.score_types = {
            "friend": ScoreType("befriend", "befriend", "friend", "friended"),
            "killer": ScoreType("killer", "shot", "killer", "killed"),
        }

        self.display_funcs = {
            "average": self.get_average_scores,
            "global": self.get_global_scores,
            None: self.get_channel_scores,
        }

        # Set up game status
        self.T = TypeVar("T")
        self.ConnMap = Dict[str, Dict[str, self.T]]
        self.scripters: Dict[int, float] = defaultdict(float)
        self.chan_locks: ConnMap[Lock] = defaultdict(lambda: defaultdict(Lock))
        self.game_status: ConnMap[ChannelState] = defaultdict(
            lambda: defaultdict(ChannelState)
        )
        self.opt_out: Dict[str, List[str]] = defaultdict(list)

        self.load_optout()

        # Start event loops
        self.save_status.start()
        self.deploy_duck.start()

        # Set up duck times for all channels
        try:
            self.load_status()
        except:
            self.log.error('Failed to set up duck times', exc_info=1)

        self.log.info("Duckhunt initialized")

    async def cog_command_error(self, ctx, error):
        return

    async def ctx_send(self, ctx, msg, delete_delay=10, source_delay=None):
        """Convenience command to first send message, then cleanup bot output"""
        out = await ctx.send(msg)
        await out.delete(delay=delete_delay)
        if self.delete_source_msg and source_delay:
            await ctx.message.delete(delay=source_delay)
        return

    def load_optout(self):
        """load a list of channels duckhunt should be off in."""
        new_data = defaultdict(list)
        chans = self.db.execute(select(self.nohunt_table)).scalars().all()
        for row in chans:
            chan = row.chan
            new_data[int(row.network)].append(int(chan))

        self.opt_out.clear()
        self.opt_out.update(new_data)

    def load_status(self):
        rows = self.db.execute(select(self.status_table)).scalars().all()
        for row in rows:
            guild_id = row.network
            channel_id = row.chan
            status = self.get_state_table(guild_id, channel_id)
            status.game_on = row.active
            status.no_duck_kick = row.duck_kick
            if status.game_on:
                self.set_ducktime(channel_id, guild_id)

    def get_state_table(self, guild_id, channel_id):
        return self.game_status[guild_id.casefold()][channel_id.casefold()]

    def set_ducktime(self, channel_id, guild_id):
        status = self.get_state_table(guild_id, channel_id)  # type: ChannelState
        # Artificially set next_duck_time low for testing purposes
        if self.test_channel_id == int(channel_id):
            status.next_duck_time = int(time()) + 30
        else:
            status.next_duck_time = random.randint(
                int(time()) + self.min_ducktime, int(time()) + self.max_ducktime
            )
        status.duck_status = 0
        # let's also reset the number of messages said and the list of masks that have spoken.
        status.clear_messages()
        self.log.info("set_ducktime: Updated duck time...")
        return

    def save_channel_state(self, guild_id, channel_id, status=None):
        if status is None:
            status = self.get_state_table(guild_id, channel_id)

        active = status.game_on
        duck_kick = status.no_duck_kick
        res = self.db.execute(
            update(self.status_table)
            .where(
                and_(self.status_table.network == guild_id, self.status_table.chan == channel_id)
            )
            .values(active=active, duck_kick=duck_kick)
        )

        if not res.rowcount:
            self.db.execute(
                insert(self.status_table).values(
                    network=guild_id, chan=channel_id, active=active, duck_kick=duck_kick
                )
            )

        self.db.commit()

    def cog_unload(self):
        # Stop event loops
        self.save_status.cancel()
        self.deploy_duck.cancel()
        # save_status is a coroutine but cog_unload CANNOT be a coroutine
        # so we create an asyncio task instead
        self.bot.loop.create_task(self.save_status(_sleep=False))

    @tasks.loop(hours=8)
    async def save_status(self, _sleep=True):
        for network in self.game_status:
            for chan, status in self.game_status[network].items():
                self.save_channel_state(network, chan, status)

                if _sleep:
                    sleep(5)

    def set_game_state(self, guild_id, channel_id, active=None, duck_kick=None):
        status = self.get_state_table(guild_id, channel_id)
        if active is not None:
            status.game_on = active

        if duck_kick is not None:
            status.no_duck_kick = duck_kick

        self.save_channel_state(guild_id, channel_id, status)

    def is_opt_out(self, guild_id, channel_id):
        if not guild_id:
            return False
        return int(channel_id) in self.opt_out[int(guild_id)]

    @commands.Cog.listener('on_message')
    async def increment_msg_counter(self, msg):
        """Increment the number of messages said in an active game channel. Also keep track of the unique masks that are speaking."""
        guild_id = str(getattr(msg.guild, 'id', None))
        channel_id = str(getattr(msg.channel, 'id', None))
        author_id = str(getattr(msg.author, 'id', None))

        if self.is_opt_out(guild_id, channel_id):
            return

        self.get_state_table(guild_id, channel_id).handle_message(author_id)

    @commands.command(aliases=["starthunt"])
    @checks.is_mod()
    async def start_hunt(self, ctx):
        """This command starts a duckhunt in your channel, to stop the hunt use .stophunt"""
        guild_id = str(getattr(ctx.guild, 'id', None))
        channel_id = str(getattr(ctx.channel, 'id', None))
        channel_name = str(getattr(ctx.channel, 'name', None))

        if self.is_opt_out(guild_id, channel_id):
            return
        elif ctx.guild is None:
            out = "No hunting by yourself, that isn't safe."
            return await self.ctx_send(ctx, out, delete_delay=5)

        check = self.get_state_table(guild_id, channel_id).game_on
        if check:
            out = f"There is already a game running in {channel_name}."
            return await self.ctx_send(ctx, out, delete_delay=5)

        self.set_game_state(guild_id, channel_id, active=True)
        self.set_ducktime(channel_id, guild_id)
        await ctx.send(
            "Ducks have been spotted nearby. "
            "See how many you can shoot or save. "
            "use !bang to shoot or !befriend to save them. "
            "NOTE: Ducks now appear as a function of time and channel activity."
        )

    @commands.command(aliases=["stophunt"])
    @checks.is_mod()
    async def stop_hunt(self, ctx):
        """This command stops the duck hunt in your channel. Scores will be preserved"""
        guild_id = str(getattr(ctx.guild, 'id', None))
        channel_id = str(getattr(ctx.channel, 'id', None))
        channel_name = str(getattr(ctx.channel, 'name', None))

        if self.is_opt_out(guild_id, channel_id):
            return

        if self.get_state_table(guild_id, channel_id).game_on:
            self.set_game_state(guild_id, channel_id, active=False)
            out = "The game has been stopped."
            await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)
        else:
            out = f"There is no game running in {channel_name}."
            await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)

    @commands.command(aliases=["duckmute"])
    @checks.is_mod()
    async def no_duck_kick(self, ctx, text=""):
        """<enable|disable> - If the bot has OP or half-op in the channel you can specify
        !duckmute enable|disable so that people are kicked for shooting or befriending
        a non-existent duck. Default is off.
        """
        guild_id = str(getattr(ctx.guild, 'id', None))
        channel_id = str(getattr(ctx.channel, 'id', None))

        if self.is_opt_out(guild_id, channel_id):
            return

        if text.lower() == "enable":
            self.set_game_state(guild_id, channel_id, duck_kick=True)
            out = "Users will now be muted for shooting or befriending non-existent ducks. The bot needs to have " \
                "appropriate flags to be able to mute users for this to work."
            return await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)

        if text.lower() == "disable":
            self.set_game_state(guild_id, channel_id, duck_kick=False)
            out = "Muting for non-existent ducks has been disabled."
            return await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)

        return

    def generate_duck(self):
        """Try and randomize the duck message so people can't highlight on it/script against it."""
        if random.randint(1, 40) == 1:
            dtail = "8====D"
            dbody = "~~~"
            dnoise = "FAP FAP FAP!"
        else:
            rt = random.randint(1, len(self.duck_tail) - 1)
            dtail = self.duck_tail[:rt] + " \u200b " + self.duck_tail[rt:]

            dbody = random.choice(self.duck)
            rb = random.randint(1, len(dbody) - 1)
            dbody = dbody[:rb] + "\u200b" + dbody[rb:]

            dnoise = random.choice(self.duck_noise)
            rn = random.randint(1, len(dnoise) - 1)
            dnoise = dnoise[:rn] + "\u200b" + dnoise[rn:]
        return (dtail, dbody, dnoise)

    @tasks.loop(seconds=10.0)
    async def deploy_duck(self):
        for network in self.game_status:
            for chan in self.game_status[network]:
                status = self.get_state_table(network, chan)
                if not status.should_deploy(chan):
                    continue

                # deploy a duck to channel
                try:
                    status.duck_status = 1
                    status.duck_time = time()
                    dtail, dbody, dnoise = self.generate_duck()
                    channel = self.bot.get_channel(int(chan))
                    em = discord.Embed(
                        title="A duck has appeared!",
                        description=f"{dtail}{dbody}{dnoise}",
                        color=469033)
                    em.set_thumbnail(url="https://i.imgur.com/nvsLpzo.png")
                    duck_msg = await channel.send(embed=em)
                    status.duck_msg_id = duck_msg.id
                    self.log.info(f"deploying duck to {channel.name}")
                except:
                    self.log.error(f"error deploying duck to {chan}", exc_info=True)

    def hit_or_miss(self, deploy: int, shoot: int):
        """This function calculates if the befriend or bang will be successful."""
        if shoot - deploy < 1:
            return 0.05

        if 1 <= shoot - deploy <= 7:
            out = random.uniform(0.60, 0.75)
            return out

        return 1

    def dbadd_entry(self, nick, channel_id: str, guild_id: str, shoot: int, friend: int):
        """Takes care of adding a new row to the database."""
        stmt = insert(self.table).values(
            network=guild_id,
            chan=channel_id,
            name=nick,
            shot=shoot,
            befriend=friend
        )
        self.db.execute(stmt)
        self.db.commit()

    def dbupdate(self, nick, channel_id: str, guild_id: str, shoot: int, friend: int):
        """update a db row"""
        values = {}
        if shoot:
            values["shot"] = shoot

        if friend:
            values["befriend"] = friend

        if not values:
            raise ValueError("No new values specified for 'friend' or 'shot'")

        query = (
            update(self.table)
            .where(
                and_(
                    self.table.network == guild_id,
                    self.table.chan == channel_id,
                    self.table.name == nick,
                )
            )
            .values(**values)
        )

        self.db.execute(query)
        self.db.commit()

    def update_score(self, nick, channel_id: str, guild_id: str, shoot=0, friend=0):
        score = self.db.execute(
            select([self.table.shot, self.table.befriend])
            .where(self.table.network == guild_id)
            .where(self.table.chan == channel_id)
            .where(self.table.name == nick)
        ).fetchone()

        if score:
            self.dbupdate(nick, channel_id, guild_id, score[0] + shoot, score[1] + friend)
            return {"shoot": score[0] + shoot, "friend": score[1] + friend}

        self.dbadd_entry(nick, channel_id, guild_id, shoot, friend)
        self.log.info("Done with update_score")
        return {"shoot": shoot, "friend": friend}

    async def attack(self, ctx, author: discord.Member, channel_id: str, channel_name: str, guild_id: str, attack_type: str):
        if self.is_opt_out(guild_id, channel_id):
            return

        nick = str(getattr(ctx.author, 'name', None))
        status = self.get_state_table(guild_id, channel_id)

        # Set various defaults based on attack type
        out = ""
        if attack_type == "shoot":
            miss = [
                "WHOOSH! You missed the duck completely!",
                "Your gun jammed!",
                "Better luck next time.",
                "WTF?! Who are you, Kim Jong Un firing missiles? You missed.",
            ]
            no_duck = "There is no duck! What are you shooting at?"
            msg = "{} you shot a duck in {:.3f} seconds! You have killed {} in {}."
            scripter_msg = (
                "You pulled the trigger in {:.3f} seconds, that's mighty fast. "
                "Are you sure you aren't a script? Take a 2 hour cool down."
            )
            attack_type = "shoot"
        else:
            miss = [
                "The duck didn't want to be friends, maybe next time.",
                "Well this is awkward, the duck needs to think about it.",
                "The duck said no, maybe bribe it with some pizza? Ducks love pizza don't they?",
                "Who knew ducks could be so picky?",
            ]
            no_duck = (
                "You tried befriending a non-existent duck. That's freaking creepy."
            )
            msg = "{} you befriended a duck in {:.3f} seconds! You have made friends with {} in {}."
            scripter_msg = (
                "You tried friending that duck in {:.3f} seconds, that's mighty fast. "
                "Are you sure you aren't a script? Take a 2 hour cool down."
            )
            attack_type = "friend"

        # Is the game disabled?
        if not status.game_on:
            out = "There is no active hunt right now. Use !starthunt to start a game."
            return await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)

        # Is there an active duck?
        if status.duck_status != 1:
            # TODO: Mute
            # if status.no_duck_kick == 1:
            #     conn.cmd("KICK", chan, nick, no_duck)
            #     return None
            return await self.ctx_send(ctx, no_duck, delete_delay=20, source_delay=10)

        status.shoot_time = time()
        deploy = status.duck_time
        shoot = status.shoot_time
        # Is the attacker on a cooldown?
        if author.id in self.scripters:
            if self.scripters[author.id] > shoot:
                # TODO: DM?
                out = "You are in a cool down period, you can try again in {:.3f} seconds.".format(
                        self.scripters[author.id] - shoot
                    )
                return await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)

        chance = self.hit_or_miss(deploy, shoot)
        # Did the attacker miss?
        if not random.random() <= chance and chance > 0.05:
            out = random.choice(miss) + " You can try again in 7 seconds."
            self.scripters[author.id] = shoot + 7
            return await self.ctx_send(ctx, out, source_delay=10)

        # Is someone cheating? (Add to scripters list)
        if chance == 0.05:
            out += scripter_msg.format(shoot - deploy)
            self.scripters[author.id] = shoot + 7200
            out = random.choice(miss) + " " + out
            return await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)

        # Finally, we can attack
        status.duck_status = 2
        try:
            args = {attack_type: 1}
            score = self.update_score(nick.lower(), channel_id, guild_id, **args)[attack_type]
        except Exception as e:
            status.duck_status = 1
            out = "An unknown error has occurred."
            self.log.error(f'An error occurred: {e.__class__.__name__}: {e}')
            await self.ctx_send(ctx, out, source_delay=10)
            return

        self.log.info("Done updating score...")
        out = msg.format(nick, shoot - deploy, pluralize_auto(score, "duck"), channel_name)
        await self.ctx_send(ctx, out, delete_delay=30, source_delay=60)
        self.log.info("Sent text confirmation")

        # Discord embed bits
        duck_stmt = ""
        if score == 1:
            duck_stmt += f"all by itself"
        else:
            duck_stmt += "next to {} other {}".format(
                *pluralize_auto(score-1, "duck").split()
            )

        self.log.info("Updating embed...")
        try:
            if attack_type == "shoot":
                duck_msg = await ctx.channel.fetch_message(status.duck_msg_id)
                duck_msg_content = duck_msg.embeds[0].description
                description = "{}\n{} pulled the trigger in {:.3f} seconds.\nIt's hanging on the wall {}".format(
                    duck_msg_content, nick, shoot-deploy, duck_stmt
                )
                em = discord.Embed(
                    title="this duck has been murdered",
                    description=description,
                    color=996666)
                em.set_thumbnail(url="https://i.imgur.com/JcIIXH4.png")
                em.set_footer(text="rest in peace little ducky")
                await duck_msg.edit(embed=em)
            else:
                duck_msg = await ctx.channel.fetch_message(status.duck_msg_id)
                duck_msg_content = duck_msg.embeds[0].description
                description = "{}\n{} sexed the duck in {:.3f} seconds.\nIt's hanging out in a harem {}".format(
                    duck_msg_content, nick, shoot-deploy, duck_stmt
                )
                em = discord.Embed(
                    title="this duck has been befriended",
                    description=description,
                    color=996666)
                em.set_thumbnail(url="https://i.imgur.com/V97OwAD.png")
                em.set_footer(text="fly on little ducky")
                await duck_msg.edit(embed=em)
        except Exception as e:
            self.log.error(f'An error occurred: {e.__class__.__name__}: {e}')
            msg = "Something went wrong with updating the duck embed, but we still recorded your score."
            await self.ctx_send(ctx, msg, source_delay=10)
        self.log.info("Done updating embed...")

        self.log.info("Setting new ducktime...")
        self.set_ducktime(channel_id, guild_id)
        self.log.info("Done setting new ducktime. Done!")
        return

    @commands.command()
    async def bang(self, ctx):
        """- when there is a duck on the loose use this command to shoot it."""
        guild_id = str(getattr(ctx.guild, 'id', None))
        channel_id = str(getattr(ctx.channel, 'id', None))
        channel_name = str(getattr(ctx.channel, 'name', None))
        author_name = str(getattr(ctx.author, 'name', None))
        with self.chan_locks[guild_id][channel_id.casefold()]:
            return await self.attack(ctx, ctx.author, channel_id, channel_name, guild_id, "shoot")

    @commands.command(aliases=["bef"])
    async def befriend(self, ctx):
        """- when there is a duck on the loose use this command to befriend it before someone else shoots it."""
        guild_id = str(getattr(ctx.guild, 'id', None))
        channel_id = str(getattr(ctx.channel, 'id', None))
        channel_name = str(getattr(ctx.channel, 'name', None))
        author_name = str(getattr(ctx.author, 'name', None))
        with self.chan_locks[guild_id][channel_id.casefold()]:
            return await self.attack(ctx, ctx.author, channel_id, channel_name, guild_id, "befriend")

    def top_list(self, prefix, data, join_char=" • "):
        sorted_data = sorted(data, key=operator.itemgetter(1), reverse=True)

        reply_text: List[str] = []
        for k,v in sorted_data:
            reply_text.append(f"{k}: {v}")
        return SimplePages(entries=reply_text, per_page=15)

    def get_scores(self, score_type, guild_id, channel_id=None):
        clause = self.table.network == guild_id
        if channel_id is not None:
            clause = and_(clause, self.table.chan == channel_id.lower())
        query_column = getattr(self.table, score_type)
        query = select(self.table.name, query_column).where(clause).order_by(
            desc(query_column)
        )

        scores = self.db.execute(query).fetchall()
        return scores

    def get_channel_scores(self, score_type: ScoreType, guild_id, channel_id):
        scores_dict: Dict[str, int] = defaultdict(int)
        scores = self.get_scores(score_type.column_name, guild_id, channel_id)

        if not scores:
            return None

        for row in scores:
            if row[1] == 0:
                continue

            scores_dict[row[0]] += row[1]

        return scores_dict

    def _get_global_scores(self, score_type: ScoreType, guild_id):
        scores_dict: Dict[str, int] = defaultdict(int)
        chancount: Dict[str, int] = defaultdict(int)
        scores = self.get_scores(score_type.column_name, guild_id)
        if not scores:
            return None, None

        for row in scores:
            if row[1] == 0:
                continue

            chancount[row[0]] += 1
            scores_dict[row[0]] += row[1]

        return scores_dict, chancount

    def get_global_scores(self, score_type: ScoreType, guild_id):
        return self._get_global_scores(score_type, guild_id)[0]

    def get_average_scores(self, score_type: ScoreType, guild_id):
        scores_dict, chancount = self._get_global_scores(score_type, guild_id)
        if not scores_dict:
            return None

        for k, v in scores_dict.items():
            scores_dict[k] = int(v / chancount[k])

        return scores_dict

    async def display_scores(self, ctx, score_type: ScoreType, text, channel_id, guild_id):
        channel_name = str(getattr(ctx.channel, 'name', None))

        if self.is_opt_out(guild_id, channel_id):
            return

        global_pfx = "Duck {noun} scores across the network: ".format(
            noun=score_type.noun
        )
        chan_pfx = "Duck {noun} scores in {chan}: ".format(
            noun=score_type.noun, chan=channel_name
        )
        no_ducks = "It appears no one has {verb} any ducks yet.".format(
            verb=score_type.verb
        )

        out = global_pfx if text else chan_pfx

        try:
            func = self.display_funcs[text.lower() or None]
        except KeyError:
            return

        scores_dict = call_with_args(
            func,
            {
                "score_type": score_type,
                "guild_id": guild_id,
                "channel_id": channel_id,
            },
        )

        if not scores_dict:
            return await self.ctx_send(ctx, no_ducks, source_delay=10)

        pages = self.top_list(out, scores_dict.items())
        try:
            await pages.start(ctx)
        except menus.MenuError as e:
            await ctx.send(repr(e))
        if self.delete_source_msg:
            await ctx.message.delete(delay=10)

    @commands.command()
    async def friends(self, ctx, text=""):
        """[{global|average}] - Prints a list of the top duck friends in the
        channel, if 'global' is specified all channels in the database are
        included.
        """
        guild_id = str(getattr(ctx.guild, 'id', None))
        channel_id = str(getattr(ctx.channel, 'id', None))
        await self.display_scores(ctx, self.score_types["friend"], text, channel_id, guild_id)

    @commands.command()
    async def killers(self, ctx, text=""):
        """[{global|average}] - Prints a list of the top duck killers in the
        channel, if 'global' is specified all channels in the database are
        included.
        """
        guild_id = str(getattr(ctx.guild, 'id', None))
        channel_id = str(getattr(ctx.channel, 'id', None))
        await self.display_scores(ctx, self.score_types["killer"], text, channel_id, guild_id)

    @commands.command()
    @checks.is_mod()
    async def duckpunish(self, ctx, nick: discord.Member, cooldown=7200):
        """<nick> - Allows people to be manually added to cooldown list for
        specified time (in seconds)
        """
        guild_id = str(getattr(ctx.guild, 'id', None))
        channel_id = str(getattr(ctx.channel, 'id', None))
        status = self.get_state_table(guild_id, channel_id)

        if nick.id in self.scripters and self.scripters[nick.id] > time():
            out = "{} is already being punished. Give them a break! Cooldown expires at: {}".format(
                nick.name, datetime.fromtimestamp(self.scripters[nick.id])
            )
            return await self.ctx_send(ctx, out, source_delay=10)

        self.scripters[nick.id] = time() + cooldown
        out = "{} has been naughty. You put them in a cooldown until {}".format(
            nick.name, datetime.fromtimestamp(self.scripters[nick.id])
        )
        await self.ctx_send(ctx, out, source_delay=10)

    @commands.command()
    @checks.is_mod()
    async def duckforgive(self, ctx, nick: discord.Member):
        """<nick> - Allows people to be removed from the mandatory cooldown period."""
        if nick.id in self.scripters and self.scripters[nick.id] > time():
            self.scripters[nick.id] = 0
            out = "{} has been removed from the mandatory cooldown period.".format(nick.name)
            return await self.ctx_send(ctx, out, source_delay=10)

        out = "I couldn't find anyone banned from the hunt by that nick"
        await self.ctx_send(ctx, out, source_delay=10)

    @commands.command()
    @checks.is_mod()
    async def hunt_opt_out(self, ctx, *, text=""):
        """[{add <chan>|remove <chan>|list}] - Running this command without any arguments displays the status of the
        current channel. hunt_opt_out add #channel will disable all duck hunt commands in the specified channel.
        hunt_opt_out remove #channel will re-enable the game for the specified channel.
        """
        guild_id = str(getattr(ctx.guild, 'id', None))
        channel_id = str(getattr(ctx.channel, 'id', None))
        channel_name = str(getattr(ctx.channel, 'name', None))
        status = self.get_state_table(guild_id, channel_id)

        if not text:
            if self.is_opt_out(guild_id, channel_id):
                out = "Duck hunt is disabled in {}. To re-enable it run `!hunt_opt_out remove <channel ID>`".format(channel_name)
                return await self.ctx_send(ctx, out, source_delay=10)

            out = "Duck hunt is enabled in {}. To disable it run `!hunt_opt_out add <channel ID>`".format(channel_name)
            return await self.ctx_send(ctx, out, source_delay=10)

        if text == "list":
            channel_list = ", #".join(self.bot.get_channel(x).name for x in self.opt_out[int(guild_id)])
            if channel_list:
                out = "Channels duck hunt is disabled in: #{}.".format(channel_list)
            else:
                out = "Duck hunt is not disabled in any channels."
            return await self.ctx_send(ctx, out, source_delay=10)


        if len(text.split(" ")) < 2:
            out = "Please specify add or remove and a valid channel name"
            return await self.ctx_send(ctx, out, source_delay=10)

        command = text.split()[0]
        try:
            channel = int(text.split()[1])
        except:
            out = "Please specify a valid channel."
            return await self.ctx_send(ctx, out, source_delay=10)

        if command.lower() == "add":
            if self.is_opt_out(guild_id, channel):
                out = "Duck hunt has already been disabled in #{}.".format(
                    self.bot.get_channel(channel).name
                )
                return await self.ctx_send(ctx, out, source_delay=10)

            query = insert(self.nohunt_table).values(network=guild_id, chan=channel)
            self.db.execute(query)
            self.db.commit()
            self.load_optout()

            out = "The duckhunt has been successfully disabled in #{}.".format(
                self.bot.get_channel(channel).name
            )
            return await self.ctx_send(ctx, out, source_delay=10)

        if command.lower() == "remove":
            if not self.is_opt_out(guild_id, channel):
                out = "Duck hunt is already enabled in #{}.".format(channel)
                return await self.ctx_send(ctx, out, source_delay=10)

            query = delete(self.nohunt_table).where(self.nohunt_table.chan == channel)
            self.db.execute(query)
            self.db.commit()
            self.load_optout()
            out = "The duckhunt has been successfully re-enabled in #{}.".format(
                self.bot.get_channel(channel).name
            )
            return await self.ctx_send(ctx, out, source_delay=10)

    @commands.command(aliases=["duckmerge"])
    @checks.is_mod()
    async def duck_merge(self, ctx, oldnick: Union[discord.Member, str], newnick: Union[discord.Member, str]):
        """<user1> <user2> - Moves the duck scores from one nick to another nick. Accepts two nicks as input the first will
        have their duck scores removed the second will have the first score added. Warning this cannot be undone.
        """
        guild_id = str(getattr(ctx.guild, 'id', None))

        if isinstance(oldnick, discord.Member):
            oldnick = oldnick.name.lower()
        else:
            oldnick = oldnick.lower()

        if isinstance(newnick, discord.Member):
            newnick = newnick.name.lower()
        else:
            newnick = newnick.lower()

        if oldnick == newnick:
            out = "Cannot merge the same nicks."
            return await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)

        if not oldnick or not newnick:
            out = "Please specify two nicks for this command."
            return await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)

        oldnickquery = select(
            self.table.name,
            self.table.chan,
            self.table.shot,
            self.table.befriend
        ).where(
            self.table.network == guild_id,
            self.table.name == oldnick
        )
        oldnickscore = self.db.execute(oldnickquery).fetchall()

        newnickquery = select(
            self.table.name,
            self.table.chan,
            self.table.shot,
            self.table.befriend
        ).where(
            self.table.network == guild_id,
            self.table.name == newnick
        )
        newnickscore = self.db.execute(newnickquery).fetchall()

        duckmerge: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        total_kills = 0
        total_friends = 0
        channelkey: Dict[str, List[str]] = {"update": [], "insert": []}
        if not oldnickscore:
            out = "There are no duck scores to migrate from {}".format(oldnick)
            return await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)

        new_chans = []

        for row in newnickscore:
            new_chans.append(row.chan)
            chan_data = duckmerge[row.chan]
            chan_data["shot"] = row.shot
            chan_data["befriend"] = row.befriend

        for row in oldnickscore:
            chan_name = row.chan
            chan_data1 = duckmerge[chan_name]
            shot: int = row.shot
            _friends: int = row.befriend
            chan_data1["shot"] += shot
            chan_data1["befriend"] += _friends
            total_kills += shot
            total_friends += _friends
            if chan_name in new_chans:
                channelkey["update"].append(chan_name)
            else:
                channelkey["insert"].append(chan_name)

        for channel in channelkey["insert"]:
            self.dbadd_entry(
                newnick,
                channel,
                guild_id,
                duckmerge[channel]["shot"],
                duckmerge[channel]["befriend"],
            )

        for channel in channelkey["update"]:
            self.dbupdate(
                newnick,
                channel,
                guild_id,
                duckmerge[channel]["shot"],
                duckmerge[channel]["befriend"],
            )

        query = delete(self.table).where(
            and_(self.table.network == guild_id, self.table.name == oldnick)
        )

        self.db.execute(query)
        self.db.commit()
        out = "Migrated {} and {} from {} to {}".format(
                pluralize_auto(total_kills, "duck kill"),
                pluralize_auto(total_friends, "duck friend"),
                oldnick,
                newnick,
            )
        await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)

    @commands.command(aliases=["ducks"])
    async def ducks_user(self, ctx, *, text=""):
        """<nick> - Prints a users duck stats. If no nick is input it will check the calling username."""
        guild_id = str(getattr(ctx.guild, 'id', None))
        channel_id = str(getattr(ctx.channel, 'id', None))
        channel_name = str(getattr(ctx.channel, 'name', None))
        nick = str(getattr(ctx.author, 'name', None))

        name = nick.lower()
        if text:
            name = text.split()[0].lower()

        ducks: Dict[str, int] = defaultdict(int)
        scores = self.db.execute(
            select(
                self.table.name, self.table.chan, self.table.shot, self.table.befriend
            ).where(
                and_(
                    self.table.network == guild_id,
                    self.table.name == name,
                ),
            )
        ).fetchall()

        if text:
            name = text.split()[0]
        else:
            name = nick

        if scores:
            has_hunted_in_chan = False
            for row in scores:
                if row.chan.lower() == channel_id.lower():
                    has_hunted_in_chan = True
                    ducks["chankilled"] += row.shot
                    ducks["chanfriends"] += row.befriend

                ducks["killed"] += row.shot
                ducks["friend"] += row.befriend
                ducks["chans"] += 1

            # Check if the user has only participated in the hunt in this channel
            if ducks["chans"] == 1 and has_hunted_in_chan:
                out = "**{}** has killed {} and befriended {} in *#{}*.".format(
                    name,
                    pluralize_auto(ducks["chankilled"], "duck"),
                    pluralize_auto(ducks["chanfriends"], "duck"),
                    channel_name,
                    )
                return await self.ctx_send(ctx, out, delete_delay=60, source_delay=10)

            kill_average = int(ducks["killed"] / ducks["chans"])
            friend_average = int(ducks["friend"] / ducks["chans"])
            out = "**{}'s** duck stats: {} killed and {} befriended in *#{}*. " \
                "Across {}: {} killed and {} befriended. " \
                "Averaging {} and {} per channel.".format(
                    name,
                    pluralize_auto(ducks["chankilled"], "duck"),
                    pluralize_auto(ducks["chanfriends"], "duck"),
                    chan,
                    pluralize_auto(ducks["chans"], "channel"),
                    pluralize_auto(ducks["killed"], "duck"),
                    pluralize_auto(ducks["friend"], "duck"),
                    pluralize_auto(kill_average, "kill"),
                    pluralize_auto(friend_average, "friend"),
                )
            return await self.ctx_send(ctx, out, delete_delay=300, source_delay=10)

        out = "It appears {} has not participated in the duck hunt.".format(name)
        await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)

    @commands.command(aliases=["duckstats"])
    async def duck_stats(self, ctx):
        """- Prints duck statistics for the entire channel and totals for the network."""
        guild_id = str(getattr(ctx.guild, 'id', None))
        channel_id = str(getattr(ctx.channel, 'id', None))
        channel_name = str(getattr(ctx.channel, 'name', None))
        
        scores = self.db.execute(
            select(
                self.table.name, self.table.chan, self.table.shot, self.table.befriend
            ).where(self.table.network == guild_id)
        ).fetchall()
        friend_chan: Dict[str, int] = defaultdict(int)
        kill_chan: Dict[str, int] = defaultdict(int)
        chan_killed = 0
        chan_friends = 0
        killed = 0
        friends = 0
        chans = set()

        if scores:
            for row in scores:
                chan_name = self.bot.get_channel(int(row.chan)).name
                chans.add(chan_name)
                friend_chan[chan_name] += row.befriend
                kill_chan[chan_name] += row.shot
                if chan_name.lower() == channel_name.lower():
                    chan_killed += row.shot
                    chan_friends += row.befriend

                killed += row.shot
                friends += row.befriend

            killerchan, killscore = sorted(
                kill_chan.items(), key=operator.itemgetter(1), reverse=True
            )[0]
            friendchan, friendscore = sorted(
                friend_chan.items(),
                key=operator.itemgetter(1),
                reverse=True,
            )[0]
            out = "**Duck Stats:** {:,} killed and {:,} befriended in *#{}*. " \
                "Across {} {:,} ducks have been killed and {:,} befriended. " \
                "**Top Channels:** *#{}* with {} and *#{}* with {}".format(
                    chan_killed,
                    chan_friends,
                    channel_name,
                    pluralize_auto(len(chans), "channel"),
                    killed,
                    friends,
                    killerchan,
                    pluralize_auto(killscore, "kill"),
                    friendchan,
                    pluralize_auto(friendscore, "friend"),
                )
            return await self.ctx_send(ctx, out, delete_delay=300, source_delay=10)

        out = "It looks like there has been no duck activity on this channel or network."
        await self.ctx_send(ctx, out, delete_delay=20, source_delay=10)


def setup(bot):
    bot.add_cog(Duckhunt(bot))
