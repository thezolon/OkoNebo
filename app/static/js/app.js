/* OkoNebo frontend */

const state = {
    units: 'f',
    forecastFilter: 'day',
    alertFilter: 'all',
    autoRefresh: true,
    refreshIntervalMs: 300000,
    stormMode: false,
    radarOpacity: 0.7,
    radarSpeedMs: 1200,
    radarProvider: 'iem-archive',
    mapProvider: 'esri_street',
    radarBoomerang: false,
    owmOverlay: 'none',
    hourlyView: 'chart',
    pwsTrendHours: 3,
    currentSourceIndex: 0,
    showAlertPolygons: true,
    showFireOverlay: true,
    showTestAlert: false,
    isOffline: false,
    browserOffline: typeof navigator !== 'undefined' ? !navigator.onLine : false,
    lastSyncTimestamp: null,
    offlineExtendedCacheTtlSec: 86400,
    showDebugPanel: false,
    alertLayerFilters: {
        tornado: true,
        flood: true,
        thunderstorm: true,
    },
};

const PROVIDER_IDS = [
    'nws',
    'openweather',
    'pws',
    'tomorrow',
    'meteomatics',
    'weatherapi',
    'visualcrossing',
    'aviationweather',
    'noaa_tides',
];

const AUTH_TOKEN_STORAGE_KEY = 'weatherapp.auth.token';

const cache = {
    config: null,
    bootstrap: null,
    current: null,
    multiCurrent: null,
    forecast: [],
    hourly: [],
    alerts: [],
    alertsViewport: [],
    firewatch: [],
    firewatchViewport: [],
    owm: null,
    pws: null,
    pwsTrend: null,
    astro: null,
    aqi: null,
    currentSources: [],
};

const PWS_NAMES = {
    KOKPRAGU20: 'ZNewHouse',
    KOKPRAGU2: 'ZOldHouse',
};

const TIMEZONE_FALLBACK_OPTIONS = [
    'UTC',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'Europe/London',
    'Europe/Berlin',
    'Asia/Tokyo',
    'Asia/Kolkata',
    'Australia/Sydney',
];

const RADAR_DEFAULT_ZOOM = 8;
const RADAR_DEFAULT_ZOOM_RAINVIEWER = 7;
const RADAR_MAX_NATIVE_ZOOM = 12;
const STORM_MODE_INTERVAL_MS = 30000;
const STORM_MODE_DETAIL_REFRESH_MS = 300000;
const AGE_RENDER_INTERVAL_MS = 30000;
const REFRESH_JITTER_MAX_RATIO = 0.12;
const SERVER_DEBUG_REFRESH_MS = 45000;
const iemState = { times: [] };
const CURRENT_SOURCE_STORAGE_KEY = 'weatherapp.currentSourceKey';
const PANEL_COLLAPSE_STORAGE_KEY = 'weatherapp.panelCollapse';
const DEFAULT_WEATHER_ICON = `data:image/svg+xml,${encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#60a5fa"/><stop offset="1" stop-color="#2563eb"/></linearGradient></defs><rect width="64" height="64" rx="8" fill="url(#bg)"/><circle cx="22" cy="24" r="10" fill="#fde68a"/><g fill="#ffffff"><ellipse cx="37" cy="38" rx="16" ry="10"/><ellipse cx="27" cy="39" rx="9" ry="7"/></g></svg>'
)}`;

let chartInstance = null;
let radarMap = null;
let baseMapLayer = null;
let baseMapProviderApplied = null;
let radarHost = 'https://tilecache.rainviewer.com';
let radarFrames = [];
let radarOverlayLayer = null;
let owmOverlayLayer = null;
let alertPolygonsLayer = null;
let fireIncidentsLayer = null;
let alertLegendControl = null;
let monitoredLocationsLayer = null;
let radarAnimating = false;
let radarDirection = 1;
let currentRFrameIndex = 0;

let timerFullRefresh = null;
let timerAgeRefresh = null;
let viewportOverlayTimer = null;

function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js?v=5').catch(() => {
            // Ignore service worker registration failures in unsupported contexts.
        });
    });
}

const runtime = {
    timelineEvents: [],
    lastStormDetailRefreshAt: 0,
    serverDebug: null,
    lastServerDebugAt: 0,
    observabilityHistory: [],
    firstRunRequired: false,
    authToken: null,
    authUser: null,
    panelLayoutStatusTimer: null,
    timelineFilterType: 'all',
    timelineSearchText: '',
    iconFallbackCount: 0,
    lastIconSourceUrl: '',
    lastIconFailedUrl: '',
    lastIconFailedAt: null,
    lastCurrentSourceKey: '',
    lastCurrentSourceLabel: '',
    pushConfig: null,
    appVersion: '--',
    appBuild: '',
    owmOverlayWarned: false,
    firewatchFeedError: '',
    viewportAlertsLoaded: false,
};

function renderRuntimeVersion() {
    const el = document.getElementById('app-version');
    if (!el) return;
    const base = runtime.appVersion || '--';
    const suffix = runtime.appBuild ? ` (${runtime.appBuild})` : '';
    el.textContent = `Version ${base}${suffix}`;
}

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let index = 0; index < rawData.length; index += 1) {
        outputArray[index] = rawData.charCodeAt(index);
    }
    return outputArray;
}

async function pushApiRequest(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (runtime.authToken) headers.Authorization = `Bearer ${runtime.authToken}`;
    if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const resp = await fetch(path, { ...options, headers });
    if (!resp.ok) throw new Error(`${path} failed: ${resp.status}`);
    return await resp.json();
}

async function renderPushControls(forceFetch = false) {
    const status = document.getElementById('push-status');
    const btn = document.getElementById('push-toggle-btn');
    if (!status || !btn) return;

    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
        btn.disabled = true;
        status.textContent = 'Push notifications unsupported in this browser.';
        return;
    }

    try {
        if (forceFetch || !runtime.pushConfig) runtime.pushConfig = await pushApiRequest('/api/push/config');
        const registration = await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.getSubscription();
        const permission = Notification.permission;

        if (subscription) {
            btn.textContent = 'Disable Severe Alert Push';
            btn.disabled = false;
            status.textContent = permission === 'granted'
                ? 'Severe alert push enabled for this browser.'
                : 'Browser permission changed; re-enable push if alerts stop arriving.';
            return;
        }

        btn.textContent = permission === 'denied' ? 'Push Blocked by Browser' : 'Enable Severe Alert Push';
        btn.disabled = permission === 'denied';
        status.textContent = permission === 'denied'
            ? 'Browser notifications are blocked. Allow notifications in site settings to enable push.'
            : 'Receive push notifications on approaching or active alert transitions.';
    } catch (err) {
        btn.disabled = true;
        status.textContent = `Push setup unavailable: ${err.message}`;
    }
}

async function togglePushSubscription() {
    const btn = document.getElementById('push-toggle-btn');
    const status = document.getElementById('push-status');
    if (!btn || !status) return;

    try {
        btn.disabled = true;
        runtime.pushConfig = await pushApiRequest('/api/push/config');
        const registration = await navigator.serviceWorker.ready;
        const existing = await registration.pushManager.getSubscription();

        if (existing) {
            await pushApiRequest('/api/push/subscribe', {
                method: 'DELETE',
                body: JSON.stringify({ endpoint: existing.endpoint }),
            });
            await existing.unsubscribe();
            status.textContent = 'Severe alert push disabled for this browser.';
            await renderPushControls(true);
            return;
        }

        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
            status.textContent = 'Browser notification permission was not granted.';
            await renderPushControls(true);
            return;
        }

        const subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(runtime.pushConfig.vapid_public_key),
        });
        await pushApiRequest('/api/push/subscribe', {
            method: 'POST',
            body: JSON.stringify(subscription.toJSON()),
        });
        status.textContent = 'Severe alert push enabled for this browser.';
        await renderPushControls(true);
    } catch (err) {
        status.textContent = `Push setup failed: ${err.message}`;
        await renderPushControls(true);
    } finally {
        btn.disabled = false;
    }
}

function normalizePressure(level) {
    const raw = String(level || 'unknown').toLowerCase();
    if (raw === 'normal' || raw === 'elevated' || raw === 'high') return raw;
    return 'unknown';
}

function pressureScore(level) {
    const normalized = normalizePressure(level);
    if (normalized === 'high') return 2;
    if (normalized === 'elevated') return 1;
    return 0;
}

function pressureLabel(level) {
    const normalized = normalizePressure(level);
    if (normalized === 'normal') return 'Normal';
    if (normalized === 'elevated') return 'Elevated';
    if (normalized === 'high') return 'High';
    return 'Unknown';
}

function summarizeGuidance(obs, recommendations) {
    if (!Array.isArray(recommendations) || recommendations.length === 0) return '--';
    if (normalizePressure(obs?.retry_pressure) === 'high') return 'High retries: check provider status/credentials and raise pull cycles.';
    if (normalizePressure(obs?.cache_pressure) === 'high') return 'Low cache efficiency: increase TTL or inspect cache key churn.';
    if (normalizePressure(obs?.rate_limit_pressure) === 'high') return 'Rate-limit pressure high: reduce bursts and tune client polling.';
    if (normalizePressure(obs?.cache_pressure) === 'elevated') return 'Cache pressure elevated: confirm lookups are not one-off heavy.';
    return String(recommendations[0]).replace(/\s+/g, ' ').trim();
}

function observabilityTrend() {
    const points = runtime.observabilityHistory;
    if (points.length < 4) return { label: 'Stable', icon: '→', cls: '' };
    const recent = points.slice(-3).reduce((sum, item) => sum + item.score, 0) / 3;
    const prev = points.slice(-6, -3).reduce((sum, item) => sum + item.score, 0) / Math.max(1, points.slice(-6, -3).length);
    const delta = recent - prev;
    if (delta > 0.34) return { label: 'Worsening', icon: '↑', cls: 'offline' };
    if (delta < -0.34) return { label: 'Improving', icon: '↓', cls: 'online' };
    return { label: 'Stable', icon: '→', cls: '' };
}

function getStoredAuthToken() {
    try {
        return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || null;
    } catch (err) {
        return null;
    }
}

function setStoredAuthToken(token) {
    try {
        if (token) window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
        else window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    } catch (err) {
        // Ignore storage failures
    }
}

function getAvailableTimezones() {
    try {
        if (typeof Intl !== 'undefined' && typeof Intl.supportedValuesOf === 'function') {
            const zones = Intl.supportedValuesOf('timeZone');
            if (Array.isArray(zones) && zones.length > 0) {
                const sorted = zones.slice().sort((a, b) => a.localeCompare(b));
                if (!sorted.includes('UTC')) sorted.unshift('UTC');
                return sorted;
            }
        }
    } catch (_) {
        // Fall back to a short common list when browser support is missing.
    }
    return TIMEZONE_FALLBACK_OPTIONS.slice();
}

function resolveBrowserTimezone() {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch (_) {
        return 'UTC';
    }
}

function populateTimezoneSelect(elementId, selectedValue) {
    const el = document.getElementById(elementId);
    if (!el || el.tagName !== 'SELECT') return;

    const zones = getAvailableTimezones();
    const preferred = String(selectedValue || '').trim() || resolveBrowserTimezone();
    const options = zones.includes(preferred) ? zones : [preferred, ...zones];

    el.innerHTML = options
        .map((zone) => `<option value="${zone}">${zone}</option>`)
        .join('');
    el.value = options.includes(preferred) ? preferred : 'UTC';
}

function readPanelCollapseState() {
    try {
        const raw = window.localStorage.getItem(PANEL_COLLAPSE_STORAGE_KEY);
        if (!raw) return {};
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (err) {
        return {};
    }
}

function writePanelCollapseState(stateMap) {
    try {
        window.localStorage.setItem(PANEL_COLLAPSE_STORAGE_KEY, JSON.stringify(stateMap));
    } catch (err) {
        // Ignore storage failures
    }
}

function applyCollapsed(section, button, collapsed) {
    section.classList.toggle('collapsed', !!collapsed);
    if (!button) return;
    button.textContent = collapsed ? '▸' : '▾';
    button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    button.setAttribute('title', collapsed ? 'Expand section' : 'Collapse section');
}

function initCollapsiblePanels() {
    const stateMap = readPanelCollapseState();
    const panelIds = ['debug-section', 'admin-section', 'viewer-help-section', 'timeline-section'];

    panelIds.forEach((panelId) => {
        const section = document.getElementById(panelId);
        if (!section) return;

        const button = section.querySelector('.panel-toggle');
        if (!button) return;

        const defaultCollapsed = section.getAttribute('data-default-collapsed') === 'true';
        const collapsed = typeof stateMap[panelId] === 'boolean' ? stateMap[panelId] : defaultCollapsed;
        applyCollapsed(section, button, collapsed);

        button.addEventListener('click', () => {
            const next = !section.classList.contains('collapsed');
            applyCollapsed(section, button, next);
            stateMap[panelId] = next;
            writePanelCollapseState(stateMap);
            updateCompactLayoutButton();
        });
    });

    updateCompactLayoutButton();
}

function updateCompactLayoutButton() {
    const btn = document.getElementById('compact-panel-layout-btn');
    if (!btn) return;
    const panelIds = ['debug-section', 'admin-section', 'viewer-help-section', 'timeline-section'];
    const allCollapsed = panelIds.every((panelId) => {
        const section = document.getElementById(panelId);
        return !!section && section.classList.contains('collapsed');
    });
    btn.textContent = allCollapsed ? 'Expand' : 'Compact';
    btn.title = allCollapsed ? 'Expand utility panels' : 'Collapse utility panels';
}

function setPanelLayoutStatus(message, persist = false) {
    const el = document.getElementById('panel-layout-status');
    if (!el) return;
    el.textContent = message;
    if (runtime.panelLayoutStatusTimer) {
        clearTimeout(runtime.panelLayoutStatusTimer);
        runtime.panelLayoutStatusTimer = null;
    }
    if (persist) return;
    runtime.panelLayoutStatusTimer = setTimeout(() => {
        el.textContent = 'Use Compact to focus map + forecast panels quickly.';
        runtime.panelLayoutStatusTimer = null;
    }, 5000);
}

function isTypingContext(eventTarget) {
    if (!eventTarget) return false;
    const tag = String(eventTarget.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
    return !!eventTarget.isContentEditable;
}

function toggleCompactLayout() {
    const panelIds = ['debug-section', 'admin-section', 'viewer-help-section', 'timeline-section'];
    const stateMap = readPanelCollapseState();
    const allCollapsed = panelIds.every((panelId) => {
        const section = document.getElementById(panelId);
        return !!section && section.classList.contains('collapsed');
    });

    panelIds.forEach((panelId) => {
        const section = document.getElementById(panelId);
        if (!section) return;
        const button = section.querySelector('.panel-toggle');
        const nextCollapsed = !allCollapsed;
        applyCollapsed(section, button, nextCollapsed);
        stateMap[panelId] = nextCollapsed;
    });

    writePanelCollapseState(stateMap);
    updateCompactLayoutButton();
    setPanelLayoutStatus(allCollapsed ? 'Layout expanded: utility sections reopened.' : 'Layout compacted: utility sections collapsed.');
    pushTimelineEvent('system', allCollapsed ? 'Layout expanded' : 'Layout compacted', allCollapsed ? 'Utility sections reopened' : 'Utility sections collapsed for map focus');
    renderTimeline();
}

function resetCollapsiblePanels() {
    const panelIds = ['debug-section', 'admin-section', 'viewer-help-section', 'timeline-section'];
    const nextState = {};

    panelIds.forEach((panelId) => {
        const section = document.getElementById(panelId);
        if (!section) return;
        const button = section.querySelector('.panel-toggle');
        const defaultCollapsed = section.getAttribute('data-default-collapsed') === 'true';
        applyCollapsed(section, button, defaultCollapsed);
        nextState[panelId] = defaultCollapsed;
    });

    writePanelCollapseState(nextState);
    pushTimelineEvent('system', 'Layout reset', 'Right-panel utility sections restored to defaults');
    renderTimeline();
    updateCompactLayoutButton();
    setPanelLayoutStatus('Layout reset to defaults.', true);
}

function formatTime(isoOrUnix) {
    if (!isoOrUnix) return '--';
    const d = typeof isoOrUnix === 'number' ? new Date(isoOrUnix * 1000) : new Date(isoOrUnix);
    return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatHM(isoOrUnix) {
    if (!isoOrUnix) return '--:--';
    const d = typeof isoOrUnix === 'number' ? new Date(isoOrUnix * 1000) : new Date(isoOrUnix);
    return d.toLocaleString([], { hour: '2-digit', minute: '2-digit' });
}

function parseTimestamp(value) {
    if (!value && value !== 0) return null;
    if (typeof value === 'number') {
        return value > 1e12 ? value : value * 1000;
    }
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function formatAgeShort(value) {
    const ts = parseTimestamp(value);
    if (ts == null) return '--';
    const ageMs = Math.max(Date.now() - ts, 0);
    const ageMin = Math.floor(ageMs / 60000);
    if (ageMin < 1) return 'live';
    if (ageMin < 60) return `${ageMin}m old`;
    const ageHr = Math.floor(ageMin / 60);
    if (ageHr < 24) return `${ageHr}h old`;
    return `${Math.floor(ageHr / 24)}d old`;
}

function ageClass(value, freshMinutes = 10, warnMinutes = 25, staleMinutes = null) {
    const ts = parseTimestamp(value);
    if (ts == null) return 'offline';
    const ageMin = Math.max(Date.now() - ts, 0) / 60000;
    if (ageMin <= freshMinutes) return 'fresh';
    const warnCap = staleMinutes != null ? staleMinutes : warnMinutes;
    if (ageMin <= warnCap) return 'warn';
    return 'stale';
}

function setAgeBadge(id, value, freshMinutes, warnMinutes, staleMinutes = null) {
    const el = document.getElementById(id);
    if (!el) return;
    const cls = ageClass(value, freshMinutes, warnMinutes, staleMinutes);
    el.className = `source-age-val ${cls}`;
    el.textContent = formatAgeShort(value);
}

function getNwsObsHealth(timestamp) {
    const ts = parseTimestamp(timestamp);
    if (ts == null) {
        return {
            level: 'offline',
            ageMin: null,
            refreshMin: Math.max(1, Math.round(state.refreshIntervalMs / 60000)),
            questionableAfterMin: 15,
            severeAfterMin: 30,
        };
    }

    const refreshMin = Math.max(1, Math.round(state.refreshIntervalMs / 60000));
    const ageMin = Math.max((Date.now() - ts) / 60000, 0);
    const questionableAfterMin = Math.min(15, refreshMin);
    const severeAfterMin = Math.max(15, refreshMin * 2);

    if (ageMin > severeAfterMin) {
        return { level: 'stale', ageMin, refreshMin, questionableAfterMin, severeAfterMin };
    }
    if (ageMin > questionableAfterMin) {
        return { level: 'questionable', ageMin, refreshMin, questionableAfterMin, severeAfterMin };
    }
    return { level: 'fresh', ageMin, refreshMin, questionableAfterMin, severeAfterMin };
}

function getSourceHealth(source) {
    if (!source) {
        return { level: 'offline', ageMin: null, label: 'Source' };
    }

    const key = String(source.key || '').toLowerCase();
    const label = String(source.label || 'Source');

    // Keep NWS-specific thresholds for station obs freshness.
    if (key === 'nws' || key === 'auto') {
        const nws = getNwsObsHealth(source.timestamp);
        return { level: nws.level, ageMin: nws.ageMin, label: 'NWS' };
    }

    const ts = parseTimestamp(source.timestamp);
    if (ts == null) {
        return { level: 'offline', ageMin: null, label };
    }

    const ageMin = Math.max((Date.now() - ts) / 60000, 0);

    if (key.startsWith('pws:')) {
        if (ageMin > 12) return { level: 'stale', ageMin, label: 'PWS' };
        if (ageMin > 5) return { level: 'questionable', ageMin, label: 'PWS' };
        return { level: 'fresh', ageMin, label: 'PWS' };
    }

    if (key === 'owm') {
        if (ageMin > 45) return { level: 'stale', ageMin, label: 'OWM' };
        if (ageMin > 20) return { level: 'questionable', ageMin, label: 'OWM' };
        return { level: 'fresh', ageMin, label: 'OWM' };
    }

    if (ageMin > 25) return { level: 'stale', ageMin, label };
    if (ageMin > 10) return { level: 'questionable', ageMin, label };
    return { level: 'fresh', ageMin, label };
}

function renderSourceAges() {
    const nwsTs = cache.current?.timestamp || null;
    const pwsTs = (cache.pws?.stations || [])
        .map((station) => parseTimestamp(station.obs_time_utc))
        .filter((value) => value != null)
        .sort((a, b) => b - a)[0] || null;
    const owmTs = cache.owm?.available === false ? null : cache.owm?.current?.dt || null;
    const alertsTs = (cache.alerts || [])
        .map((alert) => parseTimestamp(alert.effective || alert.sent || alert.expires))
        .filter((value) => value != null)
        .sort((a, b) => b - a)[0] || null;

    const nwsHealth = getNwsObsHealth(nwsTs);
    const nwsWarnMin = Math.max(5, Math.round(nwsHealth.questionableAfterMin));
    const nwsStaleMin = Math.max(nwsWarnMin + 1, Math.round(nwsHealth.severeAfterMin));
    setAgeBadge('nws-age', nwsTs, 5, nwsWarnMin, nwsStaleMin);
    setAgeBadge('pws-age', pwsTs, 5, 12);
    setAgeBadge('owm-age', owmTs, 20, 45);
    setAgeBadge('alerts-age', alertsTs, 10, 25);
}

function pushTimelineEvent(type, title, detail, timestamp = Date.now()) {
    runtime.timelineEvents.unshift({
        type,
        title,
        detail,
        timestamp: parseTimestamp(timestamp) || Date.now(),
    });
    runtime.timelineEvents = runtime.timelineEvents
        .sort((a, b) => b.timestamp - a.timestamp)
        .slice(0, 20);
}

function buildTimelineEntries() {
    const entries = [...runtime.timelineEvents];

    if (cache.current?.timestamp) {
        entries.push({
            type: 'obs',
            title: 'NWS observation',
            detail: `${cache.current.station || 'nearest station'} ${cache.current.description || ''}`.trim(),
            timestamp: parseTimestamp(cache.current.timestamp),
        });
    }

    (cache.pws?.stations || []).forEach((station) => {
        if (!station.obs_time_utc) return;
        entries.push({
            type: 'obs',
            title: `${PWS_NAMES[station.station_id] || station.station_id} PWS`,
            detail: `${displayTemp(station.temp_f)} · ${displayWind(station.wind_mph)}`,
            timestamp: parseTimestamp(station.obs_time_utc),
        });
    });

    if (cache.owm && cache.owm.available !== false && cache.owm.current?.dt) {
        entries.push({
            type: 'obs',
            title: 'OWM model update',
            detail: `UV ${cache.owm.current.uvi != null ? Number(cache.owm.current.uvi).toFixed(1) : '--'}`,
            timestamp: parseTimestamp(cache.owm.current.dt),
        });
    }

    getEffectiveAlerts().forEach((alert) => {
        const monitored = Array.isArray(alert.monitored_locations) && alert.monitored_locations.length
            ? ` · ${alert.monitored_locations.join(', ')}`
            : '';
        entries.push({
            type: 'alert',
            title: alert.event || alert.headline || 'Alert',
            detail: `${alert.severity || 'Unknown'}${monitored}${alert.synthetic ? ' · test polygon' : ''}`,
            timestamp: parseTimestamp(alert.effective || alert.sent || alert.expires),
        });
    });

    return entries
        .filter((entry) => entry.timestamp != null)
        .sort((a, b) => b.timestamp - a.timestamp)
        .slice(0, 14);
}

function renderTimeline() {
    const list = document.getElementById('timeline-list');
    const meta = document.getElementById('timeline-meta');
    if (!list || !meta) return;

    const entries = buildTimelineEntries();
    
    // Apply filters
    const filtered = entries.filter((entry) => {
        // Type filter
        if (runtime.timelineFilterType !== 'all' && entry.type !== runtime.timelineFilterType) {
            return false;
        }
        
        // Text search
        if (runtime.timelineSearchText) {
            const searchLower = runtime.timelineSearchText.toLowerCase();
            const titleMatch = entry.title.toLowerCase().includes(searchLower);
            const detailMatch = entry.detail.toLowerCase().includes(searchLower);
            if (!titleMatch && !detailMatch) {
                return false;
            }
        }
        
        return true;
    });
    
    meta.textContent = filtered.length ? `${filtered.length} events` : 'latest events';

    if (filtered.length === 0) {
        list.innerHTML = '<div class="timeline-empty">No matching events</div>';
        return;
    }

    list.innerHTML = '';
    filtered.forEach((entry) => {
        const item = document.createElement('div');
        item.className = `timeline-item ${entry.type}`;
        item.innerHTML = `
            <div class="timeline-top">
                <div class="timeline-title">${entry.title}</div>
                <div class="timeline-time">${formatTime(entry.timestamp)}</div>
            </div>
            <div class="timeline-detail">${entry.detail || ''}</div>
        `;
        list.appendChild(item);
    });
}

function setupTimelineFilters() {
    const searchInput = document.getElementById('timeline-search');
    const clearBtn = document.getElementById('timeline-clear-filter');
    const filterBtns = document.querySelectorAll('[id^="timeline-filter-"]');

    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            runtime.timelineSearchText = e.target.value;
            renderTimeline();
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            runtime.timelineFilterType = 'all';
            runtime.timelineSearchText = '';
            if (searchInput) searchInput.value = '';
            
            filterBtns.forEach((btn) => {
                btn.classList.remove('tab-active');
                if (btn.id === 'timeline-filter-all') {
                    btn.classList.add('tab-active');
                }
            });
            renderTimeline();
        });
    }

    filterBtns.forEach((btn) => {
        btn.addEventListener('click', () => {
            const filterType = btn.getAttribute('data-filter');
            runtime.timelineFilterType = filterType;

            filterBtns.forEach((b) => b.classList.remove('tab-active'));
            btn.classList.add('tab-active');

            renderTimeline();
        });
    });
}

function updateStormModeUi() {
    const toggle = document.getElementById('storm-mode-toggle');
    const badge = document.getElementById('storm-mode-badge');
    const refreshInterval = document.getElementById('refresh-interval');
    if (toggle) toggle.checked = state.stormMode;
    if (badge) {
        badge.classList.toggle('active', state.stormMode);
        badge.textContent = state.stormMode ? '30s critical refresh active' : '30s critical refresh';
    }
    if (refreshInterval) refreshInterval.disabled = state.stormMode;
}

function startAgeRefreshLoop() {
    if (timerAgeRefresh) clearInterval(timerAgeRefresh);
    timerAgeRefresh = setInterval(() => {
        refreshServerDebugStats(false);
        renderSourceAges();
        renderTimeline();
        updateOfflineUI();
        renderDebugPanel();
    }, AGE_RENDER_INTERVAL_MS);
}

function windDir(deg) {
    if (deg === null || deg === undefined) return '--';
    const dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
    return dirs[Math.round(deg / 22.5) % 16];
}

function fToC(f) { return f == null ? null : (f - 32) * 5 / 9; }

function displayTemp(tempF, digits = 0) {
    if (tempF == null) return '--';
    const v = state.units === 'c' ? fToC(tempF) : tempF;
    const n = digits > 0 ? v.toFixed(digits) : Math.round(v);
    return `${n}°${state.units.toUpperCase()}`;
}

function displayWind(raw) {
    if (raw == null) return '--';
    let mph;
    if (typeof raw === 'number') {
        mph = raw;
    } else {
        const nums = String(raw).match(/\d+/g);
        if (!nums) return '--';
        mph = nums.map(Number).reduce((a, b) => a + b, 0) / nums.length;
    }
    return state.units === 'c' ? `${Math.round(mph * 1.60934)} km/h` : `${Math.round(mph)} mph`;
}

function displayDist(miles) {
    if (miles == null) return '--';
    return state.units === 'c' ? `${(miles * 1.60934).toFixed(1)} km` : `${miles} mi`;
}

function displayPressure(inHg) {
    if (inHg == null) return '--';
    return `${inHg} inHg`;
}

function escapeHtml(value) {
    const text = String(value ?? '');
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function alertSevClass(sev) {
    const s = (sev || '').toLowerCase();
    if (s.includes('extreme')) return 'extreme';
    if (s.includes('severe')) return 'severe';
    if (s.includes('moderate')) return 'moderate';
    if (s.includes('minor')) return 'minor';
    return 'unknown';
}

function alertBannerTone(alert) {
    const text = `${alert?.event || ''} ${alert?.headline || ''}`.toLowerCase();
    if (text.includes('warning')) return 'warning';
    if (text.includes('watch')) return 'watch';
    if (text.includes('advisory')) return 'advisory';
    if (text.includes('special weather statement') || text.includes('statement')) return 'statement';
    if (text.includes('outlook')) return 'outlook';

    const sev = alertSevClass(alert?.severity);
    if (sev === 'extreme' || sev === 'severe') return 'warning';
    if (sev === 'moderate') return 'watch';
    if (sev === 'minor') return 'advisory';
    return 'info';
}

function alertBannerLabel(alert, tone) {
    const event = String(alert?.event || '').trim();
    if (event && event.length <= 32) return event.toUpperCase();
    if (tone === 'warning') return 'ACTIVE WARNING';
    if (tone === 'watch') return 'ACTIVE WATCH';
    if (tone === 'advisory') return 'ACTIVE ADVISORY';
    if (tone === 'statement') return 'STATEMENT';
    if (tone === 'outlook') return 'OUTLOOK';
    return 'ACTIVE INFO';
}

function alertBannerPriority(tone) {
    if (tone === 'warning') return 6;
    if (tone === 'watch') return 5;
    if (tone === 'advisory') return 4;
    if (tone === 'statement') return 3;
    if (tone === 'outlook') return 2;
    return 1;
}

function alertDisplaySubtype(alert) {
    const text = `${alert?.event || ''} ${alert?.headline || ''}`.toLowerCase();
    if (text.includes('tornado')) return 'tornado';
    if (text.includes('flood')) return 'flood';
    if (text.includes('thunderstorm')) return 'thunderstorm';
    return 'other';
}

function passesAlertLayerFilters(alert) {
    const subtype = alertDisplaySubtype(alert);
    if (subtype === 'other') return true;
    return !!state.alertLayerFilters[subtype];
}

function alertMapStyle(feature) {
    const tone = alertBannerTone(feature?.properties || {});
    const severity = alertSevClass(feature?.properties?.severity);
    const colorByTone = {
        warning: '#f05252',
        watch: '#ff8c3a',
        advisory: '#f2c94c',
        statement: '#5aa7d8',
        outlook: '#7e99b8',
    };
    const weightBySeverity = {
        extreme: 4,
        severe: 3,
        moderate: 2.5,
        minor: 2,
        unknown: 2,
    };

    return {
        color: colorByTone[tone] || '#7e99b8',
        weight: weightBySeverity[severity] || 2,
        opacity: 0.85,
        fillOpacity: tone === 'warning' ? 0.18 : 0.1,
    };
}

function getAlertLocations() {
    if (Array.isArray(cache.config?.alert_locations) && cache.config.alert_locations.length > 0) {
        return cache.config.alert_locations;
    }
    if (cache.config?.lat != null && cache.config?.lon != null) {
        return [{ lat: cache.config.lat, lon: cache.config.lon, label: cache.config.label || 'Configured Location' }];
    }
    return [];
}

function fitMapToAlertCoverage() {
    if (!radarMap) return;
    const locations = getAlertLocations();
    if (locations.length === 0) return;

    if (locations.length === 1) {
        const targetZoom = state.radarProvider === 'rainviewer' ? RADAR_DEFAULT_ZOOM_RAINVIEWER : RADAR_DEFAULT_ZOOM;
        radarMap.setView([locations[0].lat, locations[0].lon], targetZoom);
        return;
    }

    const bounds = L.latLngBounds(locations.map((loc) => [loc.lat, loc.lon]));
    // RainViewer has incomplete tile coverage above zoom 7; use conservative limit
    const maxInitialZoom = state.radarProvider === 'rainviewer' ? RADAR_DEFAULT_ZOOM_RAINVIEWER : 9;
    radarMap.fitBounds(bounds.pad(0.45), { maxZoom: maxInitialZoom });
}

function getMonitoredLocationIcon(index) {
    const isPrimary = index === 0;
    const iconSymbol = isPrimary ? '🏠' : '🏢';
    const iconClass = isPrimary ? 'is-home' : 'is-office';

    return L.divIcon({
        className: 'monitored-location-icon-wrap',
        html: `<span class="monitored-location-icon ${iconClass}">${iconSymbol}</span>`,
        iconSize: [20, 20],
        iconAnchor: [10, 10],
        popupAnchor: [0, -10],
    });
}

function renderMonitoredLocationMarkers() {
    if (!radarMap) return;
    if (monitoredLocationsLayer) {
        radarMap.removeLayer(monitoredLocationsLayer);
        monitoredLocationsLayer = null;
    }

    const locations = getAlertLocations();
    if (locations.length === 0) return;

    monitoredLocationsLayer = L.layerGroup();
    locations.forEach((loc, index) => {
        const role = index === 0 ? 'Home' : 'Office';
        const label = loc.label || `${role} location`;
        L.marker([loc.lat, loc.lon], {
            icon: getMonitoredLocationIcon(index),
            keyboard: true,
            title: label,
        }).bindPopup(label).addTo(monitoredLocationsLayer);
    });

    monitoredLocationsLayer.addTo(radarMap);
}

function getTestAlert() {
    if (!state.showTestAlert || !cache.config) return null;

    const { lat, lon, label } = cache.config;
    const ring = [
        [lon - 0.10, lat - 0.05],
        [lon - 0.02, lat - 0.11],
        [lon + 0.09, lat - 0.07],
        [lon + 0.11, lat + 0.03],
        [lon + 0.03, lat + 0.11],
        [lon - 0.08, lat + 0.08],
        [lon - 0.10, lat - 0.05],
    ];

    return {
        id: 'synthetic-test-alert',
        event: 'Tornado Warning',
        severity: 'Severe',
        urgency: 'Immediate',
        certainty: 'Observed',
        headline: `Synthetic test alert near ${label || 'configured location'}`,
        description: 'Synthetic alert polygon for dashboard testing. This is not a real NWS alert.',
        instruction: 'Use for validating polygon drawing, fit-to-alert, and legend styling.',
        sent: new Date().toISOString(),
        effective: new Date().toISOString(),
        expires: new Date(Date.now() + 45 * 60 * 1000).toISOString(),
        ends: new Date(Date.now() + 45 * 60 * 1000).toISOString(),
        areas_affected: label || 'Configured location',
        geometry: {
            type: 'Polygon',
            coordinates: [ring],
        },
        synthetic: true,
    };
}

function getEffectiveAlerts() {
    const alerts = [...(cache.alerts || [])];
    const testAlert = getTestAlert();
    if (testAlert) alerts.unshift(testAlert);
    return alerts;
}

function getDisplayAlerts() {
    const baseAlerts = (runtime.viewportAlertsLoaded && Array.isArray(cache.alertsViewport))
        ? [...cache.alertsViewport]
        : [...(cache.alerts || [])];
    const testAlert = getTestAlert();
    if (testAlert) baseAlerts.unshift(testAlert);

    if (!radarMap) return baseAlerts.filter(passesAlertLayerFilters);
    const bounds = radarMap.getBounds();
    const filteredBySubtype = baseAlerts.filter(passesAlertLayerFilters);
    if (!bounds || !bounds.isValid()) return filteredBySubtype;
    return filteredBySubtype.filter((alert) => _alertIntersectsViewport(alert, bounds));
}

function getAlertById(alertId) {
    return getDisplayAlerts().find((alert) => alert.id === alertId)
        || getEffectiveAlerts().find((alert) => alert.id === alertId)
        || null;
}

function updateAlertTestButton() {
    const btn = document.getElementById('alert-test-toggle-btn');
    if (!btn) return;
    btn.textContent = state.showTestAlert ? 'Test Alert On' : 'Test Alert';
    btn.classList.toggle('map-btn-accent', state.showTestAlert);
}

function updateAlertLegendVisibility() {
    if (!alertLegendControl || !alertLegendControl._container) return;
    alertLegendControl._container.style.display = state.showAlertPolygons ? '' : 'none';
}

function ensureAlertLegend() {
    if (!radarMap || alertLegendControl) return;

    alertLegendControl = L.control({ position: 'bottomleft' });
    alertLegendControl.onAdd = () => {
        const div = L.DomUtil.create('div', 'alert-map-legend');
        const mobileDefaultCollapsed = typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches;
        if (mobileDefaultCollapsed) {
            div.classList.add('collapsed');
        }
        div.innerHTML = `
            <button type="button" class="alert-map-legend-toggle" aria-expanded="${mobileDefaultCollapsed ? 'false' : 'true'}">
                <span class="alert-map-legend-title">Alert Polygons</span>
                <span class="alert-map-legend-chevron" aria-hidden="true">▾</span>
            </button>
            <div class="alert-map-legend-body">
                <div class="alert-map-legend-row"><span class="legend-swatch warning"></span><span>Warning</span></div>
                <div class="alert-map-legend-row"><span class="legend-swatch watch"></span><span>Watch</span></div>
                <div class="alert-map-legend-row"><span class="legend-swatch advisory"></span><span>Advisory</span></div>
                <div class="alert-map-legend-row"><span class="legend-swatch statement"></span><span>Statement</span></div>
                <div class="alert-map-legend-row"><span class="legend-swatch outlook"></span><span>Outlook</span></div>
            </div>
        `;

        const toggleBtn = div.querySelector('.alert-map-legend-toggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                const collapsed = div.classList.toggle('collapsed');
                toggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            });
        }

        // Keep map interactions smooth while tapping legend controls.
        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.disableScrollPropagation(div);
        return div;
    };

    alertLegendControl.addTo(radarMap);
    updateAlertLegendVisibility();
}

function zoomToAlert(alert) {
    if (!radarMap || !alert?.geometry) return;
    const bounds = L.geoJSON({ type: 'Feature', geometry: alert.geometry }).getBounds();
    if (bounds.isValid()) {
        radarMap.fitBounds(bounds.pad(0.18), { maxZoom: 11 });
    }
}

function _overlayFetchLimitForZoom(zoom) {
    if (!Number.isFinite(zoom)) return 200;
    if (zoom <= 5) return 500;
    if (zoom <= 7) return 300;
    if (zoom <= 9) return 200;
    return 120;
}

function _roundedBounds(bounds) {
    const sw = bounds.getSouthWest();
    const ne = bounds.getNorthEast();
    const round2 = (v) => Math.round(v * 100) / 100;
    return {
        min_lat: round2(sw.lat),
        min_lon: round2(sw.lng),
        max_lat: round2(ne.lat),
        max_lon: round2(ne.lng),
    };
}

function _fireMarkerStyle(acres) {
    const n = Number(acres);
    if (!Number.isFinite(n) || n <= 0) {
        return { radius: 8, color: '#7f1d1d', fillColor: '#ef4444', fillOpacity: 0.86, weight: 1.8 };
    }
    if (n >= 10000) {
        return { radius: 14, color: '#7f1d1d', fillColor: '#dc2626', fillOpacity: 0.9, weight: 2.2 };
    }
    if (n >= 1000) {
        return { radius: 12, color: '#9a3412', fillColor: '#f97316', fillOpacity: 0.88, weight: 2 };
    }
    if (n >= 100) {
        return { radius: 10, color: '#92400e', fillColor: '#f59e0b', fillOpacity: 0.86, weight: 1.8 };
    }
    return { radius: 8, color: '#7f1d1d', fillColor: '#f97316', fillOpacity: 0.84, weight: 1.7 };
}

function _alertIntersectsViewport(alert, mapBounds) {
    if (!alert || !mapBounds || !mapBounds.isValid()) return false;
    if (!alert.geometry) return true;
    try {
        const bounds = L.geoJSON({ type: 'Feature', geometry: alert.geometry }).getBounds();
        return bounds.isValid() && mapBounds.intersects(bounds);
    } catch (err) {
        return false;
    }
}

function _effectiveAlertsInViewport() {
    return getDisplayAlerts();
}

async function refreshViewportAlerts(forceFetch = false) {
    if (!radarMap) return;
    const bounds = radarMap.getBounds();
    if (!bounds || !bounds.isValid()) return;

    const rounded = _roundedBounds(bounds);
    const endpoint = `/alerts?min_lat=${rounded.min_lat}&min_lon=${rounded.min_lon}&max_lat=${rounded.max_lat}&max_lon=${rounded.max_lon}`;
    try {
        const payload = forceFetch ? await fetchAPI(endpoint) : await fetchAPIDeduped(endpoint);
        cache.alertsViewport = Array.isArray(payload) ? payload : [];
        runtime.viewportAlertsLoaded = true;
    } catch (err) {
        // Keep last viewport alerts snapshot if a refresh fails.
    }
}

function updateAlertViewportCount() {
    const badge = document.getElementById('alert-count');
    if (!badge) return;
    const alerts = _effectiveAlertsInViewport();
    badge.textContent = alerts.length ? String(alerts.length) : '';
}

async function renderFireOverlay(forceFetch = false) {
    if (!radarMap) return;

    if (fireIncidentsLayer) {
        radarMap.removeLayer(fireIncidentsLayer);
        fireIncidentsLayer = null;
    }

    if (state.owmOverlay !== 'fires' || !state.showFireOverlay) return;

    const bounds = radarMap.getBounds();
    if (!bounds || !bounds.isValid()) return;

    const rounded = _roundedBounds(bounds);
    const limit = _overlayFetchLimitForZoom(radarMap.getZoom());
    const endpoint = `/firewatch?min_lat=${rounded.min_lat}&min_lon=${rounded.min_lon}&max_lat=${rounded.max_lat}&max_lon=${rounded.max_lon}&limit=${limit}`;
    let payload = null;
    if (forceFetch) {
        payload = await fetchAPI(endpoint);
    } else {
        payload = await fetchAPIDeduped(endpoint);
    }
    let incidents = Array.isArray(payload?.incidents) ? payload.incidents : [];
    if (!incidents.length) {
        // Fallback to sidebar cache if bbox feed is temporarily sparse/delayed.
        incidents = Array.isArray(cache.firewatch) ? cache.firewatch : [];
    }
    cache.firewatchViewport = incidents;
    if (!incidents.length) return;

    fireIncidentsLayer = L.layerGroup();
    incidents.forEach((incident) => {
        const lat = Number(incident?.location?.lat);
        const lon = Number(incident?.location?.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

        const style = _fireMarkerStyle(incident?.acres);
        const iconSize = Math.max(14, Math.round(style.radius * 2));
        const acresText = formatFirewatchAcres(incident?.acres);
        const containmentText = formatFirewatchContainment(incident?.containment_percent);
        const countyState = [incident?.county, incident?.state].filter(Boolean).join(', ');
        const updated = incident?.updated_at ? formatTime(incident.updated_at) : '--';

        const marker = L.marker([lat, lon], {
            icon: L.divIcon({
                className: 'fire-icon-marker',
                html: `<span style="font-size:${iconSize}px;filter: drop-shadow(0 0 2px rgba(0,0,0,0.65));">🔥</span>`,
                iconSize: [iconSize, iconSize],
                iconAnchor: [iconSize / 2, iconSize / 2],
            }),
            keyboard: true,
            title: incident?.name || 'Wildfire Incident',
        });
        marker.bindPopup(`
            <div style="min-width:220px">
                <strong>${escapeHtml(String(incident?.name || 'Wildfire Incident'))}</strong>
                <div>${escapeHtml(acresText)} · ${escapeHtml(containmentText)}</div>
                ${countyState ? `<div>${escapeHtml(countyState)}</div>` : ''}
                <div>Updated ${escapeHtml(updated)}</div>
            </div>
        `);
        marker.addTo(fireIncidentsLayer);
    });

    fireIncidentsLayer.addTo(radarMap);
    if (typeof fireIncidentsLayer.bringToFront === 'function') {
        fireIncidentsLayer.bringToFront();
    }

    // Keep sidebar list/count aligned with currently viewed incidents.
    renderFireWatch(false).catch(() => {});
}

function scheduleViewportOverlayRefresh(forceFetch = false) {
    if (!radarMap) return;
    if (viewportOverlayTimer) clearTimeout(viewportOverlayTimer);
    viewportOverlayTimer = setTimeout(async () => {
        await refreshViewportAlerts(forceFetch);
        updateAlertViewportCount();
        renderAlertPolygons();
        renderFireWatch(false).catch(() => {
            // Keep map responsive if sidebar firewatch filtering fails.
        });
        renderFireOverlay(forceFetch).catch(() => {
            // Keep map responsive even if fire overlay fetch fails.
        });
    }, 180);
}

function renderAlertPolygons() {
    if (!radarMap) return;

    updateAlertViewportCount();

    if (alertPolygonsLayer) {
        radarMap.removeLayer(alertPolygonsLayer);
        alertPolygonsLayer = null;
    }

    updateAlertLegendVisibility();
    if (!state.showAlertPolygons) return;

    const mapBounds = radarMap.getBounds();
    const inViewport = (geometry) => {
        if (!geometry || !mapBounds || !mapBounds.isValid()) return false;
        try {
            const bounds = L.geoJSON({ type: 'Feature', geometry }).getBounds();
            return bounds.isValid() && mapBounds.intersects(bounds);
        } catch (err) {
            return false;
        }
    };

    const features = getDisplayAlerts()
        .filter((alert) => alert && alert.geometry && inViewport(alert.geometry))
        .map((alert) => ({
            type: 'Feature',
            geometry: alert.geometry,
            properties: {
                id: alert.id,
                event: alert.event,
                headline: alert.headline,
                severity: alert.severity,
                urgency: alert.urgency,
                expires: alert.expires,
                areas_affected: alert.areas_affected,
                monitored_locations: alert.monitored_locations || [],
                synthetic: !!alert.synthetic,
            },
        }));

    if (features.length === 0) return;

    alertPolygonsLayer = L.geoJSON({ type: 'FeatureCollection', features }, {
        style: alertMapStyle,
        onEachFeature: (feature, layer) => {
            const props = feature.properties || {};
            const expires = props.expires ? `<div>Expires ${formatTime(props.expires)}</div>` : '';
            const urgency = props.urgency ? `<div>Urgency: ${props.urgency}</div>` : '';
            const areas = props.areas_affected ? `<div>${props.areas_affected}</div>` : '';
            const monitored = Array.isArray(props.monitored_locations) && props.monitored_locations.length
                ? `<div>Monitoring: ${props.monitored_locations.join(', ')}</div>`
                : '';
            const synthetic = props.synthetic ? '<div>Test polygon</div>' : '';
            layer.bindPopup(`
                <div style="min-width:220px">
                    <strong>${props.event || props.headline || 'Alert'}</strong>
                    <div>${props.severity || 'Unknown severity'}</div>
                    ${urgency}
                    ${expires}
                    ${monitored}
                    ${areas}
                    ${synthetic}
                </div>
            `);

            layer.on('click', () => {
                zoomToAlert(getAlertById(props.id));
            });
        },
    }).addTo(radarMap);

    if (typeof alertPolygonsLayer.bringToFront === 'function') {
        alertPolygonsLayer.bringToFront();
    }
}

function setStatus(text, type = 'loading') {
    const el = document.getElementById('status-pill');
    if (!el) return;
    if (state.isOffline || state.browserOffline) {
        // Show most recent successful sync age while offline.
        const syncAge = state.lastSyncTimestamp ? formatAgeShort(state.lastSyncTimestamp) : 'unknown';
        el.textContent = `OFFLINE - Last synced ${syncAge}`;
        el.className = `status-pill offline`;
    } else {
        el.textContent = text;
        el.className = `status-pill ${type}`;
    }
}


function setSourceDot(id, status) {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = `src-dot dot-${status}`;
}

function setElementVisible(el, visible) {
    if (!el) return;
    el.style.display = visible ? '' : 'none';
}

function updateOwmOverlayOptions(owmAvailable) {
    const select = document.getElementById('owm-overlay');
    if (!select) return;
    Array.from(select.options || []).forEach((opt) => {
        const isNone = String(opt.value || '') === 'none';
        const isFire = String(opt.value || '') === 'fires';
        // Fire overlay is keyless; keep it available even when OWM overlays are unavailable.
        opt.disabled = !isNone && !isFire && !owmAvailable;
        opt.hidden = !isNone && !isFire && !owmAvailable;
    });
    if (!owmAvailable && state.owmOverlay !== 'none' && state.owmOverlay !== 'fires') {
        state.owmOverlay = 'none';
        select.value = 'none';
    }
}

function signed(value, digits = 1) {
    if (value == null || Number.isNaN(value)) return '--';
    const n = Number(value);
    const abs = Math.abs(n).toFixed(digits);
    return `${n >= 0 ? '+' : '-'}${abs}`;
}

function toNumber(v) {
    if (v == null) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}

function firstDefined(...values) {
    for (const v of values) {
        if (v !== null && v !== undefined) return v;
    }
    return null;
}

function hPaToInHg(hPa) {
    const n = toNumber(hPa);
    return n == null ? null : n * 0.02953;
}

function metersToMiles(meters) {
    const n = toNumber(meters);
    return n == null ? null : n / 1609.344;
}

function buildCurrentSources() {
    const d = cache.current || {};
    const pwsStations = cache.pws?.stations || [];
    const primaryPws = pwsStations[0] || null;
    const owmCurrent = cache.owm && cache.owm.available !== false ? cache.owm.current : null;
    const sources = [];

    const nwsHasData = [
        d.temp_f,
        d.feels_like_f,
        d.humidity,
        d.wind_speed_mph,
        d.wind_gust_mph,
        d.pressure_inhg,
        d.visibility_miles,
        d.dewpoint_f,
    ].some((v) => v !== null && v !== undefined);
    if (nwsHasData) {
        sources.push({
            key: 'nws',
            label: 'NWS',
            tempF: d.temp_f,
            feelsF: d.feels_like_f,
            humidity: d.humidity,
            wind: d.wind_speed_mph,
            windDirDeg: toNumber(d.wind_direction),
            gust: d.wind_gust_mph,
            pressure: d.pressure_inhg,
            visibility: d.visibility_miles,
            dewpoint: d.dewpoint_f,
            description: d.description || '--',
            icon: d.icon || '',
            station: d.station ? `${d.station} (NWS)` : 'NWS',
            timestamp: d.timestamp,
            uv: null,
            sunrise: null,
            sunset: null,
        });
    }

    pwsStations.forEach((s) => {
        const stationName = PWS_NAMES[s.station_id] || s.station_id;
        sources.push({
            key: `pws:${s.station_id}`,
            label: `PWS: ${stationName}`,
            tempF: s.temp_f,
            feelsF: firstDefined(s.heat_index_f, s.temp_f),
            humidity: s.humidity,
            wind: s.wind_mph,
            windDirDeg: toNumber(s.winddir),
            gust: s.wind_gust_mph,
            pressure: s.pressure_inhg,
            visibility: null,
            dewpoint: s.dewpt_f,
            description: 'PWS observation',
            icon: '',
            station: `${stationName} (PWS)`,
            timestamp: s.obs_time_utc,
            uv: null,
            sunrise: null,
            sunset: null,
        });
    });

    if (owmCurrent) {
        const weather = Array.isArray(owmCurrent.weather) ? owmCurrent.weather[0] : null;
        const iconCode = weather?.icon;
        sources.push({
            key: 'owm',
            label: 'OpenWeather',
            tempF: toNumber(owmCurrent.temp),
            feelsF: toNumber(owmCurrent.feels_like),
            humidity: toNumber(owmCurrent.humidity),
            wind: toNumber(owmCurrent.wind_speed),
            windDirDeg: toNumber(owmCurrent.wind_deg),
            gust: toNumber(owmCurrent.wind_gust),
            pressure: hPaToInHg(owmCurrent.pressure),
            visibility: metersToMiles(owmCurrent.visibility),
            dewpoint: toNumber(owmCurrent.dew_point),
            description: weather?.description || 'OpenWeather model',
            icon: iconCode ? `https://openweathermap.org/img/wn/${iconCode}@2x.png` : '',
            station: 'OpenWeather Model (OWM)',
            timestamp: owmCurrent.dt,
            uv: firstDefined(owmCurrent.uvi, null),
            sunrise: firstDefined(owmCurrent.sunrise, null),
            sunset: firstDefined(owmCurrent.sunset, null),
        });
    }

    const pwsEnabled = !!cache.config?.providers?.pws?.enabled;
    const preferPwsInAuto = pwsEnabled && !!primaryPws;

    sources.push({
        key: 'auto',
        label: 'Auto Blend',
        tempF: preferPwsInAuto
            ? firstDefined(primaryPws?.temp_f, d.temp_f)
            : firstDefined(d.temp_f, primaryPws?.temp_f),
        feelsF: preferPwsInAuto
            ? firstDefined(primaryPws?.heat_index_f, primaryPws?.temp_f, d.feels_like_f)
            : firstDefined(d.feels_like_f, primaryPws?.heat_index_f, primaryPws?.temp_f),
        humidity: preferPwsInAuto
            ? firstDefined(primaryPws?.humidity, d.humidity)
            : firstDefined(d.humidity, primaryPws?.humidity),
        wind: preferPwsInAuto
            ? firstDefined(primaryPws?.wind_mph, d.wind_speed_mph)
            : firstDefined(d.wind_speed_mph, primaryPws?.wind_mph),
        windDirDeg: preferPwsInAuto
            ? firstDefined(toNumber(primaryPws?.winddir), toNumber(d.wind_direction))
            : firstDefined(toNumber(d.wind_direction), toNumber(primaryPws?.winddir)),
        gust: preferPwsInAuto
            ? firstDefined(primaryPws?.wind_gust_mph, d.wind_gust_mph)
            : firstDefined(d.wind_gust_mph, primaryPws?.wind_gust_mph),
        pressure: preferPwsInAuto
            ? firstDefined(primaryPws?.pressure_inhg, d.pressure_inhg)
            : firstDefined(d.pressure_inhg, primaryPws?.pressure_inhg),
        visibility: firstDefined(d.visibility_miles, null),
        dewpoint: preferPwsInAuto
            ? firstDefined(primaryPws?.dewpt_f, d.dewpoint_f)
            : firstDefined(d.dewpoint_f, primaryPws?.dewpt_f),
        description: preferPwsInAuto
            ? (primaryPws?.weather_desc || 'PWS observation')
            : (d.description || (primaryPws ? (primaryPws.weather_desc || 'PWS observation') : '--')),
        icon: preferPwsInAuto
            ? (primaryPws?.icon || d.icon || '')
            : (d.icon || primaryPws?.icon || ''),
        station: preferPwsInAuto
            ? `${PWS_NAMES[primaryPws.station_id] || primaryPws.station_id} (PWS)`
            : (d.station ? `${d.station} (NWS)` : (primaryPws ? `${PWS_NAMES[primaryPws.station_id] || primaryPws.station_id} (PWS)` : '--')),
        timestamp: preferPwsInAuto
            ? firstDefined(primaryPws?.obs_time_utc, d.timestamp)
            : firstDefined(d.timestamp, primaryPws?.obs_time_utc),
        uv: firstDefined(owmCurrent?.uvi, null),
        sunrise: firstDefined(owmCurrent?.sunrise, null),
        sunset: firstDefined(owmCurrent?.sunset, null),
    });

    return sources;
}

function getStoredCurrentSourceKey() {
    try {
        return window.localStorage.getItem(CURRENT_SOURCE_STORAGE_KEY) || null;
    } catch (err) {
        return null;
    }
}

function storeCurrentSourceKey(key) {
    if (!key) return;
    try {
        window.localStorage.setItem(CURRENT_SOURCE_STORAGE_KEY, key);
    } catch (err) {
        // Ignore storage failures (private mode/quota) and keep in-memory behavior.
    }
}

function updateCurrentSourceLabel() {
    const labelEl = document.getElementById('source-carousel-label');
    const prevBtn = document.getElementById('source-prev-btn');
    const nextBtn = document.getElementById('source-next-btn');
    const sources = cache.currentSources || [];

    if (sources.length === 0) {
        if (labelEl) labelEl.textContent = 'Auto Blend';
        if (prevBtn) prevBtn.disabled = true;
        if (nextBtn) nextBtn.disabled = true;
        return;
    }

    if (state.currentSourceIndex >= sources.length) state.currentSourceIndex = 0;
    if (state.currentSourceIndex < 0) state.currentSourceIndex = 0;

    const active = sources[state.currentSourceIndex];
    if (labelEl) labelEl.textContent = active.label;

    const canFlip = sources.length > 1;
    if (prevBtn) prevBtn.disabled = !canFlip;
    if (nextBtn) nextBtn.disabled = !canFlip;
}

async function changeCurrentSource(step) {
    const sources = cache.currentSources || [];
    if (sources.length < 2) return;
    const len = sources.length;
    state.currentSourceIndex = (state.currentSourceIndex + step + len) % len;
    const active = sources[state.currentSourceIndex];
    if (active?.key) storeCurrentSourceKey(active.key);
    await renderCurrent(false);
}

function metricArrow(delta, eps = 0.01) {
    if (delta == null || Number.isNaN(delta)) return '→';
    if (delta > eps) return '↑';
    if (delta < -eps) return '↓';
    return '→';
}

function metricArrowClass(delta, eps = 0.01) {
    if (delta == null || Number.isNaN(delta)) return 'flat';
    if (delta > eps) return 'up';
    if (delta < -eps) return 'down';
    return 'flat';
}

function sparklineSvg(values, color = '#4a9eff', width = 120, height = 28) {
    const nums = values.filter((v) => v != null && Number.isFinite(Number(v))).map(Number);
    if (nums.length < 2) return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><line x1="0" y1="${height / 2}" x2="${width}" y2="${height / 2}" stroke="#4a6278" stroke-width="1" stroke-dasharray="2 2" /></svg>`;

    const min = Math.min(...nums);
    const max = Math.max(...nums);
    const span = Math.max(max - min, 0.01);

    const pts = nums.map((v, i) => {
        const x = (i / (nums.length - 1)) * (width - 2) + 1;
        const y = height - 2 - ((v - min) / span) * (height - 4);
        return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(' ');

    return `
        <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="trend sparkline">
            <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
    `;
}

function computeStormIndex(current, alerts, pwsData) {
    let score = 0;
    const sevWeights = { extreme: 50, severe: 30, moderate: 15, minor: 8, unknown: 4 };
    (alerts || []).forEach((a) => { score += (sevWeights[alertSevClass(a.severity)] || 0); });

    const nwsgust = toNumber(current?.wind_gust_mph) || toNumber(current?.wind_speed_mph) || 0;
    const pwsGusts = (pwsData?.stations || []).map((s) => toNumber(s.wind_gust_mph) || toNumber(s.wind_mph) || 0);
    const maxGust = Math.max(nwsgust, ...pwsGusts, 0);
    if (maxGust >= 45) score += 35;
    else if (maxGust >= 35) score += 25;
    else if (maxGust >= 25) score += 15;
    else if (maxGust >= 15) score += 8;

    const minPressure = Math.min(
        toNumber(current?.pressure_inhg) || 99,
        ...((pwsData?.stations || []).map((s) => toNumber(s.pressure_inhg) || 99)),
    );
    if (minPressure < 29.6) score += 20;
    else if (minPressure < 29.8) score += 12;

    if (score >= 80) return { level: 'extreme', label: 'Extreme' };
    if (score >= 55) return { level: 'severe', label: 'Severe' };
    if (score >= 32) return { level: 'elevated', label: 'Elevated' };
    if (score >= 15) return { level: 'guarded', label: 'Guarded' };
    return { level: 'low', label: 'Low' };
}

function renderStormIndex() {
    const el = document.getElementById('storm-index');
    if (!el) return;
    const idx = computeStormIndex(cache.current, getEffectiveAlerts(), cache.pws);
    el.className = `storm-index ${idx.level}`;
    el.textContent = `Storm: ${idx.label}`;
}

function showError(msg) {
    const t = document.getElementById('error-toast');
    if (!t) return;
    t.textContent = msg;
    t.classList.remove('hidden');
    clearTimeout(showError._timer);
    showError._timer = setTimeout(() => t.classList.add('hidden'), 8000);
}

function clearError() {
    const t = document.getElementById('error-toast');
    if (t) t.classList.add('hidden');
}

// ============================================================================
// Persistent state and offline behavior
// ============================================================================

const PERSISTENT_STATE_KEY = 'weatherapp.persistentState';
const FRAME_CACHE_KEYS = new Set();
const FRAME_CACHE_MAX_BYTES = 5 * 1024 * 1024; // 5MB

function getPersistentState() {
    try {
        const json = window.localStorage.getItem(PERSISTENT_STATE_KEY);
        return json ? JSON.parse(json) : {};
    } catch (err) {
        console.warn('Failed to load persistent state:', err);
        return {};
    }
}

function savePersistentState(data) {
    try {
        data.savedAt = Date.now();
        window.localStorage.setItem(PERSISTENT_STATE_KEY, JSON.stringify(data));
    } catch (err) {
        console.warn('Failed to save persistent state:', err);
    }
}

function persistRuntimeCache() {
    savePersistentState({
        cache: {
            config: cache.config,
            current: cache.current,
            forecast: cache.forecast,
            hourly: cache.hourly,
            alerts: cache.alerts,
            firewatch: cache.firewatch,
            owm: cache.owm,
            pws: cache.pws,
            pwsTrend: cache.pwsTrend,
        },
        lastSyncTimestamp: state.lastSyncTimestamp,
    });
}

function restorePersistentState() {
    const persistent = getPersistentState();
    if (persistent.cache && persistent.cache.config) {
        cache.config = persistent.cache.config;
    }
    if (persistent.cache && persistent.cache.current) {
        cache.current = persistent.cache.current;
    }
    if (persistent.cache && persistent.cache.forecast) {
        cache.forecast = persistent.cache.forecast;
    }
    if (persistent.cache && persistent.cache.hourly) {
        cache.hourly = persistent.cache.hourly;
    }
    if (persistent.cache && persistent.cache.alerts) {
        cache.alerts = persistent.cache.alerts;
    }
    if (persistent.cache && persistent.cache.firewatch) {
        cache.firewatch = persistent.cache.firewatch;
    }
    if (persistent.cache && persistent.cache.owm) {
        cache.owm = persistent.cache.owm;
    }
    if (persistent.cache && persistent.cache.pws) {
        cache.pws = persistent.cache.pws;
    }
    if (persistent.cache && persistent.cache.pwsTrend) {
        cache.pwsTrend = persistent.cache.pwsTrend;
    }
    state.lastSyncTimestamp = persistent.lastSyncTimestamp || null;
}

// ============================================================================
// Local cache cleanup and lifecycle management
// ============================================================================

function getFrameCacheSizeBytes() {
    let total = 0;
    for (const key of FRAME_CACHE_KEYS) {
        const item = window.localStorage.getItem(key);
        if (item) total += item.length;
    }
    return total;
}

function cleanupFrameCache() {
    const currentSize = getFrameCacheSizeBytes();
    if (currentSize > FRAME_CACHE_MAX_BYTES) {
        // Sort by age and evict oldest
        const entries = Array.from(FRAME_CACHE_KEYS).map(key => {
            const item = window.localStorage.getItem(key);
            if (!item) return null;
            try {
                const data = JSON.parse(item);
                return { key, expires: data.expires || 0, size: item.length };
            } catch {
                return null;
            }
        }).filter(Boolean).sort((a, b) => a.expires - b.expires);

        let freed = 0;
        for (const entry of entries) {
            window.localStorage.removeItem(entry.key);
            FRAME_CACHE_KEYS.delete(entry.key);
            freed += entry.size;
            logMetric('cache_eviction', 1, { key: entry.key });
            if (currentSize - freed < FRAME_CACHE_MAX_BYTES * 0.8) break;
        }
    }
}

function cleanupExpiredLocalStorage() {
    const now = Date.now();
    const keysToDelete = [];
    for (let i = 0; i < window.localStorage.length; i++) {
        const key = window.localStorage.key(i);
        if (!key || !key.startsWith('frames:')) continue;
        try {
            const item = window.localStorage.getItem(key);
            if (!item) continue;
            const data = JSON.parse(item);
            if (data.expires && data.expires < now) {
                keysToDelete.push(key);
            }
        } catch {
            // Ignore parse errors
        }
    }
    keysToDelete.forEach(key => {
        window.localStorage.removeItem(key);
        FRAME_CACHE_KEYS.delete(key);
        logMetric('cache_cleanup', 1, { key });
    });
}

// ============================================================================
// Input validation and safe rendering
// ============================================================================

function validateResponse(data, schema) {
    if (!schema) return data; // No schema = no validation
    if (!data) return null;
    
    // Perform basic validation
    for (const key of Object.keys(schema)) {
        if (schema[key] && !data[key]) {
            logMetric('validation_error', 1, { missing_field: key, schema });
        }
    }
    return data;
}

function safeRender(renderFn, section = 'unknown') {
    try {
        return renderFn();
    } catch (err) {
        console.error(`Render error in ${section}:`, err);
        logMetric('render_error', 1, { section, error: err.message });
        showError(`Error rendering ${section}: ${err.message}`);
    }
}

// ============================================================================
// Runtime metrics and observability
// ============================================================================

const metrics = {
    cache_hits: 0,
    cache_misses: 0,
    api_calls: {},
    errors: {},
};

function logMetric(name, value = 1, tags = {}) {
    if (!metrics[name]) metrics[name] = 0;
    metrics[name] += value;
    if (state.showDebugPanel) {
        console.debug(`[METRIC] ${name}: +${value}`, tags);
    }
}

function logAPICall(endpoint, durationMs, statusCode = 200) {
    if (!metrics.api_calls[endpoint]) {
        metrics.api_calls[endpoint] = { count: 0, totalMs: 0, errors: 0 };
    }
    metrics.api_calls[endpoint].count++;
    metrics.api_calls[endpoint].totalMs += durationMs;
    if (statusCode >= 400) {
        metrics.api_calls[endpoint].errors++;
    }
}

function getDebugStats() {
    const stats = {
        cacheSize: getFrameCacheSizeBytes(),
        cacheMetrics: metrics,
        offlineStatus: state.isOffline,
        browserOffline: state.browserOffline,
        lastSync: state.lastSyncTimestamp,
        onlineTime: Date.now() - (state.lastSyncTimestamp || 0),
        inflightRequests: _inflightRequests.size,
    };
    return stats;
}

function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

async function refreshServerDebugStats(force = false) {
    const now = Date.now();
    if (!force && runtime.lastServerDebugAt && now - runtime.lastServerDebugAt < SERVER_DEBUG_REFRESH_MS) {
        return runtime.serverDebug;
    }
    try {
        runtime.serverDebug = await fetchAPIDeduped('/debug');
        runtime.lastServerDebugAt = now;
    } catch (err) {
        // Keep last known value to avoid noisy UI changes when debug fetch fails.
    }
    return runtime.serverDebug;
}

function renderDebugPanel() {
    const stats = getDebugStats();
    const networkEl = document.getElementById('debug-network');
    const lastSyncEl = document.getElementById('debug-last-sync');
    const refreshEl = document.getElementById('debug-refresh');
    const requestsEl = document.getElementById('debug-requests');
    const cacheEl = document.getElementById('debug-cache');
    const upstreamEl = document.getElementById('debug-upstream');
    const clientEl = document.getElementById('debug-client');
    const observabilityEl = document.getElementById('debug-observability');
    const pressureEl = document.getElementById('debug-pressure');
    const stabilityEl = document.getElementById('debug-stability');
    const trendEl = document.getElementById('debug-trend');
    const guidanceEl = document.getElementById('debug-guidance');

    if (networkEl) {
        const online = !(state.isOffline || state.browserOffline);
        networkEl.textContent = online ? 'Online' : 'Offline';
        networkEl.className = `debug-val ${online ? 'online' : 'offline'}`;
    }
    if (lastSyncEl) lastSyncEl.textContent = state.lastSyncTimestamp ? formatAgeShort(state.lastSyncTimestamp) : '--';
    if (refreshEl) refreshEl.textContent = state.stormMode ? 'Storm / 30s' : `${Math.round(state.refreshIntervalMs / 60000)}m`;
    if (requestsEl) {
        const reuses = stats.cacheMetrics.request_reuse || 0;
        requestsEl.textContent = `${stats.inflightRequests} active / ${reuses} reused`;
    }
    if (cacheEl) {
        const hits = stats.cacheMetrics.cache_hits || 0;
        const misses = stats.cacheMetrics.cache_misses || 0;
        cacheEl.textContent = `${formatBytes(stats.cacheSize)} (${hits}/${misses})`;
    }
    if (upstreamEl) {
        const upstream = runtime.serverDebug?.upstream_calls;
        const total = upstream?.total;
        const blocked = runtime.serverDebug?.rate_limit?.blocked_total ?? 0;
        upstreamEl.textContent = Number.isFinite(total) ? `${total} calls / ${blocked} blocked` : '--';
    }
    if (clientEl) clientEl.textContent = state.autoRefresh ? 'Auto refresh on' : 'Manual refresh';

    const obs = runtime.serverDebug?.observability;
    if (observabilityEl) {
        const overall = String(obs?.overall || '--').toUpperCase();
        observabilityEl.textContent = overall;
        observabilityEl.className = `debug-val ${overall === 'DEGRADED' ? 'offline' : 'online'}`;
    }
    if (pressureEl) {
        const retry = normalizePressure(obs?.retry_pressure);
        const cache = normalizePressure(obs?.cache_pressure);
        const rate = normalizePressure(obs?.rate_limit_pressure);
        pressureEl.innerHTML = [
            `Retry:<span class="pressure-token ${retry}">${pressureLabel(retry)}</span>`,
            `Cache:<span class="pressure-token ${cache}">${pressureLabel(cache)}</span>`,
            `Rate:<span class="pressure-token ${rate}">${pressureLabel(rate)}</span>`,
        ].join(' ');

        const snapshotScore = pressureScore(retry) + pressureScore(cache) + pressureScore(rate);
        runtime.observabilityHistory.push({ t: Date.now(), score: snapshotScore });
        if (runtime.observabilityHistory.length > 20) {
            runtime.observabilityHistory = runtime.observabilityHistory.slice(-20);
        }
    }
    if (stabilityEl) {
        const stability = String(obs?.stability || 'stable');
        const flaps = Number(obs?.flaps_10m || 0);
        const seconds = Number(obs?.seconds_since_last_change || 0);
        const age = Number.isFinite(seconds) ? `${Math.round(seconds / 60)}m` : '--';
        const label = stability === 'flapping' ? 'Flapping' : stability === 'watch' ? 'Watch' : 'Stable';
        stabilityEl.textContent = `${label} (${flaps}/10m, ${age})`;
        stabilityEl.className = `debug-val ${stability === 'flapping' ? 'offline' : stability === 'stable' ? 'online' : ''}`;
    }
    if (trendEl) {
        const trend = observabilityTrend();
        trendEl.textContent = `${trend.icon} ${trend.label}`;
        trendEl.className = `debug-val ${trend.cls}`;
    }
    if (guidanceEl) {
        const recs = Array.isArray(obs?.recommendations) ? obs.recommendations : [];
        guidanceEl.textContent = summarizeGuidance(obs, recs);
    }

    if (state.showDebugPanel) {
        console.log('=== DEBUG STATS ===', stats);
    }
}

window.getDebugStats = getDebugStats;
window.renderDebugPanel = renderDebugPanel;

let lastDebugReportAt = 0;
let lastDebugReportSignature = '';

async function reportDebugSnapshot(reason = 'manual') {
    const now = Date.now();
    const payload = {
        reason,
        reported_at: now,
        offline: state.isOffline,
        last_sync: state.lastSyncTimestamp,
        storm_mode: state.stormMode,
        auto_refresh: state.autoRefresh,
        refresh_interval_ms: state.refreshIntervalMs,
        radar_provider: state.radarProvider,
        inflight_requests: _inflightRequests.size,
        cache: getDebugStats(),
        icon_health: {
            fallback_count: runtime.iconFallbackCount,
            last_source_url: runtime.lastIconSourceUrl || null,
            last_failed_url: runtime.lastIconFailedUrl || null,
            last_failed_at: runtime.lastIconFailedAt,
            current_source_key: runtime.lastCurrentSourceKey || null,
            current_source_label: runtime.lastCurrentSourceLabel || null,
        },
    };
    const signature = JSON.stringify({
        offline: payload.offline,
        last_sync: payload.last_sync,
        inflight_requests: payload.inflight_requests,
        cache_size: payload.cache.cacheSize,
        icon_fallback_count: payload.icon_health.fallback_count,
        icon_failed_at: payload.icon_health.last_failed_at,
        reason: payload.reason,
    });

    if (signature === lastDebugReportSignature && now - lastDebugReportAt < 15000) return;

    lastDebugReportAt = now;
    lastDebugReportSignature = signature;

    try {
        await fetch('/api/debug/client', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
    } catch (err) {
        // Ignore diagnostics reporting failures.
    }

    renderDebugPanel();
}

// ============================================================================
async function fetchAPI(endpoint) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 20000);
    try {
        const headers = {};
        if (runtime.authToken) headers.Authorization = `Bearer ${runtime.authToken}`;
        const resp = await fetch(`/api${endpoint}`, { signal: controller.signal, headers });
        if (!resp.ok) throw new Error(`${endpoint} failed: ${resp.status}`);
        return await resp.json();
    } catch (err) {
        if (err.name === 'AbortError') throw new Error(`${endpoint} timed out`);
        throw err;
    } finally {
        clearTimeout(timeoutId);
    }
}

// Request deduplication: prevent duplicate in-flight requests
const _inflightRequests = new Map();

// Online/offline state tracking
let _lastSuccessfulFetch = Date.now();

async function fetchAPIDeduped(endpoint) {
    // If request already in flight, return the same promise
    if (_inflightRequests.has(endpoint)) {
        logMetric('request_reuse');
        return _inflightRequests.get(endpoint);
    }

    // Build request promise and capture timing for diagnostics.
    const startTime = Date.now();
    logMetric('cache_misses');
    
    const promise = fetchAPI(endpoint)
        .then(data => {
            _lastSuccessfulFetch = Date.now();
            state.isOffline = false;
            state.lastSyncTimestamp = Date.now();
            
            // Track API latency for debug panel visibility.
            const durationMs = Date.now() - startTime;
            logAPICall(endpoint, durationMs, 200);
            if (durationMs > 5000) {
                console.warn(`Slow API: ${endpoint} took ${durationMs}ms`);
            }
            return data;
        })
        .catch(err => {
            // Track request failure for diagnostics.
            const durationMs = Date.now() - startTime;
            logAPICall(endpoint, durationMs, 500);
            logMetric('api_error', 1, { endpoint, error: err.message });
            
            // If all requests have failed for >5 sec, assume offline
            if (Date.now() - _lastSuccessfulFetch > 5000) {
                state.isOffline = true;
            }
            throw err;
        })
        .finally(() => {
            // Clean up when done (success or error)
            _inflightRequests.delete(endpoint);
        });

    // Track it
    _inflightRequests.set(endpoint, promise);
    return promise;
}

async function renderHeader(forceFetch = false) {
    if (forceFetch || !cache.config) cache.config = await fetchAPIDeduped('/config');
    if (forceFetch || !cache.bootstrap) {
        try {
            cache.bootstrap = await fetchAPIDeduped('/bootstrap');
        } catch (err) {
            cache.bootstrap = cache.bootstrap || null;
        }
    }

    const lbl = document.getElementById('location-label');
    if (lbl) lbl.textContent = cache.config.label || 'Weather';

    const owmProvider = cache.bootstrap?.providers?.openweather || null;
    const owmUiAvailable = owmProvider
        ? !!(owmProvider.enabled && owmProvider.configured)
        : !!cache.config?.owm_available;

    const owmSelect = document.getElementById('owm-overlay');
    if (owmSelect) {
        // Keep selector visible so users can still choose "No Overlay" even when OWM is unavailable.
        setElementVisible(owmSelect, true);
        owmSelect.disabled = false;
        owmSelect.title = owmUiAvailable
            ? 'OpenWeather tile overlays'
            : '';
        updateOwmOverlayOptions(owmUiAvailable);
    }

    setElementVisible(document.getElementById('owm-dot'), owmUiAvailable);
    const owmAge = document.getElementById('owm-age');
    setElementVisible(owmAge ? owmAge.closest('.source-age-card') : null, owmUiAvailable);

    renderTimeline();
}

async function renderCurrent(forceFetch = false) {
    if (forceFetch || !cache.current) cache.current = await fetchAPIDeduped('/current');
    cache.currentSources = buildCurrentSources();
    if (cache.currentSources.length === 0) {
        cache.currentSources = [{
            key: 'auto',
            label: 'Auto Blend',
            tempF: null,
            feelsF: null,
            humidity: null,
            wind: null,
            windDirDeg: null,
            gust: null,
            pressure: null,
            visibility: null,
            dewpoint: null,
            description: '--',
            icon: '',
            station: '--',
            timestamp: null,
            uv: null,
            sunrise: null,
            sunset: null,
        }];
    }

    const wantedSourceKey = getStoredCurrentSourceKey();
    if (wantedSourceKey) {
        const wantedIdx = cache.currentSources.findIndex((s) => s.key === wantedSourceKey);
        if (wantedIdx >= 0) state.currentSourceIndex = wantedIdx;
    }

    if (state.currentSourceIndex >= cache.currentSources.length) state.currentSourceIndex = 0;
    const active = cache.currentSources[state.currentSourceIndex];
    storeCurrentSourceKey(active?.key);

    updateCurrentSourceLabel();

    document.getElementById('current-temp').textContent = displayTemp(active.tempF);
    document.getElementById('current-desc').textContent = active.description || '--';
    document.getElementById('feels-like').textContent = `Feels like ${displayTemp(active.feelsF)}`;
    document.getElementById('humidity').textContent = active.humidity != null ? `${Math.round(active.humidity)}%` : '--%';
    document.getElementById('wind-speed').textContent = displayWind(active.wind);
    document.getElementById('wind-dir').textContent = active.windDirDeg != null ? `${windDir(active.windDirDeg)} (${Math.round(active.windDirDeg)}°)` : '--';
    document.getElementById('wind-gust').textContent = active.gust != null ? displayWind(active.gust) : '--';
    document.getElementById('pressure').textContent = displayPressure(active.pressure);
    document.getElementById('visibility').textContent = active.visibility != null ? displayDist(active.visibility) : '--';
    document.getElementById('dewpoint').textContent = displayTemp(active.dewpoint);
    document.getElementById('current-station').textContent = active.station || '--';

    const icon = document.getElementById('current-icon');
    runtime.lastCurrentSourceKey = active.key || '';
    runtime.lastCurrentSourceLabel = active.label || '';
    runtime.lastIconSourceUrl = active.icon || '';
    icon.onerror = () => {
        runtime.iconFallbackCount += 1;
        runtime.lastIconFailedUrl = runtime.lastIconSourceUrl || '';
        runtime.lastIconFailedAt = Date.now();
        icon.onerror = null;
        icon.src = DEFAULT_WEATHER_ICON;
    };
    icon.src = active.icon || DEFAULT_WEATHER_ICON;
    icon.alt = active.description || 'Weather icon';

    document.getElementById('last-updated').textContent = active.timestamp ? `Updated ${formatTime(active.timestamp)}` : '--';
    document.getElementById('uv-index').textContent = active.uv != null ? `${Number(active.uv).toFixed(1)}` : '--';
    document.getElementById('sunrise').textContent = active.sunrise ? formatHM(active.sunrise) : '--';
    document.getElementById('sunset').textContent = active.sunset ? formatHM(active.sunset) : '--';

    renderStormIndex();
    renderSourceAges();
    renderTimeline();
}

async function renderMultiCurrent(forceFetch = false) {
    if (forceFetch || !cache.config) cache.config = await fetchAPIDeduped('/config');

    const section = document.getElementById('multi-current-section');
    const cards = document.getElementById('multi-current-cards');
    const count = document.getElementById('multi-current-count');
    const locations = getAlertLocations();

    if (locations.length <= 1) {
        section.style.display = 'none';
        cards.innerHTML = '';
        count.textContent = '';
        return;
    }

    section.style.display = '';
    count.textContent = String(locations.length);

    if (forceFetch || !cache.multiCurrent) cache.multiCurrent = await fetchAPIDeduped('/current/multi');
    const entries = Array.isArray(cache.multiCurrent?.locations) ? cache.multiCurrent.locations : [];
    cards.innerHTML = '';

    if (entries.length === 0) {
        cards.innerHTML = '<div class="multi-current-card is-error"><div class="multi-current-error">No comparison data available.</div></div>';
        return;
    }

    const primary = entries.find((entry) => entry?.ok && entry?.current) || null;
    const primaryTemp = toNumber(primary?.current?.temp_f);

    entries.forEach((entry) => {
        const current = entry?.current || {};
        const entryTemp = toNumber(current.temp_f);
        const tempDelta = entryTemp != null && primaryTemp != null ? entryTemp - primaryTemp : null;
        const compareText = entry?.role === 'primary'
            ? 'Primary monitored location'
            : tempDelta == null
                ? 'Comparison unavailable'
                : `${signed(tempDelta, 0)} vs ${primary?.label || 'primary'}`;
        const card = document.createElement('div');
        card.className = `multi-current-card${entry?.ok ? '' : ' is-error'}`;
        card.innerHTML = `
            <div class="multi-current-head">
                <div class="multi-current-name">${escapeHtml(entry?.label || 'Location')}</div>
                <div class="multi-current-updated">${current.timestamp ? `Updated ${formatTime(current.timestamp)}` : '--'}</div>
            </div>
            <div class="multi-current-temp-row">
                <div class="multi-current-temp">${entry?.ok ? displayTemp(current.temp_f) : '--'}</div>
                <div class="multi-current-source">${escapeHtml((current.source || '--').toUpperCase())}</div>
            </div>
            <div class="multi-current-desc">${escapeHtml(entry?.ok ? (current.description || '--') : 'Unavailable')}</div>
            <div class="multi-current-compare">${escapeHtml(compareText)}</div>
            ${entry?.ok ? `
                <div class="multi-current-grid">
                    <div><div class="pws-k">Feels</div><div class="pws-v">${displayTemp(current.feels_like_f)}</div></div>
                    <div><div class="pws-k">Wind</div><div class="pws-v">${displayWind(current.wind_speed_mph)}</div></div>
                    <div><div class="pws-k">Humidity</div><div class="pws-v">${current.humidity != null ? `${Math.round(current.humidity)}%` : '--'}</div></div>
                    <div><div class="pws-k">Pressure</div><div class="pws-v">${displayPressure(current.pressure_inhg)}</div></div>
                    <div><div class="pws-k">Visibility</div><div class="pws-v">${current.visibility_miles != null ? displayDist(current.visibility_miles) : '--'}</div></div>
                    <div><div class="pws-k">Station</div><div class="pws-v">${escapeHtml(current.station || '--')}</div></div>
                </div>`
                : `<div class="multi-current-error">${escapeHtml(entry?.error || 'Current conditions unavailable')}</div>`}
        `;
        cards.appendChild(card);
    });
}

function resetRadarView() {
    if (!radarMap || !cache.config) return;
    fitMapToAlertCoverage();
    if (state.radarProvider === 'rainviewer') {
        refreshRadar(false).catch(() => {});
    }
}

async function returnHomeView() {
    if (!radarMap || !cache.config) return;
    fitMapToAlertCoverage();
    await refreshViewportAlerts(true);
    updateAlertViewportCount();
    await renderAlerts(false);
    await renderFireWatch(false);
    scheduleViewportOverlayRefresh(true);
}

function updateAlertTicker(alerts) {
    const ticker = document.getElementById('alert-ticker');
    const tickerLabel = document.getElementById('ticker-label');
    const shell = document.querySelector('.app-shell');
    if (!ticker || !shell || !tickerLabel) return;

    if (!alerts || alerts.length === 0) {
        ticker.classList.add('hidden');
        shell.classList.remove('has-ticker');
        return;
    }

    const topAlert = alerts
        .map((alert) => ({ alert, tone: alertBannerTone(alert) }))
        .sort((a, b) => alertBannerPriority(b.tone) - alertBannerPriority(a.tone))[0];

    ticker.className = `alert-ticker ${topAlert.tone}`;
    tickerLabel.textContent = alertBannerLabel(topAlert.alert, topAlert.tone);
    document.getElementById('ticker-text').textContent = alerts
        .map((a) => {
            const expires = a.expires ? `, expires ${formatTime(a.expires)}` : '';
            return `${a.event || a.headline || 'Alert'}${expires}`;
        })
        .join(' | ');
    shell.classList.add('has-ticker');
}

function formatFirewatchAcres(acres) {
    const n = Number(acres);
    if (!Number.isFinite(n) || n < 0) return '--';
    if (n >= 1000) return `${Math.round(n).toLocaleString()} ac`;
    if (n >= 100) return `${Math.round(n)} ac`;
    return `${n.toFixed(1)} ac`;
}

function formatFirewatchContainment(percent) {
    const n = Number(percent);
    if (!Number.isFinite(n) || n < 0) return 'Containment --';
    return `Containment ${Math.round(Math.min(n, 100))}%`;
}

async function renderFireWatch(forceFetch = false) {
    const incidentsInViewport = (incidents) => {
        if (!radarMap) return incidents;
        const bounds = radarMap.getBounds();
        if (!bounds || !bounds.isValid()) return incidents;
        return incidents.filter((incident) => {
            const lat = Number(incident?.location?.lat);
            const lon = Number(incident?.location?.lon);
            return Number.isFinite(lat) && Number.isFinite(lon) && bounds.contains([lat, lon]);
        });
    };

    const renderFirewatchCards = (container, incidents) => {
        incidents.slice(0, 15).forEach((incident) => {
            const card = document.createElement('div');
            card.className = 'alert-card fire-card severe';

            const locs = Array.isArray(incident?.monitored_locations) ? incident.monitored_locations : [];
            const nearest = incident?.nearest_location ? `Nearest: ${escapeHtml(String(incident.nearest_location))}` : '';
            const distance = Number.isFinite(Number(incident?.nearest_distance_miles))
                ? `${Number(incident.nearest_distance_miles).toFixed(1)} mi`
                : '--';
            const updated = incident?.updated_at ? formatTime(incident.updated_at) : '--';
            const stateCounty = [incident?.county, incident?.state].filter(Boolean).join(', ');

            card.innerHTML = `
                <div class="alert-event">${escapeHtml(String(incident?.name || 'Wildfire Incident'))}</div>
                <div class="alert-meta">
                    <span>${escapeHtml(formatFirewatchAcres(incident?.acres))}</span>
                    <span>${escapeHtml(formatFirewatchContainment(incident?.containment_percent))}</span>
                    <span>${escapeHtml(distance)}</span>
                </div>
                ${stateCounty ? `<div class="alert-coverage">${escapeHtml(stateCounty)}</div>` : ''}
                ${nearest ? `<div class="alert-coverage">${nearest}</div>` : ''}
                ${locs.length ? `<div class="alert-coverage">Monitoring ${escapeHtml(locs.join(' · '))}</div>` : ''}
                <div class="alert-desc">Updated ${escapeHtml(updated)}</div>
            `;

            card.addEventListener('click', () => {
                const fireLat = Number(incident?.location?.lat);
                const fireLon = Number(incident?.location?.lon);
                if (radarMap && Number.isFinite(fireLat) && Number.isFinite(fireLon)) {
                    radarMap.setView([fireLat, fireLon], Math.max(radarMap.getZoom(), 8));
                }
            });

            container.appendChild(card);
        });
    };

    try {
        const container = document.getElementById('firewatch-container');
        const badge = document.getElementById('firewatch-count');
        if (!container || !badge) return;

        if (!Array.isArray(cache.firewatch)) {
            cache.firewatch = [];
        }
        const previousIncidents = Array.isArray(cache.firewatch) ? cache.firewatch.slice() : [];

        if (forceFetch || cache.firewatch.length === 0) {
            // Keep sidebar payload bounded to avoid client timeout on large incident sets.
            let payload = await fetchAPIDeduped('/firewatch?limit=60');
            let incidents = Array.isArray(payload?.incidents) ? payload.incidents : [];
            if (!incidents.length) {
                // One retry with slightly broader radius for sparse local data.
                payload = await fetchAPI('/firewatch?limit=60&radius_miles=500');
                incidents = Array.isArray(payload?.incidents) ? payload.incidents : [];
            }
            runtime.firewatchFeedError = String(payload?.error || '').trim();
            if (incidents.length > 0) {
                cache.firewatch = incidents;
            } else if (runtime.firewatchFeedError && previousIncidents.length > 0) {
                // Preserve the last known good incident list during transient feed delays.
                cache.firewatch = previousIncidents;
            } else {
                cache.firewatch = incidents;
            }
        }
        container.innerHTML = '';
        const sourceIncidents = Array.isArray(cache.firewatchViewport) && cache.firewatchViewport.length
            ? cache.firewatchViewport
            : cache.firewatch;
        const visibleIncidents = incidentsInViewport(sourceIncidents);
        badge.textContent = visibleIncidents.length ? String(visibleIncidents.length) : '';

        if (!sourceIncidents.length) {
            if (runtime.firewatchFeedError) {
                container.innerHTML = '<div class="no-alerts">Fire Watch live feed delayed - showing no incidents currently</div>';
            } else {
                container.innerHTML = '<div class="no-alerts">No nearby wildfire incidents</div>';
            }
            return;
        }

        if (!visibleIncidents.length) {
            container.innerHTML = '<div class="no-alerts">No incidents in current map view</div>';
            return;
        }

        if (runtime.firewatchFeedError) {
            const delayed = document.createElement('div');
            delayed.className = 'no-alerts';
            delayed.textContent = 'Fire Watch live feed delayed - showing last cached incidents';
            container.appendChild(delayed);
        }

        renderFirewatchCards(container, visibleIncidents);
    } catch (err) {
        // Firewatch is additive; keep the dashboard usable when upstream incident feeds fail.
        if (!Array.isArray(cache.firewatch)) {
            cache.firewatch = [];
        }
        runtime.firewatchFeedError = String(err?.message || err || 'fetch failed');
        const container = document.getElementById('firewatch-container');
        const badge = document.getElementById('firewatch-count');
        if (container) {
            if (cache.firewatch.length > 0) {
                // Keep previously-renderable data when fetch path fails.
                container.innerHTML = '<div class="no-alerts">Fire Watch live feed delayed - showing last cached incidents</div>';
                renderFirewatchCards(container, cache.firewatch);
            } else {
                container.innerHTML = '<div class="no-alerts">Fire Watch live feed delayed - showing no incidents currently</div>';
            }
        }
        if (badge) badge.textContent = cache.firewatch.length ? String(cache.firewatch.length) : '';
        return;
    }
}

async function renderAlerts(forceFetch = false) {
    if (forceFetch || cache.alerts.length === 0) cache.alerts = await fetchAPIDeduped('/alerts');

    const container = document.getElementById('alerts-container');
    container.innerHTML = '';

    const effectiveAlerts = _effectiveAlertsInViewport();

    const filtered = effectiveAlerts.filter((a) => {
        if (state.alertFilter === 'all') return true;
        return alertSevClass(a.severity) === state.alertFilter;
    });

    document.getElementById('alert-count').textContent = effectiveAlerts.length ? String(effectiveAlerts.length) : '';

    if (filtered.length === 0) {
        container.innerHTML = '<div class="no-alerts">No active alerts</div>';
        updateAlertTicker(getEffectiveAlerts());
        renderAlertPolygons();
        renderStormIndex();
        renderSourceAges();
        renderTimeline();
        return;
    }

    filtered.forEach((alert) => {
        const card = document.createElement('div');
        card.className = `alert-card ${alertSevClass(alert.severity)}`;
        if (alert.synthetic) card.classList.add('synthetic');
        const monitoredLocations = Array.isArray(alert.monitored_locations) ? alert.monitored_locations : [];
        card.innerHTML = `
            <div class="alert-event">${alert.event || alert.headline || 'Alert'}</div>
            <div class="alert-meta">
                <span>${alert.severity || ''}</span>
                <span>${alert.urgency || ''}</span>
                <span>${alert.expires ? `Expires ${formatTime(alert.expires)}` : ''}</span>
            </div>
            ${monitoredLocations.length ? `<div class="alert-coverage">Affects ${monitoredLocations.join(' · ')}</div>` : ''}
            ${alert.synthetic ? '<div class="alert-test-pill">Test polygon</div>' : ''}
            ${alert.description ? `<div class="alert-desc">${alert.description}</div>` : ''}
        `;
        card.addEventListener('click', () => {
            card.classList.toggle('expanded');
            if (alert.geometry) {
                if (!state.showAlertPolygons) {
                    state.showAlertPolygons = true;
                    const toggle = document.getElementById('alert-polygons-toggle');
                    if (toggle) toggle.checked = true;
                    renderAlertPolygons();
                }
                zoomToAlert(alert);
            }
        });
        container.appendChild(card);
    });

    // Keep home/work safety stream prioritized in ticker regardless of viewport.
    updateAlertTicker(getEffectiveAlerts());
    renderAlertPolygons();
    renderFireOverlay(false).catch(() => {});
    renderStormIndex();
    renderSourceAges();
    renderTimeline();
}

async function renderAstro(forceFetch = false) {
    if (forceFetch || !cache.astro) cache.astro = await fetchAPIDeduped('/astro');
    const astro = cache.astro || {};

    const formatAstro = (value) => (value ? formatHM(value) : '--');

    document.getElementById('astro-day').textContent = astro.day || '';
    document.getElementById('astro-sunrise').textContent = formatAstro(astro.sunrise);
    document.getElementById('astro-sunset').textContent = formatAstro(astro.sunset);
    document.getElementById('astro-solar-noon').textContent = formatAstro(astro.solar_noon);

    const goldenStart = formatAstro(astro.golden_hour_start);
    const goldenEnd = formatAstro(astro.golden_hour_end);
    document.getElementById('astro-golden').textContent = `${goldenStart} - ${goldenEnd}`;

    document.getElementById('astro-moon-phase').textContent = astro.moon_phase || '--';
    document.getElementById('astro-moon-illum').textContent = astro.moon_illumination != null ? `${astro.moon_illumination}%` : '--';
}

async function renderAqi(forceFetch = false) {
    if (forceFetch || !cache.config) cache.config = await fetchAPIDeduped('/config');
    if (forceFetch || !cache.aqi) cache.aqi = await fetchAPIDeduped('/aqi');
    const aqi = cache.aqi || {};
    const section = document.getElementById('aqi-section');

    section.style.display = '';

    if (!aqi.available) {
        document.getElementById('aqi-badge').textContent = '--';
        document.getElementById('aqi-badge').style.backgroundColor = '#4b5563';
        document.getElementById('aqi-index').textContent = '--';
        const src = aqi.source ? ` (${String(aqi.source)})` : '';
        document.getElementById('aqi-category').textContent = `Unavailable${src}`;
        document.getElementById('aqi-pm25').textContent = '--';
        document.getElementById('aqi-pm10').textContent = '--';
        document.getElementById('aqi-no2').textContent = '--';
        document.getElementById('aqi-o3').textContent = '--';
        return;
    }

    const aqiIndex = aqi.aqi || '--';
    const aqiColors = {1: '#2ecc71', 2: '#f1c40f', 3: '#e67e22', 4: '#e74c3c', 5: '#8b0000'};
    const aqiLabels = {1: 'Good', 2: 'Fair', 3: 'Moderate', 4: 'Poor', 5: 'Very Poor'};

    document.getElementById('aqi-badge').textContent = aqiIndex;
    document.getElementById('aqi-badge').style.backgroundColor = aqiColors[aqiIndex] || '#ccc';
    document.getElementById('aqi-index').textContent = aqiIndex;
    const sourceLabel = aqi.source ? ` (${String(aqi.source)})` : '';
    document.getElementById('aqi-category').textContent = `${aqiLabels[aqiIndex] || '--'}${sourceLabel}`;

    const components = aqi.components || {};
    document.getElementById('aqi-pm25').textContent = components.pm2_5 != null ? `${Math.round(components.pm2_5)} µg/m³` : '--';
    document.getElementById('aqi-pm10').textContent = components.pm10 != null ? `${Math.round(components.pm10)} µg/m³` : '--';
    document.getElementById('aqi-no2').textContent = components.no2 != null ? `${Math.round(components.no2)} ppb` : '--';
    document.getElementById('aqi-o3').textContent = components.o3 != null ? `${Math.round(components.o3)} ppb` : '--';
}

async function renderPws(forceFetch = false) {
    if (forceFetch || !cache.pws) cache.pws = await fetchAPIDeduped('/pws');
    if (forceFetch || !cache.pwsTrend) cache.pwsTrend = await fetchAPIDeduped(`/pws/trend?hours=${state.pwsTrendHours}`);

    const section = document.getElementById('pws-section');
    const cards = document.getElementById('pws-cards');
    const meta = document.getElementById('pws-meta');
    const delta = document.getElementById('pws-delta');

    const pws = cache.pws;
    const trendMap = new Map((cache.pwsTrend?.stations || []).map((s) => [s.station_id, s.points || []]));
    if (!pws || !Array.isArray(pws.stations) || pws.stations.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = '';
    meta.textContent = `${pws.stations.length} stations`;
    cards.innerHTML = '';

    pws.stations.forEach((s) => {
        const stationName = PWS_NAMES[s.station_id] || s.station_id;
        const tPoints = trendMap.get(s.station_id) || [];
        const temps = tPoints.map((p) => toNumber(p.temp_f)).filter((v) => v != null);
        const press = tPoints.map((p) => toNumber(p.pressure_inhg)).filter((v) => v != null);
        const tempDelta = temps.length >= 2 ? temps[temps.length - 1] - temps[0] : null;
        const pressDelta = press.length >= 2 ? press[press.length - 1] - press[0] : null;
        const card = document.createElement('div');
        card.className = 'pws-card';
        card.innerHTML = `
            <div class="pws-card-head">
                <div class="pws-name">${stationName}</div>
                <div class="pws-time">${formatHM(s.obs_time_utc)}</div>
            </div>
            <div class="pws-grid">
                <div><div class="pws-k">Temp</div><div class="pws-v">${displayTemp(s.temp_f)}</div></div>
                <div><div class="pws-k">Humidity</div><div class="pws-v">${s.humidity != null ? Math.round(s.humidity) + '%' : '--'}</div></div>
                <div><div class="pws-k">Wind</div><div class="pws-v">${displayWind(s.wind_mph)}</div></div>
                <div><div class="pws-k">Gust</div><div class="pws-v">${displayWind(s.wind_gust_mph)}</div></div>
                <div><div class="pws-k">Pressure</div><div class="pws-v">${displayPressure(s.pressure_inhg)}</div></div>
                <div><div class="pws-k">Rain Tot</div><div class="pws-v">${s.precip_total_in != null ? s.precip_total_in.toFixed(2) + ' in' : '--'}</div></div>
            </div>
            <div class="pws-trend-row">
                <div class="pws-trend-item">
                    <div class="pws-trend-label">Temp ${state.pwsTrendHours}h <span class="trend-arrow ${metricArrowClass(tempDelta, 0.1)}">${metricArrow(tempDelta, 0.1)}</span> ${signed(tempDelta, 1)}°F</div>
                    <div class="pws-spark">${sparklineSvg(temps, '#4a9eff')}</div>
                </div>
                <div class="pws-trend-item">
                    <div class="pws-trend-label">Pressure ${state.pwsTrendHours}h <span class="trend-arrow ${metricArrowClass(pressDelta, 0.01)}">${metricArrow(pressDelta, 0.01)}</span> ${signed(pressDelta, 2)} inHg</div>
                    <div class="pws-spark">${sparklineSvg(press, '#3dd68c')}</div>
                </div>
            </div>
        `;
        cards.appendChild(card);
    });

    if (pws.stations.length >= 2) {
        const [a, b] = pws.stations;
        const dt = toNumber(a.temp_f) - toNumber(b.temp_f);
        const dh = toNumber(a.humidity) - toNumber(b.humidity);
        const dp = toNumber(a.pressure_inhg) - toNumber(b.pressure_inhg);
        const dr = toNumber(a.precip_total_in) - toNumber(b.precip_total_in);
        const tClass = dt >= 0 ? 'pws-up' : 'pws-down';
        const hClass = dh >= 0 ? 'pws-up' : 'pws-down';
        const pClass = dp >= 0 ? 'pws-up' : 'pws-down';
        const rClass = dr >= 0 ? 'pws-up' : 'pws-down';
        delta.innerHTML = `
            <div class="pws-delta-line"><span>Temp Delta</span><span class="${tClass}">${signed(dt, 1)}°F</span></div>
            <div class="pws-delta-line"><span>Humidity Delta</span><span class="${hClass}">${signed(dh, 0)}%</span></div>
            <div class="pws-delta-line"><span>Pressure Delta</span><span class="${pClass}">${signed(dp, 2)} inHg</span></div>
            <div class="pws-delta-line"><span>Rain Total Delta</span><span class="${rClass}">${signed(dr, 2)} in</span></div>
        `;
    } else {
        delta.innerHTML = '<div class="pws-delta-line"><span>Need 2 stations for delta view</span><span>--</span></div>';
    }

    renderStormIndex();

    if (cache.current) {
        await renderCurrent(false);
    }

    renderSourceAges();
    renderTimeline();
}

async function renderForecast(forceFetch = false) {
    if (forceFetch || cache.forecast.length === 0) cache.forecast = await fetchAPIDeduped('/forecast');

    const list = document.getElementById('forecast-list');
    list.innerHTML = '';

    const filtered = cache.forecast.filter((p) => {
        if (state.forecastFilter === 'day') return p.is_daytime;
        if (state.forecastFilter === 'night') return !p.is_daytime;
        return true;
    });

    filtered.forEach((p) => {
        const row = document.createElement('div');
        row.className = 'fc-row';
        row.innerHTML = `
            <div class="fc-name">${p.name || ''}</div>
            <img class="fc-icon" src="${p.icon || ''}" alt="${p.short_forecast || ''}">
            <div class="fc-desc">${p.short_forecast || ''}</div>
            <div>
                <div class="fc-temp">${displayTemp(p.temp_f)}</div>
                ${p.precip_percent != null ? `<div class="fc-pop">${p.precip_percent}%</div>` : ''}
            </div>
        `;
        list.appendChild(row);
    });
}

async function renderOwmDaily(forceFetch = false) {
    if (forceFetch || !cache.owm) cache.owm = await fetchAPIDeduped('/owm');

    const section = document.getElementById('owm-daily-section');
    const list = document.getElementById('owm-daily-list');
    if (!cache.owm || !Array.isArray(cache.owm.daily) || cache.owm.daily.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = '';
    list.innerHTML = '';

    cache.owm.daily.forEach((d) => {
        const dayName = new Date(d.dt * 1000).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
        const icon = d.weather && d.weather[0] ? `https://openweathermap.org/img/wn/${d.weather[0].icon}.png` : '';
        const desc = d.weather && d.weather[0] ? d.weather[0].description : '';
        const pop = d.pop != null ? Math.round(d.pop * 100) : null;

        const row = document.createElement('div');
        row.className = 'fc-row';
        row.innerHTML = `
            <div class="fc-name">${dayName}</div>
            <img class="fc-icon" src="${icon}" alt="${desc}">
            <div class="fc-desc">${desc}</div>
            <div>
                <div class="fc-temp">${displayTemp(d.temp?.max)} / ${displayTemp(d.temp?.min)}</div>
                ${pop != null ? `<div class="fc-pop">${pop}%</div>` : ''}
            </div>
        `;
        list.appendChild(row);
    });
}

const locationImpactPlugin = {
    id: 'locationImpactLines',
    afterDatasetsDraw(chart, _args, pluginOptions) {
        const markers = pluginOptions?.markers || [];
        if (!Array.isArray(markers) || markers.length === 0) return;

        const xScale = chart.scales?.x;
        if (!xScale) return;

        const { ctx, chartArea } = chart;
        if (!chartArea) return;

        const groupedByIndex = new Map();
        markers.forEach((m) => {
            if (!groupedByIndex.has(m.index)) groupedByIndex.set(m.index, []);
            groupedByIndex.get(m.index).push(m);
        });

        ctx.save();
        ctx.textBaseline = 'top';
        ctx.font = '10px "Segoe UI", sans-serif';

        groupedByIndex.forEach((group, index) => {
            const baseX = xScale.getPixelForValue(index);
            group.forEach((marker, groupIdx) => {
                const x = baseX + (groupIdx * 10) - ((group.length - 1) * 5);

                ctx.strokeStyle = marker.color;
                ctx.lineWidth = 1.6;
                ctx.setLineDash([5, 4]);
                ctx.beginPath();
                ctx.moveTo(x, chartArea.top);
                ctx.lineTo(x, chartArea.bottom);
                ctx.stroke();

                ctx.setLineDash([]);
                const label = marker.ongoing ? `${marker.label} now` : marker.label;
                const textWidth = ctx.measureText(label).width;
                const padX = 5;
                const padY = 2;
                const boxW = textWidth + padX * 2;
                const boxH = 14;
                const boxX = Math.max(chartArea.left, Math.min(x - (boxW / 2), chartArea.right - boxW));
                const boxY = chartArea.top + 4 + (groupIdx * 16);

                ctx.fillStyle = 'rgba(7, 11, 16, 0.88)';
                ctx.fillRect(boxX, boxY, boxW, boxH);
                ctx.strokeStyle = marker.color;
                ctx.lineWidth = 1;
                ctx.strokeRect(boxX, boxY, boxW, boxH);

                ctx.fillStyle = marker.color;
                ctx.fillText(label, boxX + padX, boxY + padY);
            });
        });

        ctx.restore();
    },
};

function buildLocationImpactMarkers(hourlyPeriods, alerts) {
    if (!Array.isArray(hourlyPeriods) || hourlyPeriods.length === 0) return [];
    if (!Array.isArray(alerts) || alerts.length === 0) return [];

    const monitored = getAlertLocations();
    if (monitored.length === 0) return [];

    const hourlyTimes = hourlyPeriods.map((h) => parseTimestamp(h.start_time)).filter((ts) => ts != null);
    if (hourlyTimes.length === 0) return [];

    const startTs = hourlyTimes[0];
    const endTs = hourlyTimes[hourlyTimes.length - 1] + (60 * 60 * 1000);

    const pickNearestIndex = (targetTs) => {
        let bestIdx = 0;
        let bestDiff = Number.POSITIVE_INFINITY;
        hourlyTimes.forEach((ts, idx) => {
            const diff = Math.abs(ts - targetTs);
            if (diff < bestDiff) {
                bestDiff = diff;
                bestIdx = idx;
            }
        });
        return bestIdx;
    };

    const defaultColors = ['#ff8f8f', '#7bc4ff'];
    const markers = [];

    monitored.slice(0, 2).forEach((loc, locIdx) => {
        const displayLabel = locIdx === 0 ? 'Home' : (locIdx === 1 ? 'Office' : (loc.label || `Location ${locIdx + 1}`));
        const relevant = alerts
            .filter((alert) => Array.isArray(alert.monitored_locations) && alert.monitored_locations.includes(loc.label))
            .map((alert) => {
                const effective = parseTimestamp(alert.effective || alert.sent);
                const expires = parseTimestamp(alert.expires || alert.ends);
                return { effective, expires };
            })
            .filter((a) => a.effective != null && (a.expires == null || a.expires >= startTs) && a.effective <= endTs)
            .sort((a, b) => a.effective - b.effective);

        if (relevant.length === 0) return;

        const first = relevant[0];
        const ongoing = first.effective < startTs;
        const markerTs = ongoing ? startTs : first.effective;
        markers.push({
            index: pickNearestIndex(markerTs),
            label: displayLabel,
            color: defaultColors[locIdx] || '#b9c4d0',
            ongoing,
        });
    });

    return markers;
}

async function renderHourlyChart(forceFetch = false) {
    if (forceFetch || cache.hourly.length === 0) cache.hourly = await fetchAPIDeduped('/hourly');

    const labels = cache.hourly.map((h) => formatHM(h.start_time));
    const temps = cache.hourly.map((h) => state.units === 'c' ? fToC(h.temp_f) : h.temp_f);
    const pops = cache.hourly.map((h) => h.precip_percent || 0);
    const impactMarkers = buildLocationImpactMarkers(cache.hourly.slice(0, 48), getEffectiveAlerts());

    const ctx = document.getElementById('hourly-chart').getContext('2d');
    if (chartInstance) chartInstance.destroy();

    chartInstance = new Chart(ctx, {
        type: 'line',
        plugins: [locationImpactPlugin],
        data: {
            labels,
            datasets: [
                {
                    label: `Temp (°${state.units.toUpperCase()})`,
                    data: temps,
                    borderColor: '#4a9eff',
                    backgroundColor: 'rgba(74,158,255,0.08)',
                    borderWidth: 2,
                    fill: true,
                    pointRadius: 1,
                    tension: 0.35,
                    yAxisID: 'yTemp',
                },
                {
                    label: 'Precip %',
                    data: pops,
                    borderColor: '#3dd68c',
                    backgroundColor: 'rgba(61,214,140,0.15)',
                    borderWidth: 1.5,
                    fill: true,
                    pointRadius: 0,
                    tension: 0.35,
                    yAxisID: 'yPop',
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
                legend: { display: true, labels: { color: '#7e99b8', font: { size: 10 } } },
                locationImpactLines: {
                    markers: impactMarkers,
                },
            },
            scales: {
                x: { ticks: { color: '#4a6278', maxRotation: 0, font: { size: 9 } }, grid: { color: '#1b2537' } },
                yTemp: { position: 'left', ticks: { color: '#4a9eff', font: { size: 9 } }, grid: { color: '#1b2537' } },
                yPop: { position: 'right', min: 0, max: 100, ticks: { color: '#3dd68c', font: { size: 9 } }, grid: { drawOnChartArea: false } },
            },
        },
    });
}

async function renderHourlyTable(forceFetch = false) {
    if (forceFetch || cache.hourly.length === 0) cache.hourly = await fetchAPIDeduped('/hourly');
    const container = document.getElementById('hourly-table');
    container.innerHTML = '';

    cache.hourly.slice(0, 48).forEach((h) => {
        const cell = document.createElement('div');
        cell.className = 'hourly-cell';
        cell.innerHTML = `
            <div class="hcell-time">${formatHM(h.start_time)}</div>
            <img class="hcell-icon" src="${h.icon || ''}" alt="${h.short_forecast || ''}">
            <div class="hcell-temp">${displayTemp(h.temp_f)}</div>
            ${h.precip_percent != null ? `<div class="hcell-pop">${h.precip_percent}%</div>` : ''}
            <div class="hcell-wind">${displayWind(h.wind_speed)}</div>
        `;
        container.appendChild(cell);
    });
}

function renderHourly(forceFetch = false) {
    return state.hourlyView === 'chart' ? renderHourlyChart(forceFetch) : renderHourlyTable(forceFetch);
}

async function fetchRainViewerFrames() {
    const resp = await fetch('https://api.rainviewer.com/public/weather-maps.json');
    if (!resp.ok) throw new Error('RainViewer API failed');
    const data = await resp.json();
    radarHost = data.host || radarHost;
    return [...(data.radar?.past || []), ...(data.radar?.nowcast || [])];
}

function clearRadarOverlay() {
    if (radarMap && radarOverlayLayer) {
        radarMap.removeLayer(radarOverlayLayer);
        radarOverlayLayer = null;
    }
}

function floorToFiveMinuteUtc(date) {
    const d = new Date(date);
    d.setUTCSeconds(0, 0);
    d.setUTCMinutes(Math.floor(d.getUTCMinutes() / 5) * 5);
    return d;
}

function buildIemArchiveTimes(frameCount = 24, stepMinutes = 5) {
    // Computed fresh every call from Date.now() — no caching; the "latest" timestamp
    // advances every 5 minutes so a long-lived cache would produce stale frames.
    const latest = floorToFiveMinuteUtc(new Date(Date.now() - 8 * 60 * 1000));
    const times = [];
    for (let i = frameCount - 1; i >= 0; i -= 1) {
        const t = new Date(latest.getTime() - i * stepMinutes * 60 * 1000);
        times.push(t.toISOString().replace('.000Z', 'Z'));
    }
    return times;
}

function getFrameListCache(key) {
    try {
        const cacheKey = `frames:${key}`;
        const cached = window.localStorage.getItem(cacheKey);
        if (!cached) return null;
        
        const { data, expires } = JSON.parse(cached);
        FRAME_CACHE_KEYS.add(cacheKey);
        
        const now = Date.now();
        const offlineGraceMs = state.offlineExtendedCacheTtlSec * 1000;
        if (now < expires || ((state.isOffline || state.browserOffline) && now < expires + offlineGraceMs)) {
            logMetric('cache_hits');
            if (now >= expires) logMetric('offline_cache_extension');
            return data;
        }
        
        window.localStorage.removeItem(cacheKey);
        FRAME_CACHE_KEYS.delete(cacheKey);
    } catch (err) {
        // Ignore cache errors
    }
    return null;
}

function setFrameListCache(key, frames, ttlMs) {
    try {
        const expires = Date.now() + ttlMs;
        const cacheKey = `frames:${key}`;
        window.localStorage.setItem(cacheKey, JSON.stringify({ data: frames, expires }));
        FRAME_CACHE_KEYS.add(cacheKey);
        
        // Keep browser storage bounded over long-running sessions.
        if (getFrameCacheSizeBytes() > FRAME_CACHE_MAX_BYTES) {
            cleanupFrameCache();
        }
    } catch (err) {
        // Ignore cache write errors (quota exceeded, private mode)
        if (err.name === 'QuotaExceededError') {
            logMetric('cache_quota_exceeded');
            cleanupFrameCache();  // Force cleanup when quota exceeded
        }
    }
}

function setIemArchiveLayerTime(timeIso) {
    if (!radarMap) return;

    if (!radarOverlayLayer || state.radarProvider !== 'iem-archive') {
        clearRadarOverlay();
        radarOverlayLayer = L.tileLayer.wms('https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0r-t.cgi', {
            layers: 'nexrad-n0r-wmst',
            format: 'image/png',
            transparent: true,
            opacity: state.radarOpacity,
            version: '1.1.1',
            attribution: 'NEXRAD via Iowa Environmental Mesonet',
            maxZoom: 12,
            minZoom: 2,
            zIndex: 10,
        }).addTo(radarMap);
    }

    radarOverlayLayer.setParams({ TIME: timeIso }, false);
}

function addIemStaticLayer() {
    clearRadarOverlay();
    radarOverlayLayer = L.tileLayer('https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png', {
        attribution: 'NEXRAD via Iowa Environmental Mesonet',
        opacity: state.radarOpacity,
        maxZoom: 12,
        maxNativeZoom: 12,
        minZoom: 2,
        zIndex: 10,
    }).addTo(radarMap);
    document.getElementById('radar-time').textContent = 'Static NEXRAD';
}

function buildBaseMapLayer(providerId) {
    switch (providerId) {
        case 'osm':
            return L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; OpenStreetMap contributors',
                maxZoom: 19,
            });
        case 'carto_light':
            return L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
                attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
                maxZoom: 20,
            });
        case 'carto_dark':
            return L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
                maxZoom: 20,
            });
        case 'esri_street':
        default:
            return L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
                attribution: '&copy; Esri, DigitalGlobe, Earthstar Geographics, and the GIS User Community',
                maxZoom: 18,
            });
    }
}

function applyBaseMapProvider(providerId) {
    if (!radarMap) return;
    if (baseMapLayer && baseMapProviderApplied === providerId) return;
    if (baseMapLayer) {
        radarMap.removeLayer(baseMapLayer);
        baseMapLayer = null;
    }
    baseMapLayer = buildBaseMapLayer(providerId).addTo(radarMap);
    baseMapProviderApplied = providerId;
}

function applyOwmOverlay(layer) {
    if (!radarMap) return;
    if (owmOverlayLayer) {
        radarMap.removeLayer(owmOverlayLayer);
        owmOverlayLayer = null;
    }

    if (layer === 'fires') {
        state.showFireOverlay = true;
        const fireToggle = document.getElementById('fire-overlay-toggle');
        if (fireToggle) fireToggle.checked = true;
        scheduleViewportOverlayRefresh(true);
        return;
    }

    if (fireIncidentsLayer) {
        radarMap.removeLayer(fireIncidentsLayer);
        fireIncidentsLayer = null;
    }

    if (!layer || layer === 'none') return;

    if (!cache.config?.owm_available) {
        const select = document.getElementById('owm-overlay');
        if (select) select.value = 'none';
        state.owmOverlay = 'none';
        if (!runtime.owmOverlayWarned) {
            runtime.owmOverlayWarned = true;
            showError('OWM overlays require OpenWeather provider + API key in setup.');
        }
        return;
    }

    owmOverlayLayer = L.tileLayer(`/api/owm-tile/${layer}/{z}/{x}/{y}`, {
        attribution: 'OpenWeather',
        opacity: 0.7,
        maxZoom: 18,
        zIndex: 5,
    }).addTo(radarMap);

    owmOverlayLayer.on('tileerror', () => {
        if (runtime.owmOverlayWarned) return;
        runtime.owmOverlayWarned = true;
        showError('OWM overlay tiles unavailable. Check OpenWeather key/plan/provider settings.');
    });
}

function updateRadarControlAvailability() {
    const isAnimated = state.radarProvider === 'rainviewer' || state.radarProvider === 'iem-archive';
    ['radar-play-btn', 'radar-pause-btn', 'radar-step-back-btn', 'radar-step-forward-btn', 'radar-frame', 'radar-speed', 'radar-boomerang', 'radar-live-btn']
        .forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.disabled = !isAnimated;
        });
}

async function updateRadarFrame() {
    if (!radarMap) return;
    const slider = document.getElementById('radar-frame');

    if (state.radarProvider === 'rainviewer') {
        if (radarFrames.length === 0) {
            clearRadarOverlay();
            document.getElementById('radar-time').textContent = 'RainViewer unavailable';
            return;
        }
        const frame = radarFrames[currentRFrameIndex];
        const time = new Date(frame.time * 1000);
        document.getElementById('radar-time').textContent = time.toLocaleTimeString();

        clearRadarOverlay();
        radarOverlayLayer = L.tileLayer(`${radarHost}${frame.path}/256/{z}/{x}/{y}/2/1_1.png`, {
            attribution: 'RainViewer',
            zIndex: 10,
            opacity: state.radarOpacity,
            maxNativeZoom: RADAR_MAX_NATIVE_ZOOM,
            maxZoom: RADAR_MAX_NATIVE_ZOOM,
            minZoom: 2,
        }).addTo(radarMap);

        slider.max = String(Math.max(radarFrames.length - 1, 0));
        slider.value = String(currentRFrameIndex);
        return;
    }

    if (state.radarProvider === 'iem-archive') {
        if (iemState.times.length === 0) return;
        const timeIso = iemState.times[currentRFrameIndex];
        setIemArchiveLayerTime(timeIso);
        document.getElementById('radar-time').textContent = formatHM(timeIso);
        slider.max = String(Math.max(iemState.times.length - 1, 0));
        slider.value = String(currentRFrameIndex);
    }
}

function moveRadarFrame(step) {
    const frameCount = state.radarProvider === 'iem-archive' ? iemState.times.length : radarFrames.length;
    if (frameCount === 0) return;
    currentRFrameIndex = (currentRFrameIndex + step + frameCount) % frameCount;
    updateRadarFrame();
}

async function animateRadar() {
    const frameCount = state.radarProvider === 'iem-archive' ? iemState.times.length : radarFrames.length;
    if (!radarAnimating || frameCount === 0 || state.radarProvider === 'iem-static') return;

    if (state.radarBoomerang) {
        if (currentRFrameIndex === frameCount - 1) radarDirection = -1;
        if (currentRFrameIndex === 0) radarDirection = 1;
        currentRFrameIndex += radarDirection;
    } else {
        currentRFrameIndex = (currentRFrameIndex + 1) % frameCount;
    }

    await updateRadarFrame();
    setTimeout(animateRadar, state.radarSpeedMs);
}

async function refreshRadar(forceMetadata = false) {
    if (!radarMap) return;

    if (state.radarProvider === 'rainviewer') {
        if (radarMap.getZoom() > RADAR_MAX_NATIVE_ZOOM) {
            radarMap.setZoom(RADAR_MAX_NATIVE_ZOOM);
        }
        if (forceMetadata || radarFrames.length === 0) {
            radarFrames = await fetchRainViewerFrames();
            currentRFrameIndex = Math.max(radarFrames.length - 1, 0);
        }
        await updateRadarFrame();
        return;
    }

    if (state.radarProvider === 'iem-archive') {
        // Always recompute times — purely derived from Date.now(), no network cost.
        // Only reset the playhead on forceMetadata (init / provider switch) or if out of bounds.
        iemState.times = buildIemArchiveTimes(24, 5);
        if (forceMetadata || currentRFrameIndex >= iemState.times.length) {
            currentRFrameIndex = Math.max(iemState.times.length - 1, 0);
        }
        await updateRadarFrame();
        return;
    }

    addIemStaticLayer();
}

async function initRadar() {
    if (!cache.config) cache.config = await fetchAPIDeduped('/config');
    state.mapProvider = cache.config.map_provider || state.mapProvider;

    if (!radarMap) {
        // Default to NEXRAD zoom capability (18), dynamically adjusted per provider
        const initialMaxZoom = state.radarProvider === 'rainviewer' ? RADAR_MAX_NATIVE_ZOOM : 18;
        radarMap = L.map('radar-map', {
            maxZoom: initialMaxZoom,
            minZoom: 2,
        });

        applyBaseMapProvider(state.mapProvider);

        renderMonitoredLocationMarkers();
        fitMapToAlertCoverage();

        setTimeout(() => radarMap.invalidateSize(), 250);
    } else {
        applyBaseMapProvider(state.mapProvider);
        renderMonitoredLocationMarkers();
    }

    ensureAlertLegend();
    applyOwmOverlay(state.owmOverlay);
    updateRadarControlAvailability();
    scheduleViewportOverlayRefresh(false);
    if (!radarMap.__viewportOverlayBound) {
        radarMap.on('moveend zoomend', () => {
            // Viewport-scoped counts should update regardless of overlay selection.
            updateAlertViewportCount();
            renderFireWatch(false).catch(() => {
                // Keep map interactions smooth if sidebar update fails.
            });
            scheduleViewportOverlayRefresh(true);
        });
        radarMap.__viewportOverlayBound = true;
    }
    await refreshRadar(true);
}

function clearTimers() {
    if (timerFullRefresh) clearTimeout(timerFullRefresh);
    timerFullRefresh = null;
}

async function loadStormMode(forceFetch = false) {
    setStatus('Storm mode refresh...', 'loading');

    const criticalTasks = [
        renderHeader(false),
        renderCurrent(forceFetch),
        renderAlerts(forceFetch),
        renderFireWatch(forceFetch),
        renderPws(forceFetch),
        initRadar(),
    ];
    const criticalNames = ['header', 'current', 'alerts', 'firewatch', 'pws', 'radar'];
    const results = await Promise.allSettled(criticalTasks);
    const failures = [];

    results.forEach((result, idx) => {
        if (result.status === 'rejected') failures.push(criticalNames[idx]);
    });

    let owmUsable = !!(cache.owm && cache.owm.available !== false);
    try {
        cache.owm = await fetchAPIDeduped('/owm');
        owmUsable = !!(cache.owm && cache.owm.available !== false);
        await renderCurrent(false);
        await renderOwmDaily(false);
    } catch (err) {
        cache.owm = null;
        owmUsable = false;
    }

    if (!runtime.lastStormDetailRefreshAt || Date.now() - runtime.lastStormDetailRefreshAt >= STORM_MODE_DETAIL_REFRESH_MS) {
        runtime.lastStormDetailRefreshAt = Date.now();
        const detailResults = await Promise.allSettled([
            renderForecast(true),
            renderHourly(true),
        ]);
        if (detailResults[0].status === 'rejected') failures.push('forecast');
        if (detailResults[1].status === 'rejected') failures.push('hourly');
    }

    setSourceDot('nws-dot', failures.some((name) => ['header', 'current', 'alerts'].includes(name)) ? 'error' : 'ok');
    setSourceDot('owm-dot', owmUsable ? 'ok' : 'warn');
    setSourceDot('pws-dot', cache.pws?.stations?.length ? 'ok' : 'warn');

    const blockingFailures = failures.filter((name) => name !== 'firewatch');

    if (blockingFailures.length === 0) {
        clearError();
        setStatus('Storm mode live', 'ok');
        pushTimelineEvent('refresh', 'Storm mode refresh', 'Critical feeds refreshed successfully');
        
        // Persist latest good data for offline recovery.
        persistRuntimeCache();
    } else {
        showError(`Storm mode partial failure: ${blockingFailures.join(', ')}`);
        setStatus('Storm mode partial', 'warn');
        pushTimelineEvent('refresh', 'Storm mode partial', `Issues: ${blockingFailures.join(', ')}`);
    }

    // Keep status controls in sync with online/offline state.
    updateOfflineUI();
    
    // Track refresh success/failure rates.
    logMetric('storm_mode_refresh', 1, { failures: failures.length, success: failures.length === 0 });

    reportDebugSnapshot('storm-refresh');

    renderSourceAges();
    renderTimeline();
    renderDebugPanel();
}

function configureAutoRefresh() {
    clearTimers();
    if (!state.autoRefresh) return;

    const scheduleNext = () => {
        if (!state.autoRefresh) return;
        const baseMs = state.stormMode ? STORM_MODE_INTERVAL_MS : state.refreshIntervalMs;
        const jitterSpan = Math.max(1, Math.round(baseMs * REFRESH_JITTER_MAX_RATIO));
        const jitter = Math.floor(Math.random() * (jitterSpan * 2 + 1)) - jitterSpan;
        const delayMs = Math.max(1500, baseMs + jitter);

        timerFullRefresh = setTimeout(async () => {
            try {
                if (state.stormMode) await loadStormMode(true);
                else await loadAll(true);
            } catch (err) {
                console.error('Auto-refresh full update failed', err);
            } finally {
                scheduleNext();
            }
        }, delayMs);
    };

    scheduleNext();
}

function updateOfflineUI() {
    // Disable manual refresh controls while offline.
    const refreshBtn = document.getElementById('refresh-btn');
    const autoRefreshToggle = document.getElementById('auto-refresh-toggle');
    const stormModeToggle = document.getElementById('storm-mode-toggle');
    const effectiveOffline = state.isOffline || state.browserOffline;
    
    if (effectiveOffline) {
        if (refreshBtn) refreshBtn.disabled = true;
        if (autoRefreshToggle) autoRefreshToggle.disabled = true;
        if (stormModeToggle) stormModeToggle.disabled = true;
        setStatus(`OFFLINE - Last synced ${formatAgeShort(state.lastSyncTimestamp)}`, 'offline');
    } else {
        if (refreshBtn) refreshBtn.disabled = false;
        if (autoRefreshToggle) autoRefreshToggle.disabled = false;
        if (stormModeToggle) stormModeToggle.disabled = false;
    }
}

function setupStatus(message, tone = 'warn') {
    const el = document.getElementById('setup-status');
    if (!el) return;
    el.textContent = message;
    el.className = `setup-status ${tone}`;
}

// ---------------------------------------------------------------------------
// First-run blocking overlay
// ---------------------------------------------------------------------------
function showFirstRunOverlay() {
    const overlay = document.getElementById('firstrun-overlay');
    if (!overlay) return;
    overlay.classList.remove('hidden');
    populateTimezoneSelect('fr-timezone');
    // Pre-populate from existing config if available
    fetchAPIDeduped('/settings').then(settings => {
        const home = settings?.location?.home || {};
        const work = settings?.location?.work || {};
        const _set = (id, val) => { const el = document.getElementById(id); if (el && val != null) el.value = val; };
        _set('fr-home-label', home.label);
        _set('fr-home-lat', home.lat);
        _set('fr-home-lon', home.lon);
        populateTimezoneSelect('fr-timezone', settings?.location?.timezone);
        _set('fr-work-label', work.label);
        _set('fr-work-lat', work.lat);
        _set('fr-work-lon', work.lon);
        _set('fr-map-provider', settings?.map?.provider);
        const providers = settings?.providers || {};
        const providerFields = ['nws','weatherapi','tomorrow','visualcrossing','openweather','aviationweather','noaa_tides','meteomatics'];
        for (const pid of providerFields) {
            const el = document.getElementById(`fr-${pid}-enabled`);
            if (el && providers[pid]) el.checked = !!providers[pid].enabled;
        }
    }).catch(() => {});
}

function hideFirstRunOverlay() {
    const overlay = document.getElementById('firstrun-overlay');
    if (overlay) overlay.classList.add('hidden');
}

async function saveFirstRunSettings() {
    const statusEl = document.getElementById('firstrun-status');
    const saveBtn = document.getElementById('firstrun-save-btn');

    const homeLabel = document.getElementById('fr-home-label')?.value.trim() || 'Home';
    const homeLat = parseFloat(document.getElementById('fr-home-lat')?.value.trim());
    const homeLon = parseFloat(document.getElementById('fr-home-lon')?.value.trim());

    if (isNaN(homeLat) || isNaN(homeLon)) {
        if (statusEl) { statusEl.textContent = 'Latitude and longitude are required and must be numeric.'; statusEl.className = 'setup-status warn'; }
        return;
    }
    if (homeLat < -90 || homeLat > 90 || homeLon < -180 || homeLon > 180) {
        if (statusEl) { statusEl.textContent = 'Latitude must be -90 to 90 and longitude -180 to 180.'; statusEl.className = 'setup-status warn'; }
        return;
    }

    if (saveBtn) saveBtn.disabled = true;
    if (statusEl) { statusEl.textContent = 'Saving…'; statusEl.className = 'setup-status'; }

    const workLat = parseFloat(document.getElementById('fr-work-lat')?.value.trim());
    const workLon = parseFloat(document.getElementById('fr-work-lon')?.value.trim());
    const workLabel = document.getElementById('fr-work-label')?.value.trim() || 'Work';
    const hasWork = !isNaN(workLat) && !isNaN(workLon);
    const pwsStations = (document.getElementById('fr-pws-stations')?.value || '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    const buildProviders = () => {
        const result = {};
        const providerFields = ['nws','weatherapi','tomorrow','visualcrossing','openweather','pws','aviationweather','noaa_tides','meteomatics'];
        for (const pid of providerFields) {
            const enabled = document.getElementById(`fr-${pid}-enabled`)?.checked ?? false;
            const keyEl = document.getElementById(`fr-${pid}-key`);
            result[pid] = { enabled };
            if (keyEl?.value?.trim()) result[pid].api_key = keyEl.value.trim();
        }
        return result;
    };

    const payload = {
        location: {
            home: { lat: homeLat, lon: homeLon, label: homeLabel },
            ...(hasWork ? { work: { lat: workLat, lon: workLon, label: workLabel } } : {}),
            timezone: document.getElementById('fr-timezone')?.value.trim() || 'UTC',
        },
        pws: {
            provider: document.getElementById('fr-pws-provider')?.value.trim() || 'weather.com',
            stations: pwsStations,
        },
        map: { provider: document.getElementById('fr-map-provider')?.value || 'esri_street' },
        providers: buildProviders(),
        mark_first_run_complete: true,
    };

    try {
        const resp = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data?.detail || 'Save failed');

        runtime.firstRunRequired = false;
        hideFirstRunOverlay();
        cache.config = null;
        cache.current = null;
        if (statusEl) { statusEl.textContent = 'Saved!'; statusEl.className = 'setup-status ok'; }
        pushTimelineEvent('system', 'First-run setup complete', 'Dashboard launched with new settings');
        await loadAll(true);
    } catch (err) {
        if (statusEl) { statusEl.textContent = `Save failed: ${err.message}`; statusEl.className = 'setup-status warn'; }
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

function _wireFirstRunOverlay() {
    const saveBtn = document.getElementById('firstrun-save-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', () => saveFirstRunSettings());
    }
}

async function loadSetupSettings() {
    try {
        const settings = await fetchAPIDeduped('/settings');
        const home = settings?.location?.home || {};
        const work = settings?.location?.work || {};

        document.getElementById('setup-home-label').value = home.label || '';
        document.getElementById('setup-home-lat').value = home.lat ?? '';
        document.getElementById('setup-home-lon').value = home.lon ?? '';
        document.getElementById('setup-work-label').value = work.label || '';
        document.getElementById('setup-work-lat').value = work.lat ?? '';
        document.getElementById('setup-work-lon').value = work.lon ?? '';
        populateTimezoneSelect('setup-timezone', settings?.location?.timezone || 'UTC');
        document.getElementById('setup-user-agent').value = settings?.user_agent || '';
        document.getElementById('setup-map-provider').value = settings?.map?.provider || 'esri_street';
        document.getElementById('setup-pws-provider').value = settings?.pws?.provider || 'weather.com';
        document.getElementById('setup-pws-stations').value = (settings?.pws?.stations || []).join(', ');

        PROVIDER_IDS.forEach((pid) => {
            const enabledEl = document.getElementById(`setup-provider-${pid}-enabled`);
            if (enabledEl) enabledEl.checked = !!settings?.providers?.[pid]?.enabled;
        });

        document.getElementById('setup-auth-enabled').checked = !!settings?.auth?.enabled;
        document.getElementById('setup-auth-viewer-required').checked = !!settings?.auth?.require_viewer_login;
        document.getElementById('setup-auth-admin-user').value = settings?.auth?.admin_user || 'admin';
        document.getElementById('setup-auth-viewer-user').value = settings?.auth?.viewer_user || 'viewer';
        document.getElementById('setup-auth-admin-pass').value = '';
        document.getElementById('setup-auth-viewer-pass').value = '';

        ['openweather', 'pws', 'tomorrow', 'meteomatics', 'weatherapi', 'visualcrossing'].forEach((pid) => {
            const keyEl = document.getElementById(`setup-provider-${pid}-key`);
            if (keyEl) keyEl.value = '';
        });

        const src = settings?.secrets_source || {};
        setupStatus(`Loaded. Keys source: OWM=${src.owm || 'config'}, PWS=${src.pws || 'config'}`, 'ok');
    } catch (err) {
        setupStatus(`Failed to load settings: ${err.message}`, 'warn');
    }
}

async function saveSetupSettings() {
    const saveBtn = document.getElementById('setup-save-btn');
    if (saveBtn) saveBtn.disabled = true;

    const homeLat = Number(document.getElementById('setup-home-lat').value);
    const homeLon = Number(document.getElementById('setup-home-lon').value);
    const workLatRaw = document.getElementById('setup-work-lat').value.trim();
    const workLonRaw = document.getElementById('setup-work-lon').value.trim();

    if (!Number.isFinite(homeLat) || !Number.isFinite(homeLon)) {
        setupStatus('Home lat/lon must be valid numbers', 'warn');
        if (saveBtn) saveBtn.disabled = false;
        return;
    }
    if (homeLat < -90 || homeLat > 90 || homeLon < -180 || homeLon > 180) {
        setupStatus('Home lat must be -90 to 90 and lon -180 to 180', 'warn');
        if (saveBtn) saveBtn.disabled = false;
        return;
    }

    let work = null;
    if (workLatRaw && workLonRaw) {
        const workLat = Number(workLatRaw);
        const workLon = Number(workLonRaw);
        if (!Number.isFinite(workLat) || !Number.isFinite(workLon)) {
            setupStatus('Work lat/lon must be valid numbers', 'warn');
            if (saveBtn) saveBtn.disabled = false;
            return;
        }
        if (workLat < -90 || workLat > 90 || workLon < -180 || workLon > 180) {
            setupStatus('Work lat must be -90 to 90 and lon -180 to 180', 'warn');
            if (saveBtn) saveBtn.disabled = false;
            return;
        }
        work = {
            label: document.getElementById('setup-work-label').value.trim() || 'Work',
            lat: workLat,
            lon: workLon,
        };
    }

    const stationText = document.getElementById('setup-pws-stations').value;
    const stations = stationText.split(',').map((s) => s.trim()).filter(Boolean);

    const providers = {};
    PROVIDER_IDS.forEach((pid) => {
        const enabledEl = document.getElementById(`setup-provider-${pid}-enabled`);
        const keyEl = document.getElementById(`setup-provider-${pid}-key`);
        const providerPayload = {
            enabled: enabledEl ? !!enabledEl.checked : false,
        };
        if (keyEl) providerPayload.api_key = keyEl.value.trim();
        providers[pid] = providerPayload;
    });

    const authPayload = {
        enabled: !!document.getElementById('setup-auth-enabled').checked,
        require_viewer_login: !!document.getElementById('setup-auth-viewer-required').checked,
        admin_username: document.getElementById('setup-auth-admin-user').value.trim(),
        admin_password: document.getElementById('setup-auth-admin-pass').value.trim(),
        viewer_username: document.getElementById('setup-auth-viewer-user').value.trim(),
        viewer_password: document.getElementById('setup-auth-viewer-pass').value.trim(),
    };

    const payload = {
        location: {
            home: {
                label: document.getElementById('setup-home-label').value.trim() || 'Home',
                lat: homeLat,
                lon: homeLon,
            },
            work,
            timezone: document.getElementById('setup-timezone').value.trim() || 'UTC',
        },
        user_agent: document.getElementById('setup-user-agent').value.trim(),
        pws: {
            provider: document.getElementById('setup-pws-provider').value.trim() || 'weather.com',
            stations,
        },
        map: {
            provider: document.getElementById('setup-map-provider').value || 'esri_street',
        },
        providers,
        auth: authPayload,
        mark_first_run_complete: true,
    };

    try {
        const headers = { 'Content-Type': 'application/json' };
        if (runtime.authToken) headers.Authorization = `Bearer ${runtime.authToken}`;
        const resp = await fetch('/api/settings', {
            method: 'POST',
            headers,
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data?.detail || 'Save failed');

        setupStatus('Saved. Refreshing dashboard with new settings...', 'ok');
        cache.config = null;
        cache.alerts = [];
        cache.firewatch = [];
        cache.current = null;
        runtime.firstRunRequired = false;
        hideFirstRunOverlay();
        await loadAll(true);
        await refreshServerDebugStats(true);
        renderDebugPanel();
    } catch (err) {
        setupStatus(`Save failed: ${err.message}`, 'warn');
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

function authStatus(message, tone = 'warn') {
    const el = document.getElementById('auth-status');
    if (!el) return;
    el.textContent = message;
    el.className = `setup-status ${tone}`;
}

function openAuthModal(subtitle = 'Login to continue.') {
    const modal = document.getElementById('auth-modal');
    const subtitleEl = document.getElementById('auth-modal-subtitle');
    if (!modal) return;
    if (subtitleEl) subtitleEl.textContent = subtitle;
    modal.classList.remove('hidden');
    authStatus('Enter credentials.', 'warn');
}

function closeAuthModal() {
    const modal = document.getElementById('auth-modal');
    if (!modal) return;
    modal.classList.add('hidden');
}

async function loginWithModalForm() {
    const username = document.getElementById('auth-username').value.trim();
    const password = document.getElementById('auth-password').value;
    if (!username || !password) {
        authStatus('Username and password are required.', 'warn');
        return;
    }

    try {
        const resp = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data?.detail || 'Login failed');
        runtime.authToken = data.token;
        runtime.authUser = data.user;
        setStoredAuthToken(data.token);
        authStatus(`Logged in as ${data.user?.username || username}`, 'ok');
        setupStatus(`Logged in as ${data.user?.username || username}`, 'ok');
        closeAuthModal();
    } catch (err) {
        authStatus(`Login failed: ${err.message}`, 'warn');
    }
}

async function logoutSession() {
    // Revoke the token server-side (best-effort).
    if (runtime.authToken) {
        try {
            await fetch('/api/auth/logout', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${runtime.authToken}` },
            });
        } catch (_) {
            // If the server is unreachable the token will expire naturally.
        }
    }
    runtime.authToken = null;
    runtime.authUser = null;
    setStoredAuthToken(null);
    setupStatus('Logged out.', 'warn');
}

function setupControls() {
    _wireFirstRunOverlay();
    populateTimezoneSelect('fr-timezone');
    populateTimezoneSelect('setup-timezone');

    const setupToggleBtn = document.getElementById('setup-toggle-btn');
    if (setupToggleBtn) {
        setupToggleBtn.addEventListener('click', async () => {
            const body = document.getElementById('setup-body');
            const btn = document.getElementById('setup-toggle-btn');
            if (!body || !btn) return;
            const hidden = body.classList.toggle('hidden');
            btn.textContent = hidden ? 'Show' : 'Hide';
            if (!hidden) {
                await loadSetupSettings();
            }
        });
    }

    const setupSaveBtn = document.getElementById('setup-save-btn');
    if (setupSaveBtn) {
        setupSaveBtn.addEventListener('click', async () => {
            await saveSetupSettings();
        });
    }

    const setupAdminLoginBtn = document.getElementById('setup-admin-login-btn');
    if (setupAdminLoginBtn) {
        setupAdminLoginBtn.addEventListener('click', () => {
            openAuthModal('Admin login is required when auth is enabled.');
        });
    }

    const setupAdminLogoutBtn = document.getElementById('setup-admin-logout-btn');
    if (setupAdminLogoutBtn) {
        setupAdminLogoutBtn.addEventListener('click', async () => {
            await logoutSession();
        });
    }

    document.getElementById('auth-login-btn').addEventListener('click', async () => {
        await loginWithModalForm();
    });

    document.getElementById('auth-cancel-btn').addEventListener('click', () => {
        closeAuthModal();
    });

    document.getElementById('refresh-btn').addEventListener('click', async () => {
        if (state.isOffline || state.browserOffline) {
            // Avoid noisy retries when network is unavailable.
            showError('Cannot refresh: offline. Check your internet connection.');
            return;
        }
        if (state.stormMode) await loadStormMode(true);
        else await loadAll(true);
    });

    const pushToggleBtn = document.getElementById('push-toggle-btn');
    if (pushToggleBtn) {
        pushToggleBtn.addEventListener('click', async () => {
            await togglePushSubscription();
        });
    }

    document.getElementById('debug-report-btn').addEventListener('click', async () => {
        await reportDebugSnapshot('manual-panel-sync');
        setStatus('Debug snapshot synced', 'loading');
    });

    document.getElementById('unit-select').addEventListener('change', (e) => {
        state.units = e.target.value;
        renderCurrent(false);
        renderForecast(false);
        renderHourly(false);
        renderOwmDaily(false);
        renderTimeline();
    });

    document.getElementById('auto-refresh-toggle').addEventListener('change', (e) => {
        state.autoRefresh = e.target.checked;
        configureAutoRefresh();
        setStatus(state.autoRefresh ? 'Auto-refresh on' : 'Auto-refresh off', 'loading');
        pushTimelineEvent('system', 'Auto-refresh changed', state.autoRefresh ? 'Automatic refresh enabled' : 'Automatic refresh disabled');
        renderTimeline();
    });

    document.getElementById('storm-mode-toggle').addEventListener('change', async (e) => {
        state.stormMode = e.target.checked;
        updateStormModeUi();
        configureAutoRefresh();
        pushTimelineEvent('system', 'Storm mode', state.stormMode ? 'Critical feeds now refresh every 30 seconds' : 'Storm mode disabled');
        renderTimeline();
        if (state.stormMode) {
            await loadStormMode(true);
        }
    });

    document.getElementById('refresh-interval').addEventListener('change', (e) => {
        state.refreshIntervalMs = Number(e.target.value);
        if (state.autoRefresh) {
            configureAutoRefresh();
            const minutes = Math.round(state.refreshIntervalMs / 60000);
            setStatus(`Auto-refresh every ${minutes}m`, 'loading');
        }
        renderTimeline();
    });

    document.getElementById('pws-trend-hours').addEventListener('change', async (e) => {
        state.pwsTrendHours = Number(e.target.value);
        cache.pwsTrend = null;
        await renderPws(true);
    });

    document.getElementById('forecast-filter').addEventListener('change', (e) => {
        state.forecastFilter = e.target.value;
        renderForecast(false);
    });

    document.getElementById('alert-filter').addEventListener('change', (e) => {
        state.alertFilter = e.target.value;
        renderAlerts(false);
    });

    ['tornado', 'flood', 'thunderstorm'].forEach((key) => {
        const el = document.getElementById(`alert-layer-${key}`);
        if (!el) return;
        el.addEventListener('change', () => {
            state.alertLayerFilters[key] = el.checked;
            renderAlerts(false);
            updateAlertViewportCount();
            renderAlertPolygons();
        });
    });

    document.getElementById('alert-polygons-toggle').addEventListener('change', (e) => {
        state.showAlertPolygons = e.target.checked;
        renderAlertPolygons();
    });

    document.getElementById('fire-overlay-toggle').addEventListener('change', (e) => {
        state.showFireOverlay = e.target.checked;
        if (!state.showFireOverlay && fireIncidentsLayer && radarMap) {
            radarMap.removeLayer(fireIncidentsLayer);
            fireIncidentsLayer = null;
        }
        scheduleViewportOverlayRefresh(state.showFireOverlay);
    });

    document.getElementById('alert-test-toggle-btn').addEventListener('click', async () => {
        state.showTestAlert = !state.showTestAlert;
        updateAlertTestButton();
        await renderAlerts(false);
    });

    document.getElementById('source-prev-btn').addEventListener('click', async () => {
        await changeCurrentSource(-1);
    });

    document.getElementById('source-next-btn').addEventListener('click', async () => {
        await changeCurrentSource(1);
    });

    document.getElementById('radar-provider').addEventListener('change', async (e) => {
        state.radarProvider = e.target.value;
        radarAnimating = false;
        
        // Adjust map's maxZoom based on radar provider
        if (state.radarProvider === 'rainviewer') {
            radarMap.setMaxZoom(RADAR_MAX_NATIVE_ZOOM);  // RainViewer capped at 12
            const targetZoom = Math.min(Math.max(radarMap.getZoom(), RADAR_DEFAULT_ZOOM_RAINVIEWER), RADAR_MAX_NATIVE_ZOOM);
            radarMap.setZoom(targetZoom);
        } else {
            radarMap.setMaxZoom(18);  // NEXRAD supports standard tile zoom up to 18
            if (state.radarProvider === 'iem-static' && radarMap.getZoom() < RADAR_DEFAULT_ZOOM) {
                radarMap.setZoom(RADAR_DEFAULT_ZOOM);
            }
        }
        updateRadarControlAvailability();
        await refreshRadar(true);
    });

    document.getElementById('owm-overlay').addEventListener('change', (e) => {
        state.owmOverlay = e.target.value;
        applyOwmOverlay(state.owmOverlay);
    });

    document.getElementById('radar-opacity').addEventListener('input', (e) => {
        state.radarOpacity = Number(e.target.value);
        if (radarOverlayLayer) radarOverlayLayer.setOpacity(state.radarOpacity);
    });

    document.getElementById('radar-speed').addEventListener('input', (e) => {
        state.radarSpeedMs = Number(e.target.value);
    });

    document.getElementById('radar-frame').addEventListener('input', (e) => {
        radarAnimating = false;
        currentRFrameIndex = Number(e.target.value);
        updateRadarFrame();
    });

    document.getElementById('radar-boomerang').addEventListener('change', (e) => {
        state.radarBoomerang = e.target.checked;
    });

    document.getElementById('radar-play-btn').addEventListener('click', async () => {
        if (state.radarProvider === 'iem-static') return;
        radarAnimating = true;
        await animateRadar();
    });

    document.getElementById('radar-pause-btn').addEventListener('click', () => {
        radarAnimating = false;
    });

    document.getElementById('radar-step-back-btn').addEventListener('click', () => {
        radarAnimating = false;
        moveRadarFrame(-1);
    });

    document.getElementById('radar-step-forward-btn').addEventListener('click', () => {
        radarAnimating = false;
        moveRadarFrame(1);
    });

    document.getElementById('return-home-btn').addEventListener('click', async () => {
        await returnHomeView();
    });

    document.getElementById('radar-reset-view-btn').addEventListener('click', () => {
        resetRadarView();
    });

    document.getElementById('radar-live-btn').addEventListener('click', () => {
        radarAnimating = false;
        const frameCount = state.radarProvider === 'iem-archive' ? iemState.times.length : radarFrames.length;
        if (frameCount > 0) {
            currentRFrameIndex = frameCount - 1;  // Jump to latest frame
            updateRadarFrame();
        }
    });

    document.getElementById('tab-chart').addEventListener('click', () => {
        state.hourlyView = 'chart';
        document.getElementById('tab-chart').classList.add('tab-active');
        document.getElementById('tab-table').classList.remove('tab-active');
        document.getElementById('hourly-chart-wrap').classList.remove('hidden');
        document.getElementById('hourly-table-wrap').classList.add('hidden');
        renderHourlyChart(false);
    });

    document.getElementById('tab-table').addEventListener('click', () => {
        state.hourlyView = 'table';
        document.getElementById('tab-table').classList.add('tab-active');
        document.getElementById('tab-chart').classList.remove('tab-active');
        document.getElementById('hourly-table-wrap').classList.remove('hidden');
        document.getElementById('hourly-chart-wrap').classList.add('hidden');
        renderHourlyTable(false);
    });
}

async function loadAll(forceFetch = false) {
    setStatus('Loading...', 'loading');

    const tasks = [
        renderHeader(forceFetch),
        renderCurrent(forceFetch),
        renderMultiCurrent(forceFetch),
        renderForecast(forceFetch),
        renderHourly(forceFetch),
        renderAlerts(forceFetch),
        renderFireWatch(forceFetch),
        renderPushControls(forceFetch),
        renderPws(forceFetch),
        renderAstro(forceFetch),
        renderAqi(forceFetch),
        initRadar(),
    ];

    const sectionNames = ['header', 'current', 'multi-current', 'forecast', 'hourly', 'alerts', 'firewatch', 'push', 'pws', 'astro', 'aqi', 'radar'];
    const nwsResults = await Promise.allSettled(tasks);

    try {
        cache.owm = await fetchAPIDeduped('/owm');
        await renderOwmDaily(false);
    } catch (err) {
        cache.owm = null;
    }

    // Rebuild current source carousel after parallel tasks settle so PWS sources
    // are available even when OWM is unavailable/failing.
    await renderCurrent(false);

    const failures = [];
    nwsResults.forEach((result, idx) => {
        if (result.status === 'rejected') failures.push(sectionNames[idx]);
    });

    const owmUsable = !!(cache.owm && cache.owm.available !== false);
    const nwsHealth = getNwsObsHealth(cache.current?.timestamp);
    const activeSource = (cache.currentSources || [])[state.currentSourceIndex] || null;
    const activeHealth = getSourceHealth(activeSource);
    const nwsDotStatus = failures.length
        ? 'error'
        : (nwsHealth.level === 'stale' ? 'error' : (nwsHealth.level === 'questionable' ? 'warn' : 'ok'));
    setSourceDot('nws-dot', nwsDotStatus);
    setSourceDot('owm-dot', owmUsable ? 'ok' : 'warn');
    setSourceDot('pws-dot', cache.pws?.stations?.length ? 'ok' : 'warn');
    renderStormIndex();

    const blockingFailures = failures.filter((name) => name !== 'firewatch');

    if (blockingFailures.length === 0) {
        clearError();
        if (activeHealth.level === 'stale') {
            const age = Math.round(activeHealth.ageMin || 0);
            setStatus(`Live (${activeHealth.label} stale ${age}m)`, 'warn');
        } else if (activeHealth.level === 'questionable') {
            const age = Math.round(activeHealth.ageMin || 0);
            setStatus(`Live (${activeHealth.label} aging ${age}m)`, 'loading');
        } else {
            setStatus(owmUsable ? 'Live' : 'Live (NWS/PWS)', owmUsable ? 'ok' : 'loading');
        }
        pushTimelineEvent('refresh', forceFetch ? 'Full refresh' : 'Initial load', owmUsable ? 'All feeds updated' : 'Primary feeds updated');
        
        // Persist latest good data for offline recovery.
        persistRuntimeCache();
    } else {
        showError(`Some sections failed: ${blockingFailures.join(', ')}`);
        setStatus('Partial', 'warn');
        pushTimelineEvent('refresh', 'Partial refresh', `Issues: ${blockingFailures.join(', ')}`);
    }

    // Keep status controls in sync with online/offline state.
    updateOfflineUI();
    
    // Track refresh success/failure rates.
    logMetric('refresh_cycle', 1, { failures: failures.length, success: failures.length === 0 });

    reportDebugSnapshot(forceFetch ? 'full-refresh' : 'initial-load');
    await refreshServerDebugStats(forceFetch);

    renderSourceAges();
    renderTimeline();
    renderDebugPanel();
}

window.addEventListener('DOMContentLoaded', async () => {
    registerServiceWorker();
    runtime.authToken = getStoredAuthToken();

    // Phase 3: Restore persistent state from localStorage
    restorePersistentState();
    
    // Phase 4: Setup periodic cache cleanup (24 hours)
    setInterval(() => {
        cleanupExpiredLocalStorage();
        cleanupFrameCache();
        logMetric('cleanup_cycle');
    }, 24 * 60 * 60 * 1000);
    
    // Phase 3: Initialize offline UI
    updateOfflineUI();
    
    setupControls();
    initCollapsiblePanels();
    setupTimelineFilters();
    const compactPanelLayoutBtn = document.getElementById('compact-panel-layout-btn');
    if (compactPanelLayoutBtn) {
        compactPanelLayoutBtn.addEventListener('click', toggleCompactLayout);
    }
    const resetPanelLayoutBtn = document.getElementById('reset-panel-layout-btn');
    if (resetPanelLayoutBtn) {
        resetPanelLayoutBtn.addEventListener('click', resetCollapsiblePanels);
    }
    updateAlertTestButton();
    updateStormModeUi();
    await refreshServerDebugStats(true);

    try {
        const bootstrap = await fetchAPIDeduped('/bootstrap');
        runtime.firstRunRequired = !!bootstrap?.first_run_required;
        runtime.appVersion = String(bootstrap?.runtime_version?.version || runtime.appVersion || '--');
        runtime.appBuild = String(bootstrap?.runtime_version?.build || runtime.appBuild || '');
        renderRuntimeVersion();
        if (runtime.firstRunRequired) {
            showFirstRunOverlay();
        }
    } catch (err) {
        // If bootstrap fails we continue with existing behavior.
    }

    renderRuntimeVersion();

    renderDebugPanel();
    startAgeRefreshLoop();
    configureAutoRefresh();
    setInterval(() => {
        reportDebugSnapshot('heartbeat');
    }, 60000);
    await loadAll(true);
});

window.addEventListener('online', () => {
    state.browserOffline = false;
    pushTimelineEvent('system', 'Network restored', 'Browser reports online');
    updateOfflineUI();
    renderDebugPanel();
});

window.addEventListener('keydown', (event) => {
    if (isTypingContext(event.target)) return;
    if (event.key === 'C' && event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        toggleCompactLayout();
    }
});

// Invalidate Leaflet map size on orientation change / window resize
// (debounced — waits for CSS reflow to settle before resizing map tiles)
let _resizeTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(() => {
        if (typeof radarMap !== 'undefined' && radarMap) {
            radarMap.invalidateSize();
        }
    }, 200);
});

window.addEventListener('offline', () => {
    state.browserOffline = true;
    pushTimelineEvent('system', 'Network offline', 'Browser reports offline');
    updateOfflineUI();
    renderDebugPanel();
});

setInterval(() => {
    updateOfflineUI();
    renderDebugPanel();
}, 30000);
