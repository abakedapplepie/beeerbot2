import copy


def truncate(content, length=100, suffix="...", sep=" "):
    """
    Truncates a string after a certain number of characters.
    Function always tries to truncate on a word boundary.
    """
    if len(content) <= length:
        return content

    return content[:length].rsplit(sep, 1)[0] + suffix


# compatibility
truncate_str = truncate


def get_text_list(list_, last_word="or"):
    """
    >>> get_text_list(['a', 'b', 'c', 'd'])
    'a, b, c or d'
    >>> get_text_list(['a', 'b', 'c'], 'and')
    'a, b and c'
    >>> get_text_list(['a', 'b'], 'and')
    'a and b'
    >>> get_text_list(['a'])
    'a'
    >>> get_text_list([])
    ''
    """
    if not list_:
        return ""

    if len(list_) == 1:
        return list_[0]

    return "%s %s %s" % (
        ", ".join([i for i in list_][:-1]),
        last_word,
        list_[-1],
    )


def gen_markdown_table(headers, rows):
    """
    Generates a Markdown formatted table from the data
    """
    rows = copy.copy(rows)
    rows.insert(0, headers)
    rotated = zip(*reversed(rows))

    sizes = tuple(map(lambda l: max(max(map(len, l)), 3), rotated))
    rows.insert(1, tuple(("-" * size) for size in sizes))
    lines = [
        "| {} |".format(
            " | ".join(cell.ljust(sizes[i]) for i, cell in enumerate(row))
        )
        for row in rows
    ]
    return "\n".join(lines)


# Pluralize
def pluralize_suffix(num=0, text="", suffix="s"):
    """
    Takes a number and a string, and pluralizes that string using the number and combines the results.
    """
    return pluralize_select(num, text, text + suffix)


pluralise_suffix = pluralize_suffix


def pluralize_select(count, single, plural):
    return "{:,} {}".format(count, single if count == 1 else plural)


pluralise_select = pluralize_select


def pluralize_auto(count, thing):
    if thing.endswith("us"):
        return pluralize_select(count, thing, thing[:-2] + "i")

    if thing.endswith("is"):
        return pluralize_select(count, thing, thing[:-2] + "es")

    if thing.endswith(("s", "ss", "sh", "ch", "x", "z")):
        return pluralize_suffix(count, thing, "es")

    if thing.endswith(("f", "fe")):
        return pluralize_select(count, thing, thing.rsplit("f", 1)[0] + "ves")

    if thing.endswith("y") and thing[-2:-1].lower() not in "aeiou":
        return pluralize_select(count, thing, thing[:-1] + "ies")

    if thing.endswith("y") and thing[-2:-1].lower() in "aeiou":
        return pluralize_suffix(count, thing)

    if thing.endswith("o"):
        return pluralize_suffix(count, thing, "es")

    if thing.endswith("on"):
        return pluralize_select(count, thing, thing[:-2] + "a")

    return pluralize_suffix(count, thing)


pluralise_auto = pluralize_auto


class plural:
    def __init__(self, value):
        self.value = value
    def __format__(self, format_spec):
        v = self.value
        singular, sep, plural = format_spec.partition('|')
        plural = plural or f'{singular}s'
        if abs(v) != 1:
            return f'{v} {plural}'
        return f'{v} {singular}'

def human_join(seq, delim=', ', final='or'):
    size = len(seq)
    if size == 0:
        return ''

    if size == 1:
        return seq[0]

    if size == 2:
        return f'{seq[0]} {final} {seq[1]}'

    return delim.join(seq[:-1]) + f' {final} {seq[-1]}'

class TabularData:
    def __init__(self):
        self._widths = []
        self._columns = []
        self._rows = []

    def set_columns(self, columns):
        self._columns = columns
        self._widths = [len(c) + 2 for c in columns]

    def add_row(self, row):
        rows = [str(r) for r in row]
        self._rows.append(rows)
        for index, element in enumerate(rows):
            width = len(element) + 2
            if width > self._widths[index]:
                self._widths[index] = width

    def add_rows(self, rows):
        for row in rows:
            self.add_row(row)

    def render(self):
        """Renders a table in rST format.

        Example:

        +-------+-----+
        | Name  | Age |
        +-------+-----+
        | Alice | 24  |
        |  Bob  | 19  |
        +-------+-----+
        """

        sep = '+'.join('-' * w for w in self._widths)
        sep = f'+{sep}+'

        to_draw = [sep]

        def get_entry(d):
            elem = '|'.join(f'{e:^{self._widths[i]}}' for i, e in enumerate(d))
            return f'|{elem}|'

        to_draw.append(get_entry(self._columns))
        to_draw.append(sep)

        for row in self._rows:
            to_draw.append(get_entry(row))

        to_draw.append(sep)
        return '\n'.join(to_draw)
