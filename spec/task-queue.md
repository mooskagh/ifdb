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

# Migration Plan: Custom Task Queue → Raw Redis

This document outlines a simplified migration strategy from the current custom database-backed task queue system to a raw Redis implementation using Python's redis library.

## Migration Overview

Since the task queue will be empty at migration time, this is a straightforward replacement with 3 phases:

1. **Prepare Production System**: Install Redis and configure environment without affecting running service
2. **Implement Changes**: Create new Redis-based task queue implementation
3. **Deploy Changes**: Switch from database-backed to Redis-backed task queue

The migration involves only 4 tasks total:
- **Periodic**: `ImportGames`, `FetchFeeds` (cron-based)
- **Queue-based**: `CloneFile`, `RecodeGame` (event-driven)

Note: `ForceReimport` and `ImportForceUpdateUrls` are CLI-only and don't use the task queue.

## Part 1: Prepare Production System

### 1.1 Redis Installation and Configuration

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

### 1.2 Environment Configuration

**Update production environment variables:**
```bash
# Add to /home/ifdb/configs/environment or .env
REDIS_URL=redis://:secure_password@localhost:6379/0
```

### 1.3 Create User Account (if needed)

```bash
# Redis typically runs as redis user (created during installation)
# No additional user setup needed for Redis
```

## Part 2: Implement Changes

### 2.1 Dependencies and Requirements

**Update `requirements.txt`:**
```python
# Add these dependencies
redis==5.0.1  # Redis client for Python
croniter==1.4.1  # For cron expression parsing
```


### 2.2 Redis Task Queue Implementation

**Create `core/redis_taskqueue.py`:**
```python
import json
import time
import logging
import signal
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable
import redis
from django.conf import settings
from django.utils import timezone
from croniter import croniter

logger = logging.getLogger(__name__)

class RedisTaskQueue:
    def __init__(self):
        self.redis_client = redis.from_url(
            getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0')
        )
        self.task_queue_key = 'ifdb:task_queue'
        self.task_data_key = 'ifdb:task_data'
        self.running = False
        
    def enqueue(self, func: Callable, *args, priority: int = 100, 
                retries: int = 3, onfail: Optional[Callable] = None,
                dependency: Optional[str] = None, scheduled_time: Optional[datetime] = None,
                name: Optional[str] = None, cron: Optional[str] = None, **kwargs):
        """Enqueue a task for execution"""
        
        task_id = f"{func.__module__}.{func.__name__}:{int(time.time()*1000000)}"
        if name:
            task_id = f"{name}:{task_id}"
            
        task_data = {
            'id': task_id,
            'name': name or f"{func.__module__}.{func.__name__}",
            'module': func.__module__,
            'function': func.__name__,
            'args': args,
            'kwargs': kwargs,
            'priority': priority,
            'retries_left': retries,
            'retry_minutes': 2000,
            'cron': cron,
            'enqueue_time': timezone.now().isoformat(),
            'scheduled_time': scheduled_time.isoformat() if scheduled_time else None,
            'dependency': dependency,
            'onfail_module': onfail.__module__ if onfail else None,
            'onfail_function': onfail.__name__ if onfail else None,
            'pending': True,
            'success': False,
            'fail': False,
            'log': ''
        }
        
        # Store task data
        self.redis_client.hset(self.task_data_key, task_id, json.dumps(task_data))
        
        # Add to priority queue (score is priority, then timestamp for FIFO within priority)
        score = priority * 1000000 + int(time.time())
        self.redis_client.zadd(self.task_queue_key, {task_id: score})
        
        return task_id
        
    def enqueue_or_get(self, func: Callable, *args, name: Optional[str] = None, **kwargs):
        """Enqueue task only if not already pending with same name"""
        if name:
            # Check for existing task with same name
            existing_tasks = self.redis_client.hgetall(self.task_data_key)
            for task_id, task_json in existing_tasks.items():
                task_data = json.loads(task_json)
                if task_data.get('name') == name and task_data.get('pending'):
                    return task_id.decode()
                    
        return self.enqueue(func, *args, name=name, **kwargs)
        
    def get_next_task(self) -> Optional[Dict[str, Any]]:
        """Get the next task ready for execution"""
        
        # Get all pending tasks ordered by priority
        task_ids = self.redis_client.zrange(self.task_queue_key, 0, -1)
        
        for task_id in task_ids:
            task_json = self.redis_client.hget(self.task_data_key, task_id)
            if not task_json:
                # Clean up orphaned queue entry
                self.redis_client.zrem(self.task_queue_key, task_id)
                continue
                
            task_data = json.loads(task_json)
            
            # Skip non-pending tasks
            if not task_data.get('pending'):
                self.redis_client.zrem(self.task_queue_key, task_id)
                continue
                
            # Check if scheduled time has passed
            if task_data.get('scheduled_time'):
                scheduled = datetime.fromisoformat(task_data['scheduled_time'])
                if timezone.now() < scheduled:
                    continue
                    
            # Check dependencies
            if task_data.get('dependency'):
                dep_json = self.redis_client.hget(self.task_data_key, task_data['dependency'])
                if dep_json:
                    dep_data = json.loads(dep_json)
                    if not dep_data.get('success'):
                        continue  # Dependency not completed
                        
            return task_data
            
        return None
        
    def execute_task(self, task_data: Dict[str, Any]) -> bool:
        """Execute a single task"""
        task_id = task_data['id']
        
        try:
            # Import and execute function
            module = __import__(task_data['module'], fromlist=[task_data['function']])
            func = getattr(module, task_data['function'])
            
            # Update task as started
            task_data['start_time'] = timezone.now().isoformat()
            task_data['log'] += f"Started at {task_data['start_time']}\n"
            self.redis_client.hset(self.task_data_key, task_id, json.dumps(task_data))
            
            # Execute function
            result = func(*task_data['args'], **task_data['kwargs'])
            
            # Mark as successful
            task_data['success'] = True
            task_data['pending'] = False
            task_data['finish_time'] = timezone.now().isoformat()
            task_data['log'] += f"Completed successfully at {task_data['finish_time']}\n"
            
            # Handle cron tasks
            if task_data.get('cron'):
                cron = croniter(task_data['cron'], timezone.now())
                next_run = cron.get_next(datetime)
                self.enqueue(
                    func, *task_data['args'],
                    name=task_data['name'],
                    cron=task_data['cron'],
                    scheduled_time=next_run,
                    **task_data['kwargs']
                )
                
            return True
            
        except Exception as e:
            logger.exception(f"Task {task_id} failed: {e}")
            
            task_data['retries_left'] -= 1
            task_data['log'] += f"Failed: {str(e)}\n"
            
            if task_data['retries_left'] > 0:
                # Schedule retry
                retry_time = timezone.now() + timedelta(minutes=task_data['retry_minutes'])
                task_data['scheduled_time'] = retry_time.isoformat()
                task_data['log'] += f"Retrying at {task_data['scheduled_time']}\n"
            else:
                # Mark as failed
                task_data['fail'] = True
                task_data['pending'] = False
                task_data['finish_time'] = timezone.now().isoformat()
                
                # Execute failure handler
                if task_data.get('onfail_module') and task_data.get('onfail_function'):
                    try:
                        onfail_module = __import__(task_data['onfail_module'], 
                                                 fromlist=[task_data['onfail_function']])
                        onfail_func = getattr(onfail_module, task_data['onfail_function'])
                        onfail_func(None, {'error': str(e), **task_data})
                    except Exception as onfail_e:
                        logger.exception(f"Failure handler failed: {onfail_e}")
                        
            return False
            
        finally:
            # Update task data
            self.redis_client.hset(self.task_data_key, task_id, json.dumps(task_data))
            
            # Remove from queue if no longer pending
            if not task_data.get('pending'):
                self.redis_client.zrem(self.task_queue_key, task_id)
                
    def worker(self):
        """Main worker loop"""
        self.running = True
        
        def signal_handler(signum, frame):
            logger.info("Received shutdown signal")
            self.running = False
            
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        logger.info("Redis task worker started")
        
        while self.running:
            try:
                task_data = self.get_next_task()
                if task_data:
                    logger.info(f"Executing task: {task_data['name']}")
                    self.execute_task(task_data)
                else:
                    # No tasks available, sleep briefly
                    time.sleep(1)
                    
            except Exception as e:
                logger.exception(f"Worker error: {e}")
                time.sleep(5)
                
        logger.info("Redis task worker stopped")

# Global instance
task_queue = RedisTaskQueue()

# Convenience functions matching original API
def Enqueue(func, *args, **kwargs):
    return task_queue.enqueue(func, *args, **kwargs)
    
def EnqueueOrGet(func, *args, **kwargs):
    return task_queue.enqueue_or_get(func, *args, **kwargs)
    
def Worker():
    return task_queue.worker()
```


### 2.3 Django Settings Integration

**Add to `ifdb/settings.py`:**
```python
import os

# Redis Configuration
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
```

### 2.4 Update Existing Task Queue

**Update `core/taskqueue.py` to use Redis backend:**
```python
# Replace the entire file with:
from .redis_taskqueue import Enqueue, EnqueueOrGet, Worker

# Re-export for backward compatibility
__all__ = ['Enqueue', 'EnqueueOrGet', 'Worker']
```

**No changes needed to existing task functions** - they will continue to work as-is since we're maintaining the same API.

### 2.5 No Code Changes Required

**No changes needed to existing code** - all existing `Enqueue()` calls will continue to work exactly as before since we're maintaining the same API in `core/taskqueue.py`.

### 2.6 Set Up Periodic Tasks

**Create `core/management/commands/setup_periodic_tasks.py`:**
```python
from django.core.management.base import BaseCommand
from core.redis_taskqueue import task_queue
from games.tasks.game_importer import ImportGames
from core.feedfetcher import FetchFeeds

class Command(BaseCommand):
    help = 'Set up periodic tasks in Redis task queue'
    
    def handle(self, *args, **options):
        # Set up ImportGames periodic task (every 6 hours)
        task_queue.enqueue(
            ImportGames,
            name='ImportGames',
            cron='0 */6 * * *',
            priority=50
        )
        
        # Set up FetchFeeds periodic task (every 30 minutes)
        task_queue.enqueue(
            FetchFeeds,
            name='FetchFeeds', 
            cron='*/30 * * * *',
            priority=75
        )
        
        self.stdout.write("Periodic tasks set up successfully")
```

### 2.7 Monitoring and Management

**Create `core/management/commands/redis_queue_status.py`:**
```python
from django.core.management.base import BaseCommand
from core.redis_taskqueue import task_queue
import json

class Command(BaseCommand):
    help = 'Check Redis task queue status and information'
    
    def handle(self, *args, **options):
        try:
            # Check Redis connection
            task_queue.redis_client.ping()
            self.stdout.write("✓ Redis connection: OK")
            
            # Get queue information
            queue_size = task_queue.redis_client.zcard(task_queue.task_queue_key)
            self.stdout.write(f"✓ Tasks in queue: {queue_size}")
            
            # Get task data count
            data_size = task_queue.redis_client.hlen(task_queue.task_data_key)
            self.stdout.write(f"✓ Task data entries: {data_size}")
            
            # Show recent tasks
            if queue_size > 0:
                recent_tasks = task_queue.redis_client.zrange(
                    task_queue.task_queue_key, 0, 4, withscores=True
                )
                self.stdout.write("\nNext 5 tasks in queue:")
                for task_id, score in recent_tasks:
                    task_json = task_queue.redis_client.hget(
                        task_queue.task_data_key, task_id
                    )
                    if task_json:
                        task_data = json.loads(task_json)
                        self.stdout.write(
                            f"  - {task_data['name']} (priority: {task_data['priority']})"
                        )
                        
        except Exception as e:
            self.stdout.write(f"✗ Redis queue status check failed: {e}")
```


## Part 3: Deploy Changes

### 3.1 Systemd Service Configuration

**Update existing worker service `/etc/systemd/system/ifdb-worker.service`:**
```ini
[Unit]
Description=IFDB Redis Task Queue Worker
After=network.target redis-server.service postgresql.service
Requires=redis-server.service postgresql.service

[Service]
Type=exec
User=ifdb
Group=ifdb
EnvironmentFile=/home/ifdb/configs/environment
WorkingDirectory=/home/ifdb/ifdb
ExecStart=/home/ifdb/ifdb/venv/bin/python manage.py ifdbworker
ExecReload=/bin/kill -s HUP $MAINPID
KillSignal=SIGTERM
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ifdb-worker

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 3.2 Deployment Steps

**Step 1: Deploy code changes**
```bash
# On production server
cd /home/ifdb/ifdb
git pull origin master

# Install new dependencies
./venv/bin/pip install -r requirements.txt

# Set up periodic tasks
./manage.py setup_periodic_tasks
```

**Step 2: Test Redis connection**
```bash
# Test Redis connection and queue status
./manage.py redis_queue_status
```

**Step 3: Restart worker service**
```bash
# Restart the existing worker service (it will now use Redis)
sudo systemctl restart ifdb-worker

# Check service status
sudo systemctl status ifdb-worker
```

**Step 4: Monitor and validate**
```bash
# Monitor worker logs
sudo journalctl -u ifdb-worker -f

# Check queue status
./manage.py redis_queue_status
```

### 3.3 Rollback Plan

**If issues arise, rollback steps:**
```bash
# Revert code changes
git checkout <previous_commit>

# Restart worker service (will use database backend again)
sudo systemctl restart ifdb-worker
```

### 3.4 Monitoring and Maintenance

**Set up monitoring scripts:**

**Create `/home/ifdb/scripts/check_redis_queue.sh`:**
```bash
#!/bin/bash
# Check Redis task queue health

# Check if worker is running
WORKER=$(systemctl is-active ifdb-worker)
if [ "$WORKER" != "active" ]; then
    echo "CRITICAL: Task queue worker not running"
    exit 2
fi

# Check if Redis is running
REDIS=$(systemctl is-active redis-server)
if [ "$REDIS" != "active" ]; then
    echo "CRITICAL: Redis not running"
    exit 2
fi

# Check queue status
cd /home/ifdb/ifdb
QUEUE_CHECK=$(./manage.py redis_queue_status 2>&1)
if [ $? -ne 0 ]; then
    echo "WARNING: Redis queue status check failed: $QUEUE_CHECK"
    exit 1
fi

echo "OK: Redis task queue system healthy"

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
# Monitor task queue health every 5 minutes
*/5 * * * * /home/ifdb/scripts/check_redis_queue.sh

# Clean up old task data weekly
0 2 * * 0 cd /home/ifdb/ifdb && ./manage.py cleanup_task_data --days=7
```

### 3.5 Performance Tuning

**Redis tuning for production:**
```bash
# Add to /etc/redis/redis.conf
# Memory optimization
maxmemory 256mb
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

**No worker optimization needed** - the existing single-worker model is maintained.

## Migration Timeline

**Day 1: Production System Preparation**
- Install and configure Redis on production server
- Update environment configuration
- Test Redis connectivity

**Day 2-3: Code Implementation**
- Implement Celery configuration and task conversion
- Update Enqueue() calls to use Celery tasks directly
- Test in development environment

**Day 4: Deployment**
- Deploy code changes with requirements.txt updates
- Set up systemd services
- Switch from ifdbworker to Celery services
- Set up periodic tasks

**Day 5: Validation and Cleanup**
- Monitor system performance and stability
- Clean up legacy task queue system (optional)

## Benefits of Migration

1. **Performance**: Redis provides excellent performance with lower latency than database queries
2. **Reliability**: Redis persistence ensures tasks survive restarts while being faster than database storage
3. **Simplicity**: Direct Redis API usage - no complex framework overhead
4. **Memory Efficiency**: Tasks stored efficiently in Redis memory with optional persistence
5. **Monitoring**: Simple Redis monitoring tools and direct inspection of queues
6. **Compatibility**: Maintains exact same API - no code changes required
7. **Resource Usage**: Lower memory and CPU overhead compared to database polling
8. **Scalability**: Easier to scale Redis than database for task storage

## Post-Migration Cleanup

**Create `core/management/commands/cleanup_task_data.py`:**
```python
from django.core.management.base import BaseCommand
from core.redis_taskqueue import task_queue
import json
from datetime import datetime, timedelta
from django.utils import timezone

class Command(BaseCommand):
    help = 'Clean up old completed task data from Redis'
    
    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7,
                          help='Remove task data older than N days (default: 7)')
        parser.add_argument('--dry-run', action='store_true',
                          help='Show what would be cleaned up without actually doing it')
    
    def handle(self, *args, **options):
        cutoff_date = timezone.now() - timedelta(days=options['days'])
        
        # Get all task data
        all_tasks = task_queue.redis_client.hgetall(task_queue.task_data_key)
        
        cleanup_count = 0
        for task_id, task_json in all_tasks.items():
            try:
                task_data = json.loads(task_json)
                
                # Skip pending tasks
                if task_data.get('pending'):
                    continue
                    
                # Check if task is old enough to clean up
                finish_time_str = task_data.get('finish_time')
                if finish_time_str:
                    finish_time = datetime.fromisoformat(finish_time_str)
                    if finish_time < cutoff_date:
                        if not options['dry_run']:
                            task_queue.redis_client.hdel(task_queue.task_data_key, task_id)
                        cleanup_count += 1
                        
            except Exception as e:
                self.stdout.write(f"Error processing task {task_id}: {e}")
                
        if options['dry_run']:
            self.stdout.write(f"Would clean up {cleanup_count} old task records")
        else:
            self.stdout.write(f"Cleaned up {cleanup_count} old task records")
```

After successful migration and validation, you can optionally clean up the legacy database model:

```bash
# Verify Redis queue is working for at least 24-48 hours
./manage.py redis_queue_status

# Optional: Remove TaskQueueElement model from database
# Edit core/models.py to remove TaskQueueElement class
# Edit core/admin.py to remove TaskQueueElement admin registration

# Create migration to remove model from database schema
python manage.py makemigrations core --empty
# Edit the migration file to add: operations = [migrations.DeleteModel(name='TaskQueueElement')]
python manage.py migrate
```

## Additional Notes

1. **Database Model Retention:**
   The `TaskQueueElement` model can be kept in the database for reference/backup purposes, or removed if desired after successful migration.

2. **Redis Persistence:**
   Redis persistence settings ensure tasks survive server restarts while providing much better performance than database storage.

3. **Cron Dependencies:**
   The implementation requires the `croniter` package for cron expression parsing:
   ```bash
   pip install croniter==1.4.1
   ```

4. **Migration Benefits:**
   - Zero API changes required
   - Significant performance improvement
   - Reduced database load
   - Better scalability options
   - Simpler monitoring and debugging

This simplified migration plan provides a direct path from the custom database-backed task queue system to a production-ready Redis implementation with minimal complexity and risk.