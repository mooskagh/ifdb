# Task: Add A Curation Feeds Dashboard

Add a new superuser-only page at `/curation/feeds/`, similar in spirit and UI style to the existing `/curation/sources/` page.

The page is for monitoring configured community/blog/forum feeds, not for game import sources. It should use the existing curation layout and conventions.

Relevant current code:

- URL config: `curation/urls.py`
- Views: `curation/views.py`
- Base curation template/sidebar: `curation/templates/curation/base.html`
- Existing source dashboard reference:
  - `curation/views.py::source_list`
  - `curation/templates/curation/source_list.html`
- Feed models:
  - `core.models.BlogFeed`
  - `core.models.FeedCache`
- Feed fetch runner:
  - `core.feedfetcher.run_fetch_feeds`
  - `core.feedfetcher.FeedFetchStats`
- Periodic task control already exists in `/curation/tasks/`:
  - task name: `Fetch feeds`
  - Celery task: `core.tasks.fetch_feeds`

Current `BlogFeed` fields:

```python
feed_id = models.CharField(max_length=32)
title = models.CharField(max_length=256)
url = models.CharField(max_length=256, null=True, blank=True)
show_author = models.BooleanField()
rss = models.CharField(max_length=256)
rss_comments = models.CharField(max_length=256, null=True, blank=True)
is_enabled = models.BooleanField(default=True)
last_attempt = models.DateTimeField(null=True, blank=True)
last_success = models.DateTimeField(null=True, blank=True)
failing_since = models.DateTimeField(null=True, blank=True)
last_error = models.TextField(null=True, blank=True)
```

Current `FeedCache` fields:

```python
feed_id = models.CharField(max_length=32)
item_id = models.CharField(max_length=512)
date_published = models.DateTimeField()
date_discovered = models.DateTimeField()
title = models.CharField(max_length=512)
authors = models.CharField(max_length=256)
url = models.CharField(max_length=2048)
```

Important recent context:

- Feed fetching was recently redesigned from an all-or-nothing hard-coded task into a limited queue over `BlogFeed` rows.
- `BlogFeed` now has health fields and `is_enabled`.
- Four formerly hard-coded feeds are seeded as `BlogFeed` rows by `core/migrations/0023_blogfeed_status.py`: `ifhub`, `ifru`, `urq`, `inst`.
- VK feeds currently fail cleanly with `VK feeds need a service access token`; this is expected until the separate VK task is done.
- Existing unrelated working-tree files may be present; do not revert unrelated changes.

Expected page purpose:

- Show configured feeds from `BlogFeed`.
- Make it easy to see feed health: enabled/disabled, last attempt, last success, failing since, last error.
- Show recent cached post activity from `FeedCache`, e.g. latest discovered/published post and/or cached item count per feed.
- Provide filtering/sorting comparable to `/curation/sources/`, adapted to feeds.
- Add a sidebar link in `curation/base.html`.

Useful design reference from `/curation/sources/`:

- `source_list` reads query params: `q`, `type`, `state`, `attached`, `sort`.
- It paginates rows and renders a compact curation table.
- It uses row CSS state classes like `error`, `warning`, `success`.
- It annotates latest related data with subqueries before rendering.

Tests to look at:

- `curation.tests.TasksViewTest` has examples of curation page tests and superuser client setup.
- Existing source-list tests are in `curation/tests.py` near `source_list` coverage.
- Feed queue tests are in `core/test_feedfetcher.py`.

Constraints:

- Keep the change lightweight.
- Preserve existing curation visual language and templates.
- Do not redesign feed fetching itself as part of this task unless strictly necessary for the page.
- Do not fix VK in this task; treat VK failures as current feed health data.
- Use idiomatic Django ORM; avoid heavy new abstractions.
