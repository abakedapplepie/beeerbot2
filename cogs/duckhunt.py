import operator
import random
from collections import defaultdict
from time import time
import logging
import discord
from discord.ext import tasks, commands
import DiscordUtils

from sqlalchemy import Table, Column, String, Integer, PrimaryKeyConstraint, desc, Boolean
from sqlalchemy.sql import select



"""
self.game_status structure 
{ 
    'network':{
        '#chan1':{
            'duck_status':0|1|2, 
            'next_duck_time':'integer', 
            'game_on':0|1,
            'no_duck_kick': 0|1,
            'duck_time': 'float', 
            'shoot_time': 'float',
            'messages': integer,
            'masks' : list
        }
    }
}
"""
#TODO: stats are not correctly notifying when no results (friends/killers)

class Duckhunt(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("beeerbot")
        self.config = bot.config
        self.db = bot.db_session

        # Set up tables
        self.table = Table(
            'duck_hunt',
            bot.db_metadata,
            Column('network', String),
            Column('name', String),
            Column('shot', Integer),
            Column('befriend', Integer),
            Column('chan', String),
            PrimaryKeyConstraint('name', 'chan', 'network')
        )
        self.optout = Table(
            'nohunt',
            bot.db_metadata,
            Column('network', String),
            Column('chan', String),
            PrimaryKeyConstraint('chan', 'network')
        )
        self.status_table = Table(
            'duck_status',
            bot.db_metadata,
            Column('network', String),
            Column('chan', String),
            Column('active', Boolean, default=False),
            Column('duck_kick', Boolean, default=False),
            PrimaryKeyConstraint('network', 'chan')
        )
        
        #Set up duck parts
        self.duck_tail = "・゜゜・。。・゜゜"
        self.duck = ["\_o< ", "\_O< ", "\_0< ", "\_\u00f6< ", "\_\u00f8< ", "\_\u00f3< "]
        self.duck_noise = ["QUACK!", "FLAP FLAP!", "quack!"]

        # Set up game status
        self.scripters = defaultdict(int)
        self.game_status = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        # set optout status
        self.opt_out = []
        chans = self.db.execute(select([self.optout.c.chan]))
        if chans:
            for row in chans:
                chan = row["chan"]
                self.opt_out.append(chan)

        #set up duck times for all channels
        rows = self.db.execute(self.status_table.select())
        for row in rows:
            net = row['network']
            chan = row['chan']
            status = self.game_status[net][chan]
            status["game_on"] = int(row['active'])
            status["no_duck_kick"] = int(row['duck_kick'])
            self.set_ducktime(chan, net)

        #TODO: set up interval to check self.deploy_duck(). every minute?
        #TODO: set up interval to self.save_status()

        self.log.info("Duckhunt initialized")

    async def cog_command_error(self, ctx, error):
        return

    def cog_unload(self):
        self.save_status()
        self.save_status.cancel()
        self.deploy_duck.cancel()

    @tasks.loop(seconds=15.0)
    async def deploy_duck(self):
        for network in self.game_status:
            for chan in self.game_status[network]:
                active = self.game_status[network][chan]['game_on']
                duck_status = self.game_status[network][chan]['duck_status']
                next_duck = self.game_status[network][chan]['next_duck_time']
                chan_messages = self.game_status[network][chan]['messages']
                chan_masks = self.game_status[network][chan]['masks']
                if active == 1 and duck_status == 0 and next_duck <= time() and chan_messages >= self.config.duckhunt_options.min_lines and len(chan_masks) >= self.config.duckhunt_options.min_users:
                    # deploy a duck to channel
                    self.game_status[network][chan]['duck_status'] = 1
                    self.game_status[network][chan]['duck_time'] = time()
                    dtail, dbody, dnoise = self.generate_duck()
                    channel = self.bot.get_channel(chan)
                    em = discord.Embed(
                        title="a duck has appeared",
                        description="{}{}{}".format(dtail, dbody, dnoise),
                        color=469033)
                    em.set_thumbnail(url="https://i.imgur.com/2cY8l5R.png")
                    duck_message = channel.send(embed=em)
                    self.game_status[network][chan]['duck_message_id'] = duck_message.id
                    self.log.info("deploying duck to {}".format(channel.name))
                # Leave this commented out for now. I haven't decided how to make ducks leave.
                # if active == 1 and duck_status == 1 and self.game_status[network][chan]['flyaway'] <= int(time()):
                #    conn.message(chan, "The duck flew away.")
                #    self.game_status[network][chan]['duck_status'] = 2
                #    set_ducktime(chan, conn)
                continue
            continue


    @tasks.loop(seconds=300)
    async def save_status(self):
        for network in self.game_status:
            for chan, status in self.game_status[network].items():
                active = bool(status['game_on'])
                duck_kick = bool(status['no_duck_kick'])
                res = self.db.execute(self.status_table.update().where(self.status_table.c.network == network).where(
                    self.status_table.c.chan == chan).values(
                    active=active, duck_kick=duck_kick
                ))
                if not res.rowcount:
                    self.db.execute(self.status_table.insert().values(network=network, chan=chan, active=active, duck_kick=duck_kick))

        self.db.commit()


    def dbadd_entry(self, nick, guild_id, channel_id, shoot, friend):
        """Takes care of adding a new row to the database."""
        query = self.table.insert().values(
            network=guild_id,
            chan=channel_id,
            name=nick,
            shot=shoot,
            befriend=friend)
        self.db.execute(query)
        self.db.commit()


    def dbupdate(self, nick, guild_id, channel_id, shoot, friend):
        """update a db row"""
        if shoot and not friend:
            query = self.table.update() \
                .where(self.table.c.network == guild_id) \
                .where(self.table.c.chan == channel_id) \
                .where(self.table.c.name == nick) \
                .values(shot=shoot)
            self.db.execute(query)
            self.db.commit()
        elif friend and not shoot:
            query = self.table.update() \
                .where(self.table.c.network == guild_id) \
                .where(self.table.c.chan == channel_id) \
                .where(self.table.c.name == nick) \
                .values(befriend=friend)
            self.db.execute(query)
            self.db.commit()
        elif friend and shoot:
            query = self.table.update() \
                .where(self.table.c.network == guild_id) \
                .where(self.table.c.chan == channel_id) \
                .where(self.table.c.name == nick) \
                .values(befriend=friend) \
                .values(shot=shoot)
            self.db.execute(query)
            self.db.commit()


    def set_ducktime(self, channel_id, guild_id):
        next_duck = random.randint(int(time()) + 480, int(time()) + 3600)
        self.game_status[guild_id][channel_id]['next_duck_time'] = next_duck
        # self.game_status[conn][chan]['flyaway'] = self.game_status[ctx.guild.id][chan]['next_duck_time'] + 600
        self.game_status[guild_id][channel_id]['duck_status'] = 0
        # let's also reset the number of messages said and the list of masks that have spoken.
        self.game_status[guild_id][channel_id]['messages'] = 0
        self.game_status[guild_id][channel_id]['masks'] = []
        return


    def generate_duck(self):
        """Try and randomize the duck message so people can't highlight on it/script against it."""
        if random.randint(1, 40) == 1:
            dtail = "8====D"
            dbody = "~~~"
            dnoise = "FAP FAP FAP!"
        else:
            rt = random.randint(1, len(self.duck_tail) - 1)
            dtail = self.duck_tail[:rt] + u' \u200b ' + self.duck_tail[rt:]

            dbody = random.choice(self.duck)
            rb = random.randint(1, len(dbody) - 1)
            dbody = dbody[:rb] + u'\u200b' + dbody[rb:]

            dnoise = random.choice(self.duck_noise)
            rn = random.randint(1, len(dnoise) - 1)
            dnoise = dnoise[:rn] + u'\u200b' + dnoise[rn:]
        return (dtail, dbody, dnoise)


    def hit_or_miss(self, deploy, shoot):
        """This function calculates if the befriend or bang will be successful."""
        if shoot - deploy < 1:
            return .05
        elif 1 <= shoot - deploy <= 7:
            out = random.uniform(.60, .75)
            return out
        else:
            return 1


    @commands.Cog.listener('on_message')
    # @hook.event([EventType.message, EventType.action], singlethread=True)
    async def incrementMsgCounter(self, msg):
        """Increment the number of messages said in an active game channel. Also keep track of the unique masks that are speaking."""
        
        if msg.channel.id in self.opt_out:
            return
        if self.game_status[msg.guild.id][msg.channel.id]['game_on'] == 1 and self.game_status[msg.guild.id][msg.channel.id]['duck_status'] == 0:
            self.game_status[msg.guild.id][msg.channel.id]['messages'] += 1
            if msg.author.id not in self.game_status[msg.guild.id][msg.channel.id]['masks']:
                self.game_status[msg.guild.id][msg.channel.id]['masks'].append(msg.author.id)


    @commands.command(aliases=["starthunt"])
    # @hook.command("starthunt", autohelp=False, permissions=["chanop", "op", "botcontrol"])
    async def start_hunt(self, ctx):
        """This command starts a duckhunt in your channel, to stop the hunt use .stophunt"""
        
        if ctx.channel.id in self.opt_out:
            return
        elif ctx.guild is None:
            return await ctx.send("Must be used in a channel")
        check = self.game_status[ctx.guild.id][ctx.channel.id]['game_on']
        if check:
            return await ctx.send("there is already a game running in {}.".format(ctx.channel.name))
        else:
            self.game_status[ctx.guild.id][ctx.channel.id]['game_on'] = 1

        self.set_ducktime(ctx.channel.id, ctx.guild.id)
        return await ctx.send("Ducks have been spotted nearby. See how many you can shoot or save. use !bang to shoot or !befriend to save them. NOTE: Ducks now appear as a function of time and channel activity.")


    @commands.command(aliases=["stophunt"])
    # @hook.command("stophunt", autohelp=False, permissions=["chanop", "op", "botcontrol"])
    async def stop_hunt(self, ctx):
        """This command stops the duck hunt in your channel. Scores will be preserved"""
        
        if ctx.channel.id in self.opt_out:
            return
        if self.game_status[ctx.guild.id][ctx.channel.id]['game_on']:
            self.game_status[ctx.guild.id][ctx.channel.id]['game_on'] = 0
            return await ctx.send("the game has been stopped.")
        else:
            return await ctx.send("There is no game running in {}.".format(ctx.channel.name))


    @commands.command(aliases=["duckmute"])
    # @hook.command("duckkick", permissions=["chanop", "op", "botcontrol"])
    async def no_duck_kick(self, ctx, text):
        """If the bot has OP or half-op in the channel you can specify .duckkick enable|disable so that people are kicked for shooting or befriending a non-existent goose. Default is off."""
        
        if ctx.channel.id in self.opt_out:
            return
        if text.lower() == 'enable':
            self.game_status[ctx.guild.id][ctx.channel.id]['no_duck_kick'] = 1
            return await ctx.send("users will now be muted for shooting or befriending non-existent ducks. The bot needs to have appropriate flags to be able to mute users for this to work.")
            return await ctx.send("users will now be muted for shooting or befriending non-existent ducks. The bot needs to have appropriate flags to be able to mute users for this to work.")
        elif text.lower() == 'disable':
            self.game_status[ctx.guild.id][ctx.channel.id]['no_duck_kick'] = 0
            return await ctx.send("muting for non-existent ducks has been disabled.")
        else:
            return


    @commands.command()
    # @hook.command("bang", autohelp=False)
    async def bang(self, ctx):
        # 
        """when there is a duck on the loose use this command to shoot it."""
        
        if ctx.channel.id in self.opt_out:
            return

        score = ""
        out = ""
        miss = ["WHOOSH! You missed the duck completely!", "Your gun jammed!", "Better luck next time.",
                "WTF?! Who are you, Kim Jong Un firing missiles? You missed."]

        if not self.game_status[ctx.guild.id][ctx.channel.id]['game_on']:
            return await ctx.send("There is no active hunt right now. Use !starthunt to start a game.")
        elif self.game_status[ctx.guild.id][ctx.channel.id]['duck_status'] != 1:
            #TODO: Mute
            #if self.game_status[ctx.guild.id][ctx.channel.id]['no_duck_kick'] == 1:
                #out = "KICK {} {} :There is no duck! What are you shooting at?".format(chan, nick)
            return await ctx.send("There is no duck. What are you shooting at?")
        else:
            self.game_status[ctx.guild.id][ctx.channel.id]['shoot_time'] = time()
            deploy = self.game_status[ctx.guild.id][ctx.channel.id]['duck_time']
            shoot = self.game_status[ctx.guild.id][ctx.channel.id]['shoot_time']

            if ctx.author.id in self.scripters:
                if self.scripters[ctx.author.id] > shoot:
                    #TODO: DM?
                    return await ctx.send("You are in a cool down period, you can try again in {} seconds.".format(str(self.scripters[ctx.author.id] - shoot)))

            chance = self.hit_or_miss(deploy, shoot)
            if not random.random() <= chance and chance > .05:
                out = random.choice(miss) + " You can try again in 7 seconds."
                self.scripters[ctx.author.id] = shoot + 7
                return await ctx.send(out)
            if chance == .05:
                out += "You pulled the trigger in {} seconds, that's mighty fast. Are you sure you aren't a script? Take a 2 hour cool down.".format(str(shoot - deploy))
                self.scripters[ctx.author.id] = shoot + 7200
                if not random.random() <= chance:
                    return await ctx.send(random.choice(miss) + " " + out)
                else:
                    return await ctx.send(out)

            self.game_status[ctx.guild.id][ctx.channel.id]['duck_status'] = 2
            score = self.db.execute(select([self.table.c.shot]) \
                            .where(self.table.c.network == ctx.guild.id) \
                            .where(self.table.c.chan == ctx.channel.id) \
                            .where(self.table.c.name == ctx.author.id)).fetchone()
            if score:
                score = score[0]
                score += 1
                self.dbupdate(ctx.author.name, ctx.channel.id, ctx.guild.id, score, 0)
            else:
                score = 1
                self.dbadd_entry(ctx.author.name, ctx.channel.id, ctx.guild.id, score, 0)

            timer = "{:.3f}".format(shoot - deploy)
            duck = "duck" if score == 1 else "ducks"
            # https://i.imgur.com/0Eyajax.png

            await ctx.send("{} you shot a duck in {} seconds! You have killed {} {} in {}.".format(ctx.author.name, timer, score, duck, ctx.channel.name))


            em = discord.Embed(
                title="this duck has been murdered",
                description="rest in peace little ducky",
                color=996666)
            em.set_thumbnail(url="https://i.imgur.com/0Eyajax.png")
            
            duck_message = ctx.channel.fetch_message(self.game_status[network][chan]['duck_message_id'])
            duck_message.edit(embed=em)
            self.set_ducktime(ctx.channel.id, ctx.guild.id)

    @commands.command(aliases=["bef"])
    # @hook.command("befriend", autohelp=False)
    async def befriend(self, ctx):
        """when there is a duck on the loose use this command to befriend it before someone else shoots it."""
        
        if ctx.channel.id in self.opt_out:
            return

        out = ""
        score = ""
        miss = ["The duck didn't want to be friends, maybe next time.",
                "Well this is awkward, the duck needs to think about it.",
                "The duck said no, maybe bribe it with some pizza? Ducks love pizza don't they?",
                "Who knew ducks could be so picky?"]
        if not self.game_status[ctx.guild.id][ctx.channel.id]['game_on']:
            return await ctx.send("There is no hunt right now. Use !starthunt to start a game.")
        elif self.game_status[ctx.guild.id][ctx.channel.id]['duck_status'] != 1:
            #TODO: Mute
            #if self.game_status[ctx.guild.id][ctx.channel.id]['no_duck_kick'] == 1:
                #out = "KICK {} {} :You tried befriending a non-existent duck. That's fucking creepy.".format(chan, nick)
                
            return await ctx.send("You tried befriending a non-existent duck. That's freaking creepy.")
        else:
            self.game_status[ctx.guild.id][ctx.channel.id]['shoot_time'] = time()
            deploy = self.game_status[ctx.guild.id][ctx.channel.id]['duck_time']
            shoot = self.game_status[ctx.guild.id][ctx.channel.id]['shoot_time']
            if ctx.author.id in self.scripters:
                if self.scripters[ctx.author.id] > shoot:
                    return await ctx.send("You are in a cool down period, you can try again in {} seconds.".format(str(self.scripters[ctx.author.id] - shoot)))

            chance = self.hit_or_miss(deploy, shoot)
            if not random.random() <= chance and chance > .05:
                out = random.choice(miss) + " You can try again in 7 seconds."
                self.scripters[ctx.author.id] = shoot + 7
                return await ctx.send(out)
            if chance == .05:
                out += "You tried friending that duck in {} seconds, that's mighty fast. Are you sure you aren't a script? Take a 2 hour cool down.".format(str(shoot - deploy))
                self.scripters[ctx.author.id] = shoot + 7200
                if not random.random() <= chance:
                    return await ctx.send(random.choice(miss) + " " + out)
                else:
                    return await ctx.send(out)

            self.game_status[ctx.guild.id][ctx.channel.id]['duck_status'] = 2
            score = self.db.execute(select([self.table.c.befriend]) \
                            .where(self.table.c.network == ctx.guild.id) \
                            .where(self.table.c.chan == ctx.channel.id) \
                            .where(self.table.c.name == ctx.author.id)).fetchone()
            if score:
                score = score[0]
                score += 1
                self.dbupdate(ctx.author.name, ctx.channel.id, ctx.guild.id, 0, score)
            else:
                score = 1
                self.dbadd_entry(ctx.author.name, ctx.channel.id, ctx.guild.id, 0, score)
            duck = "duck" if score == 1 else "ducks"
            timer = "{:.3f}".format(shoot - deploy)
            # https://i.imgur.com/XF11gK4.png
            await ctx.send(
                "{} you befriended a duck in {} seconds! You have made friends with {} {} in {}.".format(ctx.author.name, timer, score,
                                                                                                        duck, ctx.channel.name))
                                                                                                        
            em = discord.Embed(
                title="this duck has been befriended",
                description="fly on little ducky",
                color=996666)
            em.set_thumbnail(url="https://i.imgur.com/XF11gK4.png")
            
            duck_message = ctx.channel.fetch_message(self.game_status[network][chan]['duck_message_id'])
            duck_message.edit(embed=em)
            self.set_ducktime(ctx.channel.id, ctx.guild.id)


    def smart_truncate(self, content, length=2000, suffix='...'):
        if len(content) <= length:
            return content
        else:
            return content[:length].rsplit(' • ', 1)[0] + suffix


    @commands.command()
    # @hook.command("friends", autohelp=False)
    async def friends(self, ctx):
        """Prints a list of the top duck friends in the channel, if 'global' is specified all channels in the database are included."""
        if ctx.channel.id in self.opt_out:
            return

        text = str(ctx.message.content)[9:]

        friends = defaultdict(int)
        chancount = defaultdict(int)
        out = ""
        if text.lower() == 'global' or text.lower() == 'average':
            out = "Duck friend scores across the network: "
            scores = self.db.execute(select([self.table.c.name, self.table.c.befriend]) \
                                .where(self.table.c.network == ctx.guild.id) \
                                .order_by(desc(self.table.c.befriend)))
            if scores:
                for row in scores:
                    if row[1] == 0:
                        continue
                    chancount[row[0]] += 1
                    friends[row[0]] += row[1]
                if text.lower() == 'average':
                    for k, v in friends.items():
                        friends[k] = int(v / chancount[k])
            else:
                return await ctx.send("it appears no on has friended any ducks yet.")
        else:
            out = "Duck friend scores in {}: ".format(ctx.channel.name)
            scores = self.db.execute(select([self.table.c.name, self.table.c.befriend]) \
                                .where(self.table.c.network == ctx.guild.id) \
                                .where(self.table.c.chan == ctx.channel.id) \
                                .order_by(desc(self.table.c.befriend)))
            if scores:
                for row in scores:
                    if row[1] == 0:
                        continue
                    friends[row[0]] += row[1]
            else:
                return await ctx.send("it appears no on has friended any ducks yet.")

        try: 
            paginator = DiscordUtils.Pagination.AutoEmbedPaginator(ctx, auto_footer=True, remove_reactions=True, timeout=60)
            topfriends = sorted(friends.items(), key=operator.itemgetter(1), reverse=True)

            count = len(topfriends)
            pages = []
            page_no = 0
            i = 1

            while count > 0:
                field1=topfriends[:10]
                field1value = ""
                field2value = ""
                for k, v in field1:
                    if i % 10 == int(0):
                        newline = ""
                    else:
                        newline = "\n"
                    field1value += "{}. {}: {}{}".format(str(i), k, str(v), newline)
                    i += 1
                rank_1_1 = ((page_no*2)*10)+1
                rank_1_2 = ((page_no*2)+1)*10
                field1title="{} - {}".format(rank_1_1, rank_1_2)
                del topfriends[:10]
                count -= 10
                if count > 10:
                    field2=topfriends[:10]
                    rank_2_1 = rank_1_1+10
                    rank_2_2 = rank_1_2+10
                    del topfriends[:10]
                elif count > 0:
                    remaining = len(topfriends)
                    field2=topfriends[:]
                    rank_2_1 = rank_1_1+10
                    rank_2_2 = rank_1_2+remaining
                    del topfriends
                
                for k, v in field2:
                    if i % 10 == int(0):
                        newline = ""
                    else:
                        newline = "\n"
                    field2value += "{}. {}: {}{}".format(str(i), k, str(v), newline)
                    i += 1
                field2title="{} - {}".format(rank_2_1, rank_2_2)

                page = discord.Embed(title="duck friends scoreboard",description=out, color=356839) \
                            .add_field(name=field1title, value=field1value) \
                            .add_field(name=field2title, value=field2value)
                page.set_footer(text="Use the emojis to change pages")

                pages.append(page)
                count -= 10
                page_no += 1
            return await paginator.run(pages)
        except:
            self.log.error('Failed to paginate', exc_info=1)


    @commands.command()
    # @hook.command("killers", autohelp=False)
    async def killers(self, ctx):
        """Prints a list of the top duck killers in the channel, if 'global' is specified all channels in the database are included."""
        if ctx.channel.id in self.opt_out:
            return

        text = str(ctx.message.content)[9:]

        killers = defaultdict(int)
        chancount = defaultdict(int)
        out = ""
        if text.lower() == 'global' or text.lower() == 'average':
            out = "Duck killer scores across the server: "
            scores = self.db.execute(select([self.table.c.name, self.table.c.shot]) \
                                .where(self.table.c.network == ctx.guild.id) \
                                .order_by(desc(self.table.c.shot)))
            if scores:
                for row in scores:
                    if row[1] == 0:
                        continue
                    chancount[row[0]] += 1
                    killers[row[0]] += row[1]
                if text.lower() == 'average':
                    for k, v in killers.items():
                        killers[k] = int(v / chancount[k])
            else:
                return await ctx.send("it appears no on has killed any ducks yet.")
        else:
            out = "Duck killer scores in {}: ".format(ctx.channel.name)
            scores = self.db.execute(select([self.table.c.name, self.table.c.shot]) \
                                .where(self.table.c.network == ctx.guild.id) \
                                .where(self.table.c.chan == ctx.channel.id) \
                                .order_by(desc(self.table.c.shot)))
            if scores:
                for row in scores:
                    if row[1] == 0:
                        continue
                    killers[row[0]] += row[1]
            else:
                return await ctx.send("it appears no on has killed any ducks yet.")
        try: 
            paginator = DiscordUtils.Pagination.AutoEmbedPaginator(ctx, auto_footer=True, remove_reactions=True, timeout=60)
            topkillers = sorted(killers.items(), key=operator.itemgetter(1), reverse=True)

            count = len(topkillers)
            pages = []
            page_no = 0
            i = 1

            while count > 0:
                field1=topkillers[:10]
                field1value = ""
                field2value = ""
                for k, v in field1:
                    if i % 10 == int(0):
                        newline = ""
                    else:
                        newline = "\n"
                    field1value += "{}. {}: {}{}".format(str(i), k, str(v), newline)
                    i += 1
                rank_1_1 = ((page_no*2)*10)+1
                rank_1_2 = ((page_no*2)+1)*10
                field1title="{} - {}".format(rank_1_1, rank_1_2)
                del topkillers[:10]
                count -= 10
                if count > 10:
                    field2=topkillers[:10]
                    rank_2_1 = rank_1_1+10
                    rank_2_2 = rank_1_2+10
                    del topkillers[:10]
                elif count > 0:
                    remaining = len(topkillers)
                    field2=topkillers[:]
                    rank_2_1 = rank_1_1+10
                    rank_2_2 = rank_1_2+remaining
                    del topkillers
                
                for k, v in field2:
                    if i % 10 == int(0):
                        newline = ""
                    else:
                        newline = "\n"
                    field2value += "{}. {}: {}{}".format(str(i), k, str(v), newline)
                    i += 1
                field2title="{} - {}".format(rank_2_1, rank_2_2)

                page = discord.Embed(title="duck illers scoreboard",description=out, color=356839) \
                            .add_field(name=field1title, value=field1value) \
                            .add_field(name=field2title, value=field2value)
                page.set_footer(text="Use the emojis to change pages")

                pages.append(page)
                count -= 10
                page_no += 1
            return await paginator.run(pages)
        except:
            self.log.error('Failed to paginate', exc_info=1)




    @commands.command()
    # @hook.command("duckmerge", permissions=["botcontrol"])
    async def duckmerge(self, ctx):
        """Moves the duck scores from one nick to another nick. Accepts two nicks as input the first will have their duck scores removed the second will have the first score added. Warning this cannot be undone."""
        
        text = str(ctx.message.content)[11:]

        oldnick, newnick = text.split()
        if not oldnick or not newnick:
            return await ctx.send("Please specify two nicks for this command.")
        oldnickscore = self.db.execute(select([self.table.c.name, self.table.c.chan, self.table.c.shot, self.table.c.befriend])
                                .where(self.table.c.network == ctx.guild.id)
                                .where(self.table.c.name == oldnick)).fetchall()
        newnickscore = self.db.execute(select([self.table.c.name, self.table.c.chan, self.table.c.shot, self.table.c.befriend])
                                .where(self.table.c.network == ctx.guild.id)
                                .where(self.table.c.name == newnick)).fetchall()
        duckmerge = defaultdict(lambda: defaultdict(int))
        duckmerge["TKILLS"] = 0
        duckmerge["TFRIENDS"] = 0
        channelkey = {"update": [], "insert": []}
        if oldnickscore:
            if newnickscore:
                for row in newnickscore:
                    duckmerge[row["chan"]]["shot"] = row["shot"]
                    duckmerge[row["chan"]]["befriend"] = row["befriend"]
                for row in oldnickscore:
                    if row["chan"] in duckmerge:
                        duckmerge[row["chan"]]["shot"] = duckmerge[row["chan"]]["shot"] + row["shot"]
                        duckmerge[row["chan"]]["befriend"] = duckmerge[row["chan"]]["befriend"] + row["befriend"]
                        channelkey["update"].append(row["chan"])
                        duckmerge["TKILLS"] = duckmerge["TKILLS"] + row["shot"]
                        duckmerge["TFRIENDS"] = duckmerge["TFRIENDS"] + row["befriend"]
                    else:
                        duckmerge[row["chan"]]["shot"] = row["shot"]
                        duckmerge[row["chan"]]["befriend"] = row["befriend"]
                        channelkey["insert"].append(row["chan"])
                        duckmerge["TKILLS"] = duckmerge["TKILLS"] + row["shot"]
                        duckmerge["TFRIENDS"] = duckmerge["TFRIENDS"] + row["befriend"]
            else:
                for row in oldnickscore:
                    duckmerge[row["chan"]]["shot"] = row["shot"]
                    duckmerge[row["chan"]]["befriend"] = row["befriend"]
                    channelkey["insert"].append(row["chan"])
                    # TODO: Call self.dbupdate() and db_add_entry for the items in duckmerge
            for channel in channelkey["insert"]:
                self.dbadd_entry(newnick, channel, ctx.guild.id, duckmerge[channel]["shot"], duckmerge[channel]["befriend"])
            for channel in channelkey["update"]:
                self.dbupdate(newnick, channel, ctx.guild.id, duckmerge[channel]["shot"], duckmerge[channel]["befriend"])
            query = self.table.delete() \
                .where(self.table.c.network == ctx.guild.id) \
                .where(self.table.c.name == oldnick)
            self.db.execute(query)
            self.db.commit()
            await ctx.send("Migrated {} duck kills and {} duck friends from {} to {}".format(duckmerge["TKILLS"],
                                                                                    duckmerge["TFRIENDS"], oldnick,
                                                                                    newnick))
        else:
            await ctx.send("There are no duck scores to migrate from {}".format(oldnick))


    @commands.command()
    # @hook.command("ducks", autohelp=False)
    async def ducks(self, ctx):
        """Prints a users duck stats. If no nick is input it will check the calling username."""

        text = str(ctx.message.content)[6:]

        if text:
            name = text.split()[0]
        else:
            name = ctx.author.name
        ducks = defaultdict(int)
        scores = self.db.execute(select([self.table.c.name, self.table.c.chan, self.table.c.shot, self.table.c.befriend])
                            .where(self.table.c.network == ctx.guild.id)
                            .where(self.table.c.name == name)).fetchall()
                            
        if scores:
            for row in scores:
                if row["chan"] == ctx.channel.id:
                    ducks["chankilled"] += row["shot"]
                    ducks["chanfriends"] += row["befriend"]
                ducks["killed"] += row["shot"]
                ducks["friend"] += row["befriend"]
                ducks["chans"] += 1
            if ducks["chans"] == 1:
                return await ctx.send("{} has killed {} and befriended {} ducks in {}.".format(name, ducks["chankilled"],
                                                                                ducks["chanfriends"], ctx.channel.name))
            kill_average = int(ducks["killed"] / ducks["chans"])
            friend_average = int(ducks["friend"] / ducks["chans"])
            return await ctx.send(
                "\x02{}'s\x02 duck stats: \x02{}\x02 killed and \x02{}\x02 befriended in {}. Across {} channels: \x02{}\x02 killed and \x02{}\x02 befriended. Averaging \x02{}\x02 kills and \x02{}\x02 friends per channel.".format(
                    name, ducks["chankilled"], ducks["chanfriends"], ctx.channel.name, ducks["chans"], ducks["killed"], ducks["friend"],
                    kill_average, friend_average))
        else:
            return await ctx.send("It appears {} has not participated in the duck hunt.".format(name))


    @commands.command()
    # @hook.command("duckstats", autohelp=False)
    async def duckstats(self, ctx):
        """Prints duck statistics for the entire channel and totals for the network."""
        ducks = defaultdict(int)
        scores = self.db.execute(select([self.table.c.name, self.table.c.chan, self.table.c.shot, self.table.c.befriend])
                            .where(self.table.c.network == ctx.guild.id)).fetchall()
        if scores:
            ducks["friendchan"] = defaultdict(int)
            ducks["killchan"] = defaultdict(int)
            for row in scores:
                ducks["friendchan"][row["chan"]] += row["befriend"]
                ducks["killchan"][row["chan"]] += row["shot"]
                # ducks["chans"] += 1
                if row["chan"] == ctx.channel.id:
                    ducks["chankilled"] += row["shot"]
                    ducks["chanfriends"] += row["befriend"]
                ducks["killed"] += row["shot"]
                ducks["friend"] += row["befriend"]
            ducks["chans"] = int((len(ducks["friendchan"]) + len(ducks["killchan"])) / 2)
            killerchan, killscore = sorted(ducks["killchan"].items(), key=operator.itemgetter(1), reverse=True)[0]
            friendchan, friendscore = sorted(ducks["friendchan"].items(), key=operator.itemgetter(1), reverse=True)[0]
            await ctx.send(
                "\x02Duck Stats:\x02 {} killed and {} befriended in \x02{}\x02. Across {} channels \x02{}\x02 ducks have been killed and \x02{}\x02 befriended. \x02Top Channels:\x02 \x02{}\x02 with {} kills and \x02{}\x02 with {} friends".format(
                    ducks["chankilled"], ducks["chanfriends"], chan, ducks["chans"], ducks["killed"], ducks["friend"],
                    self.bot.get_channel(killerchan).name, killscore, self.bot.get_channel(friendchan).name, friendscore))
        else:
            await ctx.send( "It looks like there has been no duck activity on this channel or network.")

def setup(bot):
    bot.add_cog(Duckhunt(bot))


# @hook.command("duckforgive", permissions=["op", "ignore"])
# def duckforgive(text):
    # """Allows people to be removed from the mandatory cooldown period."""
    # global self.scripters
    # if text.lower() in self.scripters and self.scripters[text.lower()] > time():
        # self.scripters[text.lower()] = 0
        # return "{} has been removed from the mandatory cooldown period.".format(text)
    # else:
        # return "I couldn't find anyone banned from the hunt by that nick"


# @hook.command("hunt_opt_out", permissions=["op", "ignore"], autohelp=False)
# def hunt_opt_out(text, chan, db, conn):
    # """Running this command without any arguments displays the status of the current channel. hunt_opt_out add #channel will disable all duck hunt commands in the specified channel. hunt_opt_out remove #channel will re-enable the game for the specified channel."""
    # if not text:
        # if chan in opt_out:
            # return "Duck hunt is disabled in {}. To re-enable it run .hunt_opt_out remove #channel".format(chan)
        # else:
            # return "Duck hunt is enabled in {}. To disable it run .hunt_opt_out add #channel".format(chan)
    # if text == "list":
        # return ", ".join(opt_out)
    # if len(text.split(' ')) < 2:
        # return "please specify add or remove and a valid channel name"
    # command = text.split()[0]
    # channel = text.split()[1]
    # if not channel.startswith('#'):
        # return "Please specify a valid channel."
    # if command.lower() == "add":
        # if channel in opt_out:
            # return "Duck hunt has already been disabled in {}.".format(channel)
        # query = optout.insert().values(
            # network=ctx.guild.id,
            # chan=channel.lower())
        # self.db.execute(query)
        # self.db.commit()
        # load_optout(db)
        # return "The duckhunt has been successfully disabled in {}.".format(channel)
    # if command.lower() == "remove":
        # if not channel in opt_out:
            # return "Duck hunt is already enabled in {}.".format(channel)
        # delete = optout.delete(optout.c.chan == channel.lower())
        # self.db.execute(delete)
        # self.db.commit()
        # load_optout(db)
