# Just file for ifdb

# Default recipe
default:
    @just --list

# Build TypeScript frontend bundle
build-frontend:
    @echo "Building frontend..."
    esbuild frontend/main.ts --bundle --outfile=core/static/bundle.js
    esbuild frontend/editor.ts --bundle --outfile=core/static/editor.js
    esbuild frontend/llmModels.ts --bundle --outfile=core/static/llm_models.js
    esbuild frontend/reconcile.ts --bundle --outfile=core/static/reconcile.js

# Django system checks
check-django:
    @echo "Running Django system checks..."
    uv run python manage.py check --verbosity=2

# Run ruff linting
check-ruff:
    @echo "Running ruff..."
    uv run ruff check .

# Run mypy type checking
check-mypy:
    @echo "Running mypy..."
    uv run mypy .

# Run Django tests
check-tests:
    @echo "Running Django tests..."
    uv run python manage.py test

# Run ruff code formatting and import sorting
fix-ruff:
    @echo "Running ruff format..."
    uv run ruff format .
    @echo "Running ruff check --fix..."
    uv run ruff check --fix .

# Run all read-only checks
check: check-django check-ruff check-tests
    @echo "All checks passed!"

# Run all formatting fixes
fix: fix-ruff
    @echo "Formatting complete!"

# Run both fix and check
fix_and_check: fix check

pre-commit: fix_and_check

# Start PostgreSQL development server
start-db:
    @echo "Starting PostgreSQL development server..."
    @echo "Database: ifdbdev"
    @echo "Host: localhost:6432"
    @echo "User: ifdbdev"
    @echo "Password: ifdb"
    @echo ""
    @echo "Press Ctrl+C to stop"
    @echo ""
    docker-compose up

# Start Celery development worker
celery-worker:
    uv run python manage.py celeryworker

# Start Celery beat development scheduler
celery-beat:
    uv run celery -A ifdb beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler
