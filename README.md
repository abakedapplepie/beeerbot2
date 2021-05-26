## beeerbot2

Beeerbot: now in Discord

## Installing

1. **Make sure to get Python 3.5 or higher**

This is required to actually run the bot.

2. Install necessary packages [\*Nix]

You will need `git`, `python3-dev` and `libenchant1c2a`, `libxml2-dev`, `libxslt-dev` and `zlib1g-dev`. Install these with your system's package manager.

For example, on a Debian-based system, you could use:
```bash
[sudo] apt-get install -y python3-dev git libenchant-dev libxml2-dev libxslt-dev zlib1g-dev
```

You will also need to install `pip`, which can be done by following [this guide](https://packaging.python.org/guides/installing-using-pip-and-virtual-environments/#installing-pip)

3. **Set up venv**

```
$ python3 -m venv ~/path/to/venv/beeerbot/
$ source ~/path/to/venv/beeerbot/bin/activate
```

4. **Install dependencies**

`pip install -U -r requirements.txt`

5. **Setup configuration**

Copy the `config.default.yml` file in the root directory and rename to `config.yml`.
The only required field is `discord.token`. Everything else depends on which cogs
you have loaded.

6. **Configuration of database**

To configure the SQLite database for use by the bot, go to the directory where `launcher.py` is located, and run the script by doing `python3 launcher.py db init`.

## Running

Launch with `python launcher.py`
