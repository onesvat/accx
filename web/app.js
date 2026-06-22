const token = document.querySelector('meta[name="accx-token"]').content;
const tablesRoot = document.getElementById('tablesRoot');
const metrics = document.getElementById('metrics');
const syncText = document.getElementById('syncText');
const refreshButton = document.getElementById('refreshAll');
const billingDialog = document.getElementById('billingDialog');
const billingForm = document.getElementById('billingForm');
const switchDialog = document.getElementById('switchDialog');
const wakeDialog = document.getElementById('wakeDialog');
const wakeForm = document.getElementById('wakeForm');
const toast = document.getElementById('toast');

let dashboard = { profiles: [], monthly_totals: {} };
let switchTarget = null;
let wakeRecurrence = 'once';
let toastTimer = null;

const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
})[char]);

function notify(message, error = false) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.className = `toast show${error ? ' error' : ''}`;
  toastTimer = setTimeout(() => { toast.className = 'toast'; }, 3200);
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.method && options.method !== 'GET') {
    headers['Content-Type'] = 'application/json';
    headers['X-ACCX-Token'] = token;
  }
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function setBusy(busy, message) {
  refreshButton.disabled = busy;
  document.querySelector('.sync-state').classList.toggle('busy', busy);
  syncText.textContent = message;
}

function formatDate(value, dateOnly = false) {
  if (!value) return 'Veri yok';
  const date = dateOnly ? new Date(`${value}T12:00:00`) : new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('tr-TR', dateOnly
    ? { day: '2-digit', month: 'short', year: 'numeric' }
    : { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }
  ).format(date);
}

function relativeReset(value) {
  if (!value) return 'Sıfırlanma bilinmiyor';
  const diff = new Date(value).getTime() - Date.now();
  if (!Number.isFinite(diff)) return formatDate(value);
  if (diff <= 0) return 'Sıfırlanıyor';
  const hours = Math.floor(diff / 3600000);
  const minutes = Math.floor((diff % 3600000) / 60000);
  return hours >= 24 ? `${Math.floor(hours / 24)}g ${hours % 24}s sonra` : `${hours}s ${minutes}dk sonra`;
}

function renderMetrics() {
  const profiles = dashboard.profiles || [];
  const active = profiles.filter(item => item.active).length;
  const dated = profiles.filter(item => item.billing?.renewal_date);
  const next = dated.sort((a, b) => a.billing.renewal_date.localeCompare(b.billing.renewal_date))[0];
  const totals = Object.entries(dashboard.monthly_totals || {}).map(([currency, amount]) => `${amount} ${currency}`).join(' + ') || '—';
  metrics.innerHTML = `
    <div class="metric"><span>Kayıtlı profil</span><strong>${profiles.length}</strong></div>
    <div class="metric"><span>Aktif oturum</span><strong class="accent">${active}</strong></div>
    <div class="metric"><span>Sonraki yenileme</span><strong>${next ? escapeHtml(formatDate(next.billing.renewal_date, true)) : '—'}</strong></div>
    <div class="metric"><span>Aylık toplam</span><strong>${escapeHtml(totals)}</strong></div>`;
}

function usageTableCell(value, reset, color) {
  const numeric = Number(value);
  const valid = Number.isFinite(numeric);
  const percent = valid ? Math.max(0, Math.min(100, numeric)) : 0;
  return `<div class="usage-value"><span>Kullanım</span><strong>${valid ? `${numeric}%` : '—'}</strong></div>
    <div class="mini-track"><i style="--usage:${percent}%;--bar:${color}"></i></div>
    <span class="reset-text">${escapeHtml(relativeReset(reset))}</span>`;
}

function providerTable(provider) {
  const profiles = (dashboard.profiles || []).filter(item => item.provider === provider);
  const isClaude = provider === 'claude';
  const title = isClaude ? 'Claude Code' : 'Codex CLI';
  const rows = profiles.length ? profiles.map(item => {
    const usage = item.usage || {};
    const billing = item.billing || {};
    const identity = `${item.provider}:${item.profile}`;
    const billingDate = billing.renewal_date ? escapeHtml(formatDate(billing.renewal_date, true)) : 'Ayarlanmadı';
    const billingPrice = billing.amount ? `${escapeHtml(billing.amount)} ${escapeHtml(billing.currency)} / ay` : 'Fiyat yok';
    return `<tr class="account-row${item.active ? ' active-row' : ''}" data-id="${escapeHtml(identity)}">
      <td class="profile-cell"><strong class="profile-name">${escapeHtml(item.profile)}</strong></td>
      <td class="email-cell" title="${escapeHtml(item.email || '')}">${escapeHtml(item.email || 'E-posta bilinmiyor')}</td>
      <td><span class="plan-tag">${escapeHtml(item.plan || 'Bilinmiyor')}</span></td>
      <td class="usage-cell">${usageTableCell(usage.five_hour, usage.five_hour_resets_at, 'var(--green)')}</td>
      <td class="usage-cell">${usageTableCell(usage.seven_day, usage.seven_day_resets_at, 'var(--blue)')}</td>
      <td class="billing-cell" title="${escapeHtml(billing.note || '')}">
        <button class="billing-editor" type="button" data-action="billing" data-provider="${provider}" data-profile="${escapeHtml(item.profile)}">
          <span class="billing-edit-label">Planı düzenle</span>
          <span class="billing-line"><strong>${billingDate}</strong><span>${billingPrice}</span></span>
          <span class="billing-note">${billing.note ? escapeHtml(billing.note) : 'Not yok'}</span>
        </button>
      </td>
      <td><div class="row-actions">
        <button class="action-button" type="button" data-action="refresh" data-provider="${provider}" data-profile="${escapeHtml(item.profile)}">Yenile</button>
        <button class="action-button${item.wake?.enabled ? ' wake-active' : ''}" type="button" data-action="wake" data-provider="${provider}" data-profile="${escapeHtml(item.profile)}">${item.wake?.enabled ? (item.wake.recurrence === 'daily' ? 'Uyandır · Günlük' : 'Uyandır · 1×') : 'Uyandır'}</button>
        <button class="action-button switch" type="button" data-action="switch" data-provider="${provider}" data-profile="${escapeHtml(item.profile)}"${item.active ? ' disabled' : ''}>${item.active ? 'Aktif' : 'Etkinleştir'}</button>
      </div></td>
    </tr>`;
  }).join('') : '<tr class="empty-row"><td colspan="7">Bu sağlayıcı için kayıtlı profil yok.</td></tr>';

  return `<section class="provider-section provider-${provider}" style="--provider:var(--${provider});--active-soft:var(--${provider}-soft)">
    <div class="provider-heading">
      <div class="provider-title"><span class="provider-dot"></span><h2>${title}</h2></div>
      <p>${profiles.length} profil</p>
    </div>
    <div class="table-wrap">
      <table class="account-table">
        <thead><tr><th>Profil</th><th>Hesap</th><th>Plan</th><th>5 saat</th><th>7 gün</th><th>Abonelik</th><th>İşlemler</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  </section>`;
}

function renderProfiles() {
  tablesRoot.innerHTML = providerTable('claude') + providerTable('codex');
}

function render() {
  renderMetrics();
  renderProfiles();
}

async function loadDashboard() {
  setBusy(true, 'Yerel kasa okunuyor');
  try {
    dashboard = await request('/api/dashboard');
    render();
    syncText.textContent = `Son kontrol ${formatDate(dashboard.generated_at)}`;
  } catch (error) {
    notify(error.message, true);
    syncText.textContent = 'Panel verisi alınamadı';
  } finally {
    refreshButton.disabled = false;
    document.querySelector('.sync-state').classList.remove('busy');
  }
}

async function refreshUsage(force) {
  setBusy(true, force ? 'API verileri yenileniyor' : 'Kullanımlar kontrol ediliyor');
  try {
    const result = await request('/api/usage/refresh', { method: 'POST', body: JSON.stringify({ force }) });
    dashboard = result.dashboard;
    render();
    const failed = result.results.filter(item => item.status === 'unavailable').length;
    syncText.textContent = `Son kontrol ${formatDate(dashboard.generated_at)}`;
    if (force) notify(failed ? `${failed} profil yenilenemedi; önbellek korundu.` : 'Kullanımlar güncellendi.', failed > 0);
  } catch (error) {
    notify(error.message, true);
    syncText.textContent = 'Yenileme başarısız';
  } finally {
    refreshButton.disabled = false;
    document.querySelector('.sync-state').classList.remove('busy');
  }
}

async function refreshSingle(provider, profile, button) {
  button.disabled = true;
  const original = button.textContent;
  button.textContent = '...';
  try {
    const result = await request('/api/usage/refresh', {
      method: 'POST',
      body: JSON.stringify({ provider, profile, force: true })
    });
    dashboard = result.dashboard;
    render();
    const status = result.results[0]?.status;
    notify(status === 'unavailable' ? `${profile} yenilenemedi; önbellek korundu.` : `${profile} güncellendi.`, status === 'unavailable');
  } catch (error) {
    button.disabled = false;
    button.textContent = original;
    notify(error.message, true);
  }
}

function findProfile(provider, profile) {
  return dashboard.profiles.find(item => item.provider === provider && item.profile === profile);
}

function openBilling(provider, profile) {
  const item = findProfile(provider, profile);
  if (!item) return;
  document.getElementById('billingTitle').textContent = `${profile} / ${provider}`;
  document.getElementById('billingProvider').value = provider;
  document.getElementById('billingProfile').value = profile;
  document.getElementById('renewalDate').value = item.billing?.renewal_date || new Date().toISOString().slice(0, 10);
  document.getElementById('billingAmount').value = item.billing?.amount || '';
  document.getElementById('billingCurrency').value = item.billing?.currency || 'USD';
  document.getElementById('billingNote').value = item.billing?.note || '';
  billingDialog.showModal();
}

async function saveBilling() {
  const provider = document.getElementById('billingProvider').value;
  const profile = document.getElementById('billingProfile').value;
  const body = {
    renewal_date: document.getElementById('renewalDate').value,
    amount: document.getElementById('billingAmount').value,
    currency: document.getElementById('billingCurrency').value,
    note: document.getElementById('billingNote').value
  };
  const result = await request(`/api/profiles/${encodeURIComponent(provider)}/${encodeURIComponent(profile)}/billing`, { method: 'PUT', body: JSON.stringify(body) });
  dashboard = result.dashboard;
  render();
  billingDialog.close();
  notify('Plan bilgisi kaydedildi.');
}

function openSwitch(provider, profile) {
  const item = findProfile(provider, profile);
  if (!item) return;
  switchTarget = { provider, profile };
  document.getElementById('switchDescription').textContent = `${item.email || profile} hesabı ${provider === 'claude' ? 'Claude Code' : 'Codex CLI'} için aktif profil olacak. Mevcut aktif profil önce otomatik kaydedilir.`;
  switchDialog.showModal();
}

function localDateValue(date = new Date()) {
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

function setWakeRecurrence(value) {
  wakeRecurrence = value;
  document.querySelectorAll('[data-recurrence]').forEach(button => button.classList.toggle('active', button.dataset.recurrence === value));
  document.getElementById('wakeDateLabel').hidden = value === 'daily';
  document.getElementById('wakeDate').required = value === 'once';
  updateWakePreview();
}

function wakePreviewDate() {
  const time = document.getElementById('wakeTime').value;
  if (!time) return null;
  const now = new Date();
  const dateValue = wakeRecurrence === 'once' ? document.getElementById('wakeDate').value : localDateValue(now);
  if (!dateValue) return null;
  const candidate = new Date(`${dateValue}T${time}:00`);
  if (wakeRecurrence === 'daily' && candidate <= now) candidate.setDate(candidate.getDate() + 1);
  return candidate;
}

function updateWakePreview() {
  const preview = document.getElementById('wakePreview');
  const starts = wakePreviewDate();
  if (!starts || Number.isNaN(starts.getTime())) {
    preview.innerHTML = '<span>Zaman seçildiğinde çalışma penceresi burada görünecek.</span>';
    return;
  }
  const resets = new Date(starts.getTime() + 5 * 60 * 60 * 1000);
  preview.innerHTML = `<div><span>ÇALIŞIR</span><strong>${escapeHtml(formatDate(starts.toISOString()))}</strong></div><i>→</i><div><span>TAHMİNİ 5S RESET</span><strong>${escapeHtml(formatDate(resets.toISOString()))}</strong></div>`;
}

function openWake(provider, profile) {
  const item = findProfile(provider, profile);
  if (!item) return;
  const wake = item.wake || {};
  const defaultWake = new Date(Date.now() + 5 * 60 * 1000);
  document.getElementById('wakeTitle').textContent = `${profile} / ${provider === 'claude' ? 'Claude Code' : 'Codex CLI'}`;
  document.getElementById('wakeProvider').value = provider;
  document.getElementById('wakeProfile').value = profile;
  document.getElementById('wakeEnabled').checked = true;
  document.getElementById('wakeDate').value = localDateValue(defaultWake);
  document.getElementById('wakeTime').value = defaultWake.toTimeString().slice(0, 5);
  document.getElementById('wakePrompt').value = wake.prompt || '';
  setWakeRecurrence(wake.recurrence || 'once');
  wakeDialog.showModal();
}

async function saveWake() {
  const provider = document.getElementById('wakeProvider').value;
  const profile = document.getElementById('wakeProfile').value;
  const body = {
    enabled: document.getElementById('wakeEnabled').checked,
    recurrence: wakeRecurrence,
    date: document.getElementById('wakeDate').value,
    time: document.getElementById('wakeTime').value,
    prompt: document.getElementById('wakePrompt').value
  };
  const result = await request(`/api/profiles/${encodeURIComponent(provider)}/${encodeURIComponent(profile)}/wake`, { method: 'PUT', body: JSON.stringify(body) });
  dashboard = result.dashboard;
  render();
  wakeDialog.close();
  notify('Otomatik uyandırma kaydedildi.');
}

async function confirmSwitch() {
  if (!switchTarget) return;
  const button = document.getElementById('confirmSwitch');
  button.disabled = true;
  try {
    const { provider, profile } = switchTarget;
    const result = await request(`/api/profiles/${encodeURIComponent(provider)}/${encodeURIComponent(profile)}/switch`, { method: 'POST', body: '{}' });
    dashboard = result.dashboard;
    render();
    switchDialog.close();
    notify(`${profile} aktif profil oldu.`);
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
  }
}

tablesRoot.addEventListener('click', event => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const { action, provider, profile } = button.dataset;
  if (action === 'refresh') refreshSingle(provider, profile, button);
  if (action === 'billing') openBilling(provider, profile);
  if (action === 'switch') openSwitch(provider, profile);
  if (action === 'wake') openWake(provider, profile);
});

billingForm.addEventListener('submit', async event => {
  event.preventDefault();
  try { await saveBilling(); } catch (error) { notify(error.message, true); }
});
wakeForm.addEventListener('submit', async event => {
  event.preventDefault();
  try { await saveWake(); } catch (error) { notify(error.message, true); }
});
document.addEventListener('click', event => {
  const button = event.target.closest('[data-close-dialog]');
  if (!button) return;
  document.getElementById(button.dataset.closeDialog)?.close();
});
document.querySelector('.schedule-tabs').addEventListener('click', event => {
  const button = event.target.closest('[data-recurrence]');
  if (button) setWakeRecurrence(button.dataset.recurrence);
});
document.getElementById('wakeDate').addEventListener('input', updateWakePreview);
document.getElementById('wakeTime').addEventListener('input', updateWakePreview);
document.getElementById('cancelSwitch').addEventListener('click', () => switchDialog.close());
document.getElementById('confirmSwitch').addEventListener('click', confirmSwitch);
refreshButton.addEventListener('click', () => refreshUsage(true));

loadDashboard().then(() => refreshUsage(false));
setInterval(() => refreshUsage(false), 15 * 60 * 1000);
