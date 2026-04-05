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
let AUTH_MODE = { enabled: false, require_viewer_login: false };
let PROVIDER_TTL_DEFAULTS = {};
let PROVIDER_TTL_BOUNDS = { min_seconds: 60, max_seconds: 86400 };
let FORM_STATE = {};
let UNSAVED_CHANGES = false;
let OBS_LAST_SUCCESS_MS = 0;
let OBS_POLL_TIMER = null;

const OBS_POLL_INTERVAL_MS = 45000;
const OBS_STALE_WARN_MS = 120000;
const OBS_HISTORY_MAX = 20;
const OBS_HISTORY = [];

const PULL_CYCLE_LABELS = {
    nws: 'NWS',
    openweather: 'OpenWeather',
    pws: 'PWS',
    tomorrow: 'Tomorrow.io',
    meteomatics: 'Meteomatics',
    weatherapi: 'WeatherAPI',
    visualcrossing: 'Visual Crossing',
    aviationweather: 'AviationWeather',
    noaa_tides: 'NOAA Tides',
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

function estimateCallsPerHour(seconds) {
    const safe = Math.max(1, Number(seconds) || 1);
    return Math.round((3600 / safe) * 10) / 10;
}

function estimateCallsPerDay(seconds) {
    const safe = Math.max(1, Number(seconds) || 1);
    return Math.round((86400 / safe) * 10) / 10;
}

function formatSecondsAsTime(seconds) {
    const safe = Math.max(1, Number(seconds) || 1);
    if (safe < 60) return `${safe}s`;
    if (safe < 3600) return `${Math.round(safe / 60 * 10) / 10}m`;
    if (safe < 86400) return `${Math.round(safe / 3600 * 10) / 10}h`;
    return `${Math.round(safe / 86400 * 10) / 10}d`;
}

function clampCycle(seconds) {
    const min = Number(PROVIDER_TTL_BOUNDS?.min_seconds || 60);
    const max = Number(PROVIDER_TTL_BOUNDS?.max_seconds || 86400);
    const raw = Number(seconds);
    if (!Number.isFinite(raw)) return min;
    return Math.min(max, Math.max(min, Math.round(raw)));
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

function setupPullCycleListeners() {
    document.querySelectorAll('input[data-provider-id]').forEach((input) => {
        input.addEventListener('change', markUnsaved);
        input.addEventListener('input', markUnsaved);
    });
}

function collectProviderPullCycles() {
    const result = {};
    Object.keys(PULL_CYCLE_LABELS).forEach((providerId) => {
        const input = document.getElementById(`pullcycle-${providerId}`);
        if (!input) return;
        result[providerId] = clampCycle(input.value);
    });
    return result;
}

function getToken() {
    try { return window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || ''; } catch (_) { return ''; }
}

function setToken(token) {
    try {
        if (token) window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
        else window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    } catch (_) {
        // ignore
    }
}

function setStatus(id, message, tone = 'warn') {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = message;
    el.className = `setup-status ${tone}`;
}

function prettyPressureLevel(level) {
    const raw = String(level || 'unknown').toLowerCase();
    if (raw === 'normal') return 'Normal';
    if (raw === 'elevated') return 'Elevated';
    if (raw === 'high') return 'High';
    return 'Unknown';
}

function applyObsLevel(el, level) {
    if (!el) return;
    const raw = String(level || 'unknown').toLowerCase();
    el.classList.remove('obs-normal', 'obs-elevated', 'obs-high');
    if (raw === 'normal') el.classList.add('obs-normal');
    else if (raw === 'elevated') el.classList.add('obs-elevated');
    else if (raw === 'high') el.classList.add('obs-high');
}

function renderObservability(obs) {
    const overallEl = document.getElementById('obs-overall');
    const retryEl = document.getElementById('obs-retry');
    const cacheEl = document.getElementById('obs-cache');
    const rateEl = document.getElementById('obs-rate');
    const statsEl = document.getElementById('obs-stats');
    const updatedEl = document.getElementById('obs-updated');
    const actionsEl = document.getElementById('obs-actions');
    const historyEl = document.getElementById('obs-history');

    if (!obs || typeof obs !== 'object') {
        if (statsEl) statsEl.textContent = 'Observability payload unavailable.';
        return;
    }

    const overall = String(obs.overall || 'unknown').toUpperCase();
    const retry = prettyPressureLevel(obs.retry_pressure);
    const cache = prettyPressureLevel(obs.cache_pressure);
    const rate = prettyPressureLevel(obs.rate_limit_pressure);

    if (overallEl) {
        overallEl.textContent = overall;
        applyObsLevel(overallEl, obs.overall === 'degraded' ? 'high' : obs.overall === 'warning' ? 'elevated' : 'normal');
    }
    if (retryEl) {
        retryEl.textContent = retry;
        applyObsLevel(retryEl, obs.retry_pressure);
    }
    if (cacheEl) {
        cacheEl.textContent = cache;
        applyObsLevel(cacheEl, obs.cache_pressure);
    }
    if (rateEl) {
        rateEl.textContent = rate;
        applyObsLevel(rateEl, obs.rate_limit_pressure);
    }

    const retryAttempted = Number(obs.retry_attempted_total || 0);
    const retryExhausted = Number(obs.retry_exhausted_total || 0);
    const cacheHitRatio = Number(obs.cache_hit_ratio || 0);
    const cacheLookups = Number(obs.cache_lookups || 0);
    const recommendations = Array.isArray(obs.recommendations) ? obs.recommendations : [];
    if (statsEl) {
        statsEl.textContent = `Retries attempted: ${retryAttempted} | Retries exhausted: ${retryExhausted} | Cache hit ratio: ${(cacheHitRatio * 100).toFixed(1)}% (${cacheLookups} lookups)`;
    }
    if (actionsEl) {
        const actionText = recommendations.length ? recommendations.join(' | ') : 'System telemetry looks healthy. Continue normal monitoring.';
        actionsEl.textContent = `Recommendations: ${actionText}`;
    }

    OBS_HISTORY.push({
        at: new Date(),
        overall,
        retry,
        cache,
        rate,
    });
    if (OBS_HISTORY.length > OBS_HISTORY_MAX) {
        OBS_HISTORY.splice(0, OBS_HISTORY.length - OBS_HISTORY_MAX);
    }
    if (historyEl) {
        const recentItems = OBS_HISTORY.slice(-8);
        const timeLabels = recentItems.map((item) => item.at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit'})).join(' ');
        const healthDots = recentItems.map((item) => {
            if (item.overall === 'HEALTHY') return '🟢';
            if (item.overall === 'WARNING') return '🟡';
            if (item.overall === 'DEGRADED') return '🔴';
            return '⚪';
        }).join('');
        historyEl.textContent = `History: ${healthDots} (${timeLabels})`;
        historyEl.title = recentItems.map((item) => `${item.at.toLocaleTimeString()}: ${item.overall} (Retry: ${item.retry}, Cache: ${item.cache}, Rate: ${item.rate})`).join(' | ');
    }

    if (updatedEl) {
        updatedEl.textContent = `Updated: ${new Date().toLocaleTimeString()}`;
    }
}

async function loadObservability() {
    const refreshBtn = document.getElementById('obs-refresh-btn');
    const statsEl = document.getElementById('obs-stats');
    if (refreshBtn) refreshBtn.disabled = true;
    try {
        const payload = await api('/debug');
        renderObservability(payload?.observability || {});
        OBS_LAST_SUCCESS_MS = Date.now();
    } catch (err) {
        if (statsEl) statsEl.textContent = `Observability load failed: ${err.message}`;
    } finally {
        updateObservabilityStaleness();
        if (refreshBtn) refreshBtn.disabled = false;
    }
}

function updateObservabilityStaleness() {
    const staleEl = document.getElementById('obs-stale');
    if (!staleEl) return;
    if (!OBS_LAST_SUCCESS_MS) {
        staleEl.textContent = 'Staleness: unknown';
        staleEl.className = 'pws-meta';
        return;
    }
    const ageMs = Date.now() - OBS_LAST_SUCCESS_MS;
    const ageSec = Math.max(0, Math.round(ageMs / 1000));
    const stale = ageMs >= OBS_STALE_WARN_MS;
    staleEl.textContent = `Staleness: ${ageSec}s old${stale ? ' (stale)' : ''}`;
    staleEl.className = stale ? 'pws-meta warn' : 'pws-meta';
}

async function loadObservabilityAuto() {
    if (document.visibilityState === 'hidden') {
        updateObservabilityStaleness();
        return;
    }
    try {
        const payload = await api('/debug');
        renderObservability(payload?.observability || {});
        OBS_LAST_SUCCESS_MS = Date.now();
    } catch (_) {
        // Keep background polling silent to avoid status churn.
    } finally {
        updateObservabilityStaleness();
    }
}

function startObservabilityPolling() {
    if (OBS_POLL_TIMER) clearInterval(OBS_POLL_TIMER);
    OBS_POLL_TIMER = setInterval(loadObservabilityAuto, OBS_POLL_INTERVAL_MS);
}

async function api(path, method = 'GET', body = null, includeAuth = true) {
    const headers = { 'Content-Type': 'application/json' };
    if (includeAuth) {
        const token = getToken();
        if (token) headers.Authorization = `Bearer ${token}`;
    }
    const resp = await fetch(`/api${path}`, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        throw new Error(data?.detail || `${path} failed: ${resp.status}`);
    }
    return data;
}

function selectedScopes() {
    const scopes = [];
    if (document.getElementById('scope-weather-read')?.checked) scopes.push('weather.read');
    if (document.getElementById('scope-config-read')?.checked) scopes.push('config.read');
    if (document.getElementById('scope-stats-read')?.checked) scopes.push('stats.read');
    if (document.getElementById('scope-debug-read')?.checked) scopes.push('debug.read');
    return scopes;
}

async function loadAuthMe() {
    if (!AUTH_MODE.enabled) {
        setToken('');
        setStatus('admin-auth-status', 'Authentication is disabled. Admin actions are open in local mode.', 'ok');
        return;
    }
    const token = getToken();
    if (!token) {
        setStatus('admin-auth-status', 'Not authenticated. Login as admin.', 'warn');
        return;
    }
    try {
        const me = await api('/auth/me');
        setStatus('admin-auth-status', `Logged in as ${me.username} (${me.role})`, me.role === 'admin' ? 'ok' : 'warn');
    } catch (err) {
        setToken('');
        setStatus('admin-auth-status', `Auth expired: ${err.message}`, 'warn');
    }
}

async function loadAuthConfig() {
    try {
        const cfg = await api('/auth/config', 'GET', null, false);
        AUTH_MODE = {
            enabled: !!cfg?.enabled,
            require_viewer_login: !!cfg?.require_viewer_login,
        };
    } catch (_) {
        AUTH_MODE = { enabled: false, require_viewer_login: false };
    }
}

async function login() {
    const username = document.getElementById('admin-login-user')?.value.trim();
    const password = document.getElementById('admin-login-pass')?.value.trim();
    if (!username || !password) {
        setStatus('admin-auth-status', 'Username and password are required.', 'warn');
        return;
    }
    try {
        const data = await api('/auth/login', 'POST', { username, password }, false);
        setToken(data?.token || '');
        setStatus('admin-auth-status', `Logged in as ${data?.user?.username || username}`, 'ok');
        await loadSettings();
        await loadAgentTokens();
    } catch (err) {
        setStatus('admin-auth-status', `Login failed: ${err.message}`, 'warn');
    }
}

async function logout() {
    try { await api('/auth/logout', 'POST'); } catch (_) { }
    setToken('');
    setStatus('admin-auth-status', 'Logged out.', 'warn');
}

function fillSettings(settings) {
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
        const keyEl = document.getElementById(`setup-provider-${pid}-key`);
        if (keyEl) keyEl.value = '';
        const cycleEl = document.getElementById(`pullcycle-${pid}`);
        if (cycleEl) {
            const defaultVal = Number(PROVIDER_TTL_DEFAULTS?.[pid] || (pid === 'noaa_tides' ? 1800 : pid === 'aviationweather' ? 600 : 300));
            const value = clampCycle(settings?.cache?.provider_ttl_seconds?.[pid] ?? defaultVal);
            cycleEl.value = String(value);
        }
    });

    document.getElementById('setup-auth-enabled').checked = !!settings?.auth?.enabled;
    document.getElementById('setup-auth-viewer-required').checked = !!settings?.auth?.require_viewer_login;
    document.getElementById('setup-auth-admin-user').value = settings?.auth?.admin_user || 'admin';
    document.getElementById('setup-auth-viewer-user').value = settings?.auth?.viewer_user || 'viewer';
    document.getElementById('setup-auth-admin-pass').value = '';
    document.getElementById('setup-auth-viewer-pass').value = '';

    PROVIDER_TTL_DEFAULTS = settings?.cache?.provider_ttl_defaults || PROVIDER_TTL_DEFAULTS;
    PROVIDER_TTL_BOUNDS = settings?.cache?.provider_ttl_bounds || PROVIDER_TTL_BOUNDS;
    saveFormState();
}

async function loadSettings() {
    try {
        const settings = await api('/settings');
        fillSettings(settings);
        setStatus('setup-status', 'Settings loaded.', 'ok');
    } catch (err) {
        const msg = String(err?.message || 'unknown error');
        if (/401|403|Admin login required|Admin role required/i.test(msg)) {
            setStatus('setup-status', 'Admin login required. Use your configured ADMIN_USERNAME/ADMIN_PASSWORD from .env or Setup.', 'warn');
            return;
        }
        setStatus('setup-status', `Failed to load settings: ${msg}`, 'warn');
    }
}

function buildProvidersPayload() {
    const providers = {};
    PROVIDER_IDS.forEach((pid) => {
        const enabledEl = document.getElementById(`setup-provider-${pid}-enabled`);
        const keyEl = document.getElementById(`setup-provider-${pid}-key`);
        providers[pid] = {
            enabled: !!enabledEl?.checked,
            ...(keyEl ? { api_key: keyEl.value.trim() } : {}),
        };
    });
    return providers;
}

async function saveSettings() {
    const homeLat = Number(document.getElementById('setup-home-lat').value);
    const homeLon = Number(document.getElementById('setup-home-lon').value);
    if (!Number.isFinite(homeLat) || !Number.isFinite(homeLon)) {
        setStatus('setup-status', 'Home lat/lon must be valid numbers.', 'warn');
        return;
    }

    const workLatRaw = document.getElementById('setup-work-lat').value.trim();
    const workLonRaw = document.getElementById('setup-work-lon').value.trim();
    let work = null;
    if (workLatRaw || workLonRaw) {
        const workLat = Number(workLatRaw);
        const workLon = Number(workLonRaw);
        if (!Number.isFinite(workLat) || !Number.isFinite(workLon)) {
            setStatus('setup-status', 'Work lat/lon must be valid numbers.', 'warn');
            return;
        }
        work = {
            lat: workLat,
            lon: workLon,
            label: document.getElementById('setup-work-label').value.trim() || 'Work',
        };
    }

    const stationText = document.getElementById('setup-pws-stations').value;
    const stationList = stationText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    const payload = {
        location: {
            home: {
                lat: homeLat,
                lon: homeLon,
                label: document.getElementById('setup-home-label').value.trim() || 'Home',
            },
            ...(work ? { work } : {}),
            timezone: document.getElementById('setup-timezone').value.trim() || 'UTC',
        },
        user_agent: document.getElementById('setup-user-agent').value.trim(),
        pws: {
            provider: document.getElementById('setup-pws-provider').value.trim() || 'weather.com',
            stations: stationList,
        },
        map: {
            provider: document.getElementById('setup-map-provider').value || 'esri_street',
        },
        providers: buildProvidersPayload(),
        auth: {
            enabled: !!document.getElementById('setup-auth-enabled').checked,
            require_viewer_login: !!document.getElementById('setup-auth-viewer-required').checked,
            // Fall back to placeholder so leaving the field blank still submits the displayed default
            admin_username: document.getElementById('setup-auth-admin-user').value.trim() || document.getElementById('setup-auth-admin-user').placeholder || 'admin',
            admin_password: document.getElementById('setup-auth-admin-pass').value.trim(),
            viewer_username: document.getElementById('setup-auth-viewer-user').value.trim() || document.getElementById('setup-auth-viewer-user').placeholder || 'viewer',
            viewer_password: document.getElementById('setup-auth-viewer-pass').value.trim(),
        },
        cache: {
            provider_ttl_seconds: collectProviderPullCycles(),
        },
    };

    try {
        await api('/settings', 'POST', payload);
        setStatus('setup-status', '✓ Settings saved successfully!', 'ok');
        await loadSettings();
        await loadObservability();
        clearUnsaved();
    } catch (err) {
        setStatus('setup-status', `Save failed: ${err.message}`, 'warn');
    }
}

function renderTokenList(items) {
    const host = document.getElementById('agent-token-list');
    if (!host) return;
    if (!items || items.length === 0) {
        host.innerHTML = '<div style="color: #999; font-style: italic;">No agent tokens yet.</div>';
        return;
    }
    const rows = items
        .slice()
        .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
        .map((item, idx) => {
            const scopes = (item.scopes || []).join(', ') || '--';
            const exp = item.expires_at ? new Date(item.expires_at * 1000).toLocaleString() : '--';
            const created = item.created_at ? new Date(item.created_at * 1000).toLocaleString() : '--';
            const revoked = item.revoked ? 'revoked' : 'active';
            const expandId = `token-expand-${idx}`;
            const detailsId = `token-details-${idx}`;
            return `
                <div style="padding: 12px; background: rgba(255,255,255,0.05); border-radius: 4px;">
                    <div style="display: grid; grid-template-columns: 1fr auto auto; gap: 12px; align-items: center;">
                        <div>
                            <div style="font-weight: bold; color: #7dd3fc;">
                                ${item.name || 'Agent Token'}
                                <span style="font-size: 0.85em; margin-left: 8px; padding: 2px 6px; background: ${revoked === 'revoked' ? 'rgba(200,100,100,0.3)' : 'rgba(100,200,100,0.3)'}; border-radius: 3px;">${revoked.toUpperCase()}</span>
                            </div>
                            <div style="font-size: 0.85em; color: #888; margin-top: 4px; font-family: monospace;">Created ${created}</div>
                        </div>
                        <button id="${expandId}" class="map-btn" type="button" style="min-width: 80px;">Expand</button>
                        <button class="map-btn" data-token-id="${item.id}" type="button" ${item.revoked ? 'disabled' : ''}>Delete</button>
                    </div>
                    <div id="${detailsId}" style="display: none; margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.1);">
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 0.9em;">
                            <div>
                                <div style="color: #888; margin-bottom: 4px;">Scopes</div>
                                <div>${scopes}</div>
                            </div>
                            <div>
                                <div style="color: #888; margin-bottom: 4px;">Created</div>
                                <div>${created}</div>
                            </div>
                            <div>
                                <div style="color: #888; margin-bottom: 4px;">Expires</div>
                                <div>${exp}</div>
                            </div>
                        </div>
                        <div style="margin-top: 12px; padding: 8px; background: rgba(255,200,100,0.2); border-left: 3px solid #ffc864; border-radius: 3px; font-size: 0.85em; color: #ddd;">
                            ⚠️ Token value is only shown once during creation and never stored.
                        </div>
                    </div>
                </div>`;
        })
        .join('');
    host.innerHTML = rows;

    // Attach expand/collapse listeners
    items.forEach((item, idx) => {
        const expandBtn = document.getElementById(`token-expand-${idx}`);
        const detailsDiv = document.getElementById(`token-details-${idx}`);
        if (expandBtn && detailsDiv) {
            expandBtn.addEventListener('click', () => {
                const isShowing = detailsDiv.style.display !== 'none';
                detailsDiv.style.display = isShowing ? 'none' : 'block';
                expandBtn.textContent = isShowing ? 'Expand' : 'Collapse';
            });
        }
    });

    host.querySelectorAll('button[data-token-id]').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const tokenId = btn.getAttribute('data-token-id');
            if (!tokenId) return;
            const tokenName = btn.parentElement?.querySelector('[style*="color: #7dd3fc"]')?.textContent || 'token';
            if (!confirm(`Delete token "${tokenName}"? This cannot be undone.`)) return;
            try {
                await api(`/agent-tokens/${encodeURIComponent(tokenId)}`, 'DELETE');
                setStatus('agent-token-status', `✓ Token deleted.`, 'ok');
                await loadAgentTokens();
            } catch (err) {
                setStatus('agent-token-status', `Delete failed: ${err.message}`, 'warn');
            }
        });
    });
}

async function loadAgentTokens() {
    if (!AUTH_MODE.enabled) {
        renderTokenList([]);
        setStatus('agent-token-status', 'Agent tokens are available only when auth is enabled.', 'warn');
        return;
    }
    try {
        const data = await api('/agent-tokens');
        renderTokenList(data.tokens || []);
        setStatus('agent-token-status', 'Token list loaded.', 'ok');
    } catch (err) {
        const msg = String(err?.message || 'unknown error');
        if (/401|403|Admin login required|Admin role required/i.test(msg)) {
            setStatus('agent-token-status', 'Admin login required to manage agent tokens.', 'warn');
            return;
        }
        setStatus('agent-token-status', `Failed to load tokens: ${msg}`, 'warn');
    }
}

async function createAgentToken() {
    if (!AUTH_MODE.enabled) {
        setStatus('agent-token-status', 'Enable auth first to create scoped agent tokens.', 'warn');
        return;
    }
    const name = document.getElementById('agent-token-name').value.trim() || 'Agent Token';
    const ttlHours = Number(document.getElementById('agent-token-ttl').value || '168');
    const scopes = selectedScopes();
    if (scopes.length === 0) {
        setStatus('agent-token-status', 'Select at least one scope.', 'warn');
        return;
    }

    try {
        const data = await api('/agent-tokens', 'POST', {
            name,
            ttl_hours: ttlHours,
            scopes,
        });
        const tokenEl = document.getElementById('agent-token-value');
        tokenEl.style.display = 'block';
        tokenEl.innerHTML = '';
        tokenEl.textContent = `⚠️ COPY NOW - Token shown ONLY once and never again:\n\n${data.token}`;
        
        // Add copy button
        const copyBtn = document.createElement('button');
        copyBtn.className = 'map-btn';
        copyBtn.type = 'button';
        copyBtn.style.marginTop = '8px';
        copyBtn.style.display = 'block';
        copyBtn.textContent = '📋 Copy Token';
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(data.token).then(() => {
                copyBtn.textContent = '✓ Copied!';
                setTimeout(() => { copyBtn.textContent = '📋 Copy Token'; }, 2000);
            });
        };
        tokenEl.appendChild(copyBtn);
        
        setStatus('agent-token-status', `✓ Created token "${name}". Copy the token above before leaving this page!`, 'ok');
        await loadAgentTokens();
    } catch (err) {
        setStatus('agent-token-status', `Create failed: ${err.message}`, 'warn');
    }
}

async function testProvider(providerId) {
    const resultEl = document.getElementById(`test-result-${providerId}`);
    const enabledEl = document.getElementById(`setup-provider-${providerId}-enabled`);

    if (!enabledEl?.checked) {
        if (resultEl) {
            resultEl.textContent = '⚠ Provider not enabled';
            resultEl.className = 'pws-meta warn';
        }
        return;
    }

    if (resultEl) {
        resultEl.textContent = '⏳ Testing...';
        resultEl.className = 'pws-meta';
    }

    try {
        // Read API key from form if present (unsaved changes)
        const keyEl = document.getElementById(`setup-provider-${providerId}-key`);
        const formKey = keyEl?.value?.trim() || null;

        const params = new URLSearchParams({ provider: providerId });
        if (formKey) params.set('api_key', formKey);

        // PWS requires station IDs/provider from the setup form for useful test results.
        if (providerId === 'pws') {
            const pwsProvider = document.getElementById('setup-pws-provider')?.value?.trim();
            const pwsStations = document.getElementById('setup-pws-stations')?.value?.trim();
            if (pwsProvider) params.set('pws_provider', pwsProvider);
            if (pwsStations) params.set('pws_stations', pwsStations);
        }

        const url = `/test-provider?${params.toString()}`;

        const data = await api(url);
        if (resultEl) {
            if (data.ok) {
                resultEl.textContent = `✓ ${data.message}`;
                resultEl.className = 'pws-meta ok';
            } else {
                resultEl.textContent = `✗ ${data.error || 'Test failed'}`;
                resultEl.className = 'pws-meta warn';
            }
        }
    } catch (err) {
        if (resultEl) {
            resultEl.textContent = `✗ ${err.message}`;
            resultEl.className = 'pws-meta warn';
        }
    }
}

function saveFormState() {
    FORM_STATE = {
        home_label: document.getElementById('setup-home-label').value,
        home_lat: document.getElementById('setup-home-lat').value,
        home_lon: document.getElementById('setup-home-lon').value,
        work_label: document.getElementById('setup-work-label').value,
        work_lat: document.getElementById('setup-work-lat').value,
        work_lon: document.getElementById('setup-work-lon').value,
        timezone: document.getElementById('setup-timezone').value,
        user_agent: document.getElementById('setup-user-agent').value,
        map_provider: document.getElementById('setup-map-provider').value,
        pws_provider: document.getElementById('setup-pws-provider').value,
        pws_stations: document.getElementById('setup-pws-stations').value,
        auth_enabled: document.getElementById('setup-auth-enabled').checked,
        auth_viewer_required: document.getElementById('setup-auth-viewer-required').checked,
        auth_admin_user: document.getElementById('setup-auth-admin-user').value,
        auth_viewer_user: document.getElementById('setup-auth-viewer-user').value,
    };
    PROVIDER_IDS.forEach((pid) => {
        FORM_STATE[`provider_${pid}_enabled`] = document.getElementById(`setup-provider-${pid}-enabled`).checked;
        const cycleEl = document.getElementById(`pullcycle-${pid}`);
        if (cycleEl) FORM_STATE[`pullcycle_${pid}`] = cycleEl.value;
    });
}

function markUnsaved() {
    if (!UNSAVED_CHANGES) {
        UNSAVED_CHANGES = true;
        const indicator = document.getElementById('unsaved-indicator');
        if (indicator) indicator.style.display = 'inline';
    }
}

function clearUnsaved() {
    UNSAVED_CHANGES = false;
    const indicator = document.getElementById('unsaved-indicator');
    if (indicator) indicator.style.display = 'none';
}

function hasFormChanged() {
    const home_label = document.getElementById('setup-home-label').value;
    const home_lat = document.getElementById('setup-home-lat').value;
    const home_lon = document.getElementById('setup-home-lon').value;
    const work_label = document.getElementById('setup-work-label').value;
    const work_lat = document.getElementById('setup-work-lat').value;
    const work_lon = document.getElementById('setup-work-lon').value;
    const timezone = document.getElementById('setup-timezone').value;
    const user_agent = document.getElementById('setup-user-agent').value;
    const map_provider = document.getElementById('setup-map-provider').value;
    const pws_provider = document.getElementById('setup-pws-provider').value;
    const pws_stations = document.getElementById('setup-pws-stations').value;
    const auth_enabled = document.getElementById('setup-auth-enabled').checked;
    const auth_viewer_required = document.getElementById('setup-auth-viewer-required').checked;
    const auth_admin_user = document.getElementById('setup-auth-admin-user').value;
    const auth_viewer_user = document.getElementById('setup-auth-viewer-user').value;
    
    let changed = home_label !== FORM_STATE.home_label || home_lat !== FORM_STATE.home_lat || home_lon !== FORM_STATE.home_lon ||
                  work_label !== FORM_STATE.work_label || work_lat !== FORM_STATE.work_lat || work_lon !== FORM_STATE.work_lon ||
                  timezone !== FORM_STATE.timezone || user_agent !== FORM_STATE.user_agent ||
                  map_provider !== FORM_STATE.map_provider || pws_provider !== FORM_STATE.pws_provider ||
                  pws_stations !== FORM_STATE.pws_stations || auth_enabled !== FORM_STATE.auth_enabled ||
                  auth_viewer_required !== FORM_STATE.auth_viewer_required || auth_admin_user !== FORM_STATE.auth_admin_user ||
                  auth_viewer_user !== FORM_STATE.auth_viewer_user;
    
    if (!changed) {
        PROVIDER_IDS.forEach((pid) => {
            if (document.getElementById(`setup-provider-${pid}-enabled`).checked !== FORM_STATE[`provider_${pid}_enabled`]) changed = true;
            const cycleEl = document.getElementById(`pullcycle-${pid}`);
            if (cycleEl && cycleEl.value !== FORM_STATE[`pullcycle_${pid}`]) changed = true;
        });
    }
    return changed;
}

async function testAllProviders() {
    const testBtn = document.getElementById('test-all-providers');
    const testStatus = document.getElementById('test-all-status');
    testBtn.disabled = true;
    
    const enabledProviders = PROVIDER_IDS.filter((pid) => {
        const enabledEl = document.getElementById(`setup-provider-${pid}-enabled`);
        return enabledEl && enabledEl.checked;
    });
    
    if (enabledProviders.length === 0) {
        testStatus.textContent = 'No enabled providers to test';
        testBtn.disabled = false;
        return;
    }
    
    testStatus.textContent = `Testing ${enabledProviders.length} enabled provider${enabledProviders.length === 1 ? '' : 's'}...`;
    
    let passed = 0, failed = 0;
    for (const pid of enabledProviders) {
        try {
            await testProvider(pid);
            passed++;
        } catch (e) {
            failed++;
        }
    }
    
    testStatus.textContent = `✓ ${passed} passed${failed > 0 ? `, ✗ ${failed} failed` : ''}`;
    testBtn.disabled = false;
}

async function init() {
    populateTimezoneSelect('setup-timezone');

    document.getElementById('admin-login-btn').addEventListener('click', login);
    document.getElementById('admin-logout-btn').addEventListener('click', logout);
    document.getElementById('setup-save-btn').addEventListener('click', saveSettings);
    document.getElementById('setup-discard-btn').addEventListener('click', () => {
        if (hasFormChanged() && !confirm('Discard unsaved changes?')) return;
        loadSettings();
        clearUnsaved();
    });
    document.getElementById('agent-token-create-btn').addEventListener('click', createAgentToken);
    document.getElementById('test-all-providers').addEventListener('click', testAllProviders);
    document.getElementById('obs-refresh-btn').addEventListener('click', loadObservability);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') loadObservabilityAuto();
    });
    
    // Keyboard shortcut: Ctrl+S to save
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            saveSettings();
        }
    });
    
    // Setup unsaved changes detection on all form inputs
    document.querySelectorAll('.setup-input, .ctrl-lbl input').forEach((el) => {
        el.addEventListener('change', markUnsaved);
        el.addEventListener('input', markUnsaved);
    });
    
    // Warn before leaving if unsaved
    window.addEventListener('beforeunload', (e) => {
        if (hasFormChanged()) {
            e.preventDefault();
            e.returnValue = '';
        }
    });

    // Attach test provider handlers
    PROVIDER_IDS.forEach((providerId) => {
        const btn = document.getElementById(`test-provider-${providerId}`);
        if (btn) {
            btn.addEventListener('click', () => testProvider(providerId));
        }
    });
    
    // Setup pull cycle listeners for unsaved changes
    setupPullCycleListeners();

    await loadAuthConfig();
    await loadAuthMe();
    await loadSettings();
    await loadAgentTokens();
    await loadObservability();
    startObservabilityPolling();
}

document.addEventListener('DOMContentLoaded', () => {
    init().catch((err) => {
        setStatus('admin-auth-status', `Admin page failed to initialize: ${err.message}`, 'warn');
    });
});
