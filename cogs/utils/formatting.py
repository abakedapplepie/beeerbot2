import copy


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
