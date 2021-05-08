import asyncio
import os
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
import praw
import random
from random import shuffle
import logging
import discord
from discord.ext import commands

class Comic(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("beeerbot")
        self.log.info("Comic initialized")

    async def cog_command_error(self, ctx, error):
        return

    #hook to !comic
    @commands.command()
    async def comic(self, ctx):
        """comic <title string> - creates a comic and posts it to reddit. title is used for reddit title and imgur title """
        self.log.info("Comic invoked by %s", ctx.author.name)
        self.log.info(ctx.message)
        
        try:
            for msg in ctx.history(limit=10,before=ctx.message):
                self.log.info(msg)
        except Exception as e:
            self.log.error(f'Exception encountered', exc_info=1)

        return await ctx.send('testing complete')

        #existing comic code follows, not finished going over
        for i in range(len(msgs)-1, -1, -1):
            msg_count += 1
            diff = msgs[i][0] - msgs[i-1][0]
            chars.add(msgs[i][1])
            if msg_count >= bot.config.buffer_size or diff.total_seconds() > bot.config.dead_space or len(chars) > bot.config.total_characters:
                break

        panels = []
        panel = []

        seed = random.randint(0, msg_count)
        i = 0
        #fix for discord
        #  for (d, char, msg) in msgs:
            # if i == seed:
                # if len(text) > 0:
                    # reddit_title = text
                # else:
                    # reddit_title = msg
            # if len(panel) == 2 or len(panel) == 1 and panel[0][0] == char:
                # panels.append(panel)
                # panel = []
            # if msg.count('\x01') >= 2:
                # ctcp = msg.split('\x01', 2)[1].split(' ', 1)
                # if len(ctcp) == 1:
                    # ctcp += ['']
                # if ctcp[0] == 'ACTION':
                    # msg = '*'+ctcp[1]+'*'
            # panel.append((char, msg))
            # i += 1 

        panels.append(panel)
        self.log.info("Panels are prepared: %s", repr(panels))

        # Initialize a variable to store our image
        image_comic = BytesIO()

        # Save the completed composition to a JPEG in memory
        make_comic(chars, panels).save(image_comic, format="JPEG", quality=85)

        # Get API Key, upload the comic to imgur
        headers = {'Authorization': 'Client-ID ' + bot.config.imgur_client_id}
        base64img = base64.b64encode(image_comic.getvalue())
        url = "https://api.imgur.com/3/upload.json"
        r = requests.post(url, data={'key': bot.config.imgur_client_id, 'image': base64img, 'title': reddit_title}, headers=headers, verify=False)
        val = json.loads(r.text)
        try:
            result = val['data']['link']
            try:
                self.log.info("Authenticating reddit")
                reddit = praw.Reddit(
                    client_id=bot.config.reddit_api_id,
                    client_secret=bot.config.reddit_api_secret,
                    password=bot.config.reddit_password,
                    user_agent=bot.config.reddit_agent,
                    username=bot.config.reddit_username)
                self.log.info("Authenticated as %s", reddit.user.me())

                try:
                    submission = reddit.subreddit(bot.config.reddit_subreddit).submit(reddit_title, url=result)
                    submission_id = submission.id
                    return await ctx.send("https://redd.it/%s %s %s", submission_id, lol[random.randint(0, lol_count)], reddit_title)
                except Exception as e:
                    self.log.error("FAILED to post to reddit - but hey, at least we signed in!", exc_info=1)
                    return await ctx.send("fail")
            except Exception as e:
                self.log.error("FAILED to authenticate reddit", exc_info=1)
                return await ctx.send("fail")
        except KeyError:
            self.log.error("FAILED, KeyError", exc_info=1)
            return await ctx.send("fail")
        del submission, reddit, r, base64img, image_comic

    def wrap(st, font, draw, width):
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


    def rendertext(st, font, draw, pos):
        ch = pos[1]
        for s in st:
            w, h = draw.textsize(s, font=font)
            draw.text((pos[0]-1, ch), s, font=font, fill=(0x00, 0x00, 0x00, 0xff))
            draw.text((pos[0]+1, ch), s, font=font, fill=(0x00, 0x00, 0x00, 0xff))
            draw.text((pos[0], ch-1), s, font=font, fill=(0x00, 0x00, 0x00, 0xff))
            draw.text((pos[0], ch+1), s, font=font, fill=(0x00, 0x00, 0x00, 0xff))
            draw.text((pos[0], ch), s, font=font, fill=(0xff, 0xff, 0xff, 0xff))
            ch += h


    def fitimg(img, width, height):
        scale1 = float(width) / img.size[0]
        scale2 = float(height) / img.size[1]

        l1 = (img.size[0] * scale1, img.size[1] * scale1)
        l2 = (img.size[0] * scale2, img.size[1] * scale2)

        if l1[0] > width or l1[1] > height:
            l = l2
        else:
            l = l1

        return img.resize((int(l[0]), int(l[1])), Image.ANTIALIAS)


    def make_comic(chars, panels):
        panelheight = 300
        panelwidth = 450

        filenames = os.listdir('chars/')
        shuffle(filenames)
        filenames = map(lambda x: os.path.join('chars', x), filenames[:len(chars)])
        chars = list(chars)
        chars = zip(chars, filenames)
        charmap = dict()
        for ch, f in chars:
            charmap[ch] = Image.open(f)

        imgwidth = panelwidth
        imgheight = panelheight * len(panels)

        bg = Image.open(bot.config.background_file)

        im = Image.new("RGB", (imgwidth, imgheight), (0xff, 0xff, 0xff, 0xff))
        font = ImageFont.truetype(bot.config.font_file, bot.config.font_size)

        for i in range(len(panels)):
            pim = Image.new("RGB", (panelwidth, panelheight), (0xff, 0xff, 0xff, 0xff))
            pim.paste(bg, (0, 0))
            draw = ImageDraw.Draw(pim)

            st1w = 0
            st1h = 0
            st2w = 0
            st2h = 0

            (st1, (st1w, st1h)) = wrap(panels[i][0][1], font, draw, 2*panelwidth/3.0)
            rendertext(st1, font, draw, (10, 10))
            if len(panels[i]) == 2:
                (st2, (st2w, st2h)) = wrap(panels[i][1][1], font, draw, 2*panelwidth/3.0)
                rendertext(st2, font, draw, (panelwidth-10-st2w, st1h + 10))

            texth = st1h + 10
            if st2h > 0:
                texth += st2h + 10 + 5

            maxch = panelheight - texth
            im1 = fitimg(charmap[panels[i][0][0]], 2*panelwidth/5.0-10, maxch)
            pim.paste(im1, (10, panelheight-im1.size[1]), im1)

            if len(panels[i]) == 2:
                im2 = fitimg(charmap[panels[i][1][0]], 2*panelwidth/5.0-10, maxch)
                im2 = im2.transpose(Image.FLIP_LEFT_RIGHT)
                pim.paste(im2, (panelwidth-im2.size[0]-10, panelheight-im2.size[1]), im2)

            draw.line([(0, 0), (0, panelheight-1), (panelwidth-1, panelheight-1), (panelwidth-1, 0), (0, 0)], (0, 0, 0, 0xff))
            del draw
            im.paste(pim, (0, panelheight * i))

        return im



def setup(bot):
    bot.add_cog(Comic(bot))