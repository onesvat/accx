const refreshButton = document.getElementById('refreshWakes');
const syncText = document.getElementById('wakeSyncText');
const metrics = document.getElementById('wakeMetrics');
const plansRoot = document.getElementById('wakePlans');
const eventsRoot = document.getElementById('wakeEvents');
const planCount = document.getElementById('planCount');
const toast = document.getElementById('toast');

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

function formatDate(value) {
  if (!value) return 'Planlanmadı';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('tr-TR', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit'
  }).format(date);
}

function eventLabel(event) {
  return ({
    scheduler_started: 'Zamanlayıcı başladı',
    scheduler_stopped: 'Zamanlayıcı durdu',
    scheduler_check_failed: 'Zamanlayıcı kontrolü başarısız',
    schedule_saved: 'Plan kaydedildi',
    schedule_invalid: 'Plan geçersiz',
    wake_due: 'Çalışma zamanı geldi',
    wake_started: 'CLI süreci başladı',
    wake_completed: 'CLI süreci tamamlandı',
    wake_failed: 'CLI başlatılamadı',
    wake_check_failed: 'Profil kontrolü başarısız'
  })[event] || event;
}

function eventTone(event) {
  if (event.includes('failed') || event === 'schedule_invalid') return 'danger';
  if (event === 'wake_completed') return 'success';
  if (event === 'wake_started' || event === 'wake_due') return 'active';
  return 'neutral';
}

function renderMetrics(data) {
  const plans = data.plans || [];
  const active = plans.filter(plan => plan.enabled);
  const next = active.filter(plan => plan.next_run_at).sort((a, b) => a.next_run_at.localeCompare(b.next_run_at))[0];
  const failures = (data.events || []).filter(event => String(event.event).includes('failed')).length;
  metrics.innerHTML = `
    <div class="metric"><span>Toplam plan</span><strong>${plans.length}</strong></div>
    <div class="metric"><span>Etkin plan</span><strong class="accent">${active.length}</strong></div>
    <div class="metric"><span>Sıradaki çalışma</span><strong>${escapeHtml(next ? formatDate(next.next_run_at) : '—')}</strong></div>
    <div class="metric"><span>Son 200 olayda hata</span><strong class="${failures ? 'danger-text' : ''}">${failures}</strong></div>`;
}

function renderPlans(plans) {
  planCount.textContent = `${plans.length} plan`;
  if (!plans.length) {
    plansRoot.innerHTML = '<div class="wake-empty">Henüz bir uyandırma planı kaydedilmemiş.</div>';
    return;
  }
  const sorted = [...plans].sort((a, b) => Number(b.enabled) - Number(a.enabled) || String(a.next_run_at).localeCompare(String(b.next_run_at)));
  const rows = sorted.map(plan => {
    const providerName = plan.provider === 'claude' ? 'Claude Code' : 'Codex CLI';
    const recurrence = plan.recurrence === 'daily' ? 'Her gün' : 'Tek sefer';
    const output = plan.output
      ? `<details class="table-output"><summary>Göster</summary><pre>${escapeHtml(plan.output)}</pre></details>`
      : '<span class="table-muted">Yok</span>';
    return `<tr class="wake-plan-row provider-${escapeHtml(plan.provider)}">
      <td><div class="table-profile"><span class="provider-mark"></span><div><strong>${escapeHtml(plan.profile)}</strong><small>${providerName}</small></div></div></td>
      <td><span class="status-pill ${plan.enabled ? 'enabled' : 'disabled'}">${plan.enabled ? 'Etkin' : 'Pasif'}</span></td>
      <td><strong class="table-primary">${recurrence}</strong><small class="table-secondary">${escapeHtml(plan.time)}</small></td>
      <td><strong class="table-primary">${escapeHtml(formatDate(plan.next_run_at))}</strong></td>
      <td><code class="model-code">${escapeHtml(plan.model)}</code></td>
      <td class="prompt-cell" title="${escapeHtml(plan.prompt)}">${escapeHtml(plan.prompt)}</td>
      <td><span class="result-text">${escapeHtml(plan.last_result || 'Henüz çalışmadı')}</span></td>
      <td>${output}</td>
    </tr>`;
  }).join('');
  plansRoot.innerHTML = `<div class="wake-plan-table-wrap"><table class="wake-plan-table">
    <thead><tr><th>Profil</th><th>Durum</th><th>Zamanlama</th><th>Sıradaki çalışma</th><th>Model</th><th>Prompt</th><th>Sonuç</th><th>Çıktı</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

function eventDetail(event) {
  const details = [];
  if (event.provider || event.profile) details.push([event.provider, event.profile].filter(Boolean).join('/'));
  if (event.scheduled_at) details.push(`Plan: ${formatDate(event.scheduled_at)}`);
  if (event.exit_code !== undefined) details.push(`Exit: ${event.exit_code}`);
  if (event.pid) details.push(`PID: ${event.pid}`);
  if (event.error) details.push(event.error);
  if (event.output) details.push(event.output);
  return details.join(' · ');
}

function renderEvents(events) {
  if (!events.length) {
    eventsRoot.innerHTML = '<div class="wake-empty">Henüz zamanlayıcı olayı kaydedilmemiş.</div>';
    return;
  }
  eventsRoot.innerHTML = events.map(event => `<article class="wake-event ${eventTone(String(event.event || ''))}">
    <span class="event-dot"></span>
    <div class="event-copy"><strong>${escapeHtml(eventLabel(event.event))}</strong><p>${escapeHtml(eventDetail(event) || 'Ek ayrıntı yok')}</p></div>
    <time datetime="${escapeHtml(event.timestamp || '')}">${escapeHtml(formatDate(event.timestamp))}</time>
  </article>`).join('');
}

async function loadWakes(showNotice = false) {
  refreshButton.disabled = true;
  document.querySelector('.sync-state').classList.add('busy');
  syncText.textContent = 'Planlar ve loglar okunuyor';
  try {
    const response = await fetch('/api/wakes', { cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    renderMetrics(data);
    renderPlans(data.plans || []);
    renderEvents(data.events || []);
    syncText.textContent = `Son kontrol ${formatDate(data.generated_at)}`;
    if (showNotice) notify('Uyandırma verileri yenilendi.');
  } catch (error) {
    notify(error.message, true);
    syncText.textContent = 'Uyandırma verileri alınamadı';
  } finally {
    refreshButton.disabled = false;
    document.querySelector('.sync-state').classList.remove('busy');
  }
}

refreshButton.addEventListener('click', () => loadWakes(true));
loadWakes();
