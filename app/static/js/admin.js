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

function renderProviderPullCycles(values = {}) {
    const host = document.getElementById('provider-pullcycle-list');
    if (!host) return;

    const ids = Object.keys(PULL_CYCLE_LABELS);
    host.innerHTML = ids.map((providerId) => {
        const label = PULL_CYCLE_LABELS[providerId] || providerId;
        const defaultVal = Number(PROVIDER_TTL_DEFAULTS?.[providerId] || 300);
        const value = clampCycle(values?.[providerId] ?? defaultVal);
        const timeStr = formatSecondsAsTime(value);
        return `
            <div class="setup-row"><span class="setup-lbl">${label}</span>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <input
                        id="pullcycle-${providerId}"
                        class="setup-input"
                        type="number"
                        min="${Number(PROVIDER_TTL_BOUNDS?.min_seconds || 60)}"
                        max="${Number(PROVIDER_TTL_BOUNDS?.max_seconds || 86400)}"
                        value="${value}"
                        data-provider-id="${providerId}"
                        placeholder="seconds"
                        style="max-width:100px;"
                    >
                    <span id="pullcycle-time-${providerId}" class="pws-meta" style="min-width: 50px;">every ${timeStr}</span>
                    <span id="pullcycle-meta-${providerId}" class="pws-meta">~${estimateCallsPerHour(value)}/h • ~${estimateCallsPerDay(value)}/d</span>
                </div>
            </div>
        `;
    }).join('');

    host.querySelectorAll('input[data-provider-id]').forEach((input) => {
        const updateMeta = () => {
            const pid = input.getAttribute('data-provider-id');
            if (!pid) return;
            const value = clampCycle(input.value);
            input.value = String(value);
            const timeEl = document.getElementById(`pullcycle-time-${pid}`);
            const meta = document.getElementById(`pullcycle-meta-${pid}`);
            if (timeEl) {
                timeEl.textContent = `every ${formatSecondsAsTime(value)}`;
            }
            if (meta) {
                meta.textContent = `~${estimateCallsPerHour(value)}/h • ~${estimateCallsPerDay(value)}/d`;
            }
        };
        input.addEventListener('change', updateMeta);
        input.addEventListener('input', updateMeta);
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
    document.getElementById('setup-timezone').value = settings?.location?.timezone || '';
    document.getElementById('setup-user-agent').value = settings?.user_agent || '';
    document.getElementById('setup-map-provider').value = settings?.map?.provider || 'esri_street';
    document.getElementById('setup-pws-provider').value = settings?.pws?.provider || 'weather.com';
    document.getElementById('setup-pws-stations').value = (settings?.pws?.stations || []).join(', ');

    PROVIDER_IDS.forEach((pid) => {
        const enabledEl = document.getElementById(`setup-provider-${pid}-enabled`);
        if (enabledEl) enabledEl.checked = !!settings?.providers?.[pid]?.enabled;
        const keyEl = document.getElementById(`setup-provider-${pid}-key`);
        if (keyEl) keyEl.value = '';
    });

    document.getElementById('setup-auth-enabled').checked = !!settings?.auth?.enabled;
    document.getElementById('setup-auth-viewer-required').checked = !!settings?.auth?.require_viewer_login;
    document.getElementById('setup-auth-admin-user').value = settings?.auth?.admin_user || 'admin';
    document.getElementById('setup-auth-viewer-user').value = settings?.auth?.viewer_user || 'viewer';
    document.getElementById('setup-auth-admin-pass').value = '';
    document.getElementById('setup-auth-viewer-pass').value = '';

    PROVIDER_TTL_DEFAULTS = settings?.cache?.provider_ttl_defaults || PROVIDER_TTL_DEFAULTS;
    PROVIDER_TTL_BOUNDS = settings?.cache?.provider_ttl_bounds || PROVIDER_TTL_BOUNDS;
    renderProviderPullCycles(settings?.cache?.provider_ttl_seconds || {});
    setStatus('provider-pullcycle-status', 'Provider pull cycles loaded.', 'ok');
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
            admin_username: document.getElementById('setup-auth-admin-user').value.trim(),
            admin_password: document.getElementById('setup-auth-admin-pass').value.trim(),
            viewer_username: document.getElementById('setup-auth-viewer-user').value.trim(),
            viewer_password: document.getElementById('setup-auth-viewer-pass').value.trim(),
        },
        cache: {
            provider_ttl_seconds: collectProviderPullCycles(),
        },
    };

    try {
        await api('/settings', 'POST', payload);
        setStatus('setup-status', '✓ Settings saved successfully!', 'ok');
        setStatus('provider-pullcycle-status', '✓ Pull cycles saved!', 'ok');
        await loadSettings();
    } catch (err) {
        setStatus('setup-status', `Save failed: ${err.message}`, 'warn');
        setStatus('provider-pullcycle-status', `Save failed: ${err.message}`, 'warn');
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
                        <button id="${expandId}" class="map-btn" type="button" style="min-width: 80px;">Details</button>
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
            try {
                await api(`/agent-tokens/${encodeURIComponent(tokenId)}`, 'DELETE');
                setStatus('agent-token-status', `Revoked token ${tokenId}.`, 'ok');
                await loadAgentTokens();
            } catch (err) {
                setStatus('agent-token-status', `Revoke failed: ${err.message}`, 'warn');
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
        tokenEl.textContent = `⚠️ COPY NOW - Token shown ONLY once and never again:\n\n${data.token}`;
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

        let url = `/test-provider?provider=${encodeURIComponent(providerId)}`;
        if (formKey) {
            url += `&api_key=${encodeURIComponent(formKey)}`;
        }

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

async function init() {
    document.getElementById('admin-login-btn').addEventListener('click', login);
    document.getElementById('admin-logout-btn').addEventListener('click', logout);
    document.getElementById('setup-save-btn').addEventListener('click', saveSettings);
    document.getElementById('agent-token-create-btn').addEventListener('click', createAgentToken);

    // Attach test provider handlers
    PROVIDER_IDS.forEach((providerId) => {
        const btn = document.getElementById(`test-provider-${providerId}`);
        if (btn) {
            btn.addEventListener('click', () => testProvider(providerId));
        }
    });

    await loadAuthConfig();
    await loadAuthMe();
    await loadSettings();
    await loadAgentTokens();
}

document.addEventListener('DOMContentLoaded', () => {
    init().catch((err) => {
        setStatus('admin-auth-status', `Admin page failed to initialize: ${err.message}`, 'warn');
    });
});
