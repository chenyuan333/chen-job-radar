// ===== 医疗岗位雷达 - 前端交互 =====
const API = {
  jobs: '/api/jobs',
  jobsAdd: '/api/jobs',
  jobsPatch: id => `/api/jobs/${id}`,
  jobsDelete: id => `/api/jobs/${id}`,
  crawlPaste: '/api/crawl/paste',
  crawlFetchUrl: '/api/crawl/fetch-url',
  crawlSweep: '/api/crawl/sweep',
  crawlTavily: '/api/crawl/tavily',
  crawlDeadlinks: '/api/crawl/deadlinks',
  health: '/api/health',
  stats: '/api/stats',
  crawlLogs: '/api/crawl-logs',
  exportUrl: '/api/export',
};

const state = {
  filters: {
    q: '',
    category: '',
    city: '',
    reliability: '',
    user_status: '',
    hide_expired: true,
    has_bianzhi: false,
    only_fresh: false,
  },
  jobs: [],
};

// ===== 工具 =====
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const escapeHtml = (s) => (s || '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[c]);

function toast(msg, type = 'info') {
  const t = $('#toast');
  t.textContent = msg;
  t.style.background = type === 'error' ? '#e53935' : type === 'success' ? '#4caf50' : 'rgba(0,0,0,0.85)';
  t.hidden = false;
  setTimeout(() => t.hidden = true, 2400);
}

async function api(url, opts = {}) {
  const r = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `HTTP ${r.status}`);
  }
  return r.json();
}

// ===== 统计 =====
async function loadStats() {
  try {
    const s = await api(API.stats);
    $('#stat-total').textContent = s.total;
    $('#stat-new').textContent = s.new_today;
    $('#stat-saved').textContent = s.saved;
    $('#stat-applied').textContent = s.applied;
    $('#stat-bianzhi').textContent = s.bianzhi;
    const last = s.last_crawl_at || '从未抓取';
    $('#stat-last').textContent = last === '从未抓取' ? last : formatTime(last);
  } catch (e) {
    console.error('loadStats:', e);
  }
}

function formatTime(iso) {
  if (!iso) return '-';
  try {
    const d = new Date(iso.replace(' ', 'T'));
    const now = new Date();
    const diff = (now - d) / 60000;
    if (diff < 1) return '刚刚';
    if (diff < 60) return Math.floor(diff) + ' 分钟前';
    if (diff < 1440) return Math.floor(diff / 60) + ' 小时前';
    return d.toLocaleDateString('zh-CN');
  } catch { return iso; }
}

// ===== 岗位列表 =====
async function loadJobs() {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(state.filters)) {
    if (v === '' || v === false) continue;
    if (typeof v === 'boolean') {
      if (v) params.set(k, '1');
    } else {
      params.set(k, v);
    }
  }
  try {
    const data = await api(API.jobs + '?' + params);
    state.jobs = data.jobs;
    renderJobs();
    $('#result-count').textContent = `共 ${data.count} 条岗位`;
  } catch (e) {
    toast('加载失败：' + e.message, 'error');
  }
}

function renderJobs() {
  const grid = $('#job-grid');
  const empty = $('#empty-state');
  if (state.jobs.length === 0) {
    grid.innerHTML = '';
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  grid.innerHTML = state.jobs.map(renderCard).join('');
}

function renderCard(j) {
  const tags = [];
  tags.push(`<span class="tag tag-cat tag-cat-${escapeHtml(j.category || '其他')}">${escapeHtml(j.category || '其他')}</span>`);
  tags.push(`<span class="tag tag-reliability-${escapeHtml(j.reliability || '待审')}">${escapeHtml(j.reliability || '待审')}</span>`);
  if (j.has_bianzhi) tags.push(`<span class="tag tag-bianzhi">事业编制</span>`);
  if (j.user_status && j.user_status !== 'new') {
    tags.push(`<span class="tag user-status-${escapeHtml(j.user_status)}">${userStatusLabel(j.user_status)}</span>`);
  }
  if (j.status === 'expired') tags.push(`<span class="tag" style="background:#ffebee;color:#b71c1c">⏰ 已过期</span>`);

  const meta = [];
  if (j.hospital) meta.push(`<span class="job-meta-item">${escapeHtml(j.hospital)}</span>`);
  if (j.city) meta.push(`<span class="job-meta-item">${escapeHtml(j.city)}</span>`);
  if (j.salary) meta.push(`<span class="job-meta-item">💰 ${escapeHtml(j.salary)}</span>`);

  const dateInfo = [];
  if (j.publish_date) dateInfo.push(`📅 发布 ${j.publish_date}`);
  if (j.deadline) {
    const cls = isDeadlineSoon(j.deadline) ? 'deadline-warn' : '';
    dateInfo.push(`<span class="${cls}">⏳ 截止 ${j.deadline}${isDeadlineSoon(j.deadline) ? ' ⚠' : ''}</span>`);
  }
  if (j.added_at) dateInfo.push(`入库 ${formatTime(j.added_at)}`);

  const cardClass = j.status === 'expired' ? 'job-card expired' : 'job-card';

  return `
    <article class="${cardClass}" data-id="${j.id}">
      <div class="job-title">
        <a href="${escapeHtml(j.url)}" target="_blank" rel="noopener">${escapeHtml(j.title || '(无标题)')}</a>
      </div>
      ${meta.length ? `<div class="job-meta">${meta.join('')}</div>` : ''}
      <div class="tag-row">${tags.join('')}</div>
      ${dateInfo.length ? `<div class="job-meta" style="font-size:11px;color:var(--text-hint)">${dateInfo.join('')}</div>` : ''}
      ${j.notes ? `<div class="job-meta" style="font-size:12px;color:var(--text-soft);font-style:italic">📝 ${escapeHtml(j.notes)}</div>` : ''}
      <div class="job-actions">
        <button class="btn btn-small" onclick="setUserStatus(${j.id},'read')">👀 已读</button>
        <button class="btn btn-small" onclick="setUserStatus(${j.id},'saved')">⭐ 收藏</button>
        <button class="btn btn-small" onclick="setUserStatus(${j.id},'applied')">📮 已投</button>
        ${j.status !== 'expired' ? `<button class="btn btn-small" onclick="setStatus(${j.id},'expired')">❌ 标过期</button>` : ''}
        <button class="btn btn-small" onclick="delJob(${j.id})">🗑 删除</button>
      </div>
    </article>
  `;
}

function userStatusLabel(s) {
  return { read: '已读', saved: '收藏', applied: '已投递' }[s] || s;
}

function isDeadlineSoon(d) {
  if (!d) return false;
  const diff = (new Date(d) - new Date()) / 86400000;
  return diff >= 0 && diff <= 14;
}

// ===== 操作 =====
async function setUserStatus(id, status) {
  try {
    await api(API.jobsPatch(id), { method: 'PATCH', body: JSON.stringify({ user_status: status }) });
    toast('已标记', 'success');
    await Promise.all([loadJobs(), loadStats()]);
  } catch (e) { toast('失败：' + e.message, 'error'); }
}

async function setStatus(id, status) {
  try {
    await api(API.jobsPatch(id), { method: 'PATCH', body: JSON.stringify({ status }) });
    toast('已标记过期', 'success');
    await loadJobs();
  } catch (e) { toast('失败：' + e.message, 'error'); }
}

async function delJob(id) {
  if (!confirm('确认删除这条岗位？')) return;
  try {
    await api(API.jobsDelete(id), { method: 'DELETE' });
    toast('已删除', 'success');
    await Promise.all([loadJobs(), loadStats()]);
  } catch (e) { toast('失败：' + e.message, 'error'); }
}

// ===== Modal =====
function openModal(id) {
  $(`#${id}`).hidden = false;
}
function closeModal(id) {
  $(`#${id}`).hidden = true;
}

document.querySelectorAll('[data-close]').forEach(b => {
  b.addEventListener('click', e => {
    const m = e.target.closest('.modal');
    if (m) m.hidden = true;
  });
});
document.querySelectorAll('.modal').forEach(m => {
  m.addEventListener('click', e => {
    if (e.target === m) m.hidden = true;
  });
});

// ===== 粘贴抓取 =====
$('#btn-paste').addEventListener('click', () => {
  $('#paste-text').value = '';
  $('#paste-preview').innerHTML = '';
  openModal('modal-paste');
});

$('#btn-paste-preview').addEventListener('click', async () => {
  const text = $('#paste-text').value.trim();
  if (!text) return toast('请先粘贴内容', 'error');
  // 客户端预览（基于解析逻辑的轻量版）
  const lines = text.split('\n').filter(l => l.trim() && !l.trim().startsWith('#'));
  const urlCount = (text.match(/https?:\/\/[^\s\)\]\,"'<>]+/g) || []).length;
  $('#paste-preview').innerHTML = `
    <ul>
      <li>检测到 ${lines.length} 行有效内容</li>
      <li>检测到 ${urlCount} 个 URL</li>
      <li class="hint">点「入库」后将自动解析并去重</li>
    </ul>
  `;
});

$('#btn-paste-confirm').addEventListener('click', async () => {
  const text = $('#paste-text').value.trim();
  const source = $('#paste-source').value.trim() || '手动粘贴';
  if (!text) return toast('请先粘贴内容', 'error');
  try {
    const r = await api(API.crawlPaste, { method: 'POST', body: JSON.stringify({ text, source }) });
    const msg = `入库 ${r.inserted} 条 | 重复 ${r.duplicate} 条${r.expired_filtered ? ` | 过滤过期 ${r.expired_filtered} 条` : ''}`;
    toast(msg, r.inserted > 0 ? 'success' : 'info');
    closeModal('modal-paste');
    await Promise.all([loadJobs(), loadStats()]);
  } catch (e) { toast('失败：' + e.message, 'error'); }
});

// ===== 手动添加 =====
$('#btn-add').addEventListener('click', () => {
  $('#add-url').value = '';
  $('#add-title').value = '';
  $('#add-hospital').value = '';
  $('#add-city').value = '';
  $('#add-publish').value = '';
  $('#add-deadline').value = '';
  $('#add-salary').value = '';
  $('#add-bianzhi').checked = false;
  $('#add-notes').value = '';
  openModal('modal-add');
});

$('#btn-fetch-url').addEventListener('click', async () => {
  const url = $('#add-url').value.trim();
  if (!url) return toast('请先填 URL', 'error');
  toast('正在抓取页面...', 'info');
  try {
    const r = await api(API.crawlFetchUrl, { method: 'POST', body: JSON.stringify({ url }) });
    const info = r.info;
    $('#add-title').value = info.title || '';
    $('#add-city').value = info.city || '';
    $('#add-publish').value = info.publish_date || '';
    $('#add-deadline').value = info.deadline || '';
    $('#add-bianzhi').checked = !!info.has_bianzhi;
    if (info.category && info.category !== '其他') {
      $('#add-category').value = info.category;
    }
    if (info.reliability) $('#add-reliability').value = info.reliability;
    toast('已自动识别（请确认后保存）', 'success');
  } catch (e) { toast('抓取失败：' + e.message, 'error'); }
});

$('#btn-add-confirm').addEventListener('click', async () => {
  const url = $('#add-url').value.trim();
  const title = $('#add-title').value.trim();
  if (!url || !title) return toast('URL 和标题必填', 'error');
  const data = {
    url, title,
    hospital: $('#add-hospital').value.trim(),
    city: $('#add-city').value.trim(),
    category: $('#add-category').value,
    reliability: $('#add-reliability').value,
    publish_date: $('#add-publish').value.trim(),
    deadline: $('#add-deadline').value.trim(),
    salary: $('#add-salary').value.trim(),
    has_bianzhi: $('#add-bianzhi').checked,
    notes: $('#add-notes').value.trim(),
    status: 'active',
  };
  try {
    const r = await api(API.jobsAdd, { method: 'POST', body: JSON.stringify(data) });
    if (r.ok) {
      toast('已保存', 'success');
      closeModal('modal-add');
      await Promise.all([loadJobs(), loadStats()]);
    } else if (r.status === 'duplicate') {
      toast('已存在（URL 重复）', 'error');
    } else {
      toast(r.msg || '失败', 'error');
    }
  } catch (e) { toast('失败：' + e.message, 'error'); }
});

// ===== 扫描过期 =====
$('#btn-sweep').addEventListener('click', async () => {
  if (!confirm('扫描所有未过期岗位，根据截止日期标记过期的？')) return;
  try {
    const r = await api(API.crawlSweep, { method: 'POST' });
    toast(`已标记 ${r.expired_marked} 条过期`, r.expired_marked > 0 ? 'success' : 'info');
    await loadJobs();
  } catch (e) { toast('失败：' + e.message, 'error'); }
});

// ===== Tavily 自动联网搜索 =====
$('#btn-tavily').addEventListener('click', async () => {
  $('#tavily-queries').value = '';
  $('#tavily-config-hint').innerHTML = '检查配置中...';
  try {
    const h = await api(API.health);
    if (!h.tavily_configured) {
      $('#tavily-config-hint').innerHTML =
        '<span style="color:#e53935">⚠ 未设置 TAVILY_API_KEY 环境变量，无法使用联网搜索。</span><br>' +
        '<span class="hint">请到 <a href="https://tavily.com" target="_blank">tavily.com</a> 领取免费 key（1000 次/月），' +
        '然后在启动前设置环境变量：<br><code>set TAVILY_API_KEY=tvly-xxxxxx</code><br>' +
        '或在 start.bat 里加一行 <code>set TAVILY_API_KEY=tvly-xxxxxx</code></span>';
    } else {
      $('#tavily-config-hint').innerHTML =
        `<span style="color:#2e7d32">✓ Tavily 已配置（每日${h.scheduler_enabled ? '已开启' : '未开启'}自动定时）</span>`;
    }
  } catch (e) { /* ignore */ }
  openModal('modal-tavily');
});

$('#btn-tavily-run').addEventListener('click', async () => {
  const days = parseInt($('#tavily-days').value, 10) || 60;
  const maxPerQuery = parseInt($('#tavily-max').value, 10) || 8;
  const qText = $('#tavily-queries').value.trim();
  let queries = null;
  if (qText) {
    queries = qText.split('\n').filter(l => l.trim()).map(l => {
      const [q, c] = l.split('|').map(s => s.trim());
      return [q, c || '东莞'];
    });
  }
  if (!confirm(`即将联网搜索 ${queries ? queries.length : 14} 个关键词组合，过程可能耗时 30-60 秒。确定继续？`)) return;
  toast('搜索中，请稍候...', 'info');
  try {
    const r = await api(API.crawlTavily, {
      method: 'POST',
      body: JSON.stringify({ queries, days, max_per_query: maxPerQuery }),
    });
    const msg = `搜索完成 | 找到 ${r.found || 0} 条 → 入库 ${r.inserted || 0} 条 | 重复 ${r.duplicate || 0} 条 | 过期 ${r.expired_filtered || 0} 条`;
    toast(msg, r.inserted > 0 ? 'success' : 'info');
    closeModal('modal-tavily');
    await Promise.all([loadJobs(), loadStats()]);
    if (r.note) alert('提示：' + r.note);
  } catch (e) {
    toast('搜索失败：' + e.message, 'error');
  }
});

// ===== 服务状态 =====
$('#btn-health').addEventListener('click', async () => {
  openModal('modal-health');
  try {
    const h = await api(API.health);
    $('#health-info').innerHTML = `
      <ul>
        <li>服务：<b>${h.service} v${h.version}</b></li>
        <li>当前时间：${h.time}</li>
        <li>Tavily 联网搜索：${h.tavily_configured ? '<b style="color:#2e7d32">✓ 已配置</b>' : '<b style="color:#e53935">✗ 未配置</b>'}</li>
        <li>每日自动搜索：${h.scheduler_enabled ? '<b style="color:#2e7d32">✓ 已开启</b>' : '<b>关闭</b>'}</li>
        <li class="hint">如需启用每日自动搜索，启动前设置 <code>set ENABLE_SCHEDULER=1</code></li>
      </ul>
    `;
    const logs = await api(API.crawlLogs);
    $('#health-logs').innerHTML = logs.logs.length
      ? logs.logs.map(l => `<div class="log-line">
          <span class="log-time">${l.run_at || ''}</span>
          <span class="log-src">[${l.source || ''}]</span>
          找到 <b>${l.found}</b> · 入库 <b style="color:#2e7d32">${l.inserted}</b> · 重复/无效 <b>${l.duplicate || 0}</b>
          ${l.error ? `<span style="color:#e53935"> · ${l.error}</span>` : ''}
        </div>`).join('')
      : '<p class="hint">暂无抓取日志</p>';
  } catch (e) {
    $('#health-info').innerHTML = `<p style="color:#e53935">加载失败：${e.message}</p>`;
  }
});

// ===== 导出 =====
$('#btn-export').addEventListener('click', () => {
  window.location.href = API.exportUrl + '?format=csv';
  toast('开始下载 CSV...', 'success');
});

// ===== 筛选交互 =====
function bindChipRow(rowId, key) {
  const row = $(`#${rowId}`);
  row.addEventListener('click', e => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    $$(`#${rowId} .chip`).forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    state.filters[key] = chip.dataset.val || '';
    loadJobs();
  });
}
bindChipRow('f-category', 'category');
bindChipRow('f-reliability', 'reliability');
bindChipRow('f-user_status', 'user_status');

$('#f-q').addEventListener('input', debounce(e => {
  state.filters.q = e.target.value.trim();
  loadJobs();
}, 300));
$('#f-city').addEventListener('change', e => {
  state.filters.city = e.target.value;
  loadJobs();
});
$('#f-hide-expired').addEventListener('change', e => {
  state.filters.hide_expired = e.target.checked;
  loadJobs();
});
$('#f-bianzhi').addEventListener('change', e => {
  state.filters.has_bianzhi = e.target.checked;
  loadJobs();
});
$('#f-fresh').addEventListener('change', e => {
  state.filters.only_fresh = e.target.checked;
  loadJobs();
});

$('#btn-reset').addEventListener('click', () => {
  state.filters = {
    q: '', category: '', city: '', reliability: '',
    user_status: '', hide_expired: true, has_bianzhi: false, only_fresh: false,
  };
  $('#f-q').value = '';
  $('#f-city').value = '';
  $('#f-hide-expired').checked = true;
  $('#f-bianzhi').checked = false;
  $('#f-fresh').checked = false;
  $$('.chip-row').forEach(row => {
    row.querySelectorAll('.chip').forEach((c, i) => {
      c.classList.toggle('active', i === 0);
    });
  });
  loadJobs();
});

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

// ===== 加载城市选项 =====
// 城市已在前端模板中写死为「东莞 / 广州」，不再动态从数据库加载，
// 避免其他城市岗位误入下拉框。
async function loadCities() {
  // 预留空函数，保持兼容性
}

// ===== 初始化 =====
(async () => {
  await Promise.all([loadStats(), loadJobs()]);
  // 每 60 秒自动刷新统计
  setInterval(() => { loadStats(); }, 60000);
})();