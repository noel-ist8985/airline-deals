/* 航空セール情報アプリ — メインロジック */
(() => {
  'use strict';

  // ===== 航空会社マスタ(表示色・カテゴリ) =====
  const AIRLINES = {
    'JAL':           { color: '#c8102e', category: '大手' },
    'ANA':           { color: '#13448f', category: '大手' },
    'Peach':         { color: '#e6007e', category: 'LCC' },
    'Jetstar Japan': { color: '#ff5100', category: 'LCC' },
    'ZIPAIR':        { color: '#00b0b9', category: 'LCC' },
    'Spring Japan':  { color: '#00913a', category: 'LCC' },
    'Skymark':       { color: '#0068b7', category: 'LCC' },
    'Solaseed Air':  { color: '#f5a800', category: 'LCC' },
    'StarFlyer':     { color: '#374151', category: 'LCC' },
    'AIRDO':         { color: '#0093d0', category: 'LCC' },
    'Fuji Dream':    { color: '#e6338c', category: 'LCC' },
  };
  const DEFAULT_COLOR = '#8a94a6';
  const airlineColor = (name) => (AIRLINES[name] && AIRLINES[name].color) || DEFAULT_COLOR;
  const airlineCategory = (name) => (AIRLINES[name] && AIRLINES[name].category) || 'その他';

  // ===== localStorage キー =====
  const LS_FAV = 'ad.favAirlines';
  const LS_VISIT = 'ad.lastVisit';

  // ===== 状態 =====
  const state = {
    all: [],
    type: 'all',
    search: '',
    sort: 'new',
    favOnly: false,
    hideExpired: true,
    selectedAirlines: new Set(),
    favorites: new Set(loadJSON(LS_FAV, [])),
  };
  let PREV_VISIT = null; // 前回起動時刻(NEW判定用)

  // ===== ユーティリティ =====
  function loadJSON(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
    catch (_) { return fallback; }
  }
  function saveJSON(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (_) {}
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  const $ = (sel) => document.querySelector(sel);

  function parseDate(s) {
    if (!s) return null;
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }
  function fmtDate(s) {
    const d = parseDate(s);
    if (!d) return '';
    return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
  }
  function fmtPrice(v) {
    if (v == null || v === '') return '';
    return '¥' + Number(v).toLocaleString('ja-JP') + '〜';
  }

  /** 締切の状態を返す */
  function deadlineInfo(sale) {
    const end = parseDate(sale.saleEnd);
    const now = new Date();
    if (!end) return { text: '', cls: '', expired: false };
    const ms = end - now;
    if (ms <= 0) return { text: '受付終了', cls: 'expired', expired: true };
    const days = Math.ceil(ms / 86400000);
    if (ms < 86400000) return { text: '本日締切', cls: 'soon', expired: false };
    if (days <= 3) return { text: `締切まで残り${days}日`, cls: 'soon', expired: false };
    return { text: `締切まで残り${days}日`, cls: '', expired: false };
  }

  function isNew(sale) {
    if (!PREV_VISIT) return false;
    const p = parseDate(sale.postedAt);
    return p ? p > PREV_VISIT : false;
  }

  function matchesSearch(sale, q) {
    if (!q) return true;
    const hay = [sale.airline, sale.title, sale.summary, (sale.routes || []).join(' '), (sale.tags || []).join(' ')]
      .join(' ').toLowerCase();
    return hay.includes(q);
  }

  // ===== フィルタ&ソート =====
  function visibleSales() {
    const q = state.search.trim().toLowerCase();
    let list = state.all.filter((s) => {
      if (state.type !== 'all' && s.type !== state.type) return false;
      if (state.selectedAirlines.size && !state.selectedAirlines.has(s.airline)) return false;
      if (state.favOnly && !state.favorites.has(s.airline)) return false;
      if (state.hideExpired && deadlineInfo(s).expired) return false;
      if (!matchesSearch(s, q)) return false;
      return true;
    });
    list.sort((a, b) => {
      if (state.sort === 'deadline') {
        const ea = deadlineInfo(a).expired, eb = deadlineInfo(b).expired;
        if (ea !== eb) return ea ? 1 : -1;
        const da = parseDate(a.saleEnd), db = parseDate(b.saleEnd);
        return (da ? da.getTime() : Infinity) - (db ? db.getTime() : Infinity);
      }
      const pa = parseDate(a.postedAt), pb = parseDate(b.postedAt);
      return (pb ? pb.getTime() : 0) - (pa ? pa.getTime() : 0);
    });
    return list;
  }

  // ===== 描画: 航空会社フィルタ =====
  function renderAirlineFilter() {
    const container = $('#airlineFilter');
    const names = [...new Set(state.all.map((s) => s.airline))];
    // 並び: お気に入り → 大手 → 名前
    names.sort((a, b) => {
      const fa = state.favorites.has(a), fb = state.favorites.has(b);
      if (fa !== fb) return fa ? -1 : 1;
      const ca = airlineCategory(a) === '大手', cb = airlineCategory(b) === '大手';
      if (ca !== cb) return ca ? -1 : 1;
      return a.localeCompare(b, 'ja');
    });

    container.innerHTML = names.map((name) => {
      const active = state.selectedAirlines.has(name) ? ' is-active' : '';
      const fav = state.favorites.has(name) ? ' is-fav' : '';
      return `<div class="al-chip${active}${fav}" data-airline="${esc(name)}">
        <span class="dot" style="background:${airlineColor(name)}"></span>
        <span class="al-name">${esc(name)}</span>
        <span class="star" data-fav="${esc(name)}" title="お気に入り">★</span>
      </div>`;
    }).join('');
  }

  // ===== 描画: カード一覧 =====
  function renderList() {
    const list = visibleSales();
    const wrap = $('#cardList');
    const empty = $('#emptyState');

    if (!list.length) {
      wrap.innerHTML = '';
      empty.hidden = false;
      return;
    }
    empty.hidden = true;

    wrap.innerHTML = list.map((s) => {
      const dl = deadlineInfo(s);
      const color = airlineColor(s.airline);
      const price = fmtPrice(s.priceFrom);
      const routes = (s.routes || []).slice(0, 2).join('・');
      return `<article class="card${dl.expired ? ' is-expired' : ''}" data-id="${esc(s.id)}" style="--airline-color:${color}">
        <div class="card-top">
          <span class="airline-badge"><span class="dot" style="background:${color}"></span>${esc(s.airline)}</span>
          <span class="type-tag" data-type="${esc(s.type)}">${esc(s.type)}</span>
          ${isNew(s) ? '<span class="new-badge">NEW</span>' : ''}
        </div>
        <h2>${esc(s.title)}</h2>
        <p class="summary">${esc(s.summary)}</p>
        <div class="card-meta">
          ${price ? `<span class="meta-item price">${esc(price)}</span>` : ''}
          ${dl.text ? `<span class="meta-item deadline ${dl.cls}">⏳ ${esc(dl.text)}</span>` : ''}
          ${routes ? `<span class="meta-item">✈ ${esc(routes)}</span>` : ''}
        </div>
      </article>`;
    }).join('');
  }

  function renderAll() {
    renderAirlineFilter();
    renderList();
  }

  // ===== 詳細モーダル =====
  function openDetail(id) {
    const s = state.all.find((x) => x.id === id);
    if (!s) return;
    const dl = deadlineInfo(s);
    const rows = [];
    if (s.priceFrom != null) rows.push(['最安', fmtPrice(s.priceFrom)]);
    const period = [fmtDate(s.saleStart), fmtDate(s.saleEnd)].filter(Boolean);
    if (period.length) rows.push(['受付期間', period.length === 2 ? `${period[0]} 〜 ${period[1]}` : period[0]]);
    if (dl.text) rows.push(['締切', dl.text]);
    if (s.travelPeriod) rows.push(['搭乗期間', s.travelPeriod]);
    if ((s.routes || []).length) rows.push(['対象路線', s.routes.join('・')]);
    if (s.postedAt) rows.push(['掲載日', fmtDate(s.postedAt)]);
    if (s.source && s.source !== 'manual') rows.push(['情報元', s.source]);

    $('#modalBody').innerHTML = `
      <div class="card-top" style="margin-bottom:8px">
        <span class="airline-badge"><span class="dot" style="background:${airlineColor(s.airline)}"></span>${esc(s.airline)}</span>
        <span class="type-tag" data-type="${esc(s.type)}">${esc(s.type)}</span>
        ${isNew(s) ? '<span class="new-badge">NEW</span>' : ''}
      </div>
      <h2 class="modal-title" id="modalTitle">${esc(s.title)}</h2>
      <p style="color:var(--text-muted);margin:0 0 12px">${esc(s.summary)}</p>
      ${rows.map(([l, v]) => `<div class="modal-row"><span class="label">${esc(l)}</span><span>${esc(v)}</span></div>`).join('')}
      ${(s.tags || []).length ? `<div class="modal-tags">${s.tags.map((t) => `<span class="modal-tag">#${esc(t)}</span>`).join('')}</div>` : ''}
      ${s.url ? `<a class="official-btn" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">公式ページで見る ↗</a>` : ''}
    `;
    $('#detailModal').hidden = false;
    document.body.style.overflow = 'hidden';
  }
  function closeDetail() {
    $('#detailModal').hidden = true;
    document.body.style.overflow = '';
  }

  // ===== トースト =====
  let toastTimer = null;
  function toast(msg) {
    const el = $('#toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
  }

  // ===== 通知ボタン =====
  function refreshNotifyBtn() {
    const btn = $('#notifyBtn');
    const label = btn.querySelector('.notify-label');
    const p = AppNotify.permission();
    if (p === 'granted') { btn.classList.add('is-on'); label.textContent = '通知ON'; }
    else { btn.classList.remove('is-on'); label.textContent = '通知'; }
  }
  async function onNotifyClick() {
    if (!AppNotify.supported) { toast('この環境は通知に対応していません'); return; }
    const p = await AppNotify.request();
    refreshNotifyBtn();
    if (p === 'granted') {
      toast('通知をオンにしました');
      AppNotify.show('通知を設定しました', { body: '新しいセール情報が入るとお知らせします。', tag: 'welcome' });
    } else if (p === 'denied') {
      toast('通知はブラウザ設定でブロックされています');
    }
  }

  // ===== イベント =====
  function bindEvents() {
    $('#searchInput').addEventListener('input', (e) => { state.search = e.target.value; renderList(); });

    $('#categoryChips').addEventListener('click', (e) => {
      const chip = e.target.closest('.chip');
      if (!chip) return;
      state.type = chip.dataset.type;
      $('#categoryChips').querySelectorAll('.chip').forEach((c) => c.classList.toggle('is-active', c === chip));
      renderList();
    });

    $('#favOnly').addEventListener('change', (e) => { state.favOnly = e.target.checked; renderList(); });
    $('#hideExpired').addEventListener('change', (e) => { state.hideExpired = e.target.checked; renderList(); });
    $('#sortSelect').addEventListener('change', (e) => { state.sort = e.target.value; renderList(); });

    $('#airlineFilter').addEventListener('click', (e) => {
      const star = e.target.closest('[data-fav]');
      if (star) {
        const name = star.dataset.fav;
        if (state.favorites.has(name)) state.favorites.delete(name); else state.favorites.add(name);
        saveJSON(LS_FAV, [...state.favorites]);
        renderAll();
        return;
      }
      const chip = e.target.closest('.al-chip');
      if (!chip) return;
      const name = chip.dataset.airline;
      if (state.selectedAirlines.has(name)) state.selectedAirlines.delete(name); else state.selectedAirlines.add(name);
      renderAirlineFilter();
      renderList();
    });

    $('#cardList').addEventListener('click', (e) => {
      const card = e.target.closest('.card');
      if (card) openDetail(card.dataset.id);
    });

    $('#detailModal').addEventListener('click', (e) => { if (e.target.closest('[data-close]')) closeDetail(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDetail(); });

    $('#resetFilters').addEventListener('click', () => {
      state.type = 'all'; state.search = ''; state.favOnly = false; state.hideExpired = true;
      state.selectedAirlines.clear();
      $('#searchInput').value = ''; $('#favOnly').checked = false; $('#hideExpired').checked = true;
      $('#categoryChips').querySelectorAll('.chip').forEach((c) => c.classList.toggle('is-active', c.dataset.type === 'all'));
      renderAll();
    });

    $('#notifyBtn').addEventListener('click', onNotifyClick);
  }

  // ===== Service Worker 登録 =====
  function registerSW() {
    if (!('serviceWorker' in navigator)) return;
    if (location.protocol === 'file:') return; // file:// では動かない
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }

  // ===== 新着の表示 =====
  function showNewStatus(newItems) {
    const bar = $('#statusBar');
    if (!newItems.length) { bar.hidden = true; return; }
    bar.hidden = false;
    bar.textContent = `🎉 前回チェック以降の新着が ${newItems.length} 件あります`;
  }

  // ===== 初期化 =====
  async function init() {
    registerSW();
    bindEvents();
    refreshNotifyBtn();

    const prevRaw = localStorage.getItem(LS_VISIT);
    PREV_VISIT = prevRaw ? new Date(prevRaw) : null;

    let data;
    try {
      const res = await fetch('data/sales.json', { cache: 'no-cache' });
      data = await res.json();
    } catch (_) {
      $('#cardList').innerHTML = '<p style="color:var(--text-muted)">データの読み込みに失敗しました。サーバー経由で開いているか確認してください。</p>';
      return;
    }

    state.all = (data.sales || []).filter((s) => s && s.id);

    // データ更新日の表示
    const note = $('#dataNote');
    const updated = data.updatedAt ? `データ更新: ${fmtDate(data.updatedAt)}　` : '';
    note.textContent = `${updated}※これはサンプルデータです。data/sales.json を編集して更新できます。`;

    renderAll();

    // 新着検知(初回起動時は基準作りのため通知しない)
    const newItems = PREV_VISIT ? state.all.filter(isNew) : [];
    showNewStatus(newItems);
    if (newItems.length) AppNotify.notifyNewItems(newItems);

    // 今回の起動時刻を記録
    localStorage.setItem(LS_VISIT, new Date().toISOString());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
