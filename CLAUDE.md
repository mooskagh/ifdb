# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IFDB (Interactive Fiction Database) is a Django-based web platform serving as a comprehensive database for Interactive Fiction games, primarily focused on the Russian-language IF community. It provides game cataloging, user reviews, competitions, and community features.

## Development Commands

### Running the Application
```bash
python manage.py runserver  # Development server
# OR use the convenience script:
# ./run.cmd (Windows) or python manage.py runserver
```

### Database Operations
```bash
python manage.py makemigrations  # Create migrations
python manage.py migrate        # Apply migrations
python manage.py initifdb       # Initialize database with default data
```

### Data Management
```bash
python manage.py fillgames              # Import games from external sources
python manage.py forcereimport          # Force re-import all games
python manage.py initcontests           # Set up competition data
python manage.py populatepackages       # Package management
```

### Background Processing
```bash
python manage.py ifdbworker  # Start background task worker
```

### Testing
```bash
python manage.py test  # Run tests (basic Django tests available)
```

## Architecture Overview

### Django Apps Structure

**games/** - Core game management
- Central app handling game entries, authors, tags, ratings, and file resources
- Includes sophisticated import system for multiple external sources (IFWiki, Apero, QuestBook)
- Manages online interpreter integration and file hosting

**core/** - Infrastructure and user management  
- Custom user model with email authentication
- Background task queue system via TaskQueueElement
- Document/CMS management and RSS feed aggregation
- File upload and storage handling

**contest/** - Competition management
- IF competition hosting with flexible voting systems
- Automated ranking calculations and results generation
- Contest documentation and resource management

**moder/** - Moderation tools
- User action logging and administrative moderation tools
- Change history and audit trails

**rss/** - RSS feed generation
- Provides feeds for comments, activities, and competitions

### Multi-Site Configuration

The project supports multiple domains with separate configurations:
- Main IFDB site (kontigr.com, zok.quest) 
- Different templates and settings per domain
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

### Database Configuration
- Development: PostgreSQL (ifdbdev/ifdbdev@localhost)
- Production: PostgreSQL with external config files
- Migrations are app-specific (games, core, contest, moder)

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

### Version Management
Current version stored in `version.txt` (v0.14.10)