from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from games.importer import Import
from games.views import UpdateGame, Importer2Json
from ifdb.permissioner import Permissioner
import games.importer.tools

USER = 'crem'
URLS = [
    'http://ifwiki.ru/%D0%A0%D0%BE%D1%81%D0%BE%D0%BC%D0%B0%D1%85%D0%B0',
    'http://ifwiki.ru/%D0%A6%D0%B2%D0%B5%D1%82%D0%BE%D1%85%D0%B8%D0%BC%D0%B8%D1%8F',
    'http://ifwiki.ru/%D0%92%D0%BA%D1%83%D1%81_%D0%BF%D0%B0%D0%BB%D1%8C%D1%86%D0%B5%D0%B2',
    'http://ifwiki.ru/%D0%97%D0%B0%D0%B2%D0%B8%D1%81%D0%B8%D0%BC%D0%BE%D1%81%D1%82%D1%8C',
    'http://ifwiki.ru/%D0%9F%D0%BE%D0%B4%D0%B7%D0%B5%D0%BC%D0%B5%D0%BB%D1%8C%D0%B5_%D1%81%D0%BE%D0%BA%D1%80%D0%BE%D0%B2%D0%B8%D1%89',
    'http://ifwiki.ru/%D0%9B%D0%BE%D0%B3%D0%BE%D0%B2%D0%BE_%D0%93%D0%B8%D0%B4%D1%80%D1%8B',
    'http://ifwiki.ru/%D0%9A%D0%B0%D0%BA_%D1%8F_%D1%81%D1%82%D0%B0%D0%BB_%D0%BF%D0%B8%D1%80%D0%B0%D1%82%D0%BE%D0%BC',
    'http://ifwiki.ru/%D0%98%D1%81%D0%BF%D1%8B%D1%82%D0%B0%D0%BD%D0%B8%D0%B5',
    'http://ifwiki.ru/%D0%92%D0%BB%D1%8E%D0%B1%D0%BB%D1%91%D0%BD%D0%BD%D1%8B%D0%B9_%D0%BC%D0%B5%D0%BD%D0%B5%D1%81%D1%82%D1%80%D0%B5%D0%BB%D1%8C',
    'http://ifwiki.ru/%D0%92_%D0%B3%D0%BB%D1%83%D0%B1%D0%B8%D0%BD%D0%B5',
    'https://urq.plut.info/sorry',
    'https://urq.plut.info/node/1221',
    'https://urq.plut.info/node/48',
    'https://urq.plut.info/node/236',
    'https://urq.plut.info/node/857',
    'https://urq.plut.info/Dat-Navire',
    'https://urq.plut.info/node/292',
    'https://urq.plut.info/300000euro',
    'https://urq.plut.info/knights',
    'http://qsp.su/index.php?option=com_sobi2&sobi2Task=sobi2Details&sobi2Id=187&Itemid=55',
    'http://qsp.su/index.php?option=com_sobi2&sobi2Task=sobi2Details&sobi2Id=130&Itemid=55',
    'http://qsp.su/index.php?option=com_sobi2&sobi2Task=sobi2Details&sobi2Id=150&Itemid=55',
    'http://qsp.su/index.php?option=com_sobi2&sobi2Task=sobi2Details&sobi2Id=214&Itemid=55',
    'http://qsp.su/index.php?option=com_sobi2&sobi2Task=sobi2Details&catid=0&sobi2Id=30&Itemid=55',
    'http://qsp.su/index.php?option=com_sobi2&sobi2Task=sobi2Details&catid=0&sobi2Id=39&Itemid=55',
    'http://qsp.su/index.php?option=com_sobi2&sobi2Task=sobi2Details&catid=0&sobi2Id=43&Itemid=55',
    'http://qsp.su/index.php?option=com_sobi2&sobi2Task=sobi2Details&catid=0&sobi2Id=101&Itemid=55',
    'http://qsp.su/index.php?option=com_sobi2&sobi2Task=sobi2Details&catid=0&sobi2Id=49&Itemid=55',
]


class FakeRequest:
    def __init__(self, username):
        self.user = User.objects.get(username=username)
        self.perm = Permissioner(self.user)


class Command(BaseCommand):
    help = 'Populates games'

    def handle(self, *args, **options):
        games.importer.tools.URL_CACHE_DIR = settings.URL_CACHE_DIR
        fake_request = FakeRequest(USER)

        for url in URLS:
            game = Importer2Json(Import(url))
            UpdateGame(fake_request, game)
