# IFDB URL Fetching, Deduplicated Storage, and Migration Plan

Status: design proposal for staged implementation

## 1. Scope and goals

This redesign is intentionally limited to three related problems:

1. Periodically refetch external, backupable URLs so IFDB can tell whether a link is healthy and whether its bytes have changed.
2. Know when different links currently or historically point to identical bytes.
3. Store newly created game files in a game-scoped public directory such as `/f/g/123/game.zip`, while preserving every existing public file URL.

The same mechanism should work for downloadable games, posters, screenshots, and other backupable game URLs.

Uploads are part of the same storage model. A new upload associated with game 123 should ultimately live under `/f/g/123/...` unless its bytes already exist as a shared stored file somewhere else.

This proposal deliberately does **not** model “latest game version”, “old game version”, or content supersession. Fetch history records changes in bytes, but interpreting those changes as semantic versions is out of scope.

## 2. Non-negotiable invariants

These rules should guide every migration step.

### Existing public file URLs are permanent

Existing files under paths such as `/f/uploads/...` and `/f/backups/...` must continue to be served at those exact paths. There should be no redirect-based migration and no bulk filesystem move.

Even when the new database model decides that an old file is a duplicate of another stored file, the old physical file should remain in place because people may already have direct links to it.

### New files use the new layout

For newly stored unique content belonging to a game, use:

`/f/g/<game_id>/<filename>`

For example:

`/f/g/123/game.zip`

The game ID is a **storage namespace**, not ownership. If the same bytes are subsequently used by game 456, they may continue to live at `/f/g/123/game.zip` and game 456 simply refers to the same stored file.

### Stored files are immutable

Once a `StoredFile` exists at a path, do not replace its bytes in place. A changed remote URL creates or reuses a different `StoredFile`.

This is important both for history and for the stability of direct public file URLs.

### No eager filesystem migration

Backfilling the new database representation should inspect and hash existing files but should not rename, move, or delete them.

### Fetching and backup are one operation

There should no longer be a separate “initial backup” mechanism. A new external URL is simply a URL that has never been attempted, so the normal refetch worker gives it highest priority.

### Do not garbage-collect public files as part of this project

Even an apparently unreferenced file may have an external direct link. Automatic deletion can be considered separately later, with a much stronger definition of what is safe to remove.

## 3. Target data model

The intended end state has four relevant concepts.

### `URL`

`URL` remains global and represents an endpoint or local uploaded URL.

Keep the existing relationship where multiple `GameURL` rows can point to the same `URL`.

In addition to existing identity/creation fields, `URL` should eventually own fetch scheduling/health state:

- `original_url`
- `creation_date`
- `is_uploaded` (keep this for now; it has a real semantic purpose)
- `last_attempt`
- `failing_since`
- `last_error`

`ok_to_clone` can initially remain the eligibility flag so this project does not also have to redesign backup policy.

A remote URL is eligible for periodic fetching when current rules say it is backupable, it is not an upload, and it is referenced by at least one game.

An uploaded URL is never periodically fetched. URLs not referenced by any game are skipped.

### `StoredFile`

`StoredFile` represents one immutable set of bytes and one canonical physical pathname used by the new model.

Suggested fields:

- `content_hash`: SHA-256, indexed and unique
- `storage_path`: path relative to `MEDIA_ROOT`, unique
- `file_size`
- `created_at`

Examples of `storage_path`:

- existing upload: `uploads/game.zip`
- existing backup: `backups/game_a8x7.zip`
- new-style file: `g/123/game.zip`

The important simplification is to add a storage object rooted at `MEDIA_ROOT` with base URL `/f/`. Then all three examples above can be addressed by one storage backend.

A public URL is derived from `storage_path`; it does not need to be stored separately.

Do not put source-provided filename or HTTP content type on `StoredFile`. Those describe an observation/source, not the bytes themselves.

### `URLFetch`

`URLFetch` records one consecutive observation of particular bytes at a URL.

Suggested fields:

- `url` -> `URL`
- `stored_file` -> `StoredFile`
- `original_filename`, nullable
- `content_type`, nullable
- `first_fetch`
- `last_fetch`

Do **not** make `(url, stored_file)` unique.

If a URL serves A, then B, then A again, history should be:

- fetch 1 -> StoredFile A
- fetch 2 -> StoredFile B
- fetch 3 -> StoredFile A

Repeated consecutive observations of the same bytes do not create new rows; they extend `last_fetch` on the current row.

For an uploaded file, create one `URLFetch` pointing at its `StoredFile`, with `first_fetch == last_fetch == upload time`. The word “fetch” is slightly loose here, but using the same representation makes deduplication and serving much simpler.

### `GameURL`

Keep its current role:

- game
- URL
- category
- description

It should not own storage paths or fetch history.

This is what allows one URL to be shared by multiple games without copying the physical file.

## 4. Duplicate-content semantics

No separate `Content` or duplicate-group table is needed initially.

Two fetches contain the same bytes when they point to the same `StoredFile`.

Two URLs currently contain the same bytes when their latest successful `URLFetch` rows point to the same `StoredFile`.

This works:

- across different textual URLs;
- across different games;
- between a remote download and an uploaded file;
- for posters/screenshots as well as archives;
- historically as well as currently.

The SHA-256 is used to find/reuse `StoredFile`, while normal application queries can compare `stored_file_id` directly.

## 5. Filesystem layout and naming

### Existing files

Existing files stay exactly where they are.

A backfilled file under `/f/uploads/foo.zip` becomes a `StoredFile(storage_path="uploads/foo.zip")`.

A backfilled file under `/f/backups/foo_x7a2.zip` becomes `StoredFile(storage_path="backups/foo_x7a2.zip")`.

Do not create a new game-scoped copy merely to make the layout pretty.

If several existing physical files contain identical bytes, choose one of them as the canonical `StoredFile.storage_path`. The other physical files stay on disk indefinitely to preserve their public URLs, even though the new DB model may no longer reference those extra legacy copies.

### New unique game files

When new bytes must actually be persisted and the URL is referenced by one or more games, pick a deterministic game ID as the storage namespace. The simplest rule is the lowest referencing `GameURL.game_id`.

Try the source/upload filename first:

`g/123/game.zip`

If that pathname already contains the same bytes, reuse it.

If it contains different bytes, use a deterministic collision name such as:

`g/123/game-<short-hash>.zip`

This is preferable to a random suffix because it is stable and understandable. It also means identical filenames in unrelated games no longer collide at all.

If the filename is unavailable or unsafe, fall back to a safe generated filename while preserving a useful extension if possible.

### New files without a game

Automated URL fetching skips URLs which are not referenced by any game.

If a URL is ever manually fetched without a `GameURL` reference, fallback storage continues using an existing non-game/legacy namespace such as `backups/...`. Game-scoped storage can be added to competitions or personalities separately if desired.

If a URL is referenced both by a game and by another object, prefer the game-scoped path for newly stored unique bytes.

## 6. Fetch behavior

A single fetch operation should do the following.

1. Set the attempt timestamp.
2. Download to a temporary file; do not write directly over any existing public file.
3. Compute SHA-256 and size while streaming if convenient.
4. Look up `StoredFile` by hash.
5. Look up the latest `URLFetch` for this URL.
6. If latest fetch already points at that `StoredFile`, update only its `last_fetch`.
7. If the hash exists globally but differs from the URL's latest observation, create a new `URLFetch` pointing at the existing `StoredFile` and discard the temporary file.
8. If the hash is globally new, choose a permanent storage path, atomically persist the temporary file there, create `StoredFile`, then create `URLFetch`.
9. On success, clear `failing_since` and `last_error`.
10. On failure, create no `URLFetch`; update `last_attempt`, set `failing_since` if it was empty, and store `last_error`.

The operation should be idempotent enough that retrying after a process crash does not corrupt or overwrite public files.

A useful implementation pattern is to finish hashing before deciding the final path. That lets deduplication happen before any new permanent file is created.

## 7. Refetch scheduling

Do not add a queue table initially. `URL` already contains enough information to behave as the queue.

Select eligible remote URLs referenced by at least one game in this order:

1. `last_attempt IS NULL`, ordered by `creation_date DESC`.
2. Then attempted URLs ordered by `last_attempt ASC`.

This means newly-created URLs appear at the head and get their first backup/check quickly, while previously fetched URLs naturally rotate to the back after every attempt.

Initially use a single worker or otherwise prevent two workers from fetching the same URL concurrently. Add explicit claiming/leases only if actual worker concurrency makes it necessary.

The worker should expose operational controls such as:

- limit
- one URL ID
- perhaps one game ID for debugging
- summary counts: created/changed, unchanged, failed

## 8. Upload behavior

Uploads should use the same `StoredFile` representation and global deduplication as remote fetches.

### Upload associated with an existing game

When the game ID is known:

1. Receive upload into temporary storage.
2. Hash it.
3. If the hash already has a `StoredFile`, discard the temporary copy and reuse the existing file, even if it lives under another game's directory or an old legacy path.
4. Otherwise persist it as `/f/g/<game_id>/<filename>` using the same collision rules as fetched files.
5. Create/reuse the local uploaded `URL` whose `original_url` is the chosen `StoredFile` public URL.
6. Mark it as uploaded/non-refetchable.
7. Create its one `URLFetch` pointing at the `StoredFile`.
8. Attach it through `GameURL` as today.

Thus an upload for game 456 may legitimately point at `/f/g/123/game.zip` when those bytes were already stored there. This is intentional; physical storage is shared.

### Upload while creating a new game

The current editor can upload a file before a game ID exists. Therefore it cannot immediately know the desired `/f/g/<game_id>/...` path.

Use a staged upload flow:

1. The pre-save upload is provisional, not a persisted `GameURL`.
2. During game creation, after the game has an ID, finalize every provisional upload:
   - hash it if not already hashed;
   - reuse an existing `StoredFile` if duplicate;
   - otherwise place it under `/f/g/<new_game_id>/...`;
   - replace the provisional URL in the game data with the final public URL;
   - only then persist the `URL` / `URLFetch` / `GameURL` and accepted game revision.
3. The persisted game must never contain the provisional staging URL.

For the first compatibility implementation, the current `/f/uploads/...` location can remain the provisional staging area for the legacy editor, because that avoids changing the frontend protocol and server save format at the same time. After finalization, new published links should use the final `/f/g/<id>/...` path.

Once the new flow is stable, staging can be moved outside public `MEDIA_ROOT` and represented by an opaque upload token. That is a useful hardening improvement, but it is not required for the initial URL-fetch/storage migration.

Any **already-persisted** `/f/uploads/...` URL is legacy data and must never be moved. Only new provisional uploads that have not yet been committed to a game are candidates for promotion.

### Standalone API uploads without a game ID

The API currently supports an upload without a game. Such a file cannot satisfy a game-scoped pathname yet.

Keep standalone uploads in a staging/legacy namespace until they are attached to a game, or explicitly define them as non-game files. Do not invent a fake game ID.

The requirement `/f/g/<game_id>/...` applies once the upload is committed as a game file.

## 9. Detailed staged implementation plan

Each stage below is intended to be independently deployable.

### Stage 1 — Add unified media storage access

Add a new storage setting, conceptually `FILES_FS`, rooted at `MEDIA_ROOT` with public base URL `/f/`.

Do not remove or change `UPLOADS_FS` or `BACKUPS_FS` yet.

The new storage can address all of these paths:

- `uploads/foo.zip`
- `backups/foo.zip`
- `g/123/foo.zip`

No application behavior changes in this stage.

**Safe deploy condition:** existing tests and serving behavior are unchanged.

### Stage 2 — Add `StoredFile`, `URLFetch`, and URL health fields

Create the two additive tables described above.

Add nullable fields to `URL`:

- `last_attempt`
- `failing_since`
- `last_error`

Do not remove or reinterpret any existing fields.

Do not start fetching anything differently.

Add admin views for the new rows if useful for debugging.

**Safe deploy condition:** production can run indefinitely with these tables empty.

### Stage 3 — Add an idempotent backfill command

Write a management command; do not hash files inside a Django migration.

For every current `URL` with a usable local file:

1. Locate it using current `is_uploaded`, `local_filename`, and storage settings.
2. Hash the existing bytes.
3. Convert its path into one relative to `MEDIA_ROOT` (`uploads/...` or `backups/...`).
4. `get_or_create` the canonical `StoredFile` by hash.
5. Create an initial `URLFetch` if this URL does not already have the corresponding backfilled observation.
6. Preserve original filename/content-type metadata where available.

Do not change `last_attempt`: backfilling a local file is not proof that the remote URL is currently healthy.

Use “time observed during backfill” for the fetch timestamps unless there is a trustworthy historical download timestamp. Do not fabricate history.

If two legacy files have the same hash, only one becomes the canonical `StoredFile.storage_path`. Both physical legacy files remain untouched on disk.

Run this command in bounded batches and make reruns harmless.

**Safe deploy condition:** no existing URL/file field is changed and no file is moved or deleted.

### Stage 4 — Introduce new file-access helpers and migrate readers

Before producing any `/f/g/<game_id>/...` files, migrate backend code that currently assumes `local_filename` is relative to `UPLOADS_FS` or `BACKUPS_FS`.

Introduce helpers along the lines of:

- latest successful fetch for URL
- current `StoredFile` for URL
- open current local file
- current local public URL
- does a local stored copy exist

The new helpers should prefer `URLFetch -> StoredFile` and fall back to the legacy URL fields when the new rows are missing.

Migrate all code that actually opens files through `URL.GetFs()` / `local_filename`, especially:

- playable preparation/tasks;
- curation code that reads stored downloads;
- storage diagnostics/statistics;
- any remaining direct filesystem consumers found by search.

Keep rendering behavior compatible for now.

Do not yet create new-style paths.

**Safe deploy condition:** old data still works solely through fallback, and backfilled data works through `StoredFile`.

### Stage 5 — Implement the new fetch primitive, manual-only

Implement the fetch algorithm from section 6.

For globally new content associated with a game, save under `/f/g/<game_id>/...`.

For duplicate content, reuse the existing `StoredFile` regardless of its pathname.

For now expose this only through a management/debug command for a single URL or small batch. Do not schedule periodic fetching and do not change URL creation yet.

While compatibility fields still exist:

- continue updating `URL.local_url` to the canonical current stored-file public URL so old rendering paths keep working;
- continue updating `original_filename`, `content_type`, and `file_size` where useful;
- continue maintaining `is_broken` for old UI/search consumers;
- do **not** rely on `local_filename` for new-style files, because its old meaning is storage-root-specific.

All functional file readers should already have been migrated in Stage 4.

**Safe deploy condition:** manually refetching a URL cannot make any old public file disappear and existing site reads continue to work.

### Stage 6 — Put the old `clone_file` entry point on top of the new fetcher

Keep the existing task/function signature temporarily, but replace its implementation with the new fetch primitive.

This is a compatibility bridge: existing code can still request an immediate backup as before, while all actual downloads now create `URLFetch` / `StoredFile` history and deduplicate globally.

Do not delete the old task yet.

Run this in production long enough to validate new-path serving, duplicate reuse, failure handling, and historical fetch creation.

**Safe deploy condition:** callers do not know the implementation changed.

### Stage 7 — Add the periodic refetch worker

Add a command/task that selects eligible URLs using the ordering in section 7.

Start by running it manually or from an operator-triggered job with a small limit.

Verify:

- new never-attempted URLs are selected first;
- successful unchanged content only extends `last_fetch`;
- changed content creates another `URLFetch`;
- duplicate bytes from another URL reuse the same `StoredFile`;
- failures set health fields but preserve the last successful file;
- a recovered URL clears failure state;
- posters/screenshots behave the same way as downloadable archives.

**Safe deploy condition:** periodic fetching may be disabled without changing normal request handling.

### Stage 8 — Schedule periodic refetching

Run the worker regularly.

At this stage, the old immediate-backup trigger may still exist, so newly-created URLs can be fetched either immediately through the compatibility call or shortly afterward by the queue. That overlap is acceptable temporarily because the fetch operation is idempotent and hash-based.

Watch fetch volume, storage growth, failure rates, and duplicate rates.

**Safe deploy condition:** disabling the scheduler leaves the existing compatibility path working.

### Stage 9 — Change URL creation to queue-by-state instead of enqueueing `clone_file`

Stop calling `clone_file` when a new remote URL is created.

Creating a URL with `last_attempt = NULL` is now the enqueue operation.

Because never-attempted URLs are ordered by newest creation date first, new URLs naturally go to the head of the queue.

Once this has been deployed and observed successfully, delete the old `clone_file` task and its scheduling code.

There is now only one fetch mechanism.

**Safe deploy condition:** the periodic worker is already proven and running before immediate scheduling is removed.

### Stage 10 — Migrate existing-game uploads to the new storage model

Change upload paths where a game ID is already known.

The upload should hash first, globally deduplicate, then either:

- reuse an existing `StoredFile`; or
- create `/f/g/<game_id>/<filename>`.

Create `URL` / `URLFetch` data immediately and keep `is_uploaded=True` so the periodic worker excludes it.

The current API path that already receives an optional game ID is a natural first place to do this.

Keep old upload endpoints/contracts working during this stage.

**Safe deploy condition:** old `/f/uploads/...` files still exist and old uploads still resolve.

### Stage 11 — Finalize new-game uploads into the game directory

Update the game-creation save flow so provisional uploads are finalized only after the new game ID exists.

For compatibility, this can initially keep using the current `/f/uploads/...` upload response while editing, but on save it must:

1. recognize that the URL is a new provisional same-site upload;
2. resolve and hash that staging file;
3. reuse or create the final `StoredFile`;
4. if unique, place it under `/f/g/<new_game_id>/...`;
5. rewrite the game's URL entry to the final canonical public URL before persisting the game/revision;
6. create the uploaded `URLFetch` representation.

Never apply this promotion rule to an already-persisted legacy upload URL.

Once stable, optionally replace public `/f/uploads/` staging with private temporary storage and an upload token. That can be a separate cleanup change.

**Safe deploy condition:** a failed game save still leaves the old editor behavior recoverable; no previously published upload is moved.

### Stage 12 — Switch normal reads to the new model

Change central helpers and query/building code so the current file comes from the latest successful `URLFetch -> StoredFile`.

Use the new model for:

- download/local links;
- poster/screenshot local URLs;
- current file metadata where appropriate;
- duplicate grouping;
- file opening for playable creation;
- broken-link status, after compatibility UI is updated.

Keep fallback to old fields for at least one deployment.

Add diagnostics that report URLs still requiring fallback. Drive that count toward zero for data that should have been backfilled.

**Safe deploy condition:** removing the new-read feature flag/fallback preference can restore old behavior without touching files.

### Stage 13 — Stop dual-writing legacy fields

After all functional reads have moved to the new model, stop maintaining legacy local-file metadata for newly fetched files.

Keep the database columns in place for another deployment.

Keep old physical files in place permanently.

At this stage `is_broken` can be replaced in application reads by health state derived from `failing_since` / `last_error` / latest successful fetch, but the field itself can remain temporarily.

**Safe deploy condition:** tests prove there are no required writes or reads of the retired fields.

### Stage 14 — Remove obsolete database fields and old resolution code

Only now remove legacy fields that are truly unused, likely including:

- `local_url`
- `local_filename`
- `original_filename` from `URL` (metadata now belongs to `URLFetch`)
- `content_type` from `URL`
- `file_size` from `URL`
- `is_broken`

Remove `GetFs()` and old `/f/uploads/` / `/f/backups/` URL-parsing recovery code once nothing depends on it.

Do **not** remove legacy files from disk.

Keep `is_uploaded` unless/until there is a separate explicit replacement for “this URL represents a site upload and should not be refetched.”

Treat `ok_to_clone` / category backup policy cleanup as separate work unless the implementation naturally makes it trivial.

## 10. Deployment checkpoints

The migration has useful stopping points where production can remain for days or weeks:

1. Schema only.
2. Schema + backfilled observations.
3. New read helpers with fallback.
4. New fetcher behind the old `clone_file` interface.
5. Periodic refetching enabled while old enqueue path still exists.
6. Refetch queue is the only fetch mechanism.
7. New upload paths enabled.
8. New model is authoritative for reads, legacy columns still present.
9. Legacy DB fields removed.

There should be no stage that requires “deploy these two commits at exactly the same time”.

## 11. Tests that should exist before cleanup

At minimum, cover these cases.

### Fetch history

- First successful fetch creates `StoredFile` + `URLFetch`.
- Re-fetching identical bytes updates `last_fetch` only.
- A -> B creates a second fetch row.
- A -> B -> A creates a third fetch row pointing back to StoredFile A.
- Fetch failure creates no history row.
- Failure followed by success clears health state.

### Deduplication

- Two URLs with same bytes share one `StoredFile`.
- Same bytes attached to two games are physically stored once.
- Uploaded bytes and remotely fetched identical bytes share one `StoredFile`.
- Duplicate detection of current URL content uses latest fetches only.

### Paths

- New unique content for game 123 becomes `/f/g/123/...`.
- Same filename in game 456 does not collide with game 123.
- Different bytes with the same filename in the same game receive a deterministic collision name.
- A duplicate discovered from game 456 can reuse a file physically under game 123.

### Legacy compatibility

- Existing `/f/uploads/...` continues to serve.
- Existing `/f/backups/...` continues to serve.
- Backfill does not move either.
- Duplicate legacy physical files are not deleted.
- Backfilled URLs can be opened through new `StoredFile` helpers.

### Uploads

- Existing-game unique upload goes under `/f/g/<id>/...`.
- Existing-game duplicate upload reuses existing StoredFile.
- New-game provisional upload is rewritten to final path before persistence.
- An existing published legacy `/f/uploads/...` URL is never promoted/moved by the new-game finalization logic.
- Uploaded URLs never enter periodic refetch eligibility.

### Queue ordering

- Never-attempted URLs beat attempted URLs.
- Among never-attempted URLs, newest comes first.
- Among attempted URLs, oldest attempt comes first.
- After an attempt, a URL moves to the back of the attempted population.

## 12. Operational/diagnostic commands worth adding

These can be simple management commands rather than product features.

### Backfill stored files

Hash and register legacy files in bounded, idempotent batches.

### Check storage consistency

Verify every `StoredFile.storage_path` exists and hashes to `content_hash`.

Never repair by silently replacing bytes at a public path.

### Fetch URLs

Support a bounded batch and a specific URL ID for debugging.

### Duplicate report

Show groups of current URLs sharing `stored_file_id`, ideally with associated games/categories.

This is useful for validating the future UI grouping behavior before implementing it.

### Legacy-fallback report

Show URLs that still need old `local_*` fields because they lack usable fetch/storage rows.

This report should be empty (except intentionally unsupported cases) before removing the old fields.

## 13. Things intentionally deferred

Do not expand this migration to solve these unless a concrete implementation obstacle requires it:

- semantic game versions;
- “latest vs old version” UI;
- supersession relationships;
- a separate content/version domain model beyond `StoredFile`;
- reorganizing existing public files;
- redirects from old file paths;
- hard-link aliases;
- filesystem garbage collection;
- competition/personality-specific pretty directory layouts;
- redesigning all backup-policy/category semantics.

## 14. Main architectural result

After the migration:

- `URL` says **where we fetch and whether fetching currently works**.
- `URLFetch` says **what bytes that URL returned during a period of time**.
- `StoredFile` says **where one immutable copy of those bytes is physically served**.
- `GameURL` says **why a game references that URL**.

New external URLs need no special backup job: `last_attempt = NULL` puts them at the head of the same periodic refetch population.

New unique game files naturally land under `/f/g/<game_id>/...`.

Identical files are stored once regardless of how many URLs or games reference them.

Old direct links remain valid because legacy files are never moved or deleted as part of this project.
