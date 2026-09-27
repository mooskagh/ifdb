from collections import defaultdict
from dataclasses import dataclass

from django.db.models import OuterRef, Subquery

from games.models import URL, GameURL, StoredFile, URLFetch


@dataclass
class DuplicateGroup:
    stored_file: StoredFile
    urls: list[URL]
    game_urls: list[GameURL]

    @property
    def duplicate_count(self) -> int:
        return len(self.urls)

    @property
    def potential_savings(self) -> int:
        if self.duplicate_count <= 1:
            return 0
        return int(self.stored_file.file_size) * (self.duplicate_count - 1)


def get_duplicate_url_groups(
    limit: int | None = None,
) -> list[DuplicateGroup]:
    """Find groups of current URLs that share identical content.

    A URL's current content is determined by its latest successful URLFetch.
    Only groups with 2 or more active URLs pointing to the same StoredFile
    are returned.
    """
    latest_fetch_subquery = (
        URLFetch.objects
        .filter(url_id=OuterRef("id"))
        .order_by("-last_fetch", "-id")
        .values("stored_file_id")[:1]
    )

    urls = list(
        URL.objects
        .annotate(current_stored_file_id=Subquery(latest_fetch_subquery))
        .filter(current_stored_file_id__isnull=False)
        .order_by("id")
    )

    grouped_urls: dict[int, list[URL]] = defaultdict(list)
    for url in urls:
        grouped_urls[url.current_stored_file_id].append(url)

    dup_groups = {
        sf_id: u_list
        for sf_id, u_list in grouped_urls.items()
        if len(u_list) > 1
    }

    if not dup_groups:
        return []

    stored_files = {
        sf.id: sf for sf in StoredFile.objects.filter(id__in=dup_groups.keys())
    }

    all_url_ids = [u.id for u_list in dup_groups.values() for u in u_list]
    game_urls_by_url_id: dict[int, list[GameURL]] = defaultdict(list)
    for gu in (
        GameURL.objects
        .filter(url_id__in=all_url_ids)
        .select_related("game", "category")
        .order_by("game_id", "id")
    ):
        game_urls_by_url_id[gu.url_id].append(gu)

    result = []
    for sf_id, u_list in dup_groups.items():
        stored_file = stored_files.get(sf_id)
        if stored_file is None:
            continue
        gus = [gu for u in u_list for gu in game_urls_by_url_id[u.id]]
        result.append(
            DuplicateGroup(
                stored_file=stored_file,
                urls=u_list,
                game_urls=gus,
            )
        )

    # Sort groups by duplicate count descending, then file size descending
    result.sort(
        key=lambda g: (
            -g.duplicate_count,
            -g.stored_file.file_size,
            g.stored_file.id,
        )
    )

    if limit is not None:
        result = result[:limit]

    return result
