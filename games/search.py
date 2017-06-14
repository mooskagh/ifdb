import re
from .models import Game
import statistics
from .tools import FormatDate, FormatTime, StarsFromRating

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


class SearchBit:
    def __init__(self, val=0, hidden=False):
        self.val = val
        self.hidden = hidden

    def Id(self):
        return self.val * 16 + self.TYPE_ID

    def ProduceDict(self, typ):
        return {'id': self.Id(),
                'val': self.val,
                'hidden': self.hidden,
                'type': typ}

    def ModifyQuery(self, query):
        return query

    def ModifyResult(self, res):
        return res


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
                vote = DiscountRating(avg, len(votes))
                ratings.append((vote, g))

            ratings.sort(key=lambda x: x[0], reverse=self.desc)
            return list(list(zip(*ratings))[1]) + nones

        if self.method == self.DURATION:
            times = []
            nones = []
            for g in games:
                plays = [x.play_time_mins for x in g.gamevote_set.all()
                         if x.game_finished]
                if not plays:
                    nones.append(g)
                    continue
                avg = statistics.median(plays)
                g.ds['duration'] = {'hours': avg // 60, 'mins': avg % 60}
                times.append((avg, g))

            times.sort(key=lambda x: x[0], reverse=self.desc)
            return list(list(zip(*times))[1]) + nones


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

    def ModifyResult(self, games):
        if not self.text:
            return games
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


class Search:
    def __init__(self):
        self.bits = []
        self.id_to_bit = {}

    def Add(self, bit):
        self.bits.append(bit)
        self.id_to_bit[bit.Id()] = bit

    def ProduceBits(self):
        res = []
        for x in self.bits:
            res.append(x.ProduceDict())
        return res

    def UpdateFromQuery(self, query):
        reader = BaseXReader(query)
        while not reader.Done():
            key = reader.ReadInt()
            self.id_to_bit[key].LoadFromQuery(reader)

    def Search(self):
        # TODO  perms!
        q = Game.objects.all()
        for x in self.bits:
            q = x.ModifyQuery(q)
        games = list(q)
        for g in games:
            g.ds = {}
        for x in self.bits:
            games = x.ModifyResult(games)
        return games


def MakeSearch():
    s = Search()
    s.Add(SB_Sorting())
    s.Add(SB_Text())
    return s
