import markdown


def FormatDate(x):
    if not x:
        return None
    return '%d %s %d' % (x.day, [
        'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
        'августа', 'сентября', 'октября', 'ноября', 'декабря'
    ][x.month - 1], x.year)


def FormatTime(x):
    if not x:
        return None
    return "%04d-%02d-%02d %02d:%02d" % (x.year, x.month, x.day, x.hour,
                                         x.minute)


def StarsFromRating(rating):
    avg = round(rating * 10)
    res = [10] * (avg // 10)
    if avg % 10 != 0:
        res.append(avg % 10)
    res.extend([0] * (5 - len(res)))
    return res


def RenderMarkdown(content):
    return markdown.markdown(content, [
        'markdown.extensions.extra', 'markdown.extensions.meta',
        'markdown.extensions.smarty', 'markdown.extensions.wikilinks',
        'del_ins'
    ]) if content else ''