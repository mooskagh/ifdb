from core.crawler import FetchUrlToFileLike
from django.conf import settings
from django.utils import timezone
from games.models import URL, InterpretedGameUrl, GameURL
from logging import getLogger
from urllib.parse import unquote
import json
import os.path
import re
import shutil
import subprocess
import tempfile
import zipfile

logger = getLogger('crawler')

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
    logger.info('Url is id %d, URL %s' % (url.id, url.original_url))
    f = FetchUrlToFileLike(url.original_url)
    fs = settings.BACKUPS_FS
    filename = fs.save(ComeUpWithFilename(f.metadata), f, max_length=64)
    logger.info('Stored as %s' % filename)

    url.local_url = fs.url(filename)
    url.local_filename = filename
    url.original_filename = f.metadata['filename']
    url.content_type = f.metadata['content-type']
    url.file_size = fs.size(filename)
    url.save()


def MarkBroken(task, context):
    id = context['argv'][0]
    url = URL.objects.get(id=id)
    logger.warning('Found broken link at url: %s' % url.original_url)
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
        'url', 'category',
        'game').prefetch_related('game__tags').get(id=game_url_id)
    logger.info('GamUrl %d, Game %d [%s], Url %d: %s' %
                (game_url_id, game_url.game_id, game_url.game.title,
                 game_url.url_id, game_url.url.original_url))
    metadata = {
        'url': game_url.url.original_url,
        'filename': game_url.url.original_filename
    }
    filename = ComeUpWithFilename(metadata)

    if game_url.category.symbolic_id != 'play_in_interpreter':
        logger.error(
            'Requested recoding of unknown category %s' % game_url.category)
        return

    configuration = GetConfiguration(game_url)

    if configuration.get('interpreter') != 'urqw':
        logger.error('Recoding for unknown interpreter: %s' %
                     configuration.get('interpreter'))
        return

    ext = os.path.splitext(filename)[1].lower()
    if ext in ['.zip', '.qsz']:
        # Already in supported format.
        recoded_url = InterpretedGameUrl()
        recoded_url.configuration_json = json.dumps(configuration)
        recoded_url.original = game_url
        recoded_url.recoding_date = timezone.now()
        recoded_url.save()
        return

    if ext in ['.qst']:
        url = game_url.url
        with url.GetFs().open(url.local_filename, 'rb') as fi:
            fs = settings.RECODES_FS
            new_filename = fs.generate_filename(url.local_filename)
            with fs.open(new_filename, 'wb') as fo:
                fo.write(fi.read().decode('cp1251').encode('utf-8'))

        recoded_url = InterpretedGameUrl()
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
    logger.info("Unpacking %s into %s" % (url.local_filename, tmp_dir))
    try:
        subprocess.check_output(
            settings.EXTRACTOR_PATH % (url.GetFs().path(url.local_filename),
                                       tmp_dir),
            stderr=subprocess.STDOUT,
            shell=True)
    except subprocess.CalledProcessError as x:
        logger.warning(x.output, exc_info=True)
        shutil.rmtree(tmp_dir)
        raise
    fs = settings.RECODES_FS
    new_filename = fs.generate_filename("%s.zip" % url.local_filename)
    with zipfile.ZipFile(
            fs.open(new_filename, 'wb'),
            'w',
            zipfile.ZIP_DEFLATED,
            allowZip64=True) as z:

        def RaiseError(x):
            logger.exception(x)
            raise x

        for root, _, filenames in os.walk(tmp_dir, onerror=RaiseError):
            for name in filenames:
                name = os.path.join(root, name)
                name = os.path.normpath(name)
                relpath = os.path.relpath(name, tmp_dir)
                z.write(name, relpath)

    shutil.rmtree(tmp_dir)
    recoded_url = InterpretedGameUrl()
    recoded_url.configuration_json = json.dumps(configuration)
    recoded_url.original = game_url
    recoded_url.recoded_filename = new_filename
    recoded_url.recoded_url = fs.url(new_filename)
    recoded_url.recoding_date = timezone.now()
    recoded_url.save()
