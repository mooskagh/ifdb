from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import PurePath

from django.core.files.storage import Storage
from django.core.management.base import BaseCommand
from django.db.models import Q

from games.models import URL, GameURL

CHUNK_SIZE = 1024 * 1024
DOWNLOAD_DIRECT = "download_direct"


def storage_kind(url: URL) -> str:
    return "upload" if url.is_uploaded else "backup"


def filename_base(filename: str | None) -> str | None:
    if not filename:
        return None
    return PurePath(filename.replace("\\", "/")).name


def hash_file(storage: Storage, filename: str) -> str:
    digest = sha256()
    with storage.open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = "Print storage stats useful for file storage redesign."

    def add_arguments(self, parser):
        parser.add_argument(
            "--details",
            action="store_true",
            help="Print representative duplicate and rename examples.",
        )
        parser.add_argument(
            "--no-hash",
            action="store_true",
            help="Skip reading files and only print database-derived stats.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Maximum examples to print with --details.",
        )

    def handle(self, *args, **options):
        details = options["details"]
        detail_limit = options["limit"]
        urls = list(
            URL.objects.all().only(
                "id",
                "is_uploaded",
                "local_filename",
                "local_url",
                "original_filename",
            )
        )

        local_urls = [u for u in urls if u.local_filename]
        local_paths_by_kind = defaultdict(set)
        local_rows_by_kind = Counter()
        for url in local_urls:
            kind = storage_kind(url)
            local_rows_by_kind[kind] += 1
            local_paths_by_kind[kind].add(url.local_filename)

        self.print_url_stats(
            urls, local_urls, local_rows_by_kind, local_paths_by_kind
        )
        self.print_download_stats()
        self.print_rename_stats(local_urls, details, detail_limit)

        if options["no_hash"]:
            self.stdout.write("\nHashed files: skipped (--no-hash)")
            return

        hashes, missing = self.hash_local_files(local_urls)
        self.print_hash_stats(hashes, missing)
        self.print_duplicate_stats(hashes, details, detail_limit)

    def print_url_stats(
        self, urls, local_urls, local_rows_by_kind, local_paths_by_kind
    ):
        self.stdout.write("URLs:")
        self.stdout.write(f"  total: {len(urls)}")
        self.stdout.write(f"  with local filename: {len(local_urls)}")
        self.stdout.write(
            f"  uploads: {local_rows_by_kind['upload']} rows, "
            f"{len(local_paths_by_kind['upload'])} unique paths"
        )
        self.stdout.write(
            f"  backups: {local_rows_by_kind['backup']} rows, "
            f"{len(local_paths_by_kind['backup'])} unique paths"
        )
        self.stdout.write(
            f"  missing local filename: {len(urls) - len(local_urls)}"
        )

    def print_download_stats(self):
        links = GameURL.objects.filter(category__symbolic_id=DOWNLOAD_DIRECT)
        no_local_file = Q(url__local_filename__isnull=True) | Q(
            url__local_filename=""
        )
        no_local_url = Q(url__local_url__isnull=True) | Q(url__local_url="")
        total = links.count()
        no_stored = links.filter(no_local_file, no_local_url).count()
        no_backup = links.filter(
            no_local_file,
            no_local_url,
            url__is_uploaded=False,
        ).count()
        uploaded = links.filter(url__is_uploaded=True).count()
        broken_missing = links.filter(
            no_local_file,
            no_local_url,
            url__is_broken=True,
        ).count()

        self.stdout.write("\nDownloadable links:")
        self.stdout.write(f"  total {DOWNLOAD_DIRECT} links: {total}")
        self.stdout.write(f"  without any stored version: {no_stored}")
        self.stdout.write(
            f"  remote links without downloaded backup: {no_backup}"
        )
        self.stdout.write(f"  uploaded direct links: {uploaded}")
        self.stdout.write(f"  broken among missing: {broken_missing}")

    def print_rename_stats(self, local_urls, details, detail_limit):
        with_original = [u for u in local_urls if u.original_filename]
        renamed = [
            u
            for u in with_original
            if filename_base(u.local_filename)
            != filename_base(u.original_filename)
        ]
        missing_original = len(local_urls) - len(with_original)

        self.stdout.write("\nRenamed files:")
        self.stdout.write(f"  original filename present: {len(with_original)}")
        self.stdout.write(f"  renamed: {len(renamed)}")
        self.stdout.write(f"  missing original filename: {missing_original}")
        if details and renamed:
            self.print_rename_details(renamed, detail_limit)

    def print_rename_details(self, renamed, detail_limit):
        self.stdout.write("  examples:")
        for url in renamed[:detail_limit]:
            self.stdout.write(
                f"    URL #{url.id}: {url.original_filename!r} -> "
                f"{url.local_filename!r}"
            )

    def hash_local_files(self, local_urls):
        hashes = {}
        missing = []
        by_path = {}
        for url in local_urls:
            key = (storage_kind(url), url.local_filename)
            if key in by_path:
                hashes[url.id] = by_path[key]
                continue

            storage = url.GetFs()
            try:
                if not storage.exists(url.local_filename):
                    missing.append(url)
                    continue
                digest = hash_file(storage, url.local_filename)
            except OSError:
                missing.append(url)
                continue

            by_path[key] = digest
            hashes[url.id] = digest
        return hashes, missing

    def print_hash_stats(self, hashes, missing):
        self.stdout.write("\nHashed files:")
        self.stdout.write(f"  hashed URL rows: {len(hashes)}")
        self.stdout.write(f"  missing physical file: {len(missing)}")
        self.stdout.write(f"  unique hashes: {len(set(hashes.values()))}")

    def print_duplicate_stats(self, hashes, details, detail_limit):
        links = (
            GameURL.objects
            .filter(
                category__symbolic_id=DOWNLOAD_DIRECT,
                url_id__in=hashes.keys(),
            )
            .select_related("game", "url")
            .only(
                "id",
                "game__id",
                "game__title",
                "url_id",
                "url__local_filename",
            )
        )
        by_game_and_hash = defaultdict(list)
        by_hash = defaultdict(list)
        for link in links:
            digest = hashes[link.url_id]
            by_game_and_hash[(link.game_id, digest)].append(link)
            by_hash[digest].append(link)

        same_game = [v for v in by_game_and_hash.values() if len(v) > 1]
        cross_game = [
            v
            for v in by_hash.values()
            if len({link.game_id for link in v}) > 1
        ]

        self.stdout.write("\nDuplicates within same game:")
        games_with_duplicates = {links[0].game_id for links in same_game}
        self.stdout.write(f"  games affected: {len(games_with_duplicates)}")
        self.stdout.write(f"  hash clusters: {len(same_game)}")
        self.stdout.write(
            f"  duplicate links involved: {sum(len(v) for v in same_game)}"
        )

        self.stdout.write("\nDuplicates between games:")
        self.stdout.write(
            f"  hashes shared by multiple games: {len(cross_game)}"
        )
        games_involved = {
            link.game_id for links in cross_game for link in links
        }
        self.stdout.write(f"  games involved: {len(games_involved)}")
        self.stdout.write(
            f"  links involved: {sum(len(v) for v in cross_game)}"
        )

        if details:
            self.print_duplicate_details(same_game, cross_game, detail_limit)

    def print_duplicate_details(self, same_game, cross_game, detail_limit):
        if same_game:
            self.stdout.write("\nDuplicate examples within same game:")
            for links in same_game[:detail_limit]:
                filenames = ", ".join(
                    link.url.local_filename for link in links
                )
                self.stdout.write(
                    f"  game #{links[0].game_id} {links[0].game.title!r}: "
                    f"{filenames}"
                )

        if cross_game:
            self.stdout.write("\nDuplicate examples between games:")
            for links in cross_game[:detail_limit]:
                games = ", ".join(
                    f"#{game_id} {title!r}"
                    for game_id, title in sorted({
                        (link.game_id, link.game.title) for link in links
                    })
                )
                filenames = ", ".join(
                    sorted({link.url.local_filename for link in links})
                )
                self.stdout.write(f"  {games}: {filenames}")
