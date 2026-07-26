# URL Fetches And Backups

## Goal

Rework stored URL and backed-up file handling so game and competition links can
have multiple historical fetches, health tracking, uploaded-file support, and
explicit "do not backup" behavior.

This is separate from the storage path scheme change, but the model should make
owner-scoped paths natural: game backups should know their game, competition
backups should know their competition.

## Current State

`games.URL` currently mixes several concepts:

- Remote identity: `original_url`
- One local file pointer: `local_url`, `local_filename`
- File metadata: `original_filename`, `content_type`, `file_size`
- Backup/upload flags: `ok_to_clone`, `is_uploaded`
- Link health: `is_broken`
- Creation/creator metadata

`GameURL`, `PersonalityUrl`, and `CompetitionURL` attach `URL` rows to domain
objects and add category/description metadata.

`GameSource` is separate. Curation source fetching stores source text in
`GameSourceFetch` and does not go through `games.URL`. The only bridge is that
some `GameSource` rows can be seeded from existing `GameURL` rows by copying the
URL text.

Author avatar backup support appears incomplete and should not drive the new
design.

## Decision

Do not keep globally shared `URL` rows for backupable game links.

Store URL text and fetch status directly on owner link rows:

- `GameURL -> GameURLFetch`
- `CompetitionURL -> CompetitionURLFetch`

Do not implement author URL fetches now. Existing author avatar backup behavior
should be removed or left unsupported unless intentionally rebuilt later.

Use separate concrete DB tables for owner-specific integrity, but share
fetch/storage behavior in service code and possibly abstract model mixins.

## Rationale

Game backup paths are game-scoped, so fetches need to know which game they
belong to. A globally shared `URL` table would either prevent game-scoped
storage or become an unnecessary join table if sharing is forbidden.

Separate fetch tables preserve:

- Simple foreign keys and cascade behavior
- Straightforward admin and query patterns
- Natural path logic for `games/{game_id}/...` and `competitions/{competition_id}/...`
- Clear ownership of fetch history

Shared code avoids duplicating the actual fetch/hash/store/health behavior.

## Target Shape

`GameURL` owns the URL text and current health:

```python
class GameURL(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    category = models.ForeignKey(GameURLCategory, on_delete=models.CASCADE)
    description = models.CharField(null=True, blank=True, max_length=255)
    original_url = models.CharField(max_length=2048, db_index=True)

    backup_policy = models.CharField(...)
    latest_fetch = models.ForeignKey(
        "GameURLFetch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    failing_since = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)
```

`GameURLFetch` stores one distinct fetched or uploaded artifact observation:

```python
class GameURLFetch(models.Model):
    game_url = models.ForeignKey(GameURL, on_delete=models.CASCADE)
    kind = models.CharField(...)  # FETCHED / UPLOADED
    content_hash = models.CharField(max_length=64, db_index=True)

    storage_path = models.CharField(max_length=255)
    public_url = models.CharField(max_length=255, null=True, blank=True)

    original_filename = models.CharField(max_length=255, null=True, blank=True)
    content_type = models.CharField(max_length=255, null=True, blank=True)
    file_size = models.IntegerField(null=True, blank=True)

    first_fetch = models.DateTimeField()
    last_fetch = models.DateTimeField()
```

`CompetitionURL` and `CompetitionURLFetch` should mirror this shape, with storage
scoped to the competition.

## Shared Implementation

Create shared fetch/storage code that operates on a small link interface:

```python
def backup_link(link): ...
```

The link object must provide:

- `original_url`
- `backup_policy`
- `last_attempt_at`
- `last_success_at`
- `failing_since`
- `last_error`
- `latest_fetch`
- owner-specific storage scope, such as `games/{game_id}` or `competitions/{competition_id}`
- a way to create/query the owner-specific fetch model

The generic backup flow:

1. Fetch remote content.
2. Compute content hash.
3. If the latest fetch has the same hash, update `last_fetch`.
4. If the hash changed, create a new fetch row.
5. Update `latest_fetch`.
6. Update `last_attempt_at` and `last_success_at`.
7. Clear `failing_since` and `last_error`.
8. On failure, set `last_attempt_at`, set `failing_since` if empty, and store `last_error`.

## Backup Policy

Replace overloaded `allow_cloning` / `ok_to_clone` behavior with explicit policy.

Suggested values:

- `NEVER`: do not fetch or backup.
- `AUTO`: automatically backup when created or scheduled.
- `MANUAL`: allow backup only when explicitly requested.

Category rows can keep defaults, but concrete link rows should store the resolved
policy so per-link overrides are possible.

Rendering should be a separate concern from fetching. A link can have a local
copy but still choose whether `GetLocalUrl()` prefers the local artifact or the
remote URL.

## Uploaded Files

Represent uploads as fetch rows with `kind=UPLOADED`.

Uploaded files should use the same metadata fields and local serving path logic
as remote fetches.

`GetLocalUrl()` should return the latest fetch public URL when serving local
copies is allowed, otherwise `original_url`.

## Migration Plan

1. Add new fields and fetch tables.
2. Copy existing `URL.original_url` onto `GameURL.original_url` and `CompetitionURL.original_url`.
3. Convert existing `URL.local_*`, `content_type`, `file_size`, and `original_filename` into one latest fetch row per backed-up/uploaded `GameURL` or `CompetitionURL`.
4. Update render/import/editor code to read from `GameURL.original_url` and `CompetitionURL.original_url`.
5. Replace `CreateUrl` with owner-specific link creation helpers.
6. Remove or deprecate `games.URL` after all callers are migrated.
7. Remove incomplete author avatar backup behavior unless intentionally rebuilt.

## Open Questions

- Should duplicate textual URLs be allowed within the same game and category?
- Should competition backup paths mirror game paths exactly or use a separate `competitions/{competition_id}` root?
- Should `latest_fetch` be denormalized on the link row, or should code query latest by `last_fetch`?
- Should rendering preference be a per-category default, a per-link flag, or entirely derived from backup policy?
