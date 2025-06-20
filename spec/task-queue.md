# Task Queue System Specification

## Overview

The IFDB project implements a custom database-backed task queue system for handling background processing tasks. The system runs asynchronously through the database, using the `TaskQueueElement` model to store and manage queued tasks.

## Architecture

### Core Components

1. **TaskQueueElement Model** - Database table storing task definitions and execution state
2. **Task Queue Manager** (`core/taskqueue.py`) - Core logic for enqueueing and processing tasks
3. **Worker Process** (`manage.py ifdbworker`) - Background daemon that processes queued tasks
4. **Task Implementations** - Specific task functions across the codebase

## TaskQueueElement Model

The central model representing queued tasks with the following key fields:

```python
class TaskQueueElement(models.Model):
    name = models.CharField(max_length=255)           # Human-readable task identifier
    command_json = models.CharField(max_length=512)   # JSON: {module, function, argv, kwarg}
    priority = models.IntegerField(default=100)       # Lower = higher priority
    onfail_json = models.CharField(max_length=512)    # Failure handler function
    retries_left = models.IntegerField(default=3)     # Remaining retry attempts
    retry_minutes = models.IntegerField(default=2000) # Delay between retries
    cron = models.CharField(max_length=32)            # Cron expression for recurring tasks
    
    # Timing fields
    enqueue_time = models.DateTimeField()
    scheduled_time = models.DateTimeField()           # For delayed execution
    start_time = models.DateTimeField()
    finish_time = models.DateTimeField()
    
    # Dependencies
    dependency = models.ForeignKey("self")            # Wait for this task to complete
    
    # Status tracking
    pending = models.BooleanField(default=True)
    success = models.BooleanField(default=False)
    fail = models.BooleanField(default=False)
    log = models.TextField()                          # Execution logs
```

## Task Queue Manager (`core/taskqueue.py`)

### Enqueuing Tasks

**`Enqueue(func, *argv, **kwarg)`**
- Primary function for adding tasks to the queue
- Serializes function references as JSON with module/function names
- Supports optional parameters:
  - `priority`: Task priority (lower = higher priority)
  - `retries`: Number of retry attempts
  - `onfail`: Failure handler function
  - `dependency`: Wait for another task to complete
  - `scheduled_time`: Delayed execution
  - `name`: Human-readable task identifier

**`EnqueueOrGet(func, *argv, name=None, **kwarg)`**
- Prevents duplicate tasks by checking for existing tasks with the same name
- Returns existing task if found, creates new one otherwise

### Task Processing

**`Worker()`**
- Main worker loop that continuously processes tasks
- Task selection logic:
  1. Finds pending tasks without unmet dependencies
  2. Orders by priority (ascending) then enqueue_time
  3. Skips scheduled tasks not yet due for execution
- Execution flow:
  1. Deserializes JSON command into function call
  2. Captures all output and exceptions
  3. Updates task status and logs
  4. Handles retries with exponential backoff
  5. Processes recurring tasks (cron)
  6. Executes failure handlers on permanent failure

### Signal-based Notification
- Worker sleeps when no tasks available
- `SIGUSR1` signal wakes worker immediately after new tasks enqueued
- Prevents unnecessary polling while maintaining responsiveness

## Worker Management

### Starting the Worker
```bash
python manage.py ifdbworker
```

The worker runs as a long-lived daemon process, continuously polling for and executing tasks.

### Process Management
- Worker handles graceful shutdown on `SIGTERM`
- Logs all task execution details
- Supports both foreground and background execution

## Task Implementations

### File Operations (`games/tasks/uploads.py`)

**`CloneFile(id)`**
- Downloads remote files referenced by GameURL records
- Stores files locally in the upload directory
- Updates URL status and file metadata
- Failure handler: `MarkBroken` - marks URLs as broken

**`RecodeGame(game_url_id)`**
- Converts game files to web-playable formats
- Handles formats: `.qst`, `.zip`, `.qsz`
- Creates `InterpretedGameUrl` records for web interpreter
- Supports Quest format detection and conversion

### Game Import (`games/tasks/game_importer.py`)

**`ImportGames(append_urls=False)`**
- Primary game import function
- Fetches games from multiple sources:
  - IFWiki API
  - Apero database  
  - QuestBook database
  - InsteadGames database
- Handles deduplication and URL merging
- Creates/updates Game records
- Posts Discord notifications for new games

**`ForceReimport()`**
- Re-imports all games marked as updateable
- Typically used for bulk data refresh

**`ImportForceUpdateUrls()`**
- Force updates URLs for existing games
- Used for maintenance and corrections

### Feed Processing (`core/feedfetcher.py`)

**`FetchFeeds()`**
- Fetches RSS feeds from IF community sites:
  - IFHub forums
  - forum.ifiction.ru
  - urq.borda.ru 
  - instead-games.ru
- Custom parsing for VK posts and forum formats
- Stores processed items in `FeedCache` model
- Handles duplicate detection and content extraction

## Task Scheduling and Dependencies

### Priority System
- Tasks processed by priority (lower numbers = higher priority)
- Within same priority, FIFO order by enqueue time
- Default priority: 100

### Dependencies
- Tasks can wait for other tasks to complete successfully
- Dependency failures prevent dependent task execution
- Supports complex dependency chains

### Delayed Execution
- Tasks can be scheduled for future execution via `scheduled_time`
- Worker skips tasks not yet due
- Useful for retry delays and scheduled maintenance

### Recurring Tasks (Cron)
- Tasks can specify cron expressions for recurring execution
- After successful completion, new task created with next scheduled time
- Supports standard cron syntax

## Error Handling and Retries

### Retry Logic
- Configurable retry attempts (default: 3)
- Exponential backoff delay between retries (default: 2000 minutes base)
- Failed tasks marked with failure status after exhausting retries

### Failure Handlers
- Optional `onfail` function executed when task permanently fails
- Receives original task and failure context
- Common pattern: mark resources as broken/unavailable

### Logging
- Complete execution logs stored in task record
- Includes stdout, stderr, and exception traces
- Accessible via Django admin interface

## Admin Interface

TaskQueueElement includes comprehensive Django admin integration:

- **List View**: Shows task name, status, timing, retry count
- **Detail View**: Full task parameters, logs, and execution history  
- **Filtering**: By status, priority, task type
- **Actions**: Manual retry, bulk cleanup, status changes

## Maintenance Operations

### Cleanup (`core/management/commands/batchjob.py`)

**`TaskQueueCleanup()`**
- Removes old completed tasks (configurable retention)
- Prevents database bloat from historical tasks

**`RetryFailedJobs()`**
- Resets failed tasks for retry
- Useful for recovering from transient failures

## Usage Patterns

### Typical Enqueuing
```python
from core.taskqueue import Enqueue
from games.tasks.uploads import CloneFile, MarkBroken

# Simple task
Enqueue(CloneFile, url_id)

# With failure handler
Enqueue(CloneFile, url_id, 
        name=f"CloneUrl({url_id})", 
        onfail=MarkBroken)

# High priority with custom retries
Enqueue(ImportGames, 
        priority=50, 
        retries=5, 
        name="ImportGames")
```

### Preventing Duplicates
```python
# Only enqueue if not already pending
task = EnqueueOrGet(RecodeGame, game_url_id,
                   name=f"RecodeGame({game_url_id})")
```

## Performance Characteristics

- **Database-backed**: Persistent across restarts, survives crashes
- **Single Worker**: Simple model, no concurrency concerns
- **Signal Optimization**: Minimal polling overhead
- **JSON Serialization**: Compact task representation
- **Batched Processing**: Efficient database queries

## Limitations and Considerations

1. **Single Worker**: No parallel task execution (by design)
2. **JSON Serialization**: Function arguments must be JSON-serializable
3. **Database Overhead**: All task state persisted in database
4. **Memory Usage**: Large arguments stored in database, not memory-efficient
5. **No Task Result Storage**: Tasks must handle their own result persistence

## Future Enhancements

Potential improvements identified in the codebase:

1. **Worker Pool**: Multiple worker processes for CPU-intensive tasks
2. **Task Result Storage**: Built-in result caching and retrieval
3. **Dead Letter Queue**: Separate queue for permanently failed tasks
4. **Monitoring Dashboard**: Web-based task monitoring beyond Django admin
5. **Task Chaining**: Built-in support for task workflows and pipelines

---

# Migration Plan: Custom Task Queue → Celery+Redis

This document outlines a simplified migration strategy from the current custom database-backed task queue system to a standard Celery+Redis implementation.

## Migration Overview

Since the task queue will be empty at migration time, this is a straightforward replacement:

1. **Coding Phase**: Implement Celery tasks and configuration
2. **Deployment Phase**: Install Redis, deploy code, switch services

The migration involves only 4 tasks total:
- **Periodic**: `ImportGames`, `FetchFeeds` (cron-based)
- **Queue-based**: `CloneFile`, `RecodeGame` (event-driven)

Note: `ForceReimport` and `ImportForceUpdateUrls` are CLI-only and don't use the task queue.

## Part 1: Coding Changes (Pre-RabbitMQ Installation)

### 1.1 Dependencies and Requirements

**Update `requirements.txt`:**
```python
# Add these dependencies
celery==5.3.4
django-celery-beat==2.5.0  # For cron/scheduled tasks
django-celery-results==2.5.0  # For result storage
redis==5.0.1  # Redis client for Python
```


### 1.2 Celery Configuration

**Create `ifdb/celery.py`:**
```python
import os
from celery import Celery
from django.conf import settings

# Set default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ifdb.settings')

app = Celery('ifdb')

# Configure Celery using Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

```


### 1.3 Django Settings Integration

**Add to `ifdb/settings.py`:**
```python
import os

# Celery Configuration
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')

# Task configuration
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Task routing and execution
CELERY_TASK_ROUTES = {
    'games.tasks.*': {'queue': 'games'},
    'core.tasks.*': {'queue': 'core'},
}

# Worker configuration
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000

# Retry configuration
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_DEFAULT_RETRY_DELAY = 60
CELERY_TASK_MAX_RETRIES = 3

# Beat scheduler for cron tasks
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Result backend configuration
CELERY_RESULT_EXPIRES = 3600  # 1 hour
CELERY_RESULT_EXTENDED = True

# Error handling
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_TASK_TRACK_STARTED = True

# Add to INSTALLED_APPS
INSTALLED_APPS += [
    'django_celery_beat',
    'django_celery_results',
]
```

### 1.4 Task Conversion

**Convert existing task functions to Celery tasks:**

**Update `games/tasks/uploads.py`:**
```python
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def clone_file(self, url_id):
    """Celery version of CloneFile task"""
    try:
        return CloneFile(url_id)
    except Exception as exc:
        logger.error(f'CloneFile failed for URL {url_id}: {exc}')
        # Mark as broken on final failure
        if self.request.retries == self.max_retries:
            try:
                MarkBroken(None, {'url_id': url_id, 'error': str(exc)})
            except Exception as mark_exc:
                logger.error(f'MarkBroken failed: {mark_exc}')
        raise self.retry(exc=exc)

@shared_task(bind=True, max_retries=3)
def recode_game(self, game_url_id):
    """Celery version of RecodeGame task"""
    try:
        return RecodeGame(game_url_id)
    except Exception as exc:
        logger.error(f'RecodeGame failed for GameURL {game_url_id}: {exc}')
        raise self.retry(exc=exc)

# Keep original functions unchanged
def CloneFile(url_id):
    """Original CloneFile implementation"""
    # ... existing implementation ...

def RecodeGame(game_url_id):
    """Original RecodeGame implementation"""
    # ... existing implementation ...
```

**Update `games/tasks/game_importer.py`:**
```python
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

@shared_task(bind=True)
def import_games(self, append_urls=False):
    """Celery version of ImportGames - used for periodic execution"""
    try:
        return ImportGames(append_urls=append_urls)
    except Exception as exc:
        logger.error(f'ImportGames failed: {exc}')
        raise self.retry(exc=exc)

# Keep original function unchanged
def ImportGames(append_urls=False):
    """Original ImportGames implementation"""
    # ... existing implementation ...

# ForceReimport and ImportForceUpdateUrls remain CLI-only, no Celery tasks needed
```

**Update `core/feedfetcher.py`:**
```python
from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

@shared_task(bind=True)
def fetch_feeds(self):
    """Celery version of FetchFeeds - used for periodic execution"""
    try:
        return FetchFeeds()
    except Exception as exc:
        logger.error(f'FetchFeeds failed: {exc}')
        raise self.retry(exc=exc)

# Keep original function unchanged
def FetchFeeds():
    """Original FetchFeeds implementation"""
    # ... existing implementation ...
```

### 1.5 Update Code That Calls Tasks

**Update files that call `Enqueue()` to use Celery tasks directly:**

**Update `games/tools.py`:**
```python
# Find the CloneFile calls and replace:
# Old:
from core.taskqueue import Enqueue
from games.tasks.uploads import CloneFile, MarkBroken
Enqueue(CloneFile, u.id, name="CloneUrl(%d)" % u.id, onfail=MarkBroken)

# New:
from games.tasks.uploads import clone_file
clone_file.delay(u.id)
```

**Update `games/updater.py`:**
```python
# Find the RecodeGame calls and replace:
# Old:
from core.taskqueue import Enqueue
from games.tasks.uploads import RecodeGame
Enqueue(RecodeGame, game_url.id, name="RecodeGame(%d)" % game_url.id)

# New:
from games.tasks.uploads import recode_game
recode_game.delay(game_url.id)
```

### 1.6 Set Up Periodic Tasks

**Create `core/management/commands/setup_periodic_tasks.py`:**
```python
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, CrontabSchedule

class Command(BaseCommand):
    help = 'Set up periodic tasks in Celery Beat'
    
    def handle(self, *args, **options):
        # Set up ImportGames periodic task (adjust cron as needed)
        import_schedule, created = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='*/6',  # Every 6 hours
            day_of_month='*',
            month_of_year='*',
            day_of_week='*',
        )
        
        PeriodicTask.objects.get_or_create(
            name='Import Games',
            defaults={
                'task': 'games.tasks.game_importer.import_games',
                'crontab': import_schedule,
                'enabled': True,
            }
        )
        
        # Set up FetchFeeds periodic task (adjust cron as needed)
        feeds_schedule, created = CrontabSchedule.objects.get_or_create(
            minute='*/30',  # Every 30 minutes
            hour='*',
            day_of_month='*',
            month_of_year='*',
            day_of_week='*',
        )
        
        PeriodicTask.objects.get_or_create(
            name='Fetch Feeds',
            defaults={
                'task': 'core.feedfetcher.fetch_feeds',
                'crontab': feeds_schedule,
                'enabled': True,
            }
        )
        
        self.stdout.write("Periodic tasks set up successfully")
```

### 1.7 Monitoring and Management

**Create `core/management/commands/celery_status.py`:**
```python
from django.core.management.base import BaseCommand
from celery import current_app
from django.conf import settings

class Command(BaseCommand):
    help = 'Check Celery worker status and queue information'
    
    def handle(self, *args, **options):
        try:
            # Check broker connection
            with current_app.connection() as conn:
                conn.ensure_connection(max_retries=3)
            self.stdout.write("✓ Broker connection: OK")
            
            # Get active tasks
            inspect = current_app.control.inspect()
            active_tasks = inspect.active()
            if active_tasks:
                total_active = sum(len(tasks) for tasks in active_tasks.values())
                self.stdout.write(f"✓ Active tasks: {total_active}")
            else:
                self.stdout.write("✓ No active tasks")
                
            # Show broker configuration
            if hasattr(settings, 'CELERY_BROKER_URL'):
                self.stdout.write(f"✓ Broker URL: {settings.CELERY_BROKER_URL}")
                
        except Exception as e:
            self.stdout.write(f"✗ Celery status check failed: {e}")
```


## Part 2: Deployment Phase

### 2.1 Redis Installation and Configuration

**Install Redis on Debian production server:**
```bash
# Update package lists
sudo apt-get update

# Install Redis server
sudo apt-get install -y redis-server

# Enable and start Redis service
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Test Redis installation
redis-cli ping  # Should return PONG
```

**Configure Redis:**
```bash
# Create Redis configuration file
sudo tee /etc/redis/redis.conf << EOF
# Network settings
bind 127.0.0.1
port 6379

# Security settings
requirepass <secure_password>

# Memory and persistence settings
maxmemory 256mb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000

# Database settings
databases 16

# Logging
loglevel notice
logfile /var/log/redis/redis-server.log

# Performance settings
tcp-keepalive 300
timeout 0
EOF

# Set proper permissions
sudo chown redis:redis /etc/redis/redis.conf
sudo chmod 640 /etc/redis/redis.conf

# Restart Redis to apply configuration
sudo systemctl restart redis-server
```

### 2.2 Environment Configuration

**Update production environment variables:**
```bash
# Add to /home/ifdb/configs/environment or .env
CELERY_BROKER_URL=redis://:secure_password@localhost:6379/0
CELERY_RESULT_BACKEND=redis://:secure_password@localhost:6379/1
```

### 2.3 Systemd Service Configuration

**Create Celery worker service `/etc/systemd/system/ifdb-celery-worker.service`:**
```ini
[Unit]
Description=IFDB Celery Worker
After=network.target redis-server.service postgresql.service
Requires=redis-server.service postgresql.service

[Service]
Type=exec
User=ifdb
Group=ifdb
EnvironmentFile=/home/ifdb/configs/environment
WorkingDirectory=/home/ifdb/ifdb
ExecStart=/home/ifdb/ifdb/venv/bin/celery -A ifdb worker --loglevel=info --concurrency=2 --queues=high,normal,low,games,core
ExecReload=/bin/kill -s HUP $MAINPID
KillSignal=SIGTERM
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ifdb-celery-worker

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Create Celery beat service `/etc/systemd/system/ifdb-celery-beat.service`:**
```ini
[Unit]
Description=IFDB Celery Beat Scheduler
After=network.target redis-server.service postgresql.service
Requires=redis-server.service postgresql.service

[Service]
Type=exec
User=ifdb
Group=ifdb
EnvironmentFile=/home/ifdb/configs/environment
WorkingDirectory=/home/ifdb/ifdb
ExecStart=/home/ifdb/ifdb/venv/bin/celery -A ifdb beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ifdb-celery-beat

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Create Celery monitoring service `/etc/systemd/system/ifdb-celery-flower.service`:**
```ini
[Unit]
Description=IFDB Celery Flower Monitoring
After=network.target redis-server.service
Requires=redis-server.service

[Service]
Type=exec
User=ifdb
Group=ifdb
EnvironmentFile=/home/ifdb/configs/environment
WorkingDirectory=/home/ifdb/ifdb
ExecStart=/home/ifdb/ifdb/venv/bin/celery -A ifdb flower --port=5555 --url_prefix=flower
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ifdb-celery-flower

[Install]
WantedBy=multi-user.target
```

### 2.4 Deployment Steps

**Step 1: Deploy code changes**
```bash
# On production server
cd /home/ifdb/ifdb
git pull origin master

# Install new dependencies
./venv/bin/pip install -r requirements.txt

# Run database migrations for Celery tables
./manage.py migrate django_celery_beat
./manage.py migrate django_celery_results

# Set up Celery beat tasks
./manage.py setup_celery_beat
```

**Step 2: Test Celery connection**
```bash
# Test Celery broker connection
./manage.py celery_status

# Test task execution
./manage.py shell -c "from games.tasks.uploads import clone_file; print(clone_file.delay(1))"
```

**Step 3: Set up periodic tasks**
```bash
# Create periodic tasks for ImportGames and FetchFeeds
./manage.py setup_periodic_tasks
```

**Step 4: Start Celery services**
```bash
# Enable and start Celery services
sudo systemctl enable ifdb-celery-worker
sudo systemctl enable ifdb-celery-beat
sudo systemctl enable ifdb-celery-flower

sudo systemctl start ifdb-celery-worker
sudo systemctl start ifdb-celery-beat
sudo systemctl start ifdb-celery-flower

# Check service status
sudo systemctl status ifdb-celery-worker
sudo systemctl status ifdb-celery-beat
```

**Step 5: Monitor and validate**
```bash
# Monitor Celery logs
sudo journalctl -u ifdb-celery-worker -f

# Check task processing
./manage.py celery_status

# Access Flower monitoring (if enabled)
# http://your-server:5555/flower
```

**Step 6: Stop legacy worker**
```bash
# Stop the old ifdbworker process
# (Kill the process or stop systemd service if running as one)
pkill -f "manage.py ifdbworker"

# Verify Celery is handling tasks
./manage.py celery_status
```

### 2.5 Rollback Plan

**If issues arise, rollback steps:**
```bash
# Stop Celery services
sudo systemctl stop ifdb-celery-worker
sudo systemctl stop ifdb-celery-beat
sudo systemctl stop ifdb-celery-flower

# Revert code changes
git checkout <previous_commit>

# Restart legacy worker
./manage.py ifdbworker &
```

### 2.6 Monitoring and Maintenance

**Set up monitoring scripts:**

**Create `/home/ifdb/scripts/check_celery.sh`:**
```bash
#!/bin/bash
# Check Celery worker health

# Check if workers are running
WORKERS=$(systemctl is-active ifdb-celery-worker)
if [ "$WORKERS" != "active" ]; then
    echo "CRITICAL: Celery worker not running"
    exit 2
fi

# Check if Redis is running
REDIS=$(systemctl is-active redis-server)
if [ "$REDIS" != "active" ]; then
    echo "CRITICAL: Redis not running"
    exit 2
fi

# Check queue sizes
cd /home/ifdb/ifdb
QUEUE_CHECK=$(./manage.py celery_status 2>&1)
if [ $? -ne 0 ]; then
    echo "WARNING: Celery status check failed: $QUEUE_CHECK"
    exit 1
fi

echo "OK: Celery system healthy"

# Check Redis connection
REDIS_PING=$(redis-cli -a "$REDIS_PASSWORD" ping 2>/dev/null)
if [ "$REDIS_PING" != "PONG" ]; then
    echo "WARNING: Redis ping failed"
    exit 1
fi
exit 0
```

**Add to crontab for monitoring:**
```bash
# Monitor Celery health every 5 minutes
*/5 * * * * /home/ifdb/scripts/check_celery.sh

# Clean up old Celery results weekly
0 2 * * 0 cd /home/ifdb/ifdb && ./manage.py celery_cleanup_results --days=7
```

### 2.7 Performance Tuning

**Redis tuning for production:**
```bash
# Add to /etc/redis/redis.conf
# Memory optimization
maxmemory 512mb
maxmemory-policy allkeys-lru

# Network settings
tcp-backlog 511
tcp-keepalive 300
timeout 0

# Performance settings
hash-max-ziplist-entries 512
hash-max-ziplist-value 64
list-max-ziplist-size -2
list-compress-depth 0
set-max-intset-entries 512
zset-max-ziplist-entries 128
zset-max-ziplist-value 64

# Persistence settings (adjust based on needs)
save 900 1
save 300 10
save 60 10000
stop-writes-on-bgsave-error yes
```

**Celery worker optimization:**
```bash
# Update worker service for better performance
ExecStart=/home/ifdb/ifdb/venv/bin/celery -A ifdb worker \
  --loglevel=info \
  --concurrency=4 \
  --prefetch-multiplier=1 \
  --max-tasks-per-child=1000 \
  --queues=high,normal,low,games,core \
  --pool=prefork
```

## Migration Timeline

**Day 1-2: Code Preparation**
- Implement Celery configuration and task conversion
- Update Enqueue() calls to use Celery tasks directly
- Test in development environment

**Day 3: Deployment Preparation**
- Set up Redis on staging environment
- Test full migration process on staging
- Prepare monitoring and rollback procedures

**Day 4: Production Migration**
- Install and configure Redis
- Deploy code changes
- Switch from ifdbworker to Celery services
- Set up periodic tasks

**Day 5: Validation and Cleanup**
- Monitor system performance and stability
- Clean up legacy task queue system (optional)

## Benefits of Migration

1. **Scalability**: Support for multiple workers and distributed processing
2. **Reliability**: Redis persistence with high performance and low latency
3. **Monitoring**: Rich ecosystem of monitoring tools (Flower, Redis monitoring)
4. **Community Support**: Large community and extensive documentation
5. **Feature Rich**: Advanced routing, retries, rate limiting, and scheduling
6. **Standard Solution**: Industry-standard approach with simpler setup than RabbitMQ
7. **Performance**: Redis provides excellent performance for task queuing with lower resource usage
8. **Simplicity**: Fewer moving parts and easier configuration than RabbitMQ

## Post-Migration Cleanup

**Create `core/management/commands/remove_legacy_queue.py`:**
```python
from django.core.management.base import BaseCommand
from django.db import connection
import os

class Command(BaseCommand):
    help = 'Remove legacy task queue system after successful Celery migration'
    
    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true',
                          help='Actually perform the cleanup (required)')
    
    def handle(self, *args, **options):
        if not options['confirm']:
            self.stdout.write("Add --confirm flag to actually perform cleanup")
            return
            
        # Drop TaskQueueElement table
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS core_taskqueueelement CASCADE")
        self.stdout.write("Dropped TaskQueueElement table")
        
        # List files to remove manually
        files_to_remove = [
            'core/taskqueue.py',
            'core/management/commands/ifdbworker.py',
            'core/management/commands/remove_legacy_queue.py',  # This file itself
        ]
        
        self.stdout.write("\nManually remove these files:")
        for file_path in files_to_remove:
            self.stdout.write(f"  rm {file_path}")
            
        # Remove model from core/models.py
        self.stdout.write("\nRemove TaskQueueElement from core/models.py:")
        self.stdout.write("  - Delete the TaskQueueElement class definition")
        self.stdout.write("  - Remove it from __all__ if present")
        self.stdout.write("  - Remove from core/admin.py if registered")
        
        # Create a migration to remove the model
        self.stdout.write("\nCreate Django migration:")
        self.stdout.write("  python manage.py makemigrations core --empty")
        self.stdout.write("  # Edit migration to remove TaskQueueElement model")
        self.stdout.write("  python manage.py migrate")
        
        self.stdout.write("\n✓ Legacy task queue cleanup complete")
```

After successful migration and validation, run:

```bash
# Verify Celery is working for at least 24-48 hours
./manage.py celery_status

# Then clean up legacy system
./manage.py remove_legacy_queue --confirm

# Remove the files listed by the command
rm core/taskqueue.py
rm core/management/commands/ifdbworker.py  
rm core/management/commands/remove_legacy_queue.py

# Edit core/models.py to remove TaskQueueElement class
# Edit core/admin.py to remove TaskQueueElement admin registration

# Create migration to remove model from database schema
python manage.py makemigrations core --empty
# Edit the migration file to add: operations = [migrations.DeleteModel(name='TaskQueueElement')]
python manage.py migrate
```

## Additional Cleanup Steps

1. **Remove from core/models.py:**
```python
# Delete this entire class:
class TaskQueueElement(models.Model):
    # ... entire class definition ...
```

2. **Remove from core/admin.py:**
```python
# Delete TaskQueueElement admin registration if present
```

3. **Update documentation:**
   - Update deployment procedures
   - Update developer documentation
   - Remove task queue references from README/docs

4. **Optimize Celery configuration** based on production usage patterns

This simplified migration plan provides a direct path from the custom task queue system to a production-ready Celery+RabbitMQ implementation with minimal complexity and risk.