# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

db.crem.xyz is a Django-based web platform serving as a comprehensive database for Interactive Fiction games, primarily focused on the Russian-language IF community. It provides game cataloging, user reviews, competitions, and community features.

## Environment Setup

- Claude Code runs from venv, no need to activate manually
- Developer runs `./manage.py runserver` and database separately — do not start them
- ruff and mypy are installed system-wide, run without `python -m` prefix
- Use Python type annotations, but don't overdo it (omit when too much boilerplate)
- Code should be idiomatic, elegant, short, beautiful and concise

## Todo Epilogue

When creating the todo list for a task, add "Perform todo epilogue" as the final item (unless asked not to). When you reach it, replace with:
1. Check for opportunities to make code more idiomatic, elegant, concise, beautiful, nice and short
2. Are there any useful tests to add?
3. Run `just fix_and_check`, fix any issues
4. Commit the changes to git with a meaningful message
5. If the original task was an item in a checklist or spec, mark it done and remove outdated info
6. Check again for uncommitted changes, commit if needed
7. Run `git push`

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

### Running Tests

```bash
python manage.py test                                    # All tests
python manage.py test games.tests.test_ifwiki_importer   # Single module
python manage.py test games.tests.test_ifwiki_importer.TestClass.test_method
```

### Database

Development database runs via docker-compose (localhost:6432, user/db: ifdbdev, password: ifdb).

### Custom Management Commands

```bash
python manage.py initifdb           # Initialize database with default data
python manage.py fillgames          # Import games from external sources
python manage.py forcereimport      # Force re-import all games
python manage.py initcontests       # Set up competition data
python manage.py populatepackages   # Package management
python manage.py ifdbworker         # Start background task worker
```

## Architecture Overview

**games/** - Core game management
- Central app handling game entries, authors, tags, ratings, and file resources
- Includes sophisticated import system for multiple external sources (IFWiki, Apero, QuestBook)
- Manages online interpreter integration and file hosting

**core/** - Infrastructure and user management  
- "Snippets" for home page (latest games, comments, contests)
- Custom user model with email authentication
- Background task queue system via TaskQueueElement
- Document/CMS management and RSS feed aggregation
- File upload and storage handling

**contest/** - Competition management
- List of past, current, and future competitions in the IF community (not just hosted on that site)
- IF competition hosting with flexible voting systems
- Automated ranking calculations and results generation
- Contest documentation and resource management

**moder/** - Moderation tools
- User action logging and administrative moderation tools
- Change history and audit trails

**rss/** - RSS feed generation
- Provides feeds for comments, activities, and competitions -- never finished

### Multi-Site Configuration

The project supports multiple domains with separate configurations:
- Main IFDB site (kontigr.com, zok.quest) -- these sites show subset of db.crem.xyz for particular contests.
- Environment detection based on hostname

### Permission System

Uses string-based permission expressions:
- Role aliases: `@all`, `@auth`, `@admin`
- Granular permissions per game, author, and content type
- Permission inheritance and complex expressions supported

### Background Processing

- Asynchronous task queue for imports and maintenance
- Automatic game importing from multiple sources
- URL monitoring and health checking
- File processing and backup operations

### File Management

- Local file caching with multiple storage backends
- Support for uploads, backups, and recodes
- Automatic backup and mirroring capabilities

## Development Notes

### Key Models Relationships
- Game → GameAuthor → Personality (author management)
- Game → GameTag → GameTagCategory (flexible tagging)
- Game → GameURL (file resources and links)
- Game → GameVote/GameComment (user interactions)

### Import System
Multiple importers in `games/importer/` handle different sources:
- ifwiki.py, apero.py, questbook.py, insteadgames.py
- Automated enrichment and duplicate detection
- Background processing via task queue
