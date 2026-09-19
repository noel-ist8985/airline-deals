/* オタクイベントまとめ — アプリ本体
   data/events.json を読み込み、絞り込み・並び替え・表示を行う。 */

'use strict';

const DATA_URL = 'data/events.json';
const FAV_KEY = 'otaku-events:favorites';
const PAGE_SIZE = 40;           // 一度に描画する件数
const DEADLINE_SOON_DAYS = 14;  // 「締切間近」とみなす日数

const CATEGORY_LABEL = {
  doujin: '同人イベント',
  anime_event: 'アニメイベント',
  campaign: 'キャンペーン',
};

const REGION_OF = {};
[
  ['北海道・東北', ['北海道', '青森', '岩手', '宮城', '秋田', '山形', '福島']],
  ['関東', ['茨城', '栃木', '群馬', '埼玉', '千葉', '東京', '神奈川']],
  ['中部', ['新潟', '富山', '石川', '福井', '山梨', '長野', '岐阜', '静岡', '愛知']],
  ['近畿', ['三重', '滋賀', '京都', '大阪', '兵庫', '奈良', '和歌山']],
  ['中国・四国', ['鳥取', '島根', '岡山', '広島', '山口', '徳島', '香川', '愛媛', '高知']],
  ['九州・沖縄', ['福岡', '佐賀', '長崎', '熊本', '大分', '宮崎', '鹿児島', '沖縄']],
].forEach(([region, prefs]) => prefs.forEach((p) => { REGION_OF[p] = region; }));

const WDAY = ['日', '月', '火', '水', '木', '金', '土'];

// ------------------------------------------------------------ 状態

const state = {
  all: [],
  sourceNames: {},
  updatedAt: null,
  category: 'all',
  period: 'upcoming',
  area: 'all',
  sort: 'date',
  query: '',
  deadlineOnly: false,
  favorites: loadFavorites(),
  shown: PAGE_SIZE,
  filtered: [],
};

const $ = (sel) => document.querySelector(sel);
const el = {
  status: $('#statusBar'),
  list: $('#cardList'),
  empty: $('#emptyState'),
  tabs: $('#categoryTabs'),
  search: $('#searchInput'),
  clearSearch: $('#clearSearch'),
  period: $('#periodSelect'),
  area: $('#areaSelect'),
  sort: $('#sortSelect'),
  deadlineOnly: $('#deadlineOnly'),
  updatedNote: $('#updatedNote'),
  sourceList: $('#sourceList'),
  modal: $('#detailModal'),
  modalBody: $('#modalBody'),
  toast: $('#toast'),
  refresh: $('#refreshBtn'),
  sentinel: $('#sentinel'),
};

// ------------------------------------------------------- 日付ヘルパー

/** ローカル日付の 0 時を返す */
function today() {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

/** "2026-08-23" → Date（不正なら null） */
function parseDate(s) {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return null;
  const d = new Date(+m[1], +m[2] - 1, +m[3]);
  return isNaN(d) ? null : d;
}

function daysFromToday(d) {
  return Math.round((d - today()) / 86400000);
}

function fmtDate(d) {
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日(${WDAY[d.getDay()]})`;
}

/** 「あと3日」「今日」などの相対表記 */
function relLabel(d) {
  const n = daysFromToday(d);
  if (n < 0) return `${-n}日前`;
  if (n === 0) return '今日';
  if (n === 1) return '明日';
  if (n === 2) return '明後日';
  if (n < 7) return `あと${n}日`;
  if (n < 30) return `あと${Math.floor(n / 7)}週間`;
  return `あと${Math.floor(n / 30)}か月`;
}

/** イベントの「終わり」の日付（終了日が無ければ開始日） */
function endOf(ev) {
  return parseDate(ev.end_date) || parseDate(ev.start_date);
}

// ------------------------------------------------------- 文字列ヘルパー

/** 検索用に正規化（全角→半角・小文字化・空白除去） */
function normalize(s) {
  return (s || '').normalize('NFKC').toLowerCase().replace(/\s+/g, '');
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// ------------------------------------------------------------ 起動

init();

async function init() {
  bindEvents();
  try {
    const res = await fetch(DATA_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.all = (data.events || []).map(prepare);
    state.sourceNames = data.source_names || {};
    state.updatedAt = data.updated_at || null;
  } catch (err) {
    el.status.innerHTML = 'イベント情報を読み込めませんでした。通信環境を確認して、画面を再読み込みしてください。';
    console.error(err);
    return;
  }
  buildAreaOptions();
  renderFooter();
  apply();
  registerServiceWorker();
}

/** 読み込み時に一度だけ計算しておく項目 */
function prepare(ev) {
  const start = parseDate(ev.start_date);
  const end = parseDate(ev.end_date);
  const deadline = parseDate(ev.deadline);
  ev._start = start;
  ev._end = end || start;
  ev._deadline = deadline;
  ev._pref = ev.prefecture || null;
  ev._region = REGION_OF[ev._pref] || (ev._pref ? ev._pref : null);
  ev._search = normalize([
    ev.title, ev.summary, ev.venue, ev.prefecture, (ev.tags || []).join(' '),
  ].join(' '));
  ev._newTs = ev.published ? Date.parse(ev.published)
    : (ev.first_seen ? Date.parse(ev.first_seen) : 0);
  return ev;
}

function bindEvents() {
  el.tabs.addEventListener('click', (e) => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    state.category = btn.dataset.cat;
    [...el.tabs.querySelectorAll('.tab')].forEach((t) => {
      const on = t === btn;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', String(on));
    });
    apply();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  let timer = null;
  el.search.addEventListener('input', () => {
    el.clearSearch.hidden = !el.search.value;
    clearTimeout(timer);
    timer = setTimeout(() => { state.query = el.search.value.trim(); apply(); }, 200);
  });
  el.clearSearch.addEventListener('click', () => {
    el.search.value = '';
    el.clearSearch.hidden = true;
    state.query = '';
    apply();
    el.search.focus();
  });

  el.period.addEventListener('change', () => { state.period = el.period.value; apply(); });
  el.area.addEventListener('change', () => { state.area = el.area.value; apply(); });
  el.sort.addEventListener('change', () => { state.sort = el.sort.value; apply(); });
  el.deadlineOnly.addEventListener('change', () => {
    state.deadlineOnly = el.deadlineOnly.checked;
    apply();
  });

  $('#resetFilters').addEventListener('click', resetFilters);

  el.refresh.addEventListener('click', async () => {
    el.refresh.classList.add('is-spinning');
    try {
      const res = await fetch(DATA_URL, { cache: 'reload' });
      const data = await res.json();
      state.all = (data.events || []).map(prepare);
      state.sourceNames = data.source_names || {};
      state.updatedAt = data.updated_at || null;
      renderFooter();
      apply();
      toast('最新の情報に更新しました');
    } catch (_) {
      toast('更新できませんでした');
    } finally {
      el.refresh.classList.remove('is-spinning');
    }
  });

  // カードのクリック（詳細表示 / お気に入り）
  el.list.addEventListener('click', (e) => {
    const fav = e.target.closest('.fav-btn');
    if (fav) {
      e.stopPropagation();
      toggleFavorite(fav.dataset.id, fav);
      return;
    }
    const card = e.target.closest('.card');
    if (card) openDetail(card.dataset.id);
  });

  // モーダル
  el.modal.addEventListener('click', (e) => {
    if (e.target.closest('[data-close]')) closeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !el.modal.hidden) closeModal();
  });

  // 下端に近づいたら続きを描画
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      if (entries.some((x) => x.isIntersecting)) loadMore();
    }, { rootMargin: '600px' });
    io.observe(el.sentinel);
  }
  // IntersectionObserver が動かない環境向けの保険
  window.addEventListener('scroll', () => {
    const bottom = document.documentElement.scrollHeight - window.scrollY - window.innerHeight;
    if (bottom < 700) loadMore();
  }, { passive: true });
}

/** 続きを描画する（表示できるものが残っていれば） */
function loadMore() {
  if (state.shown >= state.filtered.length) return;
  state.shown += PAGE_SIZE;
  renderList();
}

function resetFilters() {
  state.category = 'all';
  state.period = 'upcoming';
  state.area = 'all';
  state.sort = 'date';
  state.query = '';
  state.deadlineOnly = false;
  el.search.value = '';
  el.clearSearch.hidden = true;
  el.period.value = 'upcoming';
  el.area.value = 'all';
  el.sort.value = 'date';
  el.deadlineOnly.checked = false;
  [...el.tabs.querySelectorAll('.tab')].forEach((t) => {
    const on = t.dataset.cat === 'all';
    t.classList.toggle('is-active', on);
    t.setAttribute('aria-selected', String(on));
  });
  apply();
}

// ------------------------------------------------------------ 絞り込み

function inPeriod(ev) {
  const start = ev._start;
  const end = ev._end;
  const t = today();

  if (state.period === 'all') return true;
  // 日付が分からないもの（ニュース系）は「これから開催」では残す
  if (!start) return state.period === 'upcoming';

  const startDays = daysFromToday(start);
  const endDays = daysFromToday(end || start);

  switch (state.period) {
    case 'upcoming':
      return endDays >= 0;
    case 'today':
      return startDays <= 0 && endDays >= 0;
    case 'week':
      return endDays >= 0 && startDays <= 7;
    case 'weekend': {
      // 直近の土日（今日が土日ならその週末）
      const dow = t.getDay();
      const toSat = (6 - dow + 7) % 7;
      const sat = new Date(t); sat.setDate(t.getDate() + toSat);
      const sun = new Date(sat); sun.setDate(sat.getDate() + 1);
      return (start <= sun && (end || start) >= sat);
    }
    case 'month': {
      const last = new Date(t.getFullYear(), t.getMonth() + 1, 0);
      return endDays >= 0 && start <= last;
    }
    case 'next-month': {
      const first = new Date(t.getFullYear(), t.getMonth() + 1, 1);
      const last = new Date(t.getFullYear(), t.getMonth() + 2, 0);
      return start <= last && (end || start) >= first;
    }
    default:
      return true;
  }
}

function inArea(ev) {
  if (state.area === 'all') return true;
  if (state.area === '__unknown') return !ev._pref;
  if (REGION_OF[state.area]) return ev._pref === state.area;      // 都道府県
  return ev._region === state.area || ev._pref === state.area;    // 地方・オンライン等
}

function isDeadlineSoon(ev) {
  if (!ev._deadline) return false;
  const n = daysFromToday(ev._deadline);
  return n >= 0 && n <= DEADLINE_SOON_DAYS;
}

function apply() {
  const q = normalize(state.query);
  const terms = q ? q.split(/[,、　 ]+/).filter(Boolean) : [];

  state.filtered = state.all.filter((ev) => {
    if (state.category === 'fav') {
      if (!state.favorites.has(ev.id)) return false;
    } else if (state.category !== 'all' && ev.category !== state.category) {
      return false;
    }
    if (state.deadlineOnly && !isDeadlineSoon(ev)) return false;
    if (!inArea(ev)) return false;
    // お気に入りタブは期間で隠さない
    if (state.category !== 'fav' && !inPeriod(ev)) return false;
    if (terms.length && !terms.every((t) => ev._search.includes(t))) return false;
    return true;
  });

  sortEvents(state.filtered);
  state.shown = PAGE_SIZE;
  updateTabCounts();
  renderStatus();
  renderList();
}

function sortEvents(list) {
  const big = 8640000000000;
  if (state.sort === 'new') {
    list.sort((a, b) => b._newTs - a._newTs);
    return;
  }
  if (state.sort === 'deadline') {
    // まだ申し込める締切 → 締切なし → 受付終了 の順に並べる
    const rank = (ev) => {
      if (!ev._deadline) return 1;
      return daysFromToday(ev._deadline) >= 0 ? 0 : 2;
    };
    list.sort((a, b) => {
      const ra = rank(a);
      const rb = rank(b);
      if (ra !== rb) return ra - rb;
      const av = a._deadline ? a._deadline.getTime() : big;
      const bv = b._deadline ? b._deadline.getTime() : big;
      // 受付終了のものは「最近終わったもの」から並べる
      if (av !== bv) return ra === 2 ? bv - av : av - bv;
      return (a._start ? a._start.getTime() : big) - (b._start ? b._start.getTime() : big);
    });
    return;
  }
  // 開催日が近い順（日付不明は末尾に新着順で）
  list.sort((a, b) => {
    const av = a._start ? a._start.getTime() : big;
    const bv = b._start ? b._start.getTime() : big;
    if (av !== bv) return av - bv;
    if (!a._start && !b._start) return b._newTs - a._newTs;
    return (a.title || '').localeCompare(b.title || '', 'ja');
  });
}

function updateTabCounts() {
  const counts = { all: 0, doujin: 0, anime_event: 0, campaign: 0, fav: state.favorites.size };
  // タブの件数は「カテゴリ以外の条件」を適用した数を出す
  const q = normalize(state.query);
  const terms = q ? q.split(/[,、　 ]+/).filter(Boolean) : [];
  for (const ev of state.all) {
    if (state.deadlineOnly && !isDeadlineSoon(ev)) continue;
    if (!inArea(ev)) continue;
    if (!inPeriod(ev)) continue;
    if (terms.length && !terms.every((t) => ev._search.includes(t))) continue;
    counts.all += 1;
    if (counts[ev.category] !== undefined) counts[ev.category] += 1;
  }
  [...el.tabs.querySelectorAll('.tab')].forEach((tab) => {
    const cat = tab.dataset.cat;
    const base = tab.textContent.replace(/\s*\d[\d,]*$/, '').trim();
    const n = counts[cat] ?? 0;
    tab.innerHTML = `${escapeHtml(base)}<span class="count">${n.toLocaleString('ja-JP')}</span>`;
  });
}

// ------------------------------------------------------------ 描画

function renderStatus() {
  const n = state.filtered.length;
  const label = state.category === 'fav' ? '保存したイベント'
    : (CATEGORY_LABEL[state.category] || 'イベント');
  el.status.innerHTML = `${escapeHtml(label)} <strong>${n.toLocaleString('ja-JP')}</strong> 件`;
  el.empty.hidden = n > 0;
}

function renderList() {
  const items = state.filtered.slice(0, state.shown);
  const frag = document.createDocumentFragment();
  const groupByDate = state.sort === 'date';
  let lastKey = null;

  for (const ev of items) {
    if (groupByDate) {
      const key = ev.start_date || 'none';
      if (key !== lastKey) {
        frag.appendChild(dateHeader(ev._start));
        lastKey = key;
      }
    }
    frag.appendChild(card(ev));
  }

  el.list.replaceChildren(frag);

  // 「もっと見る」
  const rest = state.filtered.length - state.shown;
  el.sentinel.hidden = rest <= 0;
  const old = document.querySelector('.more-btn');
  if (old) old.remove();
  if (rest > 0) {
    const btn = document.createElement('button');
    btn.className = 'more-btn';
    btn.type = 'button';
    btn.textContent = `さらに表示（残り ${rest.toLocaleString('ja-JP')} 件）`;
    btn.addEventListener('click', loadMore);
    el.list.after(btn);
  }
}

function dateHeader(d) {
  const div = document.createElement('div');
  div.className = 'date-head';
  if (!d) {
    div.innerHTML = '<span class="dh-badge">日程未定・通年</span>';
    return div;
  }
  div.innerHTML = `<span class="dh-badge">${escapeHtml(fmtDate(d))}</span>`
    + `<span class="dh-rel">${escapeHtml(relLabel(d))}</span>`;
  return div;
}

function card(ev) {
  const art = document.createElement('article');
  art.className = 'card';
  art.dataset.id = ev.id;

  const d = ev._start;
  let dateBox;
  if (d) {
    const cls = d.getDay() === 0 ? ' is-sun' : d.getDay() === 6 ? ' is-sat' : '';
    dateBox = `<div class="card-date${cls}">
        <span class="cd-month">${d.getMonth() + 1}月</span>
        <span class="cd-day">${d.getDate()}</span>
        <span class="cd-wday">${WDAY[d.getDay()]}</span>
      </div>`;
  } else {
    dateBox = '<div class="card-date is-none"><span class="cd-day">未定</span></div>';
  }

  const pills = [`<span class="pill pill-${ev.category}">${CATEGORY_LABEL[ev.category] || ''}</span>`];
  if (ev._pref) pills.push(`<span class="pill pill-area">${escapeHtml(ev._pref)}</span>`);
  if (isDeadlineSoon(ev)) {
    pills.push(`<span class="pill pill-soon">締切まで${daysFromToday(ev._deadline)}日</span>`);
  }

  const meta = [];
  if (ev.venue) meta.push(escapeHtml(ev.venue));
  if (ev.date_text && ev.date_text !== ev.start_date) meta.push(escapeHtml(ev.date_text));
  if (ev.summary) meta.push(escapeHtml(ev.summary));

  const favOn = state.favorites.has(ev.id);

  art.innerHTML = `
    ${dateBox}
    <div class="card-body">
      <div class="card-top">${pills.join('')}</div>
      <h3 class="card-title">${escapeHtml(ev.title)}</h3>
      ${meta.length ? `<p class="card-meta">${meta.join('<span class="sep">•</span>')}</p>` : ''}
      <div class="card-foot">
        <span class="src">${escapeHtml(sourceName(ev))}</span>
        ${deadlineNote(ev)}
        <button class="fav-btn${favOn ? ' is-on' : ''}" type="button"
                data-id="${escapeHtml(ev.id)}"
                aria-label="${favOn ? '保存を解除' : '保存する'}"
                title="${favOn ? '保存を解除' : '保存する'}">${favOn ? '★' : '☆'}</button>
      </div>
    </div>`;
  return art;
}

function shortDate(d) {
  return d ? `${d.getMonth() + 1}/${d.getDate()}` : '';
}

/** カード下部に出す申込締切の表示（過ぎていれば控えめに） */
function deadlineNote(ev) {
  if (!ev._deadline) return '';
  const past = daysFromToday(ev._deadline) < 0;
  const cls = past ? 'deadline is-past' : 'deadline';
  const text = past
    ? `サークル募集終了（〆 ${shortDate(ev._deadline)}）`
    : `申込〆 ${shortDate(ev._deadline)}`;
  return `<span class="${cls}">${escapeHtml(text)}</span>`;
}

function sourceName(ev) {
  return state.sourceNames[ev.source_id] || ev.source || ev.source_id || '';
}

function buildAreaOptions() {
  const prefCount = new Map();
  for (const ev of state.all) {
    if (!ev._pref) continue;
    prefCount.set(ev._pref, (prefCount.get(ev._pref) || 0) + 1);
  }
  const regions = ['北海道・東北', '関東', '中部', '近畿', '中国・四国', '九州・沖縄'];
  const frag = document.createDocumentFragment();

  const gRegion = document.createElement('optgroup');
  gRegion.label = '地方';
  for (const r of regions) {
    const n = [...prefCount].filter(([p]) => REGION_OF[p] === r).reduce((a, [, c]) => a + c, 0);
    if (!n) continue;
    gRegion.appendChild(new Option(`${r}（${n}）`, r));
  }
  if (gRegion.children.length) frag.appendChild(gRegion);

  const gPref = document.createElement('optgroup');
  gPref.label = '都道府県';
  [...prefCount.entries()]
    .filter(([p]) => REGION_OF[p])
    .sort((a, b) => b[1] - a[1])
    .forEach(([p, n]) => gPref.appendChild(new Option(`${p}（${n}）`, p)));
  if (gPref.children.length) frag.appendChild(gPref);

  const gOther = document.createElement('optgroup');
  gOther.label = 'その他';
  for (const p of ['オンライン', '海外']) {
    if (prefCount.has(p)) gOther.appendChild(new Option(`${p}（${prefCount.get(p)}）`, p));
  }
  const unknown = state.all.filter((e) => !e._pref).length;
  if (unknown) gOther.appendChild(new Option(`開催地の記載なし（${unknown}）`, '__unknown'));
  if (gOther.children.length) frag.appendChild(gOther);

  el.area.appendChild(frag);
}

function renderFooter() {
  if (state.updatedAt) {
    const d = new Date(state.updatedAt);
    if (!isNaN(d)) {
      el.updatedNote.textContent =
        `最終更新: ${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 `
        + `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
        + `（1日2回、自動で更新されます）`;
    }
  }
  const links = {
    akaboo: 'https://www.akaboo.jp/',
    ketto: 'https://ketto.com/',
    'natalie-comic': 'https://natalie.mu/comic',
    'natalie-music': 'https://natalie.mu/music',
    'natalie-stage': 'https://natalie.mu/stage',
    animeanime: 'https://animeanime.jp/',
    otakuma: 'https://otakuma.net/',
    prtimes: 'https://prtimes.jp/',
  };
  el.sourceList.replaceChildren(...Object.entries(state.sourceNames)
    .filter(([id]) => links[id])
    .map(([id, name]) => {
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = links[id];
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = name;
      li.appendChild(a);
      return li;
    }));
}

// ------------------------------------------------------------ 詳細

function openDetail(id) {
  const ev = state.all.find((x) => x.id === id);
  if (!ev) return;

  const rows = [];
  if (ev._start) {
    let when = fmtDate(ev._start);
    if (ev._end && ev.end_date && ev.end_date !== ev.start_date) when += ` 〜 ${fmtDate(ev._end)}`;
    if (ev.date_text && /\d{1,2}:\d{2}/.test(ev.date_text)) when += `　${ev.date_text}`;
    rows.push(['開催日', `${when}<br><span style="color:var(--text-faint)">${relLabel(ev._start)}</span>`]);
  } else if (ev.date_text) {
    rows.push(['開催日', escapeHtml(ev.date_text)]);
  }
  if (ev.venue) rows.push(['会場', escapeHtml(ev.venue)]);
  if (ev._pref) rows.push(['開催地', escapeHtml(ev._pref)]);
  if (ev._deadline) {
    const n = daysFromToday(ev._deadline);
    let note = '';
    if (n < 0) note = '<span style="color:var(--text-faint)"> （受付は終了しています）</span>';
    else if (n <= DEADLINE_SOON_DAYS) note = `<span style="color:var(--danger);font-weight:700"> （あと${n}日）</span>`;
    rows.push(['サークル参加申込締切', escapeHtml(fmtDate(ev._deadline)) + note]);
  }
  if (ev.entry) rows.push(['一般入場', escapeHtml(ev.entry)]);
  rows.push(['情報源', escapeHtml(sourceName(ev))]);

  const tagList = (ev.tags || []).slice(0, 8);
  const tags = tagList.map((t) => `<span class="pill pill-area">${escapeHtml(t)}</span>`).join('');
  // 要約がタグと同じ内容なら重ねて出さない
  const summary = tagList.includes((ev.summary || '').trim()) ? '' : (ev.summary || '');
  const favOn = state.favorites.has(ev.id);

  el.modalBody.innerHTML = `
    <div class="card-top" style="margin-bottom:6px">
      <span class="pill pill-${ev.category}">${CATEGORY_LABEL[ev.category] || ''}</span>
    </div>
    <h2 id="modalTitle">${escapeHtml(ev.title)}</h2>
    ${tags ? `<div class="m-tags">${tags}</div>` : ''}
    ${summary ? `<p class="m-summary">${escapeHtml(summary)}</p>` : ''}
    <table class="m-table"><tbody>
      ${rows.map(([k, v]) => `<tr><th>${escapeHtml(k)}</th><td>${v}</td></tr>`).join('')}
    </tbody></table>
    <div class="m-actions">
      <button class="btn" type="button" id="modalFav">${favOn ? '★ 保存済み' : '☆ 保存する'}</button>
      ${ev.url ? `<a class="btn btn-primary" href="${escapeHtml(ev.url)}" target="_blank" rel="noopener noreferrer">公式ページを見る →</a>` : ''}
    </div>`;

  const favBtn = $('#modalFav');
  favBtn.addEventListener('click', () => {
    toggleFavorite(ev.id);
    favBtn.textContent = state.favorites.has(ev.id) ? '★ 保存済み' : '☆ 保存する';
  });

  el.modal.hidden = false;
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  el.modal.hidden = true;
  document.body.style.overflow = '';
}

// ------------------------------------------------------------ お気に入り

function loadFavorites() {
  try {
    return new Set(JSON.parse(localStorage.getItem(FAV_KEY) || '[]'));
  } catch (_) {
    return new Set();
  }
}

function saveFavorites() {
  try {
    localStorage.setItem(FAV_KEY, JSON.stringify([...state.favorites]));
  } catch (_) { /* 保存できなくても動作は続ける */ }
}

function toggleFavorite(id, btn) {
  const on = state.favorites.has(id);
  if (on) state.favorites.delete(id); else state.favorites.add(id);
  saveFavorites();

  if (btn) {
    btn.classList.toggle('is-on', !on);
    btn.textContent = on ? '☆' : '★';
    btn.setAttribute('aria-label', on ? '保存する' : '保存を解除');
    btn.title = on ? '保存する' : '保存を解除';
  }
  toast(on ? '保存を解除しました' : '★ 保存しました');

  updateTabCounts();
  if (state.category === 'fav') apply();
}

// ------------------------------------------------------------ その他

let toastTimer = null;
function toast(msg) {
  el.toast.textContent = msg;
  el.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.toast.hidden = true; }, 1800);
}

function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  if (location.protocol === 'file:') return;
  navigator.serviceWorker.register('sw.js').catch(() => { /* 失敗しても通常表示は可能 */ });
}
