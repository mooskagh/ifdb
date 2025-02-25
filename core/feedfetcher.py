from django.utils import timezone
from .models import FeedCache, BlogFeed
import feedparser
from time import mktime
from html import unescape
from datetime import datetime
from logging import getLogger
from .crawler import FetchUrlToString
from ast import literal_eval
from collections import namedtuple
from django.conf import settings
from html2text import HTML2Text
import re
import vk

logger = getLogger('worker')


def ProcessFeedEntries(feed_id, items, id_field='id'):
    now = timezone.now()
    for x in items:
        item_id = getattr(x, id_field)
        try:
            f = FeedCache.objects.get(feed_id=feed_id, item_id=item_id)
        except FeedCache.DoesNotExist:
            f = FeedCache()
            f.feed_id = feed_id
            f.item_id = item_id
            f.date_discovered = now
        if hasattr(x, 'date_published'):
            f.date_published = x.date_published
        else:
            f.date_published = datetime.fromtimestamp(
                mktime(x.published_parsed))
        f.title = x.title
        f.authors = x.author
        f.url = x.link
        f.save()


def FetchFeed(url, feed_id, id_field='id'):
    logger.info("Fetching feed at %s, feed ud %s" % (url, feed_id))
    feed = feedparser.parse(url)
    ProcessFeedEntries(feed_id, feed.entries, id_field)


VK_RE = re.compile(r'https://vk.com/(.*)')


def FetchVkFeed(api, url, feed_id):
    logger.info("Fetching vk feed %s" % url)
    m = VK_RE.match(url)
    gid = api.groups.getById(group_ids=m.group(1))[0]['id']
    posts = api.wall.get(owner_id=-gid)
    now = timezone.now()
    tt = HTML2Text()
    tt.body_width = 0
    for x in posts['items']:
        if x['marked_as_ads']:
            continue
        item_id = x['id']
        try:
            f = FeedCache.objects.get(feed_id=feed_id, item_id=item_id)
        except FeedCache.DoesNotExist:
            f = FeedCache()
            f.feed_id = feed_id
            f.item_id = item_id
            f.date_discovered = now
        f.date_published = datetime.fromtimestamp(x['date'])
        title = [tt.handle(x['text']).strip()]
        f.url = "%s?w=wall-%d_%d" % (url, gid, item_id)
        user_id = None
        if x['from_id'] > 0:
            user_id = x['from_id']
        elif 'signer_id' in x and x['signer_id']:
            user_id = x['signer_id']
        if 'copy_history' in x:
            for y in x['copy_history']:
                if not user_id:
                    if y['from_id'] > 0:
                        user_id = y['from_id']
                    elif 'signer_id' in y and y['signer_id']:
                        user_id = y['signer_id']
                title.append(tt.handle(y['text']).strip())
        if user_id:
            user = api.users.get(user_ids=user_id)
            if user:
                f.authors = "%s %s" % (user[0]['first_name'],
                                       user[0]['last_name'])

        f.title = ' '.join([x for x in title if x])[:255] or '(пусто)'
        f.save()


def FetchIficionFeed():
    logger.info("Fetching forum.ifiction.ru")
    feed = feedparser.parse(
        "http://forum.ifiction.ru/extern.php?action=active&type=rss")
    for x in feed.entries:
        (thema, url, author,
         timestamp) = [unescape(x) for x in x.description_int.split('<br />')]
        x.feed_id = url
        x.author = author
        x.id = x.link
        x.date_published = datetime.fromtimestamp(int(timestamp))
    ProcessFeedEntries('ifru', feed.entries)


URQF_RE = re.compile(r'ubb(\([^\x0d]*\));')


def FetchUrqFeed():
    logger.info("Fetching http://urq.borda.ru")
    PseudoFeed = namedtuple(
        'PseudoFeed', ['author', 'id', 'date_published', 'title', 'link'])
    x = FetchUrlToString("http://urq.borda.ru/",
                         use_cache=False,
                         encoding="cp1251",
                         headers={'Accept-Language': 'ru'})
    items = []
    for m in URQF_RE.finditer(x):
        print(m)
        (_, _, sect, id, _, title, count, _, _, author, date_published,
         _) = literal_eval(m.group(1))
        link = 'http://urq.borda.ru/?1-%d-0-%d-0-%d-0-%d' % (
            int(sect), int(id), (int(count) // 20 * 20), int(date_published))
        items.append(
            PseudoFeed(id=id,
                       title=unescape(title),
                       author=unescape(author),
                       date_published=datetime.fromtimestamp(
                           int(date_published)),
                       link=link))
    ProcessFeedEntries('urq', items)


def FetchFeeds():
    FetchFeed('https://ifhub.club/rss/full', 'ifhub')
    FetchIficionFeed()
    FetchUrqFeed()
    FetchFeed(
        'http://instead-games.ru/forum/index.php?p=/discussions/feed.rss',
        'inst')
   # session = vk.Session(settings.VK_SERVICE_KEY)
   # api = vk.API(session, lang='ru', timeout=60, v='5.131')
  #  for x in BlogFeed.objects.all():
      #  if x.feed_id.startswith('blog-'):
       #     FetchFeed(x.rss, x.feed_id)
        # elif x.feed_id.startswith('vk-'):
        #    FetchVkFeed(api, x.rss, x.feed_id)
