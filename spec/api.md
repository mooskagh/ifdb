# IFDB REST API Documentation

The IFDB REST API allows clients to programmatically create, retrieve, update, and publish games using the canonical text format, as well as upload game files and attach download links.

The machine-readable OpenAPI 3.0 specification is served at `/api/openapi.json`.

---

## Canonical Format Reference

The **canonical format** is the YAML front matter + Markdown representation of a game.

```yaml
---
- name: "The Lost Cavern"
- release_date: "2026-03-01"
- personalities:
  - author:
    - "John Doe"
  - translator:
    - "Jane Smith"
- tags:
  - ["genre", "Приключения"]
  - ["os", "Windows"]
  - ["platform", "QSP"]
  - ["control", "Парсерная"]
  - ["state", "Готовая"]
- urls:
  - ["download_direct", "Windows archive", "https://ifdb.example.com/f/uploads/games/42/game.zip"]
  - ["play_online", "Play in browser", "https://example.com/play/"]
- attributions:
  - "ifwiki.ru"
---
Markdown description body...
```

### Supported Front Matter Fields:
1. `name`: Game title (string).
2. `release_date`: Release date (`YYYY-MM-DD` or year `YYYY`).
3. `personalities`: Grouped by role. Names are scalar strings or database alias IDs. Supported roles:
   - `author`: Author
   - `orig_author`: Original author
   - `programmer`: Programmer
   - `artist`: Artist / illustrator
   - `composer`: Composer / musician
   - `voiceover`: Voice actor
   - `tester`: Playtester
   - `translator`: Translator
   - `porter`: Platform porter
   - `character`: Character
   - `member`: Other team member
4. `tags`: Pairs of `[category, value]`, `[category, tag_id]`, or tag slugs (`"os_win"`, `"g_adventure"`). Categories:
   - `genre`: Genres (`Приключения`, `Фэнтези`, `Детектив`, `Хоррор`, `Юмор`, `Фантастика`, `Боевик`, `Драма`, `Дистопия`, `Сказка`, `Фанфик`, `Мистика`, `Головоломка`, `Романтика`, `RPG`, `Симулятор`, `Детское`, `18+`, `Экспериментальное`)
   - `platform`: Game engine/platform (free text, e.g. `QSP`, `URQ`, `Twine`, `INSTEAD`, `Ren'Py`, `Inform`, `AXMA`, `HTML`)
   - `os`: Operating system (`Windows`, `Web (online)`, `Linux`, `MacOs`, `Android`, `iOS`, `DOS`, `Другая ОС`)
   - `control`: Controls (`Парсерная`, `Менюшная`)
   - `state`: Development state (`Готовая`, `В разработке`, `Бета`, `Демо`)
   - `language`: Language (`ru`, `en`, etc.)
   - `country`: Country of origin
   - `competition`: Competition participation
   - `version`: Game version
   - `ifid`: IFID identifier
   - `tag`: Freeform user tags (e.g. `ifwiki_featured`)
   - `admin`: Administrative flags
5. `urls`: Items of `[category, description, url_or_id]` or `[category, url_or_id]`. Categories:
   - `download_direct`: Direct download link to game archive/file
   - `download_landing`: File hosting / landing page download link
   - `play_online`: Online playable web link
   - `game_page`: External game page (itch.io, Steam, etc.)
   - `poster`: Poster / cover art
   - `screenshot`: Screenshot
   - `forum`: Forum discussion thread
   - `review`: Review
   - `video`: Video (walkthrough, review, trailer)
   - `other`: Other link
   - `unknown`: Uncategorized
6. `attributions`: List of source strings (e.g. `"ifwiki.ru"`, `"Википедия"`) or numeric IDs.

---

## Authentication & Authorization

All mutating endpoints require an API token.

### Headers

Pass the token in the standard `Authorization` header:

```http
Authorization: Bearer <your_token_key>
```
or
```http
Authorization: Token <your_token_key>
```

### Scopes / Permissions

Each token is linked to a user account and has a `permissions` list. If the list is empty or contains `"*"`, the token has all permissions. Otherwise, specific scopes can be assigned:

- `games:read`: Read game information and canonical text.
- `games:write`: Create or update games.
- `games:publish`: Publish or unpublish games, or create a game directly in `published` state.
- `files:upload`: Upload files.

### Attribution

All actions and edits performed via the API appear as the user associated with the token.

---

## Endpoints

### 1. Games

#### `POST /api/v1/games/`
Create a new game.

- **Scope Required**: `games:write` (and `games:publish` if `state="published"`).
- **Default State**: `draft`.
- **Content-Type**: `application/json` or `text/plain`.

**JSON Request Body**:
```json
{
  "canonical_text": "---\n- name: \"The Lost Cavern\"\n- release_date: 2026-03-01\n- personalities:\n  - author:\n    - \"John Doe\"\n- tags:\n  - [\"genre\", \"Приключения\"]\n---\nA thrilling text adventure in a sunken cave system.",
  "state": "draft"
}
```

**Raw Text Request Body (`Content-Type: text/plain`)**:
```yaml
---
- name: "The Lost Cavern"
- release_date: 2026-03-01
- personalities:
  - author:
    - "John Doe"
- tags:
  - ["genre", "Приключения"]
---
A thrilling text adventure in a sunken cave system.
```

**Response (`201 Created`)**:
```json
{
  "id": 42,
  "title": "The Lost Cavern",
  "state": "draft",
  "revision_id": 105,
  "canonical_text": "---\n- name: \"The Lost Cavern\"\n...",
  "created_at": "2026-09-05T15:58:00+00:00",
  "updated_at": "2026-09-05T15:58:00+00:00"
}
```

---

#### `GET /api/v1/games/<int:game_id>/`
Retrieve a game's details and canonical document.

- **Scope Required**: `games:read`.

**Response (`200 OK`)**:
```json
{
  "id": 42,
  "title": "The Lost Cavern",
  "state": "draft",
  "revision_id": 105,
  "canonical_text": "---\n- name: \"The Lost Cavern\"\n- release_date: \"2026-03-01\"\n...\n---\nA thrilling text adventure...",
  "created_at": "2026-09-05T15:58:00+00:00",
  "updated_at": "2026-09-05T15:58:00+00:00"
}
```

---

#### `PUT /api/v1/games/<int:game_id>/` (or `PATCH`)
Update a game's metadata and description by submitting updated canonical text.

- **Scope Required**: `games:write`.
- **Behavior**: Parses canonical text, updates the game, and creates a new `GameRevision` with `origin=API`.

**Request Body (`application/json`)**:
```json
{
  "canonical_text": "---\n- name: \"The Lost Cavern (Director's Cut)\"\n---\nUpdated description."
}
```

**Response (`200 OK`)**:
```json
{
  "id": 42,
  "title": "The Lost Cavern (Director's Cut)",
  "state": "draft",
  "revision_id": 106,
  "canonical_text": "---\n- name: \"The Lost Cavern (Director's Cut)\"\n...\n---\nUpdated description.",
  "created_at": "2026-09-05T15:58:00+00:00",
  "updated_at": "2026-09-05T16:00:00+00:00"
}
```

---

#### `POST /api/v1/games/<int:game_id>/publish/`
Transition a draft game to published.

- **Scope Required**: `games:publish`.
- **Behavior**: Publishes the latest revision and sets `state` to `published`. Idempotent.

**Response (`200 OK`)**:
```json
{
  "id": 42,
  "state": "published"
}
```

---

#### `POST /api/v1/games/<int:game_id>/unpublish/`
Transition a published game to draft.

- **Scope Required**: `games:publish`.
- **Behavior**: Sets `state` to `draft`. Idempotent.

**Response (`200 OK`)**:
```json
{
  "id": 42,
  "state": "draft"
}
```

---

### 2. File Uploads

#### `POST /api/v1/files/`
Upload a standalone game file to obtain a download link.

- **Scope Required**: `files:upload`.
- **Content-Type**: `multipart/form-data`.
- **Form Fields**:
  - `file`: binary file.
  - `category` *(optional)*: default `"download_direct"`.
  - `description` *(optional)*: label for download link.

**Response (`201 Created`)**:
```json
{
  "url_id": 350,
  "url": "https://ifdb.example.com/f/uploads/cavern.zip",
  "filename": "cavern.zip",
  "canonical_snippet": ["download_direct", "", 350]
}
```
The returned `canonical_snippet` can be pasted directly under `- urls:` in your canonical text document when creating or updating a game.

---

#### `POST /api/v1/games/<int:game_id>/files/`
Upload a file directly connected to an existing game.

- **Scope Required**: `files:upload`.
- **Content-Type**: `multipart/form-data`.
- **Form Fields**:
  - `file`: binary file.
  - `category` *(optional)*: default `"download_direct"`.
  - `description` *(optional)*: label (e.g. "Release 1.2 zip").

**Behavior**:
1. Saves the file under `games/<game_id>/<filename>`.
2. Creates a `URL` record (`creator=token.user`, `is_uploaded=True`).
3. Attaches `GameURL` under category `download_direct`.
4. Appends to the game's canonical text and records a new revision with `origin=API`.

**Response (`201 Created`)**:
```json
{
  "game_id": 42,
  "url_id": 351,
  "url": "https://ifdb.example.com/f/uploads/games/42/cavern_v1.zip",
  "filename": "cavern_v1.zip",
  "category": "download_direct",
  "description": "Release 1.2 zip",
  "canonical_snippet": ["download_direct", "Release 1.2 zip", 351],
  "canonical_text": "---\n- name: \"The Lost Cavern\"\n- urls:\n  - [\"download_direct\", \"Release 1.2 zip\", 351]\n---\n..."
}
```

---

### 3. OpenAPI Specification

- **OpenAPI Schema**: `GET /api/openapi.json`
