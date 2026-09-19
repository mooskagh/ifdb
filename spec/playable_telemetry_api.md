# Playable Telemetry API Specification

This document describes the Telemetry API endpoint used by client-side player wrappers (`*.play.<domain>`) to report gameplay sessions and activity to the main database backend.

---

## Endpoint Details

- **URL**: `/play/telemetry/` (e.g. `https://<main-domain>/play/telemetry/`)
- **HTTP Method**: `POST` (preflight `OPTIONS` requests are handled automatically)
- **Content-Type**: `application/json`
- **Credentials**: `credentials: 'include'` must be passed in `fetch()` so Django session cookies are attached if the user is logged in on the main domain.
- **CORS**: Enabled for subdomains matching `PLAYABLE_BASE_DOMAIN` (e.g. `*.play.crem.xyz`) and `localhost` in debug mode.

---

## 1. Event: `game_loaded`

Sent once as soon as the game player page initializes. It registers the session on the server and returns game metadata.

### Request Body (JSON)

| Field | Type | Required | Description |
|---|---|---|---|
| `event` | `string` | **Yes** | Must be `"game_loaded"`. |
| `play_session_id` | `string` | **Yes** | Client-generated UUIDv4 (e.g. `crypto.randomUUID()`). Unique per play session. |
| `playable_id` | `string` \| `number` | **Yes** | Playable identifier. Can be: <br>• Integer PK (e.g. `42`)<br>• Playable slug (e.g. `"my-game"`)<br>• Game URL or hostname (e.g. `window.location.href` or `window.location.hostname`). The backend automatically parses the subdomain/slug from URLs. |
| `state` | `string` | No | Initial user state: `"active"`, `"idle"`, or `"background"`. Defaults to `"active"`. |

#### Example Request
```json
{
  "event": "game_loaded",
  "play_session_id": "c8a6f3b0-68d7-4b13-a521-9876543210ab",
  "playable_id": "https://my-game.play.crem.xyz/",
  "state": "active"
}
```

### Response (200 OK)

```json
{
  "status": "ok",
  "play_session_id": "c8a6f3b0-68d7-4b13-a521-9876543210ab",
  "playable_id": 42,
  "game_name": "Mystic Woods",
  "authors": "Jane Doe, John Smith",
  "game_url": "https://db.crem.xyz/game/105/",
  "player_name": "INSTEAD",
  "player_url": "https://instead3.hugeping.ru/"
}
```

- `player_name` and `player_url` may be `null` if the player type is unknown.
- `game_url` is the canonical game details page on the main website.

---

## 2. Event: `ping`

Sent periodically (recommended: every 60 seconds), on user state transitions, and on page unload.

### Request Body (JSON)

| Field | Type | Required | Description |
|---|---|---|---|
| `event` | `string` | **Yes** | Must be `"ping"`. |
| `play_session_id` | `string` | **Yes** | Same UUIDv4 string generated for `game_loaded`. |
| `seconds_since_last_ping` | `integer` | **Yes** | Number of elapsed seconds since the previous ping (non-negative integer). |
| `state` | `string` | **Yes** | Current user state: `"active"`, `"idle"`, or `"background"`. |

#### Example Request
```json
{
  "event": "ping",
  "play_session_id": "c8a6f3b0-68d7-4b13-a521-9876543210ab",
  "seconds_since_last_ping": 60,
  "state": "active"
}
```

### Response (200 OK)

```json
{
  "status": "ok",
  "play_session_id": "c8a6f3b0-68d7-4b13-a521-9876543210ab",
  "active_seconds": 120
}
```

- `active_seconds` reflects the cumulative active time recorded for the current segment.

---

## State Definitions & Server Collapsing Logic

### States
- `"active"`: The tab is visible (`document.visibilityState === 'visible'`) and the user has performed interaction (key press, mouse move, click, touch, scroll) within the idle timeout threshold (e.g. last 60 seconds).
- `"idle"`: The tab is visible, but no user input occurred for longer than the idle threshold.
- `"background"`: The tab is not visible (`document.visibilityState === 'hidden'`).

### Segment Collapsing & Transitions
- **Same state**: Consecutive pings with the same state and client parameters (IP, session, user) do **not** create new database rows; the server updates `last_seen_at` and adds `seconds_since_last_ping` to `active_seconds` (if `state === "active"`).
- **State change**: When transitioning (e.g. `"active"` to `"idle"`), the client sends a ping with `seconds_since_last_ping` and the *new* state. The server credits elapsed time to the previous state segment, closes it, and opens a new segment for the new state.
- **Gaps / Inactivity**: If more than 300 seconds elapse between pings (e.g. computer was asleep or suspended), the server automatically starts a new segment rather than attributing the entire gap to active time.

---

## Error Responses

| Status Code | Reason | Body Format |
|---|---|---|
| `400 Bad Request` | Missing or invalid parameter (e.g. invalid UUID, negative seconds, unknown state) | `{"error": "Description of error"}` |
| `404 Not Found` | Unknown `playable_id` or `play_session_id` | `{"error": "Description of error"}` |
| `405 Method Not Allowed` | Non-`POST`/`OPTIONS` method | `{"error": "Method not allowed"}` |

---

## Client-Side JavaScript Reference Implementation

```javascript
class PlayTelemetry {
  /**
   * @param {Object} options
   * @param {string} options.endpointUrl - Full URL to /play/telemetry/ on backend.
   * @param {string|number} [options.playableId] - Slug, PK, or full URL (defaults to window.location.href).
   * @param {number} [options.pingIntervalMs=60000] - Ping frequency (default 60s).
   * @param {number} [options.idleThresholdMs=60000] - Inactivity duration before state becomes 'idle' (default 60s).
   */
  constructor(options) {
    this.endpointUrl = options.endpointUrl;
    this.playableId = options.playableId || window.location.href;
    this.pingIntervalMs = options.pingIntervalMs || 60000;
    this.idleThresholdMs = options.idleThresholdMs || 60000;

    this.sessionId = crypto.randomUUID();
    this.lastPingTime = Date.now();
    this.lastActivityTime = Date.now();
    this.currentState = this._computeState();

    this.timer = null;
    this._boundOnActivity = () => this._onActivity();
    this._boundOnVisibility = () => this._onVisibilityChange();
  }

  async start() {
    this._attachListeners();

    // 1. Send game_loaded event
    const data = await this._send({
      event: 'game_loaded',
      play_session_id: this.sessionId,
      playable_id: this.playableId,
      state: this.currentState,
    });

    this.lastPingTime = Date.now();

    // 2. Start heartbeat timer
    this.timer = setInterval(() => this._tick(), this.pingIntervalMs);

    return data;
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this._detachListeners();
    this._flushUnload();
  }

  _computeState() {
    if (document.visibilityState === 'hidden') {
      return 'background';
    }
    const isIdle = (Date.now() - this.lastActivityTime) > this.idleThresholdMs;
    return isIdle ? 'idle' : 'active';
  }

  _onActivity() {
    this.lastActivityTime = Date.now();
    if (this.currentState === 'idle') {
      this._transitionTo('active');
    }
  }

  _onVisibilityChange() {
    const newState = this._computeState();
    if (newState !== this.currentState) {
      this._transitionTo(newState);
    }
  }

  async _transitionTo(newState) {
    const now = Date.now();
    const elapsedSeconds = Math.max(0, Math.round((now - this.lastPingTime) / 1000));
    this.lastPingTime = now;
    this.currentState = newState;

    await this._send({
      event: 'ping',
      play_session_id: this.sessionId,
      seconds_since_last_ping: elapsedSeconds,
      state: newState,
    });
  }

  async _tick() {
    const newState = this._computeState();
    const now = Date.now();
    const elapsedSeconds = Math.max(0, Math.round((now - this.lastPingTime) / 1000));
    this.lastPingTime = now;
    this.currentState = newState;

    await this._send({
      event: 'ping',
      play_session_id: this.sessionId,
      seconds_since_last_ping: elapsedSeconds,
      state: newState,
    });
  }

  _send(payload, keepalive = false) {
    return fetch(this.endpointUrl, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: keepalive,
    }).then(res => res.ok ? res.json() : null).catch(() => null);
  }

  _flushUnload() {
    const now = Date.now();
    const elapsedSeconds = Math.max(0, Math.round((now - this.lastPingTime) / 1000));
    if (elapsedSeconds > 0) {
      this._send({
        event: 'ping',
        play_session_id: this.sessionId,
        seconds_since_last_ping: elapsedSeconds,
        state: this.currentState,
      }, true);
    }
  }

  _attachListeners() {
    ['keydown', 'mousedown', 'pointerdown', 'touchstart', 'scroll'].forEach(evt => {
      window.addEventListener(evt, this._boundOnActivity, { passive: true });
    });
    document.addEventListener('visibilitychange', this._boundOnVisibility);
    window.addEventListener('pagehide', () => this._flushUnload());
  }

  _detachListeners() {
    ['keydown', 'mousedown', 'pointerdown', 'touchstart', 'scroll'].forEach(evt => {
      window.removeEventListener(evt, this._boundOnActivity);
    });
    document.removeEventListener('visibilitychange', this._boundOnVisibility);
  }
}
```
