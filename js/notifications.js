/* 通知まわり(ローカル通知)
 * - 起動中/起動時に新着を検知して通知するためのモジュール。
 * - アプリを閉じた状態でのサーバープッシュは未対応(将来バックエンドが必要)。
 */
const AppNotify = (() => {
  const supported = 'Notification' in window;

  function permission() {
    return supported ? Notification.permission : 'unsupported';
  }

  async function request() {
    if (!supported) return 'unsupported';
    if (Notification.permission === 'granted') return 'granted';
    try {
      return await Notification.requestPermission();
    } catch (_) {
      return Notification.permission;
    }
  }

  /** 通知を表示。Service Worker があればそちら経由(より確実)、無ければ直接。 */
  async function show(title, options = {}) {
    if (!supported || Notification.permission !== 'granted') return false;
    const opts = {
      body: options.body || '',
      icon: 'icons/icon-192.png',
      badge: 'icons/icon-192.png',
      tag: options.tag || 'airline-deals',
      data: options.data || {},
      ...options,
    };
    try {
      if ('serviceWorker' in navigator) {
        const reg = await navigator.serviceWorker.ready;
        await reg.showNotification(title, opts);
        return true;
      }
    } catch (_) { /* フォールバックへ */ }
    try {
      new Notification(title, opts);
      return true;
    } catch (_) {
      return false;
    }
  }

  /** 新着(前回閲覧より新しい postedAt)をまとめて1通知にする。 */
  async function notifyNewItems(items) {
    if (!items.length) return;
    if (Notification.permission !== 'granted') return;
    const count = items.length;
    const title = count === 1
      ? `新着セール: ${items[0].airline}`
      : `新着セール情報 ${count}件`;
    const body = count === 1
      ? items[0].title
      : items.slice(0, 3).map((s) => `・${s.airline} ${s.title}`).join('\n');
    await show(title, { body, tag: 'new-sales', renotify: true });
  }

  return { supported, permission, request, show, notifyNewItems };
})();
