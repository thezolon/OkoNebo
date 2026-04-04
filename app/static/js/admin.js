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
}

async function loadSettings() {
    try {
        const settings = await api('/settings');
        fillSettings(settings);
        setStatus('setup-status', 'Settings loaded.', 'ok');
    } catch (err) {
        setStatus('setup-status', `Failed to load settings: ${err.message}`, 'warn');
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
    };

    try {
        await api('/settings', 'POST', payload);
        setStatus('setup-status', 'Settings saved.', 'ok');
        await loadSettings();
    } catch (err) {
        setStatus('setup-status', `Save failed: ${err.message}`, 'warn');
    }
}

function renderTokenList(items) {
    const host = document.getElementById('agent-token-list');
    if (!host) return;
    if (!items || items.length === 0) {
        host.innerHTML = '<div class="timeline-empty">No agent tokens yet.</div>';
        return;
    }
    const rows = items
        .slice()
        .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
        .map((item) => {
            const scopes = (item.scopes || []).join(', ') || '--';
            const exp = item.expires_at ? new Date(item.expires_at * 1000).toLocaleString() : '--';
            const revoked = item.revoked ? 'revoked' : 'active';
            return `
                <div class="timeline-item system">
                    <div><strong>${item.name || 'Agent Token'}</strong> <span class="badge">${revoked}</span></div>
                    <div>ID: ${item.id}</div>
                    <div>Scopes: ${scopes}</div>
                    <div>Expires: ${exp}</div>
                    <div class="setup-actions" style="margin-top:6px;">
                        <button class="map-btn" data-token-id="${item.id}" ${item.revoked ? 'disabled' : ''}>Revoke</button>
                    </div>
                </div>`;
        })
        .join('');
    host.innerHTML = rows;

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
    try {
        const data = await api('/agent-tokens');
        renderTokenList(data.tokens || []);
        setStatus('agent-token-status', 'Token list loaded.', 'ok');
    } catch (err) {
        setStatus('agent-token-status', `Failed to load tokens: ${err.message}`, 'warn');
    }
}

async function createAgentToken() {
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
        tokenEl.textContent = `Token (copy now, shown once):\n${data.token}`;
        setStatus('agent-token-status', `Created token ${data.id}.`, 'ok');
        await loadAgentTokens();
    } catch (err) {
        setStatus('agent-token-status', `Create failed: ${err.message}`, 'warn');
    }
}

async function init() {
    document.getElementById('admin-login-btn').addEventListener('click', login);
    document.getElementById('admin-logout-btn').addEventListener('click', logout);
    document.getElementById('setup-save-btn').addEventListener('click', saveSettings);
    document.getElementById('agent-token-create-btn').addEventListener('click', createAgentToken);

    await loadAuthMe();
    await loadSettings();
    await loadAgentTokens();
}

document.addEventListener('DOMContentLoaded', () => {
    init().catch((err) => {
        setStatus('admin-auth-status', `Admin page failed to initialize: ${err.message}`, 'warn');
    });
});
