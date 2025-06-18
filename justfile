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

# Run ruff code formatting and import sorting
fix-ruff:
    @echo "Running ruff format..."
    ruff format .
    @echo "Running ruff check --fix..."
    ruff check --fix .

# Run all read-only checks
check: check-django check-ruff check-tests
    @echo "All checks passed!"

# Run all formatting fixes
fix: fix-ruff
    @echo "Formatting complete!"

# Run both fix and check
fix_and_check: fix check

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