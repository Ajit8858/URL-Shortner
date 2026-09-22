const API_BASE = window.location.origin;
const TOKEN_KEY = 'url_shortener_token';

const statusBox = document.getElementById('statusBox');
const registerForm = document.getElementById('registerForm');
const loginForm = document.getElementById('loginForm');
const shortenForm = document.getElementById('shortenForm');
const registerResult = document.getElementById('registerResult');
const loginResult = document.getElementById('loginResult');
const shortenResult = document.getElementById('shortenResult');
const headerLogoutBtn = document.getElementById('headerLogoutBtn');
const authView = document.getElementById('authView');
const dashboardView = document.getElementById('dashboardView');
const registerSection = document.getElementById('registerSection');
const loginSection = document.getElementById('loginSection');
const tabButtons = document.querySelectorAll('.tab-button');

function setStatus(message) {
  statusBox.textContent = message;
}

function setResult(element, text, isError = false) {
  element.textContent = text;
  element.className = `result ${isError ? 'error' : 'success'}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    };
    return map[char] || char;
  });
}

function renderCopyableUrlResult(shortUrl, longUrl) {
  shortenResult.innerHTML = `
    <div class="result-panel">
      <div class="result-row">
        <label>Short URL</label>
        <div class="copy-box">
          <input type="text" readonly value="${escapeHtml(shortUrl)}" />
          <button type="button" class="copy-btn" data-copy="${escapeHtml(shortUrl)}">Copy</button>
        </div>
      </div>
      <div class="result-row">
        <label>Original URL</label>
        <div class="copy-box">
          <input type="text" readonly value="${escapeHtml(longUrl)}" />
          <button type="button" class="copy-btn secondary" data-copy="${escapeHtml(longUrl)}">Copy</button>
        </div>
      </div>
    </div>
  `;
}

async function copyTextToClipboard(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }

    const helper = document.createElement('textarea');
    helper.value = text;
    helper.style.position = 'fixed';
    helper.style.opacity = '0';
    document.body.appendChild(helper);
    helper.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(helper);
    return ok;
  } catch (error) {
    return false;
  }
}

function getToken() {
  return localStorage.getItem(TOKEN_KEY) || '';
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

function setAuthMode(mode) {
  const isRegister = mode === 'register';
  registerSection.classList.toggle('hidden', !isRegister);
  loginSection.classList.toggle('hidden', isRegister);
  tabButtons.forEach((button) => {
    const isActive = button.dataset.mode === mode;
    button.classList.toggle('active', isActive);
  });
}

function refreshAuthView() {
  const hasToken = !!getToken();
  authView.classList.toggle('hidden', hasToken);
  dashboardView.classList.toggle('hidden', !hasToken);

  if (hasToken) {
    setStatus('Logged in');
    if (headerLogoutBtn) headerLogoutBtn.classList.remove('hidden');
  } else {
    setStatus('Please sign in');
    if (headerLogoutBtn) headerLogoutBtn.classList.add('hidden');
    if (shortenResult) shortenResult.textContent = '';
    setAuthMode('register');
  }
}

async function apiRequest(path, options = {}) {
  const headers = options.headers || {};
  headers['Content-Type'] = headers['Content-Type'] || 'application/json';

  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (error) {
    data = text;
  }

  if (!response.ok) {
    throw new Error(data?.detail || data || 'Request failed');
  }

  return data;
}

registerForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const email = document.getElementById('registerEmail').value.trim();
  const password = document.getElementById('registerPassword').value;

  try {
    setStatus('Registering...');
    const result = await apiRequest('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });

    setToken(result.access_token);
    setResult(registerResult, 'Registered successfully. Access token saved.', false);
    refreshAuthView();
  } catch (error) {
    setResult(registerResult, error.message, true);
    setStatus('Registration failed');
  }
});

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value;

  try {
    setStatus('Logging in...');
    const result = await apiRequest('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });

    setToken(result.access_token);
    setResult(loginResult, `Login successful. Token saved.`, false);
    refreshAuthView();
  } catch (error) {
    setResult(loginResult, error.message, true);
    setStatus('Login failed');
  }
});

shortenForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const longUrl = document.getElementById('longUrl').value.trim();
  const customAlias = document.getElementById('customAlias').value.trim();

  if (!getToken()) {
    setResult(shortenResult, 'Please log in before creating a short URL.', true);
    setStatus('Authentication required');
    return;
  }

  try {
    setStatus('Creating short URL...');
    const payload = { long_url: longUrl };
    if (customAlias) payload.custom_alias = customAlias;

    const result = await apiRequest('/api/v1/shorten', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    renderCopyableUrlResult(result.short_url, result.long_url);
    setStatus('Short URL created');
  } catch (error) {
    setResult(shortenResult, error.message, true);
    setStatus('Failed to create link');
  }
});

shortenResult.addEventListener('click', async (event) => {
  const button = event.target.closest('.copy-btn');
  if (!button) return;

  const value = button.dataset.copy || '';
  const copied = await copyTextToClipboard(value);
  const originalText = button.textContent;
  button.textContent = copied ? 'Copied' : 'Copy failed';
  setTimeout(() => {
    button.textContent = originalText;
  }, 1200);
});

headerLogoutBtn.addEventListener('click', () => {
  localStorage.removeItem(TOKEN_KEY);
  refreshAuthView();
  registerResult.textContent = '';
  loginResult.textContent = '';
  shortenResult.textContent = '';
});

tabButtons.forEach((button) => {
  button.addEventListener('click', () => {
    setAuthMode(button.dataset.mode);
  });
});

window.addEventListener('DOMContentLoaded', () => {
  refreshAuthView();
});
