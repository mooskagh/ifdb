# db.crem.xyz Development Setup

This guide describes how to set up a local development instance of db.crem.xyz on a fresh machine.

## Prerequisites

* **Docker & Docker Compose** (running)
* **[uv](https://docs.astral.sh/uv/)**: Fast Python package manager
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
  *(Python >= 3.14 will automatically be fetched and managed by `uv`)*
* **[just](https://github.com/casey/just)**: Command runner
  ```bash
  cargo install just
  # or via your system package manager (e.g., apt install just, brew install just)
  ```
* *(Optional)* **unar**: Archive extractor used for game uploads (`sudo apt install unar`)

---

## Setup Steps

### 1. Clone the repository
```bash
git clone <repo-url>
cd ifdb
```

### 2. Configure environment
```bash
cp .env.sample .env
```
Default database credentials in `.env.sample` match `docker-compose.yml` and are ready for local development.

### 3. Install dependencies
```bash
uv sync
```
This sets up the virtual environment (`.venv`) and installs all runtime and development packages (Django, Ruff, Mypy, etc.).

### 4. Start the PostgreSQL database
```bash
just start-db
```
*(Runs PostgreSQL 15 on port `6432` via Docker Compose).*

### 5. Run database migrations
In a new terminal:
```bash
uv run python manage.py migrate
```

### 6. Seed initial data & create superuser
Populate base categories, author roles, tags, and curation rules:
```bash
uv run python manage.py initifdb
uv run python manage.py initenrichment
uv run python manage.py createsuperuser
```

### 7. Start the development server
```bash
uv run python manage.py runserver
```
The site is now live at [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

---

## Development & Quality Checks

Common commands defined in `justfile`:

```bash
just                   # List all available commands
just check             # Run all checks (Django system checks, Ruff format/lint, Mypy, tests)
just fix               # Format code and auto-fix lint issues with Ruff
just fix_and_check     # Run formatting then all checks
```

---

## Optional: Celery & Celery Beat

> **Note:** Celery workers and scheduler are **only needed for fetch & import and automated curation workflows**. For regular web development, template editing, and running tests, they are **not needed**.

If you are working on fetch/import or scheduled tasks:

1. **Celery Worker**:
   ```bash
   just celery-worker
   # or: uv run python manage.py celeryworker
   ```

2. **Celery Beat** (scheduler):
   ```bash
   just celery-beat
   # or: uv run celery -A ifdb beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler
   ```
