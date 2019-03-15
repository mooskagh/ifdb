from django.contrib.auth import get_user_model
from games.importer.tools import (Importer, HashizeUrl, GetBagOfWords,
                                  ComputeSimilarity)
from games.models import Game, URL
from games.importer.discord import PostNewGameToDiscord
from games.updater import UpdateGame, Importer2Json
from ifdb.permissioner import Permissioner
from logging import getLogger
from django.contrib.sessions.backends.db import SessionStore

logger = getLogger('worker')

URLCATS_TO_HASH = [
    'game_page', 'download_direct', 'download_landing', 'play_online'
]
USER = 'бездушный робот'
SIMILAR_TITLES_LOWCONF = 0.67
SIMILAR_TITLES_HIGHCONF = 0.9


class FakeRequest:
    def __init__(self, username):
        self.user = get_user_model().objects.get(username=username)
        self.session = SessionStore()
        self.is_fake = True
        self.META = {}
        self.perm = Permissioner(self)


class ImportedGame:
    def __init__(self, importer, game=None):
        self.importer = importer
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
                x.url.original_url for x in game.gameurl_set.select_related()
                if self.importer.IsFamiliarUrl(x.url.original_url,
                                               x.category.symbolic_id)
            ]
            self.hash_urls = [
                HashizeUrl(x.url.original_url)
                for x in game.gameurl_set.filter(
                    category__symbolic_id__in=URLCATS_TO_HASH)
            ]
            self.is_updateable = (game.added_by.username == USER
                                  and game.edit_time is None)

    def Dirtify(self):
        self.is_modified = True

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
        (self.content, error_urls) = self.importer.Import(*self.seed_urls)
        self.is_error = 'title' not in self.content

        if self.is_error:
            logger.warning(
                "Was unable to fetch: %s\n%s" % (self.seed_urls, self.content))
            return False

        for x in self.seed_urls:
            if x in self.new_urls:
                continue
            if x in error_urls:
                logger.error(
                    "Was unable to fetch old url %s: %s" % (x, error_urls[x]))
                return False

        self.seed_urls = [
            x['url'] for x in self.content['urls']
            if self.importer.IsFamiliarUrl(x['url'], x['urlcat_slug'])
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
                logger.warning("Failed to fetch %s" % self)
                return
        game = Importer2Json(self.content)
        is_new_game = not self.game
        if self.game:
            game['game_id'] = self.game.id
        logger.info("Updating %s" % self)
        id = UpdateGame(
            request, game, update_edit_time=False, kill_existing_urls=False)
        if is_new_game:
            PostNewGameToDiscord(id)

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
                logger.warning("Game [%s] has the same URL [%s] has game [%s]"
                               % (game, u, self.url_to_game[u]))
            else:
                self.url_to_game[u] = game

        self.games.append(game)

    def HasUrl(self, url):
        h = HashizeUrl(url)
        return h in self.url_to_game

    def DirtifyUrl(self, url):
        url = HashizeUrl(url)
        if url in self.url_to_game:
            logger.info("Dirtifying url %s" % url)
            self.url_to_game[url].Dirtify()

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
            logger.warning("Found %d similar games while importing [%s]:\n%s" %
                           (len(similar_games), game, '\n'.join(
                               [str(x) for x in similar_games])))

        best_game = None
        best_similariry = 0.0
        for x in similar_games:
            sim = ComputeSimilarity(game.GetTitleBow(), x.GetTitleBow())
            if sim > best_similariry:
                best_similariry = sim
                best_game = x

        if best_game is None or best_similariry <= SIMILAR_TITLES_LOWCONF:
            if len(similar_games) > 0:
                logger.error(
                    "Similar games are too dissimilar (%.2f) [%s]:\n%s" %
                    (best_similariry, game, '\n'.join(
                        [str(x) for x in similar_games])))

            self.AddGame(game)
            return

        for x in game.SeedUrls():
            logger.info("Found games with similarity %.2f merging:\n%s\n%s" %
                        (best_similariry, game, best_game))
            if x not in best_game.HashizedUrls():
                best_game.AddUrl(x)

    def Games(self):
        return self.games


def ImportGames():
    importer = Importer()
    existing_urls = set(
        [HashizeUrl(x.original_url) for x in URL.objects.all()])
    logger.info("Fetched %d existing urls" % len(existing_urls))

    gameset = GameSet()
    for x in Game.objects.prefetch_related('gameurl_set__category',
                                           'gameurl_set__url').all():
        gameset.AddGame(ImportedGame(importer, x))

    candidates = set(importer.GetUrlCandidates())
    logger.info("%d Url candidates to check" % len(candidates))

    while candidates:
        u = candidates.pop()
        if gameset.HasUrl(u):
            logger.debug('Url %s already existed.' % u)
            continue
        if HashizeUrl(u) in existing_urls:
            logger.warning(
                'Url [%s] is known, yet no games had it. Deleted?' % u)
            continue

        g = ImportedGame(importer)
        g.AddUrl(u)
        if g.Fetch():
            gameset.TryMerge(g)

    for x in importer.GetDirtyUrls():
        gameset.DirtifyUrl(x)

    fake_request = FakeRequest(USER)

    for x in gameset.Games():
        if not x.IsModified():
            continue
        if x.IsUpdateable():
            x.Store(fake_request)
        else:
            new_urls = '\n'.join(x.NewUrls())
            logger.error('New URLs for existing non-updateable game:'
                         '\n%s\nNew urls are:\n%s' % (x, new_urls))


def ForceReimport():
    importer = Importer()
    importer.GetUrlCandidates()
    gameset = GameSet()
    for x in Game.objects.prefetch_related('gameurl_set__category',
                                           'gameurl_set__url').all():
        gameset.AddGame(ImportedGame(importer, x))

    fake_request = FakeRequest(USER)

    for x in gameset.Games():
        if x.IsUpdateable():
            x.Store(fake_request)
        else:
            logger.warning("Unable to reimport non-updateable game %s" % x)
