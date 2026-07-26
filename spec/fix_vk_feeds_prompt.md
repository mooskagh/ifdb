# Task: Fix VK Feed Fetching

Fix fetching of `vk-*` rows in `BlogFeed` so VK posts are imported into `FeedCache` again.

This is separate from the `/curation/feeds/` dashboard task.

Relevant current code:

- Feed runner: `core/feedfetcher.py`
- Celery task: `core/tasks.py::fetch_feeds`
- Feed models: `core.models.BlogFeed`, `core.models.FeedCache`
- Settings: `ifdb/settings.py`
- Dependency list: `pyproject.toml`
- Tests for feed queue: `core/test_feedfetcher.py`

Current feed runner behavior:

- `run_fetch_feeds(limit=5, feed_id=None)` selects enabled `BlogFeed` rows ordered by `last_attempt NULLS FIRST`, then `feed_id`.
- Each feed is fetched independently.
- Failures are caught per feed and stored on `BlogFeed.last_attempt`, `failing_since`, `last_error`.
- Success stores `last_attempt`, `last_success`, and clears failure fields.
- Regular RSS/Atom feeds use `FetchFeed` and write posts into `FeedCache` through `ProcessFeedEntries`.
- Special feeds:
  - `ifru` uses `FetchIficionFeed()`.
  - `urq` uses `FetchUrqFeed()`.
  - `vk-*` currently raises `NotImplementedError("VK feeds need a service access token")`.

Current legacy VK code still present in `core/feedfetcher.py`:

```python
VK_RE = re.compile(r"https://vk.com/(.*)")


def FetchVkFeed(api, url, feed_id):
    logger.info("Fetching vk feed %s" % url)
    m = VK_RE.match(url)
    gid = api.groups.getById(group_ids=m.group(1))[0]["id"]
    posts = api.wall.get(owner_id=-gid)
    ...
```

That legacy function expects an old `vk` Python package API object. The project no longer has the `vk` package dependency.

Old history/context:

- Old code used `vk==2.0.2` and `vk.API(..., v='5.71')`, later updated to `v='5.131'`.
- The old VK block was commented out during modernization; current `pyproject.toml` has no VK client dependency.
- A direct probe without token returned VK API `error_code: 15`, `Access denied: token required` for `groups.getById` and `wall.get`.
- VK current schema/references indicate API version `5.199` and that these methods can use a service token:
  - `wall.get`: `user`, `service`
  - `groups.getById`: `user`, `group`, `service`
  - `users.get`: `user`, `group`, `service`

Settings context:

- In production/non-debug, `ifdb/settings.py` reads `VK_SERVICE_KEY = open("/home/ifdb/configs/vk.txt").read().strip()`.
- In DEBUG, `VK_SERVICE_KEY = "dummy-vk-key-for-debug"`.
- The likely desired secret is a VK service access token stored in the existing `vk.txt` path, unless project owner says otherwise.

Configured VK feeds from local DB snapshot:

```text
vk-interfict     https://vk.com/club673750
vk-ifrpg         https://vk.com/club12922446
vk-urqclub       https://vk.com/urqclub
vk-urq           https://vk.com/club767975
vk-qsp           https://vk.com/club21582484
vk-instead       https://vk.com/club18020281
vk-nlbproject    https://vk.com/nlbproject
vk-kvester       https://vk.com/kvesterik
vk-kontigr       https://vk.com/kontigr
vk-axma          https://vk.com/axmastorymaker
vk-apero         https://vk.com/games_online
vk-instory_top   https://vk.com/instory_top
vk-instorysu     https://vk.com/instorysu
vk-zok           https://vk.com/zok_ifiction
vk-twine         https://vk.com/academy_twine
```

Expected behavior:

- Fetch public VK wall posts for configured `vk-*` feeds.
- Store posts in `FeedCache` with stable `feed_id` and `item_id`.
- Preserve existing feed queue health behavior: one bad VK feed must not block other feeds.
- Preserve existing title behavior as much as possible: post text plus repost/copy-history text, truncated for `FeedCache.title`.
- Preserve author behavior as much as possible: use signer/from-user names when available.
- Skip ad posts like the old code did (`marked_as_ads`).
- Keep feed post URLs linking back to VK wall posts.

Important implementation constraints:

- Do not reintroduce the old `vk` package unless there is a strong reason; direct `requests` calls are likely better because `requests` is already a dependency.
- Use current API version, likely `5.199`.
- Keep code small and local to feed fetching unless a broader change is clearly needed.
- Add tests using mocked HTTP/API responses; do not require real VK network access or a real token in tests.
- Be careful with VK URL forms: both `https://vk.com/club12345` and `https://vk.com/screen_name` exist in current feed rows.
- Existing unrelated working-tree files may be present; do not revert unrelated changes.

Useful current files for tests:

- `core/test_feedfetcher.py` already tests queue ordering, disabled feeds, and failure isolation.
- Add VK-specific tests there or a nearby test module.

Operational note:

- If a real VK service token is not available locally, tests should still fully cover request construction and response parsing through mocks.
