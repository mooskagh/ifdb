from .models import URL, RecodedGameURL, GameURL, GameTagCategory
from core.crawler import FetchUrlToFileLike
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from urllib.parse import unquote
from django.utils import timezone
import logging
import os.path
import re
import shutil
import subprocess
import tempfile
import json
import zipfile

FILENAME_RE = re.compile(
    r'^.*?\b((?:%[0-9a-f]{2}|[$:+()_\w\d\.])+\.[\w\d]{2,4})\b[^/]*$')


def HasTag(game, category, regex):
    r = re.compile(regex)
    for tag in game.tags.filter(category__symbolic_id=category).all():
        if r.match(tag.name.lower()):
            return True
    return False


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
    url.local_filename = filename
    url.original_filename = f.metadata['filename']
    url.content_type = f.metadata['content-type']
    url.file_size = fs.size(filename)
    url.save()


def MarkBroken(task, context):
    id = context['argv'][0]
    url = URL.objects.get(id=id)
    logging.warn('Found broken link at url: %s' % url.original_url)
    url.is_broken = True
    url.save()


def GetConfiguration(game_url):
    # The only one supported for now.
    res = {'interpreter': 'urqw'}
    if HasTag(game_url.game, 'platform', '.*dosurq.*'):
        res['variant'] = 'dosurq'
    elif HasTag(game_url.game, 'platform', '.*ripurq.*'):
        res['variant'] = 'ripurq'
    else:
        res['variant'] = None
    return res


def RecodeGame(game_url_id):
    game_url = GameURL.objects.select_related(
        'url', 'category', 'game').prefetch_related('game__tags').get(
            id=game_url_id)
    metadata = {
        'url': game_url.url.original_url,
        'filename': game_url.url.original_filename
    }
    filename = ComeUpWithFilename(metadata)
    if game_url.category.symbolic_id != 'play_in_interpreter':
        logging.error(
            'Requested recoding of unknown category %s' % game_url.category)
        return

    configuration = GetConfiguration(game_url)

    if configuration.get('interpreter') != 'urqw':
        logging.error('Recoding for unknown interpreter: %s' %
                      configuration.get('interpreter'))
        return

    ext = os.path.splitext(filename)[1].lower()
    if ext in ['.zip', '.qsz']:
        # Already in supported format.
        recoded_url = RecodedGameURL()
        recoded_url.configuration_json = json.dumps(configuration)
        recoded_url.original = game_url
        recoded_url.recoding_date = timezone.now()
        recoded_url.save()
        return

    if ext in ['.qst']:
        url = game_url.url
        fs = FileSystemStorage()
        with fs.open(url.local_filename, 'rb') as fi:
            new_filename = fs.generate_filename(
                "recode/%s" % url.local_filename)
            with fs.open(new_filename, 'wb') as fo:
                fo.write(fi.read().decode('cp1251').encode('utf-8'))

        recoded_url = RecodedGameURL()
        recoded_url.configuration_json = json.dumps(configuration)
        recoded_url.original = game_url
        recoded_url.recoded_filename = new_filename
        recoded_url.recoded_url = fs.url(new_filename)
        recoded_url.recoding_date = timezone.now()
        recoded_url.save()
        return

    # Trying to treat the archive as an non-zip archive
    url = game_url.url
    tmp_dir = tempfile.mkdtemp(dir=settings.TMP_DIR)
    fs = FileSystemStorage()
    logging.info("Unpacking %s into %s" % (fs.path(url.local_filename),
                                           tmp_dir))
    try:
        subprocess.check_output(
            settings.EXTRACTOR_PATH % (fs.path(url.local_filename), tmp_dir),
            stderr=subprocess.STDOUT,
            shell=True)
    except subprocess.CalledProcessError as x:
        logging.error(x.output)
        raise
    new_filename = fs.generate_filename("recode/%s.zip" % url.local_filename)
    with zipfile.ZipFile(
            fs.open(new_filename, 'wb'),
            'w',
            zipfile.ZIP_DEFLATED,
            allowZip64=True) as z:

        def RaiseError(x):
            logging.exception(x)
            raise x

        for root, _, filenames in os.walk(tmp_dir, onerror=RaiseError):
            for name in filenames:
                name = os.path.join(root, name)
                name = os.path.normpath(name)
                relpath = os.path.relpath(name, tmp_dir)
                z.write(name, relpath)

    shutil.rmtree(tmp_dir)
    recoded_url = RecodedGameURL()
    recoded_url.configuration_json = json.dumps(configuration)
    recoded_url.original = game_url
    recoded_url.recoded_filename = new_filename
    recoded_url.recoded_url = fs.url(new_filename)
    recoded_url.recoding_date = timezone.now()
    recoded_url.save()
