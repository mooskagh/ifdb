# AGENTS.md

## Environment Setup

- We use `uv` for virtual environment management.
- Developer runs `uv run ./manage.py runserver` and database separately — do not start them
- Use strict Python type annotations
- Code should be idiomatic, elegant, short, beautiful and concise. Don't overdo comments, don't overengineer, don't introduce unnecessary abstractions.

## Development Commands

### Just Commands (Primary Interface)

```bash
just                   # List all available commands
just fix               # Format code with ruff (format + check --fix)
just check             # Run all checks (Django, ruff lint, tests)
just fix_and_check     # Fix formatting then run all checks
just check-mypy        # Type checking only
just start-db          # Start PostgreSQL via docker-compose
```

### Multi-Site Configuration

The project supports multiple domains with separate configurations:
- Main IFDB site (kontigr.com, zok.quest) -- these sites show subset of db.crem.xyz for particular contests.
- Environment detection based on hostname
