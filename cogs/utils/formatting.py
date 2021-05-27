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
