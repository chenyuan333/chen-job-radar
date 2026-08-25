// 医疗岗位雷达 - PWA 前端逻辑
const DATA_URL = 'jobs.json';
const LS_KEY_FAV = 'jr_favorites';
const LS_KEY_APPLIED = 'jr_applied';
const LS_KEY_READ = 'jr_read';

let allJobs = [];
let meta = {};
let currentTab = 'all'; // all | favorite | applied

const state = {
  q: '',
  city: '',
  category: '',
  onlyBianzhi: false,
  hideExpired: true,
};

// 类别标签顺序
const CATEGORIES = ['全部', '体检科', '心电图', '社区医师', '校医', '心血管内科', 'AI医疗', '卫健委', '疾控中心'];

function $ (s) { return document.querySelector(s); }
function $$ (s) { return document.querySelectorAll(s); }

function loadLS(key) {
  try { return JSON.parse(localStorage.getItem(key) || '[]'); } catch { return []; }
}
function saveLS(key, arr) { localStorage.setItem(key, JSON.stringify(arr)); }

function isFav(url) { return loadLS(LS_KEY_FAV).includes(url); }
function isApplied(url) { return loadLS(LS_KEY_APPLIED).includes(url); }
function isRead(url) { return loadLS(LS_KEY_READ).includes(url); }

function toggleLS(key, url) {
  const arr = loadLS(key);
  const idx = arr.indexOf(url);
  if (idx >= 0) arr.splice(idx, 1); else arr.push(url);
  saveLS(key, arr);
  return idx < 0; // true 表示现在已加入
}

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return `${d.getMonth()+1}月${d.getDate()}日 ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

function isDeadlineSoon(deadline) {
  if (!deadline) return false;
  const d = new Date(deadline);
  if (isNaN(d)) return false;
  const diff = (d - new Date()) / (1000 * 60 * 60 * 24);
  return diff >= 0 && diff <= 7;
}

async function loadJobs() {
  $('#list').innerHTML = '<div class="empty">加载中…</div>';
  try {
    const r = await fetch(DATA_URL + '?t=' + Date.now());
    const data = await r.json();
    allJobs = data.jobs || [];
    meta = { updated_at: data.updated_at, total: data.total };
    render();
    $('#updated').textContent = '更新于 ' + fmtDate(meta.updated_at);
  } catch (e) {
    $('#list').innerHTML = '<div class="empty">加载失败，请下拉刷新<br>' + e.message + '</div>';
  }
}

function getFilteredJobs() {
  let list = allJobs.slice();

  if (currentTab === 'favorite') list = list.filter(j => isFav(j.url));
  if (currentTab === 'applied') list = list.filter(j => isApplied(j.url));

  if (state.city) list = list.filter(j => j.city === state.city);
  if (state.category && state.category !== '全部') list = list.filter(j => j.category === state.category);
  if (state.onlyBianzhi) list = list.filter(j => j.has_bianzhi);
  if (state.hideExpired) list = list.filter(j => j.status !== 'expired');
  if (state.q) {
    const k = state.q.toLowerCase();
    list = list.filter(j =>
      (j.title || '').toLowerCase().includes(k) ||
      (j.hospital || '').toLowerCase().includes(k) ||
      (j.description || '').toLowerCase().includes(k)
    );
  }

  // 排序：active 在前，编内优先，有发布日期新的在前
  list.sort((a, b) => {
    const sa = a.status === 'expired' ? 0 : 1;
    const sb = b.status === 'expired' ? 0 : 1;
    if (sa !== sb) return sb - sa;
    const ba = a.has_bianzhi ? 1 : 0;
    const bb = b.has_bianzhi ? 1 : 0;
    if (ba !== bb) return bb - ba;
    const pa = a.publish_date || '1970-01-01';
    const pb = b.publish_date || '1970-01-01';
    return pb.localeCompare(pa);
  });

  return list;
}

function render() {
  const list = getFilteredJobs();
  $('#count').textContent = `共 ${list.length} 条`;
  const container = $('#list');
  if (!list.length) {
    container.innerHTML = '<div class="empty">暂无符合条件的岗位<br>试试调整筛选条件</div>';
    return;
  }

  container.innerHTML = list.map(j => {
    const soon = isDeadlineSoon(j.deadline);
    const expired = j.status === 'expired';
    const read = isRead(j.url);
    const cls = 'job-card' + (expired ? ' expired' : '') + (read ? ' read' : '');
    const cityCls = j.city === '广州' ? 'badge-city-gz' : 'badge-city-dg';
    return `
      <div class="${cls}" data-url="${escapeHtml(j.url)}">
        <div class="card-top" onclick="openDetail('${escapeHtml(j.url)}')">
          <div class="hospital">${escapeHtml(j.hospital || '')}</div>
          <div class="badges">
            <span class="badge ${cityCls}">${escapeHtml(j.city || '')}</span>
            ${j.has_bianzhi ? '<span class="badge badge-bianzhi">编内</span>' : ''}
          </div>
        </div>
        <div class="title" onclick="openDetail('${escapeHtml(j.url)}')">${escapeHtml(j.title)}</div>
        <div class="meta" onclick="openDetail('${escapeHtml(j.url)}')">
          <span class="category">${escapeHtml(j.category || '其他')}</span>
          <span class="deadline ${soon ? 'soon' : ''}">${j.deadline ? (expired ? '已截止 ' : '截止 ') + j.deadline : '无截止'}</span>
          <span class="source ${j.reliability === '官方' ? 'official' : ''}">${escapeHtml(j.reliability || '')}</span>
        </div>
        <div class="actions">
          <button class="action-btn ${isFav(j.url) ? 'active' : ''}" onclick="toggleFav(event, '${escapeHtml(j.url)}')">⭐ 收藏</button>
          <button class="action-btn ${isApplied(j.url) ? 'active' : ''}" onclick="toggleApplied(event, '${escapeHtml(j.url)}')">✅ 已投</button>
          <button class="action-btn link-btn" onclick="openLink(event, '${escapeHtml(j.url)}')">🔗 原文</button>
        </div>
      </div>
    `;
  }).join('');
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function openDetail(url) {
  markRead(null, url);
  const j = allJobs.find(x => x.url === url);
  if (!j) return;
  $('#modalTitle').textContent = j.title;
  $('#modalHospital').textContent = j.hospital || '未知医院';
  $('#modalMeta').innerHTML = `
    <div>城市：${escapeHtml(j.city || '')}</div>
    <div>类别：${escapeHtml(j.category || '其他')}</div>
    <div>信源：${escapeHtml(j.reliability || '')}</div>
    <div>编制：${j.has_bianzhi ? '有编制' : '未明确/无编'}</div>
    <div>发布：${j.publish_date || '未知'}</div>
    <div>截止：${j.deadline || '未知'}</div>
    <div>来源：${escapeHtml(j.source || '')}</div>
  `;
  // 描述：为空时给出引导，让用户去看原文
  $('#modalDesc').textContent = j.description
    || '此岗位暂无简介，点下方「查看原文 & 投递」按钮，查看具体要求和报名方式。';
  // 链接：显示完整 URL + 大按钮
  const wrap = $('#modalUrlWrap');
  const urlEl = $('#modalUrl');
  const linkBtn = $('#modalLink');
  if (j.url) {
    wrap.style.display = 'block';
    urlEl.href = j.url;
    urlEl.textContent = j.url;
    linkBtn.href = j.url;
    linkBtn.classList.remove('disabled');
    linkBtn.textContent = '🔗 查看原文 & 投递';
  } else {
    wrap.style.display = 'none';
    urlEl.removeAttribute('href');
    urlEl.textContent = '';
    linkBtn.removeAttribute('href');
    linkBtn.classList.add('disabled');
    linkBtn.textContent = '暂无直达链接';
  }
  $('#modal').classList.add('show');
}

// 卡片上的「原文」按钮：直接跳转招聘页面（不打开弹窗）
function openLink(e, url) {
  e.stopPropagation();
  if (url) window.open(url, '_blank', 'noopener');
}

function closeDetail() {
  $('#modal').classList.remove('show');
}

function toggleFav(e, url) {
  e.stopPropagation();
  const on = toggleLS(LS_KEY_FAV, url);
  const btn = e.currentTarget;
  btn.classList.toggle('active', on);
  if (currentTab === 'favorite' && !on) render();
}

function toggleApplied(e, url) {
  e.stopPropagation();
  const on = toggleLS(LS_KEY_APPLIED, url);
  const btn = e.currentTarget;
  btn.classList.toggle('active', on);
  if (currentTab === 'applied' && !on) render();
}

function markRead(e, url) {
  if (e) e.stopPropagation();
  toggleLS(LS_KEY_READ, url);
  render();
}

function renderCategoryChips() {
  $('#categoryChips').innerHTML = CATEGORIES.map(c =>
    `<span class="chip ${state.category === c || (!state.category && c === '全部') ? 'active' : ''}" data-cat="${escapeHtml(c)}">${escapeHtml(c)}</span>`
  ).join('');
  $$('#categoryChips .chip').forEach(el => {
    el.onclick = () => {
      state.category = el.dataset.cat === '全部' ? '' : el.dataset.cat;
      renderCategoryChips();
      render();
    };
  });
}

function bindEvents() {
  // 城市筛选
  $$('#cityChips .chip').forEach(el => {
    el.onclick = () => {
      state.city = el.dataset.city;
      $$('#cityChips .chip').forEach(c => c.classList.toggle('active', c.dataset.city === state.city));
      render();
    };
  });

  renderCategoryChips();

  // 搜索
  $('#searchInput').addEventListener('input', debounce(e => {
    state.q = e.target.value.trim();
    render();
  }, 200));

  // 开关
  $('#bianzhiToggle').addEventListener('change', e => {
    state.onlyBianzhi = e.target.checked;
    render();
  });
  $('#expiredToggle').addEventListener('change', e => {
    state.hideExpired = e.target.checked;
    render();
  });

  // 刷新
  $('#refreshBtn').onclick = () => loadJobs();

  // 底部导航
  $$('.nav-item').forEach(el => {
    el.onclick = () => {
      currentTab = el.dataset.tab;
      $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.tab === currentTab));
      render();
    };
  });

  // 离线检测
  window.addEventListener('online', () => $('#offlineTip').classList.remove('show'));
  window.addEventListener('offline', () => $('#offlineTip').classList.add('show'));
  if (!navigator.onLine) $('#offlineTip').classList.add('show');
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

// 注册 Service Worker
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(console.error);
}

window.openDetail = openDetail;
window.closeDetail = closeDetail;
window.toggleFav = toggleFav;
window.toggleApplied = toggleApplied;
window.openLink = openLink;

bindEvents();
loadJobs();
