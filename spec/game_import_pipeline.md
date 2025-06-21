# Game Import Pipeline

One of the main features of the platform is to import games from various sources and reconcile them.

## Current Implementation

As a reminder, every game is stored as a `Game` object, which has title, textual description, and, among other things, list of URLs with descriptions and types (whether it's a download link, a video, the game page at the different source, etc.).

For every known source website, we have an implementation of `Importer` interface in `games/importer` directory. The importers have to implement (among others) the following methods:

- `Match(url)` - checks if the URL is the game page from that source.
- `Import(url)` - imports the game into the standartized dict.
- `GetUrlCandidates()` - returns a list of URLs that can be used to import the game.

The process as an entrypoint ImportGames in `games/tasks/game_importer.py` is as follows:

- We build a list of all URL candidates from all importers.
- URLs that are not already in the database are fetched.
- For each URL, we try to find the most similar game in the database, based on the set of URLs that the fetched game has, and bag-of-words of the title.
- If a game is not found, we create a new game.
- Otherwise, if the game was ever edited by a human, we only append the new URLs.
- Otherwise, we also append the description with the new description.

From time to time, we reimport all games. Which is basically the same except we don't filter the URLs that are already in the database.

### Issues

The current approach has several issues:

- If any error occurs during the import (for example the source changed API), the whole import fails. Nothing gets imported. Sometimes for years, until somebody comments out the failing importer.
- If somebody edited a game manually, the import will never update the game.
- The description merge is not very good, as it just appends the new description to the old one, which leads to duplicates. We should use LLMs instead.
- We don't handle updates to the source URLs. If a game page is updated, we don't reimport it. We should probably attach a hash to each URL and date of last import.
- There's no monitoring page, we should have one.

## Proposed Reimplementation

### Design Principles

The new pipeline should be built around these core principles:

1. **Fault Isolation** - Individual importer failures don't break the entire system
2. **Intelligent Conflict Resolution** - Use AI/LLM for smart data merging decisions  
3. **Change Detection** - Only process content that has actually changed
4. **Human-AI Collaboration** - Preserve human intent while allowing beneficial updates
5. **Observability First** - Built-in monitoring, alerting, and debugging
6. **Graceful Degradation** - System works even when components are degraded

### Architecture Overview

The reimplemented pipeline uses an event-driven architecture with the following components:

#### 1. Import Orchestrator
Central coordinator that manages the import process without being a single point of failure:
- Schedules imports based on configurable policies (daily, weekly, on-demand)
- Distributes work across independent workers using task queues
- Implements circuit breaker pattern for failing importers
- Aggregates results and handles global operations like duplicate detection

#### 2. Source Monitors  
Lightweight services that track changes at source websites:
- Continuous polling with respectful rate limiting
- Content hashing to detect actual changes (not just timestamp updates)
- Change events trigger targeted imports rather than full rescans
- Configurable monitoring frequencies per source based on update patterns

#### 3. Import Workers (One per Source)
Independent workers that handle specific import sources:
- Isolated failure domains - one worker failure doesn't affect others
- Retry logic with exponential backoff for transient failures
- Progress tracking and resumability for long-running imports
- Source-specific optimizations and caching strategies

#### 4. Game State Manager
Tracks the complete state and history of each game across all sources:
- Immutable version history for all game data with source attribution
- Conflict detection and flagging when sources disagree
- Human edit tracking with field-level granularity
- Rollback capabilities for problematic imports

#### 5. AI-Powered Conflict Resolver
Intelligently merges conflicting data using language models:
- LLM-based description merging that eliminates duplicates
- Confidence scoring for automated merge decisions
- Human review queue for low-confidence conflicts
- Learning system that improves from human feedback
- Multi-language support for international games

#### 6. Monitoring Dashboard
Real-time operational visibility and control:
- Import progress tracking with estimated completion times
- Source health monitoring with uptime/error metrics
- Conflict resolution queue management
- Performance analytics and alerting
- Manual override controls for emergency situations

#### 7. Event Store
Central immutable log of all system activities:
- Complete audit trail for debugging and compliance
- Event replay capability for testing and recovery
- Integration hooks for external systems
- Foundation for analytics and reporting

### Data Flow

#### Phase 1: Change Detection
1. Source monitors continuously poll known game pages
2. Content hashes detect actual changes vs. false positives
3. Change events are published to the event store
4. Import orchestrator prioritizes and queues import tasks

#### Phase 2: Import Processing  
1. Import workers receive tasks for specific URLs
2. Workers extract and normalize game data independently
3. Game state manager detects conflicts with existing data
4. Successful imports update the canonical game records

#### Phase 3: Conflict Resolution
1. Conflicting data triggers the AI conflict resolver
2. High-confidence resolutions are applied automatically
3. Low-confidence conflicts enter human review queue
4. Resolved conflicts update game state with audit trail

#### Phase 4: Quality Assurance
1. All changes undergo validation and anomaly detection
2. Large changes or suspicious patterns trigger review
3. Monitoring dashboard provides real-time visibility
4. Alerts notify operators of issues requiring attention

### Smart Human Edit Handling

Instead of permanently locking human-edited games, the new system:

- **Field-Level Tracking**: Records which specific fields were human-edited
- **Selective Updates**: Allows updates to non-edited fields while preserving human changes
- **Suggested Improvements**: Uses AI to suggest updates to human-edited fields for review
- **Trust Decay**: Very old human edits (>2 years) may be candidates for override
- **Intent Preservation**: Maintains context about why humans made specific edits

### Intelligent Description Merging

The AI-powered merger handles descriptions by:

- **Duplicate Detection**: Identifies and removes redundant content across sources
- **Fact Extraction**: Pulls key information from multiple descriptions
- **Coherent Synthesis**: Generates readable merged descriptions
- **Source Attribution**: Maintains credits for contributed information  
- **Quality Scoring**: Rates the quality of merged vs. original content

### Error Handling and Recovery

#### Circuit Breaker Pattern
- Tracks failure rates per importer over sliding time windows
- Temporarily disables persistently failing importers
- Implements gradual recovery with exponential backoff
- Escalates to human intervention for chronic issues

#### Graceful Degradation
- Continues processing successful importers when others fail
- Provides clear reporting of partial vs. complete failures
- Maintains service availability even during component outages
- Implements intelligent retry strategies for different error types

#### Data Quality Safeguards
- Validation rules prevent obviously incorrect data from entering
- Anomaly detection flags suspicious changes for review
- Rollback mechanisms allow recovery from bad imports
- Change size limits trigger human approval for major updates

### Implementation Strategy

#### Phase 1: Foundation (Weeks 1-4)
- Implement event store and basic event publishing
- Create monitoring dashboard with current system metrics
- Build import worker framework with one reference implementation
- Establish game state tracking with audit capabilities

#### Phase 2: Core Pipeline (Weeks 5-8)  
- Migrate existing importers to new worker framework
- Implement change detection and smart polling
- Deploy import orchestrator with circuit breaker logic
- Add basic conflict detection and human review queue

#### Phase 3: Intelligence Layer (Weeks 9-12)
- Integrate AI-powered conflict resolution
- Implement smart human edit handling
- Add advanced monitoring and alerting
- Performance optimization and stress testing

#### Phase 4: Migration and Optimization (Weeks 13-16)
- Gradual migration from old to new pipeline
- Performance tuning and optimization
- Documentation and operator training
- Post-migration monitoring and adjustment

### Database Model Updates

The new architecture requires several new models and modifications to existing ones:

#### New Models

**Event Store Models**:
```python
class ImportEvent(models.Model):
   event_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
   event_type = models.CharField(max_length=50)  # 'import_started', 'conflict_detected', etc.
   game = models.ForeignKey(Game, on_delete=models.CASCADE, null=True)
   source_url = models.URLField(null=True)
   payload = models.JSONField()  # Event-specific data
   timestamp = models.DateTimeField(auto_now_add=True)
   correlation_id = models.UUIDField()  # Group related events
```

**Import State Tracking**:
```python
class GameImportState(models.Model):
   game = models.OneToOneField(Game, on_delete=models.CASCADE)
   source_states = models.JSONField(default=dict)  # Per-source metadata
   last_full_import = models.DateTimeField(null=True)
   human_edited_fields = models.JSONField(default=list)
   human_edit_dates = models.JSONField(default=dict)  # Field -> timestamp mapping
   conflict_count = models.IntegerField(default=0)

class SourceUrlState(models.Model):
   url = models.URLField(unique=True)
   content_hash = models.CharField(max_length=64)
   last_checked = models.DateTimeField(auto_now=True)
   last_imported = models.DateTimeField(null=True)
   import_success = models.BooleanField(default=True)
   failure_count = models.IntegerField(default=0)
   importer_name = models.CharField(max_length=100)
```

**Conflict Resolution Models**:
```python
class DataConflict(models.Model):
   game = models.ForeignKey(Game, on_delete=models.CASCADE)
   field_name = models.CharField(max_length=100)
   source_a = models.CharField(max_length=100)
   source_b = models.CharField(max_length=100)
   value_a = models.TextField()
   value_b = models.TextField()
   status = models.CharField(max_length=20)  # 'pending', 'resolved', 'escalated'
   created_at = models.DateTimeField(auto_now_add=True)

class ConflictResolution(models.Model):
   conflict = models.OneToOneField(DataConflict, on_delete=models.CASCADE)
   resolution_method = models.CharField(max_length=20)  # 'ai_auto', 'human', 'rule_based'
   chosen_value = models.TextField()
   confidence_score = models.FloatField(null=True)
   resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
   resolved_at = models.DateTimeField(auto_now_add=True)
   reasoning = models.TextField()  # Why this resolution was chosen
```

**AI Decision Tracking**:
```python
class AIDecision(models.Model):
   decision_type = models.CharField(max_length=50)  # 'description_merge', 'conflict_resolve'
   input_data = models.JSONField()
   output_data = models.JSONField()
   confidence_score = models.FloatField()
   model_version = models.CharField(max_length=50)
   timestamp = models.DateTimeField(auto_now_add=True)
   validated_by_human = models.BooleanField(null=True)  # True/False/None
```

**Worker Management Models**:
```python
class ImportTask(models.Model):
   task_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
   task_type = models.CharField(max_length=50)  # 'url_import', 'conflict_resolve'
   priority = models.IntegerField(default=0)
   payload = models.JSONField()
   status = models.CharField(max_length=20)  # 'queued', 'processing', 'completed', 'failed'
   worker_id = models.CharField(max_length=100, null=True)
   created_at = models.DateTimeField(auto_now_add=True)
   started_at = models.DateTimeField(null=True)
   completed_at = models.DateTimeField(null=True)
   error_message = models.TextField(null=True)
   retry_count = models.IntegerField(default=0)

class ImporterHealth(models.Model):
   importer_name = models.CharField(max_length=100, unique=True)
   is_enabled = models.BooleanField(default=True)
   last_success = models.DateTimeField(null=True)
   last_failure = models.DateTimeField(null=True)
   consecutive_failures = models.IntegerField(default=0)
   circuit_breaker_open = models.BooleanField(default=False)
   next_retry_at = models.DateTimeField(null=True)
```

#### Modifications to Existing Models

**Game Model Extensions**:
```python
# Add to existing Game model
class Game(models.Model):
   # ... existing fields ...
   
   # New fields for import tracking
   import_metadata = models.JSONField(default=dict)  # Source attribution per field
   quality_score = models.FloatField(null=True)  # AI-calculated data quality
   last_ai_review = models.DateTimeField(null=True)
   needs_human_review = models.BooleanField(default=False)
   
   class Meta:
       # ... existing meta ...
       indexes = [
           models.Index(fields=['needs_human_review']),
           models.Index(fields=['last_ai_review']),
       ]
```

**GameURL Model Extensions**:
```python
# Add to existing GameURL model  
class GameURL(models.Model):
   # ... existing fields ...
   
   # New fields for change tracking
   content_hash = models.CharField(max_length=64, null=True)
   import_source = models.CharField(max_length=100, null=True)
   confidence_score = models.FloatField(null=True)
   verified_by_human = models.BooleanField(default=False)
```

#### Migration Strategy

**Phase 1**: Add new models without affecting existing functionality
**Phase 2**: Add new fields to existing models with sensible defaults  
**Phase 3**: Populate historical data where possible using data migration scripts
**Phase 4**: Enable new functionality that depends on the updated schema

This design provides a robust, scalable, and maintainable import pipeline that addresses all current limitations while being extensible for future requirements.
