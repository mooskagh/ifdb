# Just file for ifdb

# Default recipe
default:
    @just --list

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