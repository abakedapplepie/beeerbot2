import asyncio
import sys
import os
import asyncpraw
from random import shuffle
import random
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
import base64
import requests
import json
from datetime import datetime
from io import BytesIO
import logging
import discord
from discord.ext import commands

class Comic(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger(__name__)
        self.config = bot.config
        self.lol = ['mfw', 'dae', 'member', 'tfw', 'lol']
        self.log.info("Comic initialized")

    async def cog_command_error(self, ctx, error):
        return

    #hook to !comic
    @commands.command()
    async def comic(self, ctx, *arg):
        """comic <title string> - creates a comic and posts it to reddit. title is used for reddit title and imgur title """
        comic_title = " ".join(arg)
        try: 
            self.log.info("Comic invoked by %s, he supplied the title %s", ctx.author.name, comic_title)

            msgs = []
            try:
                async for msg in ctx.history(limit=15,before=ctx.message):
                    if not msg.author.bot:
                        msgs.append(msg)

            except Exception as e:
                self.log.error(f'Exception encountered', exc_info=1)
            
            del msgs[self.config.comic_options.buffer_size:]
            msg_count = 0
            chars = set()
            for i in range(len(msgs)-1, -1, -1):
                msg_count += 1
                diff = msgs[i].created_at - msgs[i-1].created_at
                chars.add(msgs[i].author.name)
                if msg_count >= self.config.comic_options.buffer_size or diff.total_seconds() > self.config.comic_options.dead_space or len(chars) > self.config.comic_options.total_characters:
                    self.log.info('breaking out of msg char loop')
                    break
            
            del msgs[msg_count:]
            msgs.reverse()

            panels = []
            panel = []

            seed = random.randint(0, msg_count)
            i = 0
            for msg in msgs:
                if i == seed:
                    if len(comic_title) > 0:
                        reddit_title = comic_title
                    else:
                        reddit_title = "{} {}".format(random.choice(self.lol), msg.content)
                if len(panel) == 2 or len(panel) == 1 and panel[0][0] == msg.author.name:
                    panels.append(panel)
                    panel = []
                panel.append((msg.author.name, msg.content))
                i += 1 

            panels.append(panel)

            # Initialize a variable to store our image
            image_comic = BytesIO()

            # Save the completed composition to a JPEG in memory
            self.make_comic(chars, panels).save(image_comic, format="JPEG", quality=85)

            # Get API Key, upload the comic to imgur
            headers = {'Authorization': 'Client-ID ' + self.config.api_keys.imgur_client_id}
            base64img = base64.b64encode(image_comic.getvalue())
            url = "https://api.imgur.com/3/upload.json"
            r = requests.post(url, data={'key': self.config.api_keys.imgur_client_id, 'image': base64img, 'title': reddit_title}, headers=headers, verify=False)
            val = json.loads(r.text)
            try:
                imgur_result = val['data']['link']
                self.log.info(val['data']['link'])
                try:
                    self.log.info("Authenticating reddit")
                    reddit = asyncpraw.Reddit(
                        client_id=self.config.api_keys.reddit_api_id,
                        client_secret=self.config.api_keys.reddit_api_secret,
                        password=self.config.comic_options.reddit_password,
                        user_agent=self.config.comic_options.reddit_agent,
                        username=self.config.comic_options.reddit_username)
                    self.log.info("Authenticated as %s", await reddit.user.me())

                    try:
                        subreddit = await reddit.subreddit(self.config.comic_options.reddit_subreddit)
                        submission = await subreddit.submit(reddit_title, url=imgur_result)
                        submission_id = submission.id
                    except Exception as e:
                        self.log.error("FAILED to post to reddit - but hey, at least we signed in!", exc_info=1)
                        return await ctx.send("fail")
                except Exception as e:
                    self.log.error("FAILED to authenticate reddit", exc_info=1)
                    return await ctx.send("fail")
            except KeyError:
                self.log.error("FAILED to upload to imgur", exc_info=1)
                return await ctx.send("fail")

            em = discord.Embed(
                title=reddit_title,
                url="https://redd.it/{}".format(submission_id),
                description="",
                color=0xF4B400)
            em.set_thumbnail(url=imgur_result)
            em.set_author(name="beeerbot enterprises", icon_url="https://i.imgur.com/UAXu5U7.png")
            em.set_footer(text="brought to you by raid shadow legends", icon_url="https://i.imgur.com/YKWsNyI.png")

            return await ctx.send(embed=em)

            del submission, reddit, r, base64img, image_comic
        except  Exception as e:
            self.log.error("FAILED ", exc_info=1)

    def wrap(self, st, font, draw, width):
        st = st.split()
        mw = 0
        mh = 0
        ret = []

        while len(st) > 0:
            s = 1
            while True and s < len(st):
                w, h = draw.textsize(" ".join(st[:s]), font=font)
                if w > width:
                    s -= 1
                    break
                else:
                    s += 1

            if s == 0 and len(st) > 0:  # we've hit a case where the current line is wider than the screen
                s = 1

            w, h = draw.textsize(" ".join(st[:s]), font=font)
            mw = max(mw, w)
            mh += h
            ret.append(" ".join(st[:s]))
            st = st[s:]

        return ret, (mw, mh)

    def rendertext(self, st, font, draw, pos):
        ch = pos[1]
        for s in st:
            w, h = draw.textsize(s, font=font)
            draw.text((pos[0]-1, ch), s, font=font, fill=(0x00, 0x00, 0x00, 0xff))
            draw.text((pos[0]+1, ch), s, font=font, fill=(0x00, 0x00, 0x00, 0xff))
            draw.text((pos[0], ch-1), s, font=font, fill=(0x00, 0x00, 0x00, 0xff))
            draw.text((pos[0], ch+1), s, font=font, fill=(0x00, 0x00, 0x00, 0xff))
            draw.text((pos[0], ch), s, font=font, fill=(0xff, 0xff, 0xff, 0xff))
            ch += h

    def fitimg(self, img, width, height):
        scale1 = float(width) / img.size[0]
        scale2 = float(height) / img.size[1]

        l1 = (img.size[0] * scale1, img.size[1] * scale1)
        l2 = (img.size[0] * scale2, img.size[1] * scale2)

        if l1[0] > width or l1[1] > height:
            l = l2
        else:
            l = l1

        return img.resize((int(l[0]), int(l[1])), Image.ANTIALIAS)

    def make_comic(self, chars, panels):

        panelheight = 300
        panelwidth = 450

        filenames = os.listdir(self.config.comic_options.char_files)
        shuffle(filenames)
        filenames = map(lambda x: os.path.join(self.config.comic_options.char_files, x), filenames[:len(chars)])
        chars = list(chars)
        chars = zip(chars, filenames)
        charmap = dict()
        for ch, f in chars:
            charmap[ch] = Image.open(f)

        imgwidth = panelwidth
        imgheight = panelheight * len(panels)

        bg = Image.open(self.config.comic_options.background_file)

        im = Image.new("RGB", (imgwidth, imgheight), (0xff, 0xff, 0xff, 0xff))
        font = ImageFont.truetype(self.config.comic_options.font_file, self.config.comic_options.font_size)

        for i in range(len(panels)):
            pim = Image.new("RGB", (panelwidth, panelheight), (0xff, 0xff, 0xff, 0xff))
            pim.paste(bg, (0, 0))
            draw = ImageDraw.Draw(pim)

            st1w = 0
            st1h = 0
            st2w = 0
            st2h = 0

            (st1, (st1w, st1h)) = self.wrap(panels[i][0][1], font, draw, 2*panelwidth/3.0)
            self.rendertext(st1, font, draw, (10, 10))
            if len(panels[i]) == 2:
                (st2, (st2w, st2h)) = self.wrap(panels[i][1][1], font, draw, 2*panelwidth/3.0)
                self.rendertext(st2, font, draw, (panelwidth-10-st2w, st1h + 10))

            texth = st1h + 10
            if st2h > 0:
                texth += st2h + 10 + 5

            maxch = panelheight - texth
            im1 = self.fitimg(charmap[panels[i][0][0]], 2*panelwidth/5.0-10, maxch)
            pim.paste(im1, (10, panelheight-im1.size[1]), im1)

            if len(panels[i]) == 2:
                im2 = self.fitimg(charmap[panels[i][1][0]], 2*panelwidth/5.0-10, maxch)
                im2 = im2.transpose(Image.FLIP_LEFT_RIGHT)
                pim.paste(im2, (panelwidth-im2.size[0]-10, panelheight-im2.size[1]), im2)

            draw.line([(0, 0), (0, panelheight-1), (panelwidth-1, panelheight-1), (panelwidth-1, 0), (0, 0)], (0, 0, 0, 0xff))
            del draw
            im.paste(pim, (0, panelheight * i))

        return im


def setup(bot):
    bot.add_cog(Comic(bot))
