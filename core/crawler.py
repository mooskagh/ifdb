from django.conf import settings
from django.utils import timezone
from logging import getLogger
from urllib.parse import quote
import datetime
import hashlib
import json
import os.path
import shutil
import urllib.request

logger = getLogger('crawler')

def FetchUrlToString(url, use_cache=True):
    return FetchUrlToFileLike(url, use_cache).read().decode('utf-8')


def _ResponseInfoToMetadata(url, response):
    res = {
        'url': url,
        'time': str(timezone.now()),
        'filename': response.get_filename(),
        'content-type': response.get_content_type(),
    }
    if res['filename']:
        res['filename'] = res['filename'].lstrip('"')
    return res


def FetchUrlToFileLike(url, use_cache=True):
    logger.info('Fetching: %s' % url)
    url = quote(url.encode('utf-8'), safe='/+=&?%:@;!#$*()_-')
    if not settings.CRAWLER_CACHE_DIR or not use_cache:
        response = urllib.request.urlopen(url)
        response.metadata = _ResponseInfoToMetadata(url, response.info())
        return response

    urlhash = hashlib.md5(url.encode('utf-8')).hexdigest()
    filename = os.path.join(settings.CRAWLER_CACHE_DIR, urlhash)
    metadata_filename = os.path.join(settings.CRAWLER_CACHE_DIR,
                                     "%s.meta" % urlhash)
    listing_filename = os.path.join(settings.CRAWLER_CACHE_DIR,
                                    "%s.list" % timezone.now().date())

    if os.path.isfile(metadata_filename):
        with open(metadata_filename, 'r') as f:
            metadata = json.loads(f.read())
    else:
        response = urllib.request.urlopen(url)
        metadata = _ResponseInfoToMetadata(url, response.info())
        with open(filename, 'wb') as f:
            shutil.copyfileobj(response, f)
        with open(metadata_filename, 'w') as f:
            f.write(json.dumps(metadata, indent=2, separators=(',', ': ')))
        with open(listing_filename, 'a') as f:
            f.write('%s %s\n' % (urlhash, url))

    f = open(filename, 'rb')
    f.metadata = metadata
    return f