/**
 * Play Overlay & Telemetry Script for IFDB playable games.
 *
 * Renders an unobtrusive bottom-right overlay via Shadow DOM and
 * communicates with the /play/telemetry/ API.
 */

interface GameLoadedResponse {
  status: string;
  play_session_id?: string;
  playable_id?: number | string;
  game_name?: string;
  authors?: string;
  game_url?: string;
  player_name?: string | null;
  player_url?: string | null;
  error?: string;
}

type UserState = 'active' | 'idle' | 'background';

const FAVICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="13" height="13" shape-rendering="crispEdges" aria-hidden="true" style="vertical-align: -1px; margin-right: 3px;">
  <path fill="#ff5431" d="M1,9h3v1h-3z M1,10h3v1h-3z M15,25h3v1h-3z M15,26h3v1h-3z M15,27h3v1h-3z M15,28h3v1h-3z M13,29h5v1h-5z M13,30h4v1h-4z"/>
  <path fill="#3f51b5" d="M7,1h5v1h-5z M6,2h9v1h-9z M5,3h11v1h-11z M4,4h12v1h-12z M4,5h2v1h-2z M8,5h9v1h-9z M4,6h2v1h-2z M8,6h9v1h-9z M4,7h13v1h-13z M4,8h12v1h-12z M4,9h12v1h-12z M4,10h11v1h-11z M29,10h1v1h-1z M5,11h9v1h-9z M28,11h2v1h-2z M8,12h9v1h-9z M27,12h4v1h-4z M7,13h13v1h-13z M25,13h6v1h-6z M6,14h25v1h-25z M5,15h7v1h-7z M18,15h13v1h-13z M4,16h7v1h-7z M19,16h4v1h-4z M25,16h5v1h-5z M4,17h6v1h-6z M24,17h6v1h-6z M4,18h6v1h-6z M23,18h6v1h-6z M4,19h6v1h-6z M22,19h7v1h-7z M4,20h7v1h-7z M21,20h7v1h-7z M5,21h7v1h-7z M20,21h7v1h-7z M6,22h20v1h-20z M7,23h17v1h-17z M9,24h13v1h-13z"/>
  <path fill="#ffffff" d="M12,15h6v1h-6z M11,16h8v1h-8z M23,16h2v1h-2z M10,17h14v1h-14z M10,18h13v1h-13z M10,19h12v1h-12z M11,20h10v1h-10z M12,21h8v1h-8z"/>
  <path fill="#000000" d="M6,5h2v1h-2z M6,6h2v1h-2z"/>
</svg>`;

const STYLES = `
:host {
  all: initial;
  position: fixed;
  right: 0;
  bottom: 0;
  z-index: 2147483647;
  pointer-events: none;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 11px;
  line-height: 1.2;
}
.overlay-wrapper {
  display: flex;
  justify-content: flex-end;
  align-items: flex-end;
}
.overlay-bar {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  color: #333333;
  border-top-left-radius: 4px;
  border-top: 1px solid rgba(0, 0, 0, 0.15);
  border-left: 1px solid rgba(0, 0, 0, 0.15);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
  padding: 2px 6px;
  white-space: nowrap;
  user-select: none;
  transition: background 0.15s ease, box-shadow 0.15s ease;
}
.overlay-bar:hover {
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.16);
}
.toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: transparent;
  border: none;
  padding: 0;
  margin: 0;
  font: inherit;
  font-size: 11px;
  color: inherit;
  cursor: pointer;
  outline: none;
}
.toggle-btn:focus-visible {
  outline: 1px dotted #666;
}
.label {
  font-weight: 500;
  letter-spacing: -0.1px;
}
.chevron {
  display: inline-block;
  font-size: 10px;
  line-height: 1;
  margin-left: 2px;
  color: #666;
  vertical-align: baseline;
}
.details-slot {
  display: inline-flex;
  align-items: center;
  max-width: 0;
  opacity: 0;
  overflow: hidden;
  pointer-events: none;
  transition: max-width 0.3s cubic-bezier(0.2, 0, 0, 1), opacity 0.2s ease, margin-left 0.25s ease;
  margin-left: 0;
}
.overlay-bar.expanded .details-slot {
  max-width: 800px;
  opacity: 1;
  pointer-events: auto;
  margin-left: 6px;
}
.details-content {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
a {
  color: #2a6496;
  text-decoration: none;
  cursor: pointer;
}
a:hover {
  color: #174785;
  text-decoration: underline;
}
.game-link {
  font-weight: 500;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.player-link {
  color: #555555;
  font-size: 11px;
}
.player-link:hover {
  color: #174785;
}
@media (prefers-color-scheme: dark) {
  .overlay-bar {
    background: rgba(30, 32, 36, 0.92);
    color: #e0e0e0;
    border-top: 1px solid rgba(255, 255, 255, 0.15);
    border-left: 1px solid rgba(255, 255, 255, 0.15);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
  }
  .overlay-bar:hover {
    background: rgba(36, 39, 44, 0.98);
  }
  .chevron {
    color: #999;
  }
  a {
    color: #6db3f2;
  }
  a:hover {
    color: #9cd0ff;
  }
  .player-link {
    color: #aaaaaa;
  }
}
`;

function generateUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, c =>
    (+c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (+c / 4)))).toString(16)
  );
}

class PlayOverlay {
  private endpointUrl: string;
  private playableId: string;
  private baseDomainUrl: string;
  private sessionId: string;
  private lastPingTime: number;
  private lastActivityTime: number;
  private currentState: UserState;
  private idleThresholdMs: number = 60000;
  private pingIntervalMs: number = 60000;

  private isExpanded: boolean = false;
  private gameMetadata: GameLoadedResponse | null = null;
  private gameLoadedPromise: Promise<GameLoadedResponse | null> | null = null;

  private heartbeatTimer: number | null = null;
  private idleTimer: number | null = null;

  private shadowRoot!: ShadowRoot;
  private overlayBarEl!: HTMLElement;
  private chevronEl!: HTMLElement;
  private gameLinkEl!: HTMLAnchorElement;
  private playerLinkEl!: HTMLAnchorElement;

  private boundOnActivity = () => this.onActivity();
  private boundOnVisibilityChange = () => this.onVisibilityChange();
  private boundOnPageHide = () => this.flushUnload();

  constructor() {
    this.sessionId = generateUUID();
    this.lastPingTime = Date.now();
    this.lastActivityTime = Date.now();
    this.currentState = document.visibilityState === 'hidden' ? 'background' : 'active';

    const script = this.findScriptElement();
    const explicitEndpoint = script?.getAttribute('data-endpoint');
    const explicitPlayableId = script?.getAttribute('data-playable-id');

    let scriptOrigin = 'https://db.crem.xyz';
    if (script?.src) {
      try {
        const parsed = new URL(script.src);
        scriptOrigin = parsed.origin;
      } catch {
        // fallback
      }
    } else if (typeof window !== 'undefined' && window.location) {
      scriptOrigin = window.location.origin;
    }

    this.baseDomainUrl = scriptOrigin;
    this.endpointUrl = explicitEndpoint
      ? new URL(explicitEndpoint, window.location.href).href
      : new URL('/play/telemetry/', scriptOrigin).href;

    this.playableId = explicitPlayableId || (typeof window !== 'undefined' ? window.location.href : '');
  }

  private findScriptElement(): HTMLScriptElement | null {
    if (document.currentScript && document.currentScript instanceof HTMLScriptElement) {
      return document.currentScript;
    }
    const scripts = document.querySelectorAll('script');
    for (let i = scripts.length - 1; i >= 0; i--) {
      const s = scripts[i];
      if (s.src && s.src.includes('play-overlay.js')) {
        return s;
      }
    }
    return null;
  }

  public start(): void {
    this.render();
    this.attachListeners();

    // Reset idle timer
    this.resetIdleTimer();

    // 1. Send game_loaded event
    this.gameLoadedPromise = this.send({
      event: 'game_loaded',
      play_session_id: this.sessionId,
      playable_id: this.playableId,
      state: this.currentState,
    }).then(res => {
      if (res && res.status === 'ok') {
        this.gameMetadata = res;
        this.updateMetadata(res);
      }
      this.lastPingTime = Date.now();
      return res;
    });

    // 2. Start heartbeat
    this.heartbeatTimer = window.setInterval(() => this.tickHeartbeat(), this.pingIntervalMs);
  }

  public stop(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.idleTimer !== null) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
    this.detachListeners();
    this.flushUnload();
  }

  private render(): void {
    let host = document.getElementById('ifdb-play-overlay-root');
    if (!host) {
      host = document.createElement('div');
      host.id = 'ifdb-play-overlay-root';
      document.body.appendChild(host);
    }

    this.shadowRoot = host.attachShadow({ mode: 'open' });

    const styleEl = document.createElement('style');
    styleEl.textContent = STYLES;
    this.shadowRoot.appendChild(styleEl);

    const wrapper = document.createElement('div');
    wrapper.className = 'overlay-wrapper';

    const bar = document.createElement('div');
    bar.className = 'overlay-bar';
    this.overlayBarEl = bar;

    // Toggle button: "(icon) db.crem.xyz <"
    const toggleBtn = document.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = 'toggle-btn';
    toggleBtn.setAttribute('aria-expanded', 'false');
    toggleBtn.setAttribute('title', 'db.crem.xyz');

    toggleBtn.innerHTML = `${FAVICON_SVG}<span class="label">db.crem.xyz</span>`;

    const chevron = document.createElement('span');
    chevron.className = 'chevron';
    chevron.textContent = '◂';
    this.chevronEl = chevron;
    toggleBtn.appendChild(chevron);

    toggleBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.toggle();
    });

    bar.appendChild(toggleBtn);

    // Details slot: "[<title> на db.crem.xyz](link) [<player name>](link)"
    const detailsSlot = document.createElement('div');
    detailsSlot.className = 'details-slot';

    const detailsContent = document.createElement('div');
    detailsContent.className = 'details-content';

    const gameLink = document.createElement('a');
    gameLink.className = 'game-link';
    gameLink.target = '_blank';
    gameLink.rel = 'noopener noreferrer';
    gameLink.href = this.baseDomainUrl;
    gameLink.textContent = 'db.crem.xyz';
    gameLink.addEventListener('click', (e) => e.stopPropagation());
    this.gameLinkEl = gameLink;

    const playerLink = document.createElement('a');
    playerLink.className = 'player-link';
    playerLink.target = '_blank';
    playerLink.rel = 'noopener noreferrer';
    playerLink.style.display = 'none';
    playerLink.addEventListener('click', (e) => e.stopPropagation());
    this.playerLinkEl = playerLink;

    detailsContent.appendChild(gameLink);
    detailsContent.appendChild(playerLink);
    detailsSlot.appendChild(detailsContent);
    bar.appendChild(detailsSlot);

    wrapper.appendChild(bar);
    this.shadowRoot.appendChild(wrapper);
  }

  private toggle(): void {
    this.isExpanded = !this.isExpanded;
    if (this.isExpanded) {
      this.overlayBarEl.classList.add('expanded');
      this.chevronEl.textContent = '▸';
    } else {
      this.overlayBarEl.classList.remove('expanded');
      this.chevronEl.textContent = '◂';
    }
  }

  private updateMetadata(data: GameLoadedResponse): void {
    if (data.game_name) {
      this.gameLinkEl.textContent = `${data.game_name} на db.crem.xyz`;
    }
    if (data.game_url) {
      this.gameLinkEl.href = data.game_url;
    }
    if (data.authors) {
      this.gameLinkEl.title = `${data.authors} — ${data.game_name || ''}`;
    }

    if (data.player_name) {
      this.playerLinkEl.textContent = data.player_name;
      if (data.player_url) {
        this.playerLinkEl.href = data.player_url;
      } else {
        this.playerLinkEl.removeAttribute('href');
      }
      this.playerLinkEl.style.display = 'inline';
    } else {
      this.playerLinkEl.style.display = 'none';
    }
  }

  private computeState(): UserState {
    if (document.visibilityState === 'hidden') {
      return 'background';
    }
    const isIdle = Date.now() - this.lastActivityTime >= this.idleThresholdMs;
    return isIdle ? 'idle' : 'active';
  }

  private resetIdleTimer(): void {
    if (this.idleTimer !== null) {
      clearTimeout(this.idleTimer);
    }
    if (document.visibilityState === 'visible') {
      this.idleTimer = window.setTimeout(() => this.checkIdleTimeout(), this.idleThresholdMs);
    }
  }

  private onActivity(): void {
    this.lastActivityTime = Date.now();
    this.resetIdleTimer();

    if (this.currentState === 'idle' && document.visibilityState === 'visible') {
      this.transitionTo('active');
    }
  }

  private checkIdleTimeout(): void {
    if (document.visibilityState === 'visible') {
      const isIdle = Date.now() - this.lastActivityTime >= this.idleThresholdMs;
      if (isIdle && this.currentState !== 'idle') {
        this.transitionTo('idle');
      }
    }
  }

  private onVisibilityChange(): void {
    const newState = this.computeState();
    if (newState !== this.currentState) {
      this.transitionTo(newState);
    }
    if (newState === 'active') {
      this.resetIdleTimer();
    }
  }

  private async transitionTo(newState: UserState): Promise<void> {
    if (newState === this.currentState) {
      return;
    }
    const now = Date.now();
    const elapsedSeconds = Math.max(0, (now - this.lastPingTime) / 1000);
    this.lastPingTime = now;
    this.currentState = newState;

    if (this.gameLoadedPromise) {
      await this.gameLoadedPromise.catch(() => null);
    }

    await this.send({
      event: 'ping',
      play_session_id: this.sessionId,
      seconds_since_last_ping: elapsedSeconds,
      state: newState,
    });
  }

  private async tickHeartbeat(): Promise<void> {
    const newState = this.computeState();
    const now = Date.now();
    const elapsedSeconds = Math.max(0, (now - this.lastPingTime) / 1000);
    this.lastPingTime = now;
    this.currentState = newState;

    if (this.gameLoadedPromise) {
      await this.gameLoadedPromise.catch(() => null);
    }

    await this.send({
      event: 'ping',
      play_session_id: this.sessionId,
      seconds_since_last_ping: elapsedSeconds,
      state: newState,
    });
  }

  private send(payload: Record<string, unknown>, keepalive = false): Promise<any> {
    return fetch(this.endpointUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      keepalive,
    })
      .then(res => (res.ok ? res.json() : null))
      .catch(() => null);
  }

  private flushUnload(): void {
    const now = Date.now();
    const elapsedSeconds = Math.max(0, (now - this.lastPingTime) / 1000);
    if (elapsedSeconds > 0) {
      this.send(
        {
          event: 'ping',
          play_session_id: this.sessionId,
          seconds_since_last_ping: elapsedSeconds,
          state: this.currentState,
        },
        true
      );
    }
  }

  private attachListeners(): void {
    ['keydown', 'mousedown', 'pointerdown', 'touchstart', 'scroll'].forEach(evt => {
      window.addEventListener(evt, this.boundOnActivity, { passive: true });
    });
    document.addEventListener('visibilitychange', this.boundOnVisibilityChange);
    window.addEventListener('pagehide', this.boundOnPageHide);
  }

  private detachListeners(): void {
    ['keydown', 'mousedown', 'pointerdown', 'touchstart', 'scroll'].forEach(evt => {
      window.removeEventListener(evt, this.boundOnActivity);
    });
    document.removeEventListener('visibilitychange', this.boundOnVisibilityChange);
    window.removeEventListener('pagehide', this.boundOnPageHide);
  }
}

function initOverlay(): void {
  if (typeof document === 'undefined') {
    return;
  }
  if (document.getElementById('ifdb-play-overlay-root')) {
    return;
  }
  const overlay = new PlayOverlay();
  overlay.start();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initOverlay);
} else {
  initOverlay();
}
