## beeerbot2

Beeerbot: now in Discord

## Installing

1. **Make sure to get Python 3.5 or higher**

This is required to actually run the bot.

2. **Set up venv**

```
$ python3 -m venv ~/path/to/venv/beeerbot/
$ source ~/path/to/venv/beeerbot/bin/activate
```

3. **Install dependencies**

`pip install -U -r requirements.txt`

4. **Setup configuration**

Copy the `config.default.yml` file in the root directory and rename to `config.yml`.
The only required field is `discord.token`. Everything else depends on which cogs
you have loaded.

6. **Configuration of database**

To configure the SQLite database for use by the bot, go to the directory where `launcher.py` is located, and run the script by doing `python3 launcher.py db init`.

## Running

Launch with `python launcher.py`
