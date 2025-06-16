# Tech Debt Reduction Plan for IFDB

## Implementation Checklist (Update as phases are completed)

### Phase 1: Critical Security & Infrastructure ⚠️
- [ ] 1.1: Django upgrade from 3.0.5 to 5.2 (latest stable)
- [ ] 1.2: Security dependency audit and updates  
- [ ] 1.3: Add comprehensive logging system
- [ ] 1.4: Add type annotations to critical modules
- [ ] 1.5: Set up proper development environment with modern tooling

### Phase 2: Code Architecture & Quality 🏗️
- [ ] 2.1: Extract business logic from fat views using Managers/QuerySets/Models
- [ ] 2.2: Implement comprehensive test suite
- [ ] 2.3: Add linting and code formatting (black, isort, flake8)
- [ ] 2.4: Convert old URL patterns to modern path() syntax
- [ ] 2.5: Add comprehensive type annotations to remaining modules

### Phase 3: Task Queue & Import System Overhaul 🔄
- [ ] 3.1: Replace custom task queue with Celery + RabbitMQ
- [ ] 3.2: Refactor game import system for fault tolerance
- [ ] 3.3: Update VK API integration to latest version
- [ ] 3.4: Add proper error handling and retry logic for importers
- [ ] 3.5: Implement monitoring and alerting for background tasks

### Phase 4: Performance & Search Optimization 🚀  
- [ ] 4.1: Implement Elasticsearch for game search
- [ ] 4.2: Add database query optimization (select_related, prefetch_related)
- [ ] 4.3: Add caching layer for events/jams section
- [ ] 4.4: Optimize slow database queries with indexes
- [ ] 4.5: Implement pagination for large datasets

### Phase 5: Modern Frontend Architecture 🎨
- [ ] 5.1: Restructure CSS with CSS custom properties (--vars) and consistent organization
- [ ] 5.2: Replace jQuery with modern JavaScript and build tools
- [ ] 5.3: Redesign UI with contemporary design system
- [ ] 5.4: Add responsive design and mobile-first approach
- [ ] 5.5: Implement component-based CSS architecture

### Phase 6: Feature Cleanup & Enhancement 🧹
- [ ] 6.1: Remove "Справка" (Help) section
- [ ] 6.2: Enhance Authors section with better UI/UX
- [ ] 6.3: Add comprehensive REST API with DRF
- [ ] 6.4: Add API documentation
- [ ] 6.5: Implement progressive web app features

---

## Phase 1: Critical Security & Infrastructure ⚠️

**Priority**: CRITICAL
**Estimated Time**: 4-5 weeks
**Risk Level**: High (security vulnerabilities)

### 1.1 Django Upgrade (3.0.5 → 5.2)

**Current Issue**: Using Django 3.0.5 (April 2020) with 4+ years of missing security patches.

**Major Version Jump Considerations**:
- Django 3.0.5 → 5.2 is a significant jump (5 major versions)
- Multiple breaking changes across versions
- Need to handle deprecations from Django 3.x, 4.x, and 5.x

**Implementation Steps**:

1. **Pre-upgrade Preparation**:
   ```bash
   # Create comprehensive backup
   pg_dump ifdbdev > backup_pre_django5.sql
   
   # Create feature branch
   git checkout -b django-5-upgrade
   
   # Install Django upgrade tools
   pip install django-upgrade
   ```

2. **Incremental Upgrade Strategy**:
   ```python
   # Step 1: Django 3.0.5 → 3.2 LTS (final 3.x)
   # Step 2: Django 3.2 → 4.2 LTS  
   # Step 3: Django 4.2 → 5.2
   ```

3. **Update requirements.txt** (Final target):
   ```
   Django==5.2
   django-debug-toolbar==4.4.6
   django-extensions==3.2.3
   django-recaptcha==4.0.0
   django-registration==3.4
   djangorestframework==3.15.2
   djangorestframework-jwt==1.11.0  # May need replacement
   psycopg==3.2.1  # Updated from psycopg2-binary
   ```

**Breaking Changes to Address**:

**Django 4.x Breaking Changes**:
- `USE_TZ = False` → Must handle timezone-aware datetimes
- `DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'`
- Updated `CSRF_TRUSTED_ORIGINS` format
- Signal `providing_args` parameter removed

**Django 5.x Breaking Changes**:
- Deprecated features removed from 4.x
- Updated form rendering
- Changes to admin interface
- Updated middleware order requirements

**Code Changes Required**:

1. **Translation imports**:
   ```python
   # Before
   from django.utils.translation import ugettext_lazy as _
   
   # After  
   from django.utils.translation import gettext_lazy as _
   ```

2. **URL patterns** (already identified):
   ```python
   # Before
   url(r'^game/(?P<game_id>\d+)/', views.show_game, name='show_game')
   
   # After
   path('game/<int:game_id>/', views.show_game, name='show_game')
   ```

3. **Model changes**:
   ```python
   # Add to settings.py
   DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
   
   # Or explicitly in models
   class Game(models.Model):
       id = models.BigAutoField(primary_key=True)
   ```

4. **psycopg2 → psycopg3**:
   ```python
   # Update DATABASES config in settings.py
   DATABASES = {
       'default': {
           'ENGINE': 'django.db.backends.postgresql',  # Updated engine
           'NAME': 'ifdbdev',
           'USER': 'ifdbdev', 
           'PASSWORD': 'ifdb',
           'HOST': 'localhost',
           'PORT': '',
           'OPTIONS': {
               'server_side_binding': True,  # psycopg3 optimization
           },
       }
   }
   ```

5. **CSRF Configuration** (Django 4.0+):
   ```python
   # Update for Django 4.0+ format
   CSRF_TRUSTED_ORIGINS = [
       'https://db.crem.xyz',
       'https://kontigr.com',
       'https://zok.quest',
   ]
   ```

**Testing Strategy**:
1. Run existing minimal tests at each upgrade step
2. Manual testing of critical user flows:
   - User registration/login
   - Game viewing and editing
   - Competition voting
   - Game imports
3. Performance testing to ensure no regressions

### 1.2 Security Dependency Audit

**Critical Updates for Django 5.2**:
```python
# Severely outdated packages that need immediate updates:
cryptography==2.9.2    # → cryptography==42.0.8 (critical CVEs)
lxml==5.2.1           # → lxml==5.3.0 (check for recent CVEs)
requests==2.31.0      # → requests==2.32.3
urllib3==1.25.9       # → urllib3==2.2.2 (bundled with requests)
```

**Implementation**:
```bash
# Security audit
pip install pip-audit
pip-audit

# Update critical packages
pip install --upgrade cryptography lxml requests

# Verify no breaking changes
python manage.py check --deploy
```

### 1.3 Modern Logging System

**Django 5.2 Compatible Logging**:
```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'detailed': {
            'format': '{asctime} {levelname} {name} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOG_DIR, 'django.log'),
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
            'formatter': 'detailed',
        },
        'console': {
            'level': 'DEBUG' if DEBUG else 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
            'include_html': True,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'ifdb': {  # App-specific logger
            'handlers': ['file', 'console', 'mail_admins'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}
```

### 1.4 Type Annotations for Django 5.2

**Django 5.2 has improved type support**:
```python
from typing import Any, Optional
from django.http import HttpRequest, HttpResponse
from django.db.models import QuerySet

# Type-annotated view example
def show_game(request: HttpRequest, game_id: int) -> HttpResponse:
    game: Game = get_object_or_404(Game, pk=game_id)
    context: dict[str, Any] = {'game': game}
    return render(request, 'games/game.html', context)

# Model with type annotations
class Game(models.Model):
    title: str = models.CharField(max_length=255)
    description: Optional[str] = models.TextField(null=True, blank=True)
    
    def get_authors(self) -> QuerySet['GameAuthor']:
        return self.gameauthor_set.all()
```

### 1.5 Modern Development Environment

**pyproject.toml** (Django 5.2 compatible):
```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ifdb"
version = "0.15.0"
dependencies = [
    "Django>=5.2,<5.3",
    "psycopg[binary]>=3.2.1",
    "celery[redis]>=5.3.0",
    "django-elasticsearch-dsl>=8.0",
]

[project.optional-dependencies]
dev = [
    "django-debug-toolbar>=4.4.6",
    "django-extensions>=3.2.3",
    "black>=24.0.0",
    "isort>=5.13.0",
    "flake8>=7.0.0",
    "mypy>=1.11.0",
    "django-stubs>=5.0.0",
    "pytest-django>=4.8.0",
]

[tool.black]
line-length = 88
target-version = ['py311']
extend-exclude = '''
/(
    migrations
)/
'''

[tool.isort]
profile = "black"
multi_line_output = 3
skip = ["migrations"]

[tool.mypy]
python_version = "3.11"
check_untyped_defs = true
ignore_missing_imports = true
exclude = ["migrations/", "venv/"]
plugins = ["mypy_django_plugin.main"]

[tool.django-stubs]
django_settings_module = "ifdb.settings"
```

**Development Commands**:
```bash
# Install development dependencies
pip install -e ".[dev]"

# Code formatting
black .
isort .

# Type checking
mypy .

# Linting
flake8 .

# Run tests
pytest
```

---

## Phase 2: Code Architecture & Quality 🏗️

**Priority**: High
**Estimated Time**: 4-5 weeks
**Dependencies**: Phase 1 complete

### 2.1 Extract Business Logic Using Django Patterns

**Architecture Philosophy**:
- **Manager/QuerySet**: Per-model functionality, database queries
- **Model methods**: Per-instance functionality, computed properties
- **Service classes**: Cross-model operations, complex business logic

**Current Fat View Example** (`games/views.py:store_game`):
```python
# Before: 50+ lines of mixed logic in view
def store_game(request):
    if request.method == 'POST':
        # Complex validation
        # Business rules
        # Database operations
        # Response handling
```

**After: Refactored with Managers/Models/Services**:

1. **Custom Manager for Game queries**:
   ```python
   # games/models.py
   from django.db import models
   from django.db.models import QuerySet
   from typing import Optional, List
   
   class GameQuerySet(QuerySet['Game']):
       def published(self) -> 'GameQuerySet':
           return self.exclude(title='')
       
       def by_author(self, author_name: str) -> 'GameQuerySet':
           return self.filter(gameauthor__author__name__icontains=author_name)
       
       def recent(self, days: int = 30) -> 'GameQuerySet':
           from django.utils import timezone
           date_threshold = timezone.now() - timezone.timedelta(days=days)
           return self.filter(creation_time__gte=date_threshold)
       
       def with_authors(self) -> 'GameQuerySet':
           return self.prefetch_related('gameauthor_set__author')
       
       def search(self, query: str) -> 'GameQuerySet':
           return self.filter(
               models.Q(title__icontains=query) |
               models.Q(description__icontains=query)
           )
   
   class GameManager(models.Manager['Game']):
       def get_queryset(self) -> GameQuerySet:
           return GameQuerySet(self.model, using=self._db)
       
       def published(self) -> GameQuerySet:
           return self.get_queryset().published()
       
       def create_game(self, title: str, description: str = '', **kwargs) -> 'Game':
           """Manager method for creating games with validation."""
           if not title.strip():
               raise ValueError("Game title cannot be empty")
           
           return self.create(
               title=title.strip(),
               description=description.strip(),
               **kwargs
           )
   ```

2. **Model methods for instance functionality**:
   ```python
   class Game(models.Model):
       # ... field definitions ...
       
       objects = GameManager()
       
       def get_primary_author(self) -> Optional['Personality']:
           """Get the primary author of this game."""
           primary_author = self.gameauthor_set.filter(
               role__in=['author', 'главный автор']
           ).first()
           return primary_author.author if primary_author else None
       
       def get_rating_stats(self) -> dict[str, float]:
           """Calculate rating statistics for this game."""
           votes = self.gamevote_set.all()
           if not votes:
               return {'average': 0.0, 'count': 0}
           
           ratings = [vote.rating for vote in votes if vote.rating]
           return {
               'average': sum(ratings) / len(ratings) if ratings else 0.0,
               'count': len(ratings)
           }
       
       def is_editable_by(self, user) -> bool:
           """Check if user can edit this game."""
           if user.is_superuser:
               return True
           if self.added_by == user:
               return True
           # Check permission system
           from ifdb.permissioner import check_permission
           return check_permission(user, self.edit_perm)
   ```

3. **Service class for cross-model operations**:
   ```python
   # games/services.py
   from typing import List, Dict, Any
   from django.db import transaction
   from django.core.exceptions import ValidationError
   
   class GameImportService:
       """Service for importing games from external sources."""
       
       def __init__(self):
           self.logger = logging.getLogger('ifdb.services.import')
       
       @transaction.atomic
       def import_game_with_authors(
           self, 
           game_data: Dict[str, Any], 
           author_data: List[Dict[str, Any]]
       ) -> Game:
           """Import game with associated authors and metadata."""
           
           # Create or update game
           game, created = Game.objects.get_or_create(
               title=game_data['title'],
               defaults={
                   'description': game_data.get('description', ''),
                   'release_date': game_data.get('release_date'),
               }
           )
           
           # Handle authors (cross-model operation)
           for author_info in author_data:
               self._add_author_to_game(game, author_info)
           
           # Handle tags (cross-model operation)
           if tags := game_data.get('tags'):
               self._add_tags_to_game(game, tags)
           
           return game
   ```

4. **Thin view using the refactored components**:
   ```python
   # games/views.py
   from django.shortcuts import render, redirect, get_object_or_404
   from django.contrib.auth.decorators import login_required
   from django.contrib import messages
   from .services import GameImportService
   
   @login_required
   def store_game(request: HttpRequest) -> HttpResponse:
       """Thin view for game creation/editing."""
       if request.method == 'POST':
           try:
               # Simple validation
               title = request.POST.get('title', '').strip()
               if not title:
                   messages.error(request, "Game title is required")
                   return render(request, 'games/edit.html')
               
               # Use manager method for creation
               game = Game.objects.create_game(
                   title=title,
                   description=request.POST.get('description', ''),
                   added_by=request.user
               )
               
               messages.success(request, f"Game '{game.title}' created successfully")
               return redirect('show_game', game_id=game.id)
               
           except ValueError as e:
               messages.error(request, str(e))
               return render(request, 'games/edit.html')
       
       return render(request, 'games/edit.html')
   ```

---

## Phase 3: Task Queue & Import System Overhaul 🔄

**Priority**: High  
**Estimated Time**: 3-4 weeks
**Dependencies**: Phase 1-2 complete

### 3.1 Celery with Django 5.2

**Modern Celery Configuration**:
```python
# celery_app.py
import os
from celery import Celery
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ifdb.settings')

app = Celery('ifdb')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Celery settings in Django settings.py
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'

# Task routing
CELERY_TASK_ROUTES = {
    'games.tasks.import_*': {'queue': 'imports'},
    'games.tasks.process_*': {'queue': 'processing'},
}
```

### 3.2 Fault-Tolerant Import System

**Current Issue**: If any importer fails, entire process fails.

**New Architecture**:
```python
class ImportOrchestrator:
    def import_all_sources(self):
        sources = [
            ('ifwiki', import_from_ifwiki),
            ('apero', import_from_apero), 
            ('questbook', import_from_questbook)
        ]
        
        results = []
        for source_name, task in sources:
            try:
                result = task.delay()
                results.append((source_name, result))
            except Exception as e:
                logger.error(f"Failed to start {source_name} import: {e}")
                # Continue with other sources
        
        return results
```

---

## Phase 4: Performance & Search Optimization 🚀

**Priority**: Medium-High
**Estimated Time**: 4-5 weeks
**Dependencies**: Phase 3 complete

### 4.1 Elasticsearch Implementation

**Current Issue**: Custom search in `games/search.py` is slow and limited.

**Implementation**:
1. **Install Elasticsearch + django-elasticsearch-dsl**
2. **Define Search Documents**:
   ```python
   from django_elasticsearch_dsl import Document, fields
   
   @registry.register_document
   class GameDocument(Document):
       title = fields.TextField(
           analyzer='russian',
           fields={
               'suggest': fields.CompletionField(),
           }
       )
       description = fields.TextField()
       authors = fields.NestedField(properties={
           'name': fields.TextField(),
       })
       
       class Index:
           name = 'games'
           
       class Django:
           model = Game
   ```

### 4.3 Caching for Events/Jams

**Current Issue**: Events section extremely slow.

**Implementation**:
```python
from django.core.cache import cache
from django.views.decorators.cache import cache_page

@cache_page(60 * 15)  # 15 minutes
def events_list(request):
    return render(request, 'events.html', get_events_data())

def get_events_data():
    cache_key = 'events_data'
    data = cache.get(cache_key)
    if data is None:
        data = expensive_events_query()
        cache.set(cache_key, data, 60 * 15)
    return data
```

---

## Phase 5: Modern Frontend Architecture 🎨

**Priority**: High
**Estimated Time**: 6-8 weeks
**Dependencies**: Phase 1-2 complete

### Current Frontend Issues Analysis

**Major Problems**:
- **Monolithic CSS**: Single 2123-line CSS file with no organization
- **2015-era Material Design**: Outdated design language with bright colors (#ff5431, #512da8)
- **jQuery dependency**: Heavy reliance on jQuery 3.1.1 (2016)
- **No build process**: Raw files served directly
- **No modern CSS features**: No Grid, limited Flexbox, no CSS variables
- **Mixed responsive approach**: Desktop-first with afterthought mobile support

### 5.1 Modern CSS Architecture

**Implementation Strategy**:

1. **Setup Sass/PostCSS with Vite**:
   ```bash
   npm init -y
   npm install -D vite sass postcss autoprefixer
   npm install -D @vitejs/plugin-legacy
   ```

2. **New CSS Architecture**:
   ```scss
   // src/styles/main.scss
   @use 'abstracts' as *;
   @use 'base';
   @use 'components';
   @use 'layout';
   @use 'pages';
   
   // abstracts/_variables.scss
   :root {
     // Modern color palette
     --color-primary: hsl(210, 100%, 50%);
     --color-secondary: hsl(280, 100%, 70%);
     --color-accent: hsl(25, 100%, 60%);
     
     // Semantic colors
     --color-text: hsl(0, 0%, 13%);
     --color-text-light: hsl(0, 0%, 40%);
     --color-background: hsl(0, 0%, 98%);
     --color-surface: hsl(0, 0%, 100%);
     
     // Spacing system
     --space-xs: 0.25rem;
     --space-sm: 0.5rem;
     --space-md: 1rem;
     --space-lg: 1.5rem;
     --space-xl: 2rem;
     --space-2xl: 3rem;
     
     // Typography
     --font-family-base: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
     --font-family-heading: 'Inter', sans-serif;
     --font-size-xs: 0.75rem;
     --font-size-sm: 0.875rem;
     --font-size-base: 1rem;
     --font-size-lg: 1.125rem;
     --font-size-xl: 1.25rem;
     --font-size-2xl: 1.5rem;
     --font-size-3xl: 1.875rem;
     
     // Shadows
     --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
     --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
     --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);
     
     // Border radius
     --radius-sm: 0.25rem;
     --radius-md: 0.375rem;
     --radius-lg: 0.5rem;
     --radius-xl: 0.75rem;
   }
   ```

3. **Component-based CSS**:
   ```scss
   // components/_game-card.scss
   .game-card {
     background: var(--color-surface);
     border-radius: var(--radius-lg);
     box-shadow: var(--shadow-md);
     padding: var(--space-lg);
     transition: transform 0.2s ease, box-shadow 0.2s ease;
     
     &:hover {
       transform: translateY(-2px);
       box-shadow: var(--shadow-lg);
     }
     
     &__title {
       font-size: var(--font-size-xl);
       font-weight: 600;
       color: var(--color-text);
       margin-bottom: var(--space-sm);
     }
     
     &__description {
       color: var(--color-text-light);
       line-height: 1.6;
       margin-bottom: var(--space-md);
     }
     
     &__meta {
       display: flex;
       align-items: center;
       gap: var(--space-sm);
       font-size: var(--font-size-sm);
       color: var(--color-text-light);
     }
   }
   ```

4. **Modern Layout with CSS Grid**:
   ```scss
   // layout/_grid.scss
   .games-grid {
     display: grid;
     grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
     gap: var(--space-lg);
     padding: var(--space-lg);
     
     @media (min-width: 768px) {
       grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
       gap: var(--space-xl);
     }
   }
   
   .game-detail {
     display: grid;
     grid-template-columns: 1fr;
     gap: var(--space-xl);
     
     @media (min-width: 1024px) {
       grid-template-columns: 2fr 1fr;
       grid-template-areas: 
         "content sidebar"
         "comments sidebar";
     }
     
     &__content {
       grid-area: content;
     }
     
     &__sidebar {
       grid-area: sidebar;
     }
     
     &__comments {
       grid-area: comments;
     }
   }
   ```

### 5.2 Modern JavaScript Architecture

**Replace jQuery with Modern JS**:

1. **Vite Configuration**:
   ```javascript
   // vite.config.js
   import { defineConfig } from 'vite';
   import { resolve } from 'path';
   
   export default defineConfig({
     base: '/static/',
     build: {
       outDir: 'dist',
       rollupOptions: {
         input: {
           main: resolve(__dirname, 'src/js/main.js'),
           search: resolve(__dirname, 'src/js/search.js'),
           game: resolve(__dirname, 'src/js/game.js'),
         },
       },
     },
     server: {
       proxy: {
         '/': 'http://localhost:8000',
       },
     },
   });
   ```

2. **Modern JavaScript Structure**:
   ```javascript
   // src/js/main.js
   import './styles/main.scss';
   import { initializeSearch } from './modules/search';
   import { initializeGameInteractions } from './modules/game';
   
   document.addEventListener('DOMContentLoaded', () => {
     initializeSearch();
     initializeGameInteractions();
   });
   
   // src/js/modules/search.js
   export function initializeSearch() {
     const searchInput = document.querySelector('[data-search-input]');
     const searchResults = document.querySelector('[data-search-results]');
     
     if (!searchInput || !searchResults) return;
     
     let debounceTimer;
     
     searchInput.addEventListener('input', (e) => {
       clearTimeout(debounceTimer);
       debounceTimer = setTimeout(() => {
         performSearch(e.target.value, searchResults);
       }, 300);
     });
   }
   
   async function performSearch(query, resultsContainer) {
     if (!query.trim()) {
       resultsContainer.innerHTML = '';
       return;
     }
     
     try {
       const response = await fetch(`/api/search/?q=${encodeURIComponent(query)}`);
       const data = await response.json();
       
       renderSearchResults(data.results, resultsContainer);
     } catch (error) {
       console.error('Search failed:', error);
       resultsContainer.innerHTML = '<p>Search failed. Please try again.</p>';
     }
   }
   
   function renderSearchResults(results, container) {
     if (!results.length) {
       container.innerHTML = '<p>No results found.</p>';
       return;
     }
     
     const html = results.map(game => `
       <div class="search-result">
         <h3><a href="/game/${game.id}/">${escapeHtml(game.title)}</a></h3>
         <p>${escapeHtml(game.description?.substring(0, 150) || '')}...</p>
         <div class="search-result__meta">
           <span>By ${escapeHtml(game.primary_author || 'Unknown')}</span>
           <span>Rating: ${game.rating || 'Not rated'}</span>
         </div>
       </div>
     `).join('');
     
     container.innerHTML = html;
   }
   
   function escapeHtml(text) {
     const div = document.createElement('div');
     div.textContent = text;
     return div.innerHTML;
   }
   ```

3. **TypeScript Support**:
   ```typescript
   // src/js/types/api.ts
   export interface Game {
     id: number;
     title: string;
     description?: string;
     primary_author?: string;
     rating?: number;
     release_date?: string;
   }
   
   export interface SearchResponse {
     results: Game[];
     total: number;
   }
   
   // src/js/modules/api.ts
   import type { SearchResponse } from '../types/api';
   
   export class ApiClient {
     private baseUrl = '/api';
     
     async search(query: string): Promise<SearchResponse> {
       const response = await fetch(`${this.baseUrl}/search/?q=${encodeURIComponent(query)}`);
       if (!response.ok) {
         throw new Error(`Search failed: ${response.statusText}`);
       }
       return response.json();
     }
     
     async getGame(id: number): Promise<Game> {
       const response = await fetch(`${this.baseUrl}/games/${id}/`);
       if (!response.ok) {
         throw new Error(`Failed to fetch game: ${response.statusText}`);
       }
       return response.json();
     }
   }
   ```

### 5.3 Contemporary Design System

**Design Philosophy**:
- **Modern aesthetics**: Clean, minimal design with subtle shadows and rounded corners
- **Improved typography**: Better font choices and hierarchy
- **Consistent spacing**: Systematic spacing scale
- **Accessible colors**: WCAG-compliant color contrast
- **Mobile-first**: Responsive design from the ground up

**Key Design Updates**:

1. **Typography**:
   ```scss
   // Replace Roboto with Inter for better readability
   @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
   
   body {
     font-family: var(--font-family-base);
     font-size: var(--font-size-base);
     line-height: 1.6;
     color: var(--color-text);
   }
   
   h1, h2, h3, h4, h5, h6 {
     font-family: var(--font-family-heading);
     font-weight: 600;
     line-height: 1.2;
     margin-bottom: var(--space-md);
   }
   ```

2. **Color Palette**:
   ```scss
   // Modern, accessible color palette
   :root {
     --color-primary: hsl(210, 100%, 50%);     // Blue
     --color-primary-hover: hsl(210, 100%, 45%);
     --color-secondary: hsl(280, 100%, 70%);   // Purple
     --color-accent: hsl(25, 100%, 60%);       // Orange
     --color-success: hsl(142, 71%, 45%);      // Green
     --color-warning: hsl(38, 92%, 50%);       // Yellow
     --color-error: hsl(0, 84%, 60%);          // Red
     
     // Neutral colors
     --color-gray-50: hsl(0, 0%, 98%);
     --color-gray-100: hsl(0, 0%, 95%);
     --color-gray-200: hsl(0, 0%, 89%);
     --color-gray-300: hsl(0, 0%, 83%);
     --color-gray-400: hsl(0, 0%, 64%);
     --color-gray-500: hsl(0, 0%, 45%);
     --color-gray-600: hsl(0, 0%, 32%);
     --color-gray-700: hsl(0, 0%, 25%);
     --color-gray-800: hsl(0, 0%, 15%);
     --color-gray-900: hsl(0, 0%, 9%);
   }
   ```

3. **Component Library**:
   ```scss
   // Button component
   .btn {
     display: inline-flex;
     align-items: center;
     gap: var(--space-xs);
     padding: var(--space-sm) var(--space-md);
     border: none;
     border-radius: var(--radius-md);
     font-size: var(--font-size-sm);
     font-weight: 500;
     text-decoration: none;
     cursor: pointer;
     transition: all 0.2s ease;
     
     &--primary {
       background: var(--color-primary);
       color: white;
       
       &:hover {
         background: var(--color-primary-hover);
         transform: translateY(-1px);
       }
     }
     
     &--secondary {
       background: var(--color-gray-100);
       color: var(--color-gray-700);
       
       &:hover {
         background: var(--color-gray-200);
       }
     }
     
     &--large {
       padding: var(--space-md) var(--space-lg);
       font-size: var(--font-size-base);
     }
   }
   ```

### 5.4 Mobile-First Responsive Design

**Implementation**:
```scss
// Mobile-first approach
.container {
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 var(--space-md);
  
  @media (min-width: 768px) {
    padding: 0 var(--space-lg);
  }
  
  @media (min-width: 1024px) {
    padding: 0 var(--space-xl);
  }
}

// Responsive navigation
.navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-md);
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-gray-200);
  
  &__menu {
    display: none;
    
    @media (min-width: 768px) {
      display: flex;
      gap: var(--space-lg);
    }
  }
  
  &__mobile-toggle {
    display: block;
    
    @media (min-width: 768px) {
      display: none;
    }
  }
}
```

### 5.5 Build Process Integration

**Django Integration**:
```python
# settings.py
STATICFILES_DIRS = [
    BASE_DIR / "frontend/dist",
]

# For development
if DEBUG:
    INSTALLED_APPS += ['django_vite']
    
    DJANGO_VITE = {
        'default': {
            'dev_mode': True,
            'dev_server_port': 5173,
        }
    }
```

**Template Integration**:
```html
<!-- templates/base.html -->
{% load static %}
{% load django_vite %}

<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}IFDB{% endblock %}</title>
    
    {% if DEBUG %}
        {% vite_hmr_client %}
        {% vite_asset 'src/js/main.js' %}
    {% else %}
        <link rel="stylesheet" href="{% static 'main.css' %}">
    {% endif %}
</head>
<body>
    <div id="app">
        {% block content %}{% endblock %}
    </div>
    
    {% if not DEBUG %}
        <script src="{% static 'main.js' %}"></script>
    {% endif %}
</body>
</html>
```

---

## Phase 6: Feature Cleanup & Enhancement 🧹

**Priority**: Medium
**Estimated Time**: 2-3 weeks
**Dependencies**: All previous phases

### 6.1 Remove "Справка" Section

**Implementation**:
1. Remove URL patterns for help section
2. Remove templates and static files
3. Update navigation menus
4. Add redirect for old URLs to prevent 404s

### 6.2 Enhanced Authors Section

**Current Issue**: Minimalistic author pages.

**Enhancements**:
1. **Rich Author Profiles**:
   - Biography section
   - Profile photos
   - Social media links
   - Game statistics

2. **Author Relationship Mapping**:
   - Collaboration network visualization
   - Related authors suggestions
   - Author influence metrics

---

## Implementation Timeline & Dependencies

**Total Estimated Time**: 22-26 weeks
**Critical Path**: 
1. Phase 1 (Security) must be completed first
2. Phase 5 (Frontend) can be done in parallel with Phase 2-4
3. Phase 6 depends on all previous phases

**Resource Requirements**: 
- Node.js for frontend build tools
- Redis server for Celery
- Elasticsearch cluster  
- Updated Python dependencies
- Comprehensive testing environment

**Frontend-Specific Requirements**:
- Modern browser support (ES2020+)
- CSS Grid and Flexbox support
- Node.js 18+ for build tools
- Sass/PostCSS for CSS preprocessing

This comprehensive plan addresses both the backend modernization and the critical frontend overhaul needed to bring IFDB's visual appearance and user experience up to contemporary standards.