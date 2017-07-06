import re
from .models import Game, GameTag, GameTagCategory
import statistics
from .tools import FormatDate, FormatTime, StarsFromRating
from django.db.models import Q, Count, prefetch_related_objects

RE_WORD = re.compile(r"\w(?:[-\w']+\w)?")


def TokenizeText(text):
    res = set()
    for x in RE_WORD.finditer(text):
        res.add(x.group(0).lower())
    return res


class BaseXReader:
    ALPHABET = (b"0123456789abcdefghijklmnopqrstuvwxyz"
                b"ABCDEFGHIJKLMNOPQRSTUVWXYZ~-_.!*'(),$")
    XLAT = None
    HEAD_SPACE = len(ALPHABET) // 2
    TRUNK_SPACE = len(ALPHABET) - HEAD_SPACE

    def __init__(self, s):
        self.buf = s
        self.ptr = 0
        if self.XLAT is None:
            res = [None] * 256
            for i, x in enumerate(self.ALPHABET):
                res[x] = i
            BaseXReader.XLAT = res

    def Done(self):
        return self.ptr >= len(self.buf)

    def getUnit(self):
        res = self.XLAT[ord(self.buf[self.ptr])]
        self.ptr += 1
        return res

    def ReadInt(self):
        multiplier = 1
        res = 0
        while True:
            u = self.getUnit()
            res += multiplier * u
            if u < self.HEAD_SPACE:
                break
            multiplier *= self.TRUNK_SPACE
        return res

    def ReadString(self):
        size = self.ReadInt()
        return ''.join([chr(self.ReadInt()) for x in range(size)]).encode(
            'utf-16', 'surrogatepass').decode('utf-16')

    def ReadBool(self):
        return self.ReadInt() != 0

    def ReadSet(self):
        res = []
        count = self.ReadInt()
        for i in range(count):
            res.append(self.ReadInt())
            if i > 0:
                res[i] += res[i - 1] + 1
        return set(res)

    def ReadFlags(self, count):
        res = []
        val = self.ReadInt()
        while val:
            res.append(val % 2 == 1)
            val //= 2
        res += [False] * (count - len(res))
        return res


class SearchBit:
    def __init__(self, val=0, hidden=False):
        self.val = val
        self.hidden = hidden

    def Id(self):
        return self.val * 16 + self.TYPE_ID

    def NeedsFullSet(self):
        return True

    def ProduceDict(self, typ):
        return {
            'id': self.Id(),
            'val': self.val,
            'hidden': self.hidden,
            'type': typ
        }

    def ModifyQuery(self, query):
        return query

    def ModifyResult(self, res):
        return res

    def IsActive(self):
        return False

    def Hidden(self):
        return self.hidden

    def Unhide(self):
        self.hidden = False


# Types of sorting:
# 0,1 - Creation date
# 2,3 - Release date
# 4,5 - Rating
# 5,6 - Duration
class SB_Sorting(SearchBit):
    TYPE_ID = 0

    CREATION_DATE = 0
    RELEASE_DATE = 1
    RATING = 2
    DURATION = 3

    STRINGS = {
        CREATION_DATE: 'дате добавления',
        RELEASE_DATE: 'дате релиза',
        RATING: 'рейтингу',
        DURATION: 'продолжительности',
    }

    ALLOWED_SORTINGS = [CREATION_DATE, RELEASE_DATE, RATING, DURATION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.method = self.ALLOWED_SORTINGS[0]
        self.desc = True

    def ProduceDict(self):
        res = super().ProduceDict('sorting')
        res['items'] = []
        for x in self.ALLOWED_SORTINGS:
            current = x == self.method
            res['items'].append({
                'val': x,
                'name': self.STRINGS[x],
                'current': current,
                'desc': current and self.desc,
                'asc': current and not self.desc,
            })
        return res

    def LoadFromQuery(self, reader):
        v = reader.ReadInt()
        self.desc = (v % 2 == 0)
        self.method = v // 2
        if self.method not in self.ALLOWED_SORTINGS:
            self.method = self.ALLOWED_SORTINGS[0]

    def ModifyQuery(self, query):
        if self.method == self.CREATION_DATE:
            return query.order_by(('-' if self.desc else '') + 'creation_time')

        if self.method in [self.RATING, self.DURATION]:
            return query.prefetch_related('gamevote_set')
        return query

    def NeedsFullSet(self):
        return self.method not in [self.CREATION_DATE]

    def ModifyResult(self, games):
        r = self.desc
        if self.method == self.CREATION_DATE:
            for g in games:
                g.ds['creation_date'] = FormatDate(g.creation_time)
            return games

        # TODO move to Query part
        if self.method == self.RELEASE_DATE:
            for g in games:
                if g.release_date is not None:
                    g.ds['release_date'] = FormatDate(g.release_date)
            games.sort(
                key=lambda x: ((x.release_date is None) != r, x.release_date),
                reverse=self.desc)
            return games

        if self.method == self.RATING:
            ratings = []
            nones = []
            for g in games:

                def DiscountRating(x, count):
                    P1 = 2.7
                    P2 = 0.5
                    return (x - P1) * (P2 + count) / (P2 + count + 1) + P1

                votes = [x.star_rating for x in g.gamevote_set.all()]
                if not votes:
                    nones.append(g)
                    continue
                avg = statistics.mean(votes)
                g.ds['stars'] = StarsFromRating(avg)
                g.ds['scores'] = len(votes)
                vote = DiscountRating(avg, len(votes))
                ratings.append((vote, g))

            ratings.sort(key=lambda x: x[0], reverse=self.desc)
            rated_games = list(list(zip(*ratings))[1]) if ratings else []
            return rated_games + nones

        if self.method == self.DURATION:
            times = []
            nones = []
            for g in games:
                plays = [
                    x.play_time_mins for x in g.gamevote_set.all()
                    if x.game_finished
                ]
                if not plays:
                    nones.append(g)
                    continue
                avg = statistics.median(plays)
                g.ds['duration'] = {'hours': avg // 60, 'mins': avg % 60}
                times.append((avg, g))

            times.sort(key=lambda x: x[0], reverse=self.desc)
            timed_games = list(list(zip(*times))[1]) if times else []
            return timed_games + nones

    def IsActive(self):
        return True


class SB_Text(SearchBit):
    TYPE_ID = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.text = ''
        self.titles_only = True

    def ProduceDict(self):
        res = super().ProduceDict('text')
        res['text'] = self.text
        res['titles_only'] = self.titles_only
        return res

    def LoadFromQuery(self, reader):
        self.titles_only = reader.ReadBool()
        self.text = reader.ReadString()

    def IsActive(self):
        return bool(self.text)

    def NeedsFullSet(self):
        return True

    def ModifyResult(self, games):
        # TODO(crem) Do something at query time.
        query = TokenizeText(self.text or '')
        res = []
        for g in games:
            tokens = TokenizeText(g.title or '')
            if not self.titles_only:
                tokens |= TokenizeText(g.description or '')
            if len(tokens & query) >= 0.7 * len(query):
                res.append(g)
        return res


class SB_Tag(SearchBit):
    TYPE_ID = 2

    def __init__(self, cat, *args, **kwargs):
        super().__init__(cat.id, True)
        self.cat = cat
        self.items = set()

    def ProduceDict(self):
        res = super().ProduceDict('tags')
        res['cat'] = self.cat
        items = []
        for x in (GameTag.objects.select_related('category').filter(
                category=self.cat).annotate(
                    Count('game')).order_by('-game__count')):
            items.append({
                'id': x.id,
                'name': x.name,
                'on': x.id in self.items,
                'tag': x,
            })

        if len(items) > 10 and items[0]['tag'].category.allow_new_tags:
            for x in items[6:]:
                x['hidden'] = True
            items.append({'show_all': True})

        items.append({'id': 0, 'name': 'Не указано', 'on': 0 in self.items})
        res['items'] = items
        return res

    def LoadFromQuery(self, reader):
        self.items = reader.ReadSet()

    def ModifyQuery(self, query):
        return query.prefetch_related('tags')

    def NeedsFullSet(self):
        return True

    def IsActive(self):
        return bool(self.items)

    def ModifyResult(self, games):
        # TODO This should absolutely be in ModifyQuery!
        res = []
        for g in games:
            tags = set(
                [x.id for x in g.tags.all() if x.category_id == self.cat.id])
            if tags & self.items or not tags and 0 in self.items:
                res.append(g)
        return res


# !!!!NOTE!!!! If adding new flag sets, reflect that in google analytics!
class SB_Flags(SearchBit):
    TYPE_ID = 3

    def __init__(self):
        super().__init__(self.VAL_ID, True)
        self.items = [False] * len(self.FIELDS)

    def ProduceDict(self):
        res = super().ProduceDict('flags')
        res['header'] = self.HEADER
        items = []
        for i, x in enumerate(self.FIELDS):
            items.append({'id': i, 'name': x, 'on': self.items[i]})
        res['items'] = items
        return res

    def LoadFromQuery(self, reader):
        self.items = reader.ReadFlags(len(self.FIELDS))

    def ModifyQuery(self, query):
        q = None
        for i, v in enumerate(self.items):
            if not v:
                continue
            if i in self.ANNOTATIONS:
                query = query.annotate(self.ANNOTATIONS[i])
            q = q | self.QUERIES[i] if q else self.QUERIES[i]
        return query.filter(q)

    def NeedsFullSet(self):
        return False

    def IsActive(self):
        return True in self.items


class SB_UserFlags(SB_Flags):
    HEADER = 'Наличие ресурсов'
    VAL_ID = 0

    FIELDS = [
        'С видео',
        'С обзорами',
        'С комментариями',
        'С обсуждениями на форуме',
        'Можно скачать',
        'Можно поиграть онлайн',
    ]

    ANNOTATIONS = {}

    QUERIES = {
        0:
            Q(gameurl__category__symbolic_id='video'),
        1:
            Q(gameurl__category__symbolic_id='review'),
        2:
            Q(gamecomment__isnull=False),
        3:
            Q(gameurl__category__symbolic_id='forum'),
        4:
            Q(gameurl__category__symbolic_id__in=[
                'download_direct', 'download_landing'
            ]),
        5: (Q(gameurl__category__symbolic_id='play_online') |
            Q(gameurl__interpretedgameurl__is_playable=True)),
    }


class SB_AuxFlags(SB_Flags):
    HEADER = 'Для садовников'
    VAL_ID = 1

    FIELDS = [
        'С файлами без категорий',
        'Без авторов',
        'Без даты выпуска',
        'UrqW -- проверенные',
        'UrqW -- непроверенные',
        'UrqW -- неработающие',
        'С участниками без роли',
    ]

    ANNOTATIONS = {
        1: (Count('gameauthor')),
        7: (Count('gameurl__url__gameurl')),
    }

    QUERIES = {
        0:
            Q(gameurl__category__symbolic_id='unknown'),
        1:
            Q(gameauthor__count=0),
        2:
            Q(release_date__isnull=True),
        3:
            Q(gameurl__interpretedgameurl__is_playable=True),
        4: (Q(gameurl__interpretedgameurl__isnull=False) & Q(
            gameurl__interpretedgameurl__is_playable__isnull=True)),
        5:
            Q(gameurl__interpretedgameurl__is_playable=False),
        6:
            Q(gameauthor__role__symbolic_id='member'),
    }


# [int:0] - Sorting. + [int: sort type, lowest bit for direction]
# [int:1] [int:type] text input [bool:flags] [sting]
#         { type 0 -> text search, flag:0 -> only titles }
# [int:2] - Tag [int:category] [set:values]
# [int:3] [int:0] - BitEncoded + [bools:flags]
# [int:4] [int:0] - Duration [int:min or 0] [int:max or 0]
#                   [bool:games without duration]
# [int:5] [int:0 for release] -
#         Date [int:min:days since 1900 or 0] [int:max:days or 0]
#         [bool:games without duration]
#     Possibly merge int:4 and int:5 into range input.


def LimitListlike(q, start, limit):
    if start is None:
        if limit is None:
            return q
        else:
            return q[:limit]
    else:
        if limit is None:
            return q[start:]
        else:
            return q[start:start + limit]


class Search:
    def __init__(self, perm):
        self.perm = perm
        self.bits = []
        self.id_to_bit = {}

    def Add(self, bit):
        self.bits.append(bit)
        self.id_to_bit[bit.Id()] = bit

    def ProduceBits(self):
        unhide_all = False
        for x in self.bits:
            if x.Hidden() and x.IsActive():
                unhide_all = True

        if unhide_all:
            for x in self.bits:
                x.Unhide()

        res = []
        for x in self.bits:
            res.append(x.ProduceDict())
        return {'unhide_button': not unhide_all, 'search': res}

    def UpdateFromQuery(self, query):
        reader = BaseXReader(query)
        while not reader.Done():
            key = reader.ReadInt()
            self.id_to_bit[key].LoadFromQuery(reader)

    def Search(self, *, prefetch_related=None, start=None, limit=None):
        need_full_query = False
        partial_query = start is not None or limit is not None

        q = Game.objects.all()
        for x in self.bits:
            if x.IsActive():
                q = x.ModifyQuery(q)
                if x.NeedsFullSet(): need_full_query = True

        two_stage_fetch = need_full_query and partial_query
        if prefetch_related and not two_stage_fetch:
            q = q.prefetch_related(*prefetch_related)
        q = q.distinct()

        if not two_stage_fetch:
            q = LimitListlike(q, start, limit)

        games = [x for x in q if self.perm(x.view_perm)]
        for g in games:
            g.ds = {}
        for x in self.bits:
            if x.IsActive():
                games = x.ModifyResult(games)

        if two_stage_fetch:
            games = LimitListlike(games, start, limit)
            if prefetch_related:
                prefetch_related_objects(games, *prefetch_related)

        return games


def MakeSearch(perm):
    s = Search(perm)
    s.Add(SB_Sorting())
    s.Add(SB_Text())
    for x in GameTagCategory.objects.order_by('order').all():
        if not perm(x.show_in_search_perm):
            continue
        s.Add(SB_Tag(x))
    s.Add(SB_UserFlags())
    s.Add(SB_AuxFlags())
    return s
