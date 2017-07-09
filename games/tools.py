import markdown
from urllib.parse import urlparse, parse_qs


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


def ConcoreNumeral(value, arg):
    bits = arg.split(u',')
    try:
        one = str(value)[-1:]
        dec = str(value)[-2:-1]
        if dec == '1':
            res = bits[2]
        elif one == '1':
            res = bits[0]
        elif one in '234':
            res = bits[1]
        else:
            res = bits[2]
        return "%s %s" % (value, res)
    except:
        raise TemplateSyntaxError
    return ''


def FormatLag(x):
    x = int(x)
    if x <= 0:
        x = -x
        fmtstr = "%s назад"
    else:
        fmtstr = "через %s"

    def GetDurationStr(x):
        if x < 60: return ConcoreNumeral(x, 'секунду,секунды,секунд')
        x //= 60
        if x < 60: return ConcoreNumeral(x, 'минуту,минуты,минут')
        x //= 60
        if x < 24: return ConcoreNumeral(x, 'час,часа,часов')
        x //= 24
        if x < 31: return ConcoreNumeral(x, 'день,дня,дней')
        x //= 30
        if x < 12: return ConcoreNumeral(x, 'месяц,месяца,месяцев')
        x //= 12
        return ConcoreNumeral(x, 'год,года,лет')

    return fmtstr % GetDurationStr(x)


def ExtractYoutubeId(url):
    purl = urlparse(url)
    if purl.hostname in ['youtube.com', 'www.youtube.com']:
        q = parse_qs(purl.query).get('v')
        if q:
            return q[0]
    elif purl.hostname == 'youtu.be':
        return purl.path[1:]


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