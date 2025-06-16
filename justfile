# Just file for ifdb

# Default recipe
default:
    @just --list

# Django system checks
check-django:
    @echo "Running Django system checks..."
    python manage.py check --verbosity=2

# Run ruff linting
check-ruff:
    @echo "Running ruff..."
    ruff check .

# Run mypy type checking
check-mypy:
    @echo "Running mypy..."
    mypy .

# Run Django tests
check-tests:
    @echo "Running Django tests..."
    python manage.py test

# Run isort import sorting
fix-isort:
    @echo "Running isort..."
    isort .

# Run black code formatting
fix-black:
    @echo "Running black..."
    black --preview --line-length=79 --enable-unstable-feature string_processing .

# Run all read-only checks
check: check-django check-ruff check-tests
    @echo "All checks passed!"

# Run all formatting fixes
fix: fix-isort fix-black
    @echo "Formatting complete!"

# Run both fix and check
fix_and_check: fix check

# Start PostgreSQL development server
start-db:
    @echo "Starting PostgreSQL development server..."
    @echo "Database: ifdbdev"
    @echo "Host: localhost:5432"
    @echo "User: ifdbdev"
    @echo "Password: ifdb"
    @echo ""
    @echo "Press Ctrl+C to stop"
    @echo ""
    docker-compose up