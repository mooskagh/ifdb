import logging
from games.importer.tools import (Import, GetUrlCandidates, HashizeUrl,
                                  GetBagOfWords, ComputeSimilarity)
from games.models import Game
from django.contrib.auth import get_user_model
from ifdb.permissioner import Permissioner
from games.views import UpdateGame, Importer2Json

URLCATS_TO_HASH = [
    'game_page', 'download_direct', 'download_landing', 'play_online'
]
USER = 'бездушный робот'
SIMILAR_TITLES_LOWCONF = 0.67
SIMILAR_TITLES_HIGHCONF = 0.9


class FakeRequest:
    def __init__(self, username):
        self.user = get_user_model().objects.get(username=username)
        self.perm = Permissioner(self.user)


class ImportedGame:
    def __init__(self, game=None):
        self.game = game
        self.title = None
        self.title_bow = set()
        self.seed_urls = []
        self.hash_urls = []
        self.new_urls = []
        self.content = None
        self.is_updateable = True
        self.is_error = False
        self.is_modified = False

        if game:
            self.title = game.title
            self.title_bow = GetBagOfWords(self.title)
            self.seed_urls = [
                x.url.original_url
                for x in game.gameurl_set.filter(
                    category__symbolic_id='game_page')
            ]
            self.hash_urls = [
                HashizeUrl(x.url.original_url)
                for x in game.gameurl_set.filter(
                    category__symbolic_id__in=URLCATS_TO_HASH)
            ]
            self.is_updateable = (game.added_by.username == USER and
                                  game.edit_time is None)

    def HashizedUrls(self):
        return self.hash_urls

    def SeedUrls(self):
        return self.seed_urls

    def AddUrl(self, url):
        self.seed_urls.append(url)
        self.new_urls.append(url)
        self.hash_urls.append(HashizeUrl(url))
        self.content = None
        self.is_modified = True

    def GetTitleBow(self):
        return self.title_bow

    def Fetch(self):
        self.content = Import(*self.seed_urls)
        self.is_error = 'title' not in self.content

        if self.is_error:
            logging.warn("Was unable to fetch: %s\n%s" % (self.seed_urls,
                                                          self.content))
            return False

        self.seed_urls = [
            x['url'] for x in self.content['urls']
            if x['urlcat_slug'] == 'game_page'
        ]
        self.hash_urls = [
            HashizeUrl(x['url']) for x in self.content['urls']
            if x['urlcat_slug'] in URLCATS_TO_HASH
        ]
        self.title = self.content['title']
        self.title_bow = GetBagOfWords(self.title)
        return True

    def IsModified(self):
        return self.is_modified

    def IsUpdateable(self):
        return self.is_updateable

    def NewUrls(self):
        return self.new_urls

    def Store(self, request):
        if not self.content:
            if not self.Fetch():
                logging.error("Failed to fetch %s" % self)
                return
        game = Importer2Json(self.content)
        if self.game:
            game['game_id'] = self.game.id
        logging.info("Updating %s" % self)
        UpdateGame(request, game, update_edit_time=False)

    def __str__(self):
        s = 'Game: [%s]' % self.title
        if self.game:
            s += ', id: [%d]' % self.game.id
        for x in self.seed_urls:
            s += ', url: [%s]' % x
        return s


class GameSet:
    def __init__(self):
        self.games = []
        self.url_to_game = {}

    def AddGame(self, game):
        for u in game.HashizedUrls():
            if u in self.url_to_game:
                logging.error("Game [%s] has the same URL [%s] has game [%s]" %
                              (game, u, self.url_to_game[u]))
            else:
                self.url_to_game[u] = game

        self.games.append(game)

    def HasUrl(self, url):
        h = HashizeUrl(url)
        return h in self.url_to_game

    def TryMerge(self, game):
        similar_games = set()
        for x in game.HashizedUrls():
            if x in self.url_to_game:
                similar_games.add(self.url_to_game[x])

        if not similar_games:
            for x in self.games:
                if ComputeSimilarity(
                        x.GetTitleBow(),
                        game.GetTitleBow()) > SIMILAR_TITLES_HIGHCONF:
                    similar_games.add(x)

        if len(similar_games) > 1:
            logging.error("Found %d similar games while importing [%s]:\n%s" %
                          (len(similar_games), game,
                           '\n'.join([str(x) for x in similar_games])))

        best_game = None
        best_similariry = 0.0
        for x in similar_games:
            sim = ComputeSimilarity(game.GetTitleBow(), x.GetTitleBow())
            if sim > best_similariry:
                best_similariry = sim
                best_game = x

        if best_game is None or best_similariry <= SIMILAR_TITLES_LOWCONF:
            if len(similar_games) > 0:
                logging.error(
                    "Similar games are too dissimilar (%.2f) [%s]:\n%s" %
                    (best_similariry, game,
                     '\n'.join([str(x) for x in similar_games])))

            self.AddGame(game)
            return

        for x in game.SeedUrls():
            logging.error("Found games with similarity %.2f merging:\n%s\n%s" %
                          (best_similariry, game, best_game))
            if x not in best_game.HashizedUrls():
                best_game.AddUrl(x)

    def Games(self):
        return self.games


def ImportGames():
    gameset = GameSet()
    for x in Game.objects.prefetch_related('gameurl_set__category',
                                           'gameurl_set__url').all():
        gameset.AddGame(ImportedGame(x))

    candidates = set(GetUrlCandidates())

    while candidates:
        u = candidates.pop()
        if gameset.HasUrl(u):
            logging.debug('Url %s already existed.' % u)
            continue

        g = ImportedGame()
        g.AddUrl(u)
        if g.Fetch():
            gameset.TryMerge(g)

    fake_request = FakeRequest(USER)

    for x in gameset.Games():
        if not x.IsModified():
            continue
        if x.IsUpdateable():
            x.Store(fake_request)
        else:
            new_urls = '\n'.join(x.NewUrls())
            logging.error('New URLs for existing non-updateable game:'
                          '\n%s\nNew urls are:\n%s' % (x, new_urls))
