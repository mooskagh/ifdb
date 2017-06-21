import re
from .models import URL
from core.crawler import FetchUrlToFileLike
from django.core.files.storage import FileSystemStorage
from urllib.parse import unquote
import logging

FILENAME_RE = re.compile(
    r'^.*?\b((?:%[0-9a-f]{2}|[$:+()_\w\d\.])+\.[\w\d]{2,4})\b[^/]*$')


def ComeUpWithFilename(metadata):
    if metadata['filename']:
        return metadata['filename']
    else:
        m = FILENAME_RE.match(metadata['url'])
        if m:
            return unquote(m.group(1))
    return "unknown"


def CloneFile(id):
    url = URL.objects.get(id=id)
    f = FetchUrlToFileLike(url.original_url)
    fs = FileSystemStorage()
    filename = fs.save(ComeUpWithFilename(f.metadata), f, max_length=64)
    logging.info('Stored as %s' % filename)

    url.local_url = fs.url(filename)
    url.original_filename = f.metadata['filename']
    url.content_type = f.metadata['content-type']
    url.file_size = fs.size(filename)
    url.save()
