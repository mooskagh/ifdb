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
import re

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
    x = FetchUrlToString(
        "http://urq.borda.ru/", use_cache=False, encoding="cp1251")
    items = []
    for m in URQF_RE.finditer(x):
        (_, _, sect, id, _, title, count, _, _, author, date_published,
         _) = literal_eval(m.group(1))
        link = 'http://urq.borda.ru/?1-%d-0-%d-0-%d-0-%d' % (
            int(sect), int(id), (int(count) // 20 * 20), int(date_published))
        items.append(
            PseudoFeed(
                id=id,
                title=unescape(title),
                author=unescape(author),
                date_published=datetime.fromtimestamp(int(date_published)),
                link=link))
    ProcessFeedEntries('urq', items)


def FetchFeeds():
    FetchFeed('https://ifhub.club/rss/full', 'ifhub')
    FetchIficionFeed()
    FetchUrqFeed()
    FetchFeed(
        'http://instead.syscall.ru/talk/feed.php', 'inst', id_field='title')
    for x in BlogFeed.objects.all():
        FetchFeed(x.rss, x.feed_id)
