# Source Pipeline / Next-Gen Importer Specification

## Overview

Redesign of how game data is imported and updated. The old monolithic
`games/importer/` (one `Import(url)` call does discover + fetch + parse + merge +
enrich synchronously, returns a loose dict, persists nothing between steps) is
replaced by a **staged pipeline with a DB checkpoint between every stage**,
driven by the `curation` models.

Per-site logic shrinks to a thin **driver**; orchestration (crawl, schedule,
merge, apply) moves out of the driver into stage runners.

## The pipeline

```
Phase 1  discover      → GameSource (orphan, history=null)   [driver: discover()]
Phase 2  fetch         → GameSourceFetch.raw_content          [orchestrator/crawler — NOT the driver]
Phase 2.5 canonicalize → GameSourceFetch.canonical_text(+hash)[driver: canonicalize() — its whole reason to exist]
Phase 3  reconcile     → GameSource.history set               [orchestrator]
Phase 4  filter chain  → GameEdit                             [orchestrator]
```

- **Fetch is the orchestrator's job, not the driver's** (network, scheduling,
  retries — that's what `GameSource.failing_since/last_attempt/last_error` are
  for). The driver's defining job is **raw document → canonical form**.
- **`canonicalize()` is a pure function over stored `raw_content`** — improving a
  parser means re-running Phase 2.5 over the DB with zero re-crawling. Drivers
  stop importing `core.crawler`.
- **Discovery is listing-sourced** in Phase B: providers crawl their own listing
  pages via `discover()`. URL fan-out from parsed `GameInfo.urls` was dropped
  from this slice; there is no stored parsed content to fan out from until later
  phases.

## Driver interface (target)

One driver per `GameSource.SourceType`. Routed by URL (registry, like the old
`REGISTERED_IMPORTERS`).

```python
class SourceDriver(Protocol):
    source_type: GameSource.SourceType

    def owns(self, url: str) -> bool: ...  # routing (old Match)
    def discover(
        self,
    ) -> Iterable[DiscoveredSource]: ...  # Phase 1 (old GetUrlCandidates)
    def canonicalize(
        self, raw: str, url: str
    ) -> GameInfo: ...  # Phase 2.5 (pure)
    # optional, only apero + ifwiki implement; default returns None
    def canonicalize_author(
        self, raw: str, url: str
    ) -> CanonicalAuthor | None: ...
```

### As shipped in A/B (`curation/providers.py`)

`GameSourceProvider` is the realized interface. It's an **ABC** (not a
`Protocol`): `owns`/`canonicalize` are `@abstractmethod`, `discover` is concrete
and returns no candidates by default, and `canonicalize_author` is concrete and
returns `None` by default. ABC over Protocol because providers are a closed
in-tree registry that already share a base — structural typing buys nothing,
and `@abstractmethod` enforces the contract at instantiation. Concrete providers
subclass it and live in `REGISTERED_PROVIDERS`. `CanonicalAuthor(name, bio,
urls)` is the author analogue of `GameInfo`; `DiscoveredSource(url)` is the
Phase 1 candidate wrapper.

Providers are thin bridges: each per-site `ImportFromX(url)` in
`games/importer/` was split into `FetchX(url)→raw` + `ParseX(raw, url)→dict`
(the old dict, behavior preserved; the `ImportFromX` wrappers stay live), and
`canonicalize` runs `GameInfo.from_importer_dict(ParseX(raw, url))`. Migrated:
apero, ifwiki, insteadgames, questbook, ifiction, qspsu, plut (apero + ifwiki
also do `canonicalize_author`). A `PLUT` value was added to
`GameSource.SourceType` for the plut driver (qspsu reuses the existing `QSP`).

Decisions locked in A:

- **ifiction & ifwiki** `canonicalize`/`canonicalize_author` _may fetch_ during
  canonicalization to chase redirects (ifiction `ResolveRedirect`, ifwiki
  `#REDIRECT` chase). This is the intended exception to "pure over stored raw",
  not tech debt — no nicer design exists.
- **rilarhiv** is _not_ migrated: it has no per-game page (data lives in the
  listing rows from `GetUrlCandidates`), so it stays on the old path until
  discover-coupled sources get bespoke handling in/after B.
- `from_importer_dict` is pure/DB-free except the rare `role`-title→slug
  fallback (no importer emits a bare `role` today).

## What already exists: `curation/gameinfo.py`

`GameInfo` **is** the canonical-game representation (do not build a separate
"CanonicalGame"). The file already provides, request-free:

- **Representation** — `GameInfo` dataclass (name/date/description/personalities/
  tags/urls/attributions).
- **Serde** — `to_canonical()` emits the canonical doc (YAML front matter +
  markdown body); `parse()` reads canonical-or-loose docs back. *This is the
  format stored in `GameSourceFetch.canonical_text` and `GameEdit.canonical_text`.*
- **Merge filter** — `merge(base, incoming)` is `MergeImport` reborn (union,
  dedup by identity, concat descriptions, first-wins).
- **Apply + alias machinery** — `save()` writes the `Game` and syncs
  tags/authors/urls/attributions; `_resolve_alias_id` is the "name → redirect →
  existing alias → spawn orphan alias" resolution. Replaces `games/updater.py`.

## Locked decisions

- **Canonical form** = `GameInfo.to_canonical()` (YAML front matter + markdown).
  Both `GameSourceFetch.canonical_text` and `GameEdit.canonical_text` use it, so
  the two ends of the pipeline speak the same representation. The change-detection
  hash hashes this. **Rename** `GameSourceFetch.filtered_content` →
  `canonical_text` (+ `_hash`); there is no separate "denoise" step —
  canonicalizing *is* the denoise.
- **Filter chain (Phase 4)** = a hardcoded ordered list of functions in a module
  (drivers get a registry because they're URL-routed; filters run in fixed order,
  so a plain list is simpler). First filters wrap `merge()` and `enrichment.py`'s
  `enricher` for a low-diff migration; better/LLM filters swap in later.
- **Authors**: in scope minimally —
  - alias resolution (already in `gameinfo._resolve_alias_id`) and
  - author-source discovery via `canonicalize_author` (apero + ifwiki only).
  - **Deferred**: any per-author Source/Fetch/Edit review history (never finished
    on the old site either).
- **Migration safety**: the old `Importer`/`updater.py` stay live and untouched
  through phases A–C; the new pipeline populates `curation` tables in shadow. The
  old path is retired only at the end of Phase 4, once `GameEdit` output is
  trustworthy.

## Slice plan & status

The one boundary to hold: **everything-except-reconcile, then reconcile**.
Phase 3 (reconcile) is the only real design-risk and wants a populated corpus to
develop against, so it ships alone.

- [x] **A. Driver interface + migrate importers** — done.
  - `GameSourceProvider` ABC + `CanonicalAuthor` in `curation/providers.py`
    (see "As shipped in A/B" above). `discover()`/`DiscoveredSource` shipped
    in B.
  - Migrated apero, ifwiki, insteadgames, questbook, ifiction, qspsu, plut via
    the bridge adapter `GameInfo.from_importer_dict` (old dict → `GameInfo`);
    each `ImportFromX` split into `FetchX` + `ParseX`, wrappers kept live.
    rilarhiv skipped (no per-game page). qspsu/plut were unregistered legacy
    importers; their split was free, so they migrated too (plut needed a new
    `PLUT` `SourceType`).
- [x] **B. Phase 1 discover runner** — `discover()` → dedup against existing
  `GameSource` by (type, url) → create orphan rows.
  - Added `DiscoveredSource` and default `GameSourceProvider.discover()`.
  - Seven registered providers bridge to the legacy listing crawls (apero,
    ifwiki, insteadgames, questbook, ifiction, qspsu, plut).
  - Added `manage.py sources discover [--type TYPE]` and `curation.discovery`;
    command output reports discovered, existing, new, and missing URL counts.
  - URL fan-out and rilarhiv remain out of scope for this slice.
- [ ] **C. Phase 2 fetch runner** — crawler/schedule → store `raw_content`;
  canonicalize → `GameInfo.to_canonical()` into `canonical_text`; hash for
  change-detection (unchanged hash ⇒ bump `last_fetch`, no new edit).
- [ ] **D. Phase 3 reconcile** *(the risk — build against the corpus from B/C)* —
  cluster orphan sources → `GameHistory`: match by URL-identity (url already
  linked to a history), title similarity (old `SimilarEnough` bag-of-words,
  `games/importer/tools.py`), shared authors. Attach to existing or spawn new.
- [ ] **E. Phase 4 filter chain + GameEdit + apply** — gather a history's source
  canonicals → run the filter list (`merge` core, `enricher` wrapped) → diff vs
  `GameInfo.from_game(game)` → write `GameEdit` → apply via `GameInfo.save()`
  honoring `GameHistory.auto_updates` (REJECT/PROPOSE/ACCEPT).

A and C/E can merge if convenient (all "plumbing around code that exists"); only
the D boundary is firm.

## Open questions (unresolved)

- Phase 3 reconcile heuristics: thresholds, conflict handling, how to cluster
  several orphans that refer to one game before any history exists.
- Where `discover()` scheduling/cadence lives (crawler integration in Phase 2).
- Whether `canonicalize_author` output needs storage at all pre-Phase-4, or is
  consumed inline during apply.

## Code map

- `curation/models.py` — `GameHistory`, `GameSource`, `GameSourceFetch`,
  `GameEdit`, `GameHistoryComment`, `GameHistoryAuditLog`.
- `curation/gameinfo.py` — `GameInfo` (canonical form), `merge`, `parse`,
  `to_canonical`, `save`, alias resolution. The heart of the new system.
- `games/importer/` — old importers + `tools.py` (`Importer`, `MergeImport`,
  `SimilarEnough`, `CategorizeUrl`, `URL_CATEGORIZER_RULES`) + `enrichment.py`.
  Source material to port; stays live until Phase 4 cutover.
- `games/updater.py` — old apply path (`UpdateGameUrls`, `UpdatePersonalityUrls`)
  being replaced by `GameInfo.save()`.
