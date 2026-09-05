# IFDB REST API Documentation

The IFDB REST API allows clients to programmatically create, retrieve, update, and publish games using the canonical text format, as well as upload game files and attach download links.

Interactive documentation (Redoc) is available at `/api/docs/` and the machine-readable OpenAPI 3.0 specification is served at `/api/openapi.json`.

---

## Authentication & Authorization

All mutating endpoints require an API token. API tokens can be created in the Django Admin (`/adminz/api/apitoken/`).

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

Actions performed via the API record:
- `Game.added_by` is set to the token owner.
- `GameRevision.created_by` and `GameRevision.published_by` are set to the token owner.
- `GameRevision.origin` is set to `API`.
- `URL.creator` is set to the token owner.

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
  "canonical_text": "---\n- name: \"The Lost Cavern\"\n- release_date: 2026-03-01\n- tags:\n  - [\"genre\", \"Приключения\"]\n---\nA thrilling text adventure in a sunken cave system.",
  "state": "draft"
}
```

**Raw Text Request Body (`Content-Type: text/plain`)**:
```yaml
---
- name: "The Lost Cavern"
- release_date: 2026-03-01
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

### 3. Documentation

- **Interactive UI**: `GET /api/docs/`
- **OpenAPI Schema**: `GET /api/openapi.json`
