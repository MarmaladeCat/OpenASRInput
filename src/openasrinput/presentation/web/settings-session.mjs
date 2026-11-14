// A launcher credential creates a bounded page session; reloads never renew it.
const storageKey = 'openasrinput-settings-token';

export class SettingsSession {
  constructor(onExpire) {
    this.onExpire = onExpire;
    this.expired = false;
    this.expiresAt = null;
    this.abort = new AbortController();
    this.check = () => {
      if (this.expiresAt !== null && Date.now() >= this.expiresAt) this.expire();
      return !this.expired;
    };
  }

  async start() {
    const launchToken = new URLSearchParams(location.hash.slice(1)).get('token');
    this.token = launchToken || sessionStorage.getItem(storageKey);
    history.replaceState(null, '', location.pathname);
    if (!this.token) {
      this.expire();
      throw new Error('设置会话已失效，请重新打开设置');
    }
    const value = await this.request('settings/session', launchToken ? 'POST' : 'GET');
    if (value.token) this.token = value.token;
    if (!this.check()) return;
    sessionStorage.setItem(storageKey, this.token);
    this.timer = setInterval(this.check, 1000);
    window.addEventListener('pageshow', this.check);
    window.addEventListener('focus', this.check);
    document.addEventListener('visibilitychange', this.check);
  }

  update(session) {
    this.expiresAt = session.expiresAt;
    document.getElementById('settings-session-deadline').textContent =
      this.expiresAt === null ? '不限时' : new Date(this.expiresAt).toLocaleString();
    this.check();
  }

  expire() {
    if (this.expired) return;
    this.expired = true;
    this.token = null;
    sessionStorage.removeItem(storageKey);
    clearInterval(this.timer);
    this.abort.abort();
    window.removeEventListener('pageshow', this.check);
    window.removeEventListener('focus', this.check);
    document.removeEventListener('visibilitychange', this.check);
    this.onExpire();
  }

  async request(path, method = 'GET', body) {
    if (!this.check()) throw new Error('设置会话已失效，请重新打开设置');
    // One lifetime signal also aborts outstanding requests when the page expires.
    const controller = new AbortController();
    const cancel = () => controller.abort();
    this.abort.signal.addEventListener('abort', cancel, { once: true });
    const timer = setTimeout(cancel, path.startsWith('text-model/') ? 70000 : 35000);
    try {
      const response = await fetch('/api/' + path, {
        method,
        headers: { Authorization: 'Bearer ' + this.token, 'Content-Type': 'application/json' },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: controller.signal,
        redirect: 'error'
      });
      const value = await response.json();
      if (response.status === 401) this.expire();
      if (!response.ok) throw new Error(value.error || `设置请求失败（${response.status}）`);
      if (this.expired) throw new Error('设置会话已失效，请重新打开设置');
      if (value.settingsSession) this.update(value.settingsSession);
      return value;
    } finally {
      clearTimeout(timer);
      this.abort.signal.removeEventListener('abort', cancel);
    }
  }
}
