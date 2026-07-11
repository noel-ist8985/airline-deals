# 航空セール情報アプリ ✈️🏷️

日本の航空会社(JAL・ANA・Peach・Jetstar Japan・ZIPAIR ほか)の**セール・キャンペーン・イベント情報をまとめてチェック**できる、スマホ向けの Web アプリ(PWA)です。ホーム画面に追加すれば、ふつうのアプリのように全画面で使えます。

**情報は PR TIMES から自動取得**でき、GitHub の無料機能でクラウド上で定期更新・公開できます。

## できること
- 航空会社のセール/キャンペーン/イベントを一覧表示
- **PR TIMES から自動取得**(JAL・Jetstar・Peach を初期設定済み。他社も追加可)
- 航空会社・種別での絞り込み、キーワード検索
- お気に入り航空会社の登録(★)、お気に入りのみ表示
- 締切までの残り日数を表示、終了したものは自動で淡色/非表示
- 前回チェック以降の**新着に「NEW」バッジ**+**ローカル通知**

---

## 情報の2系統
このアプリのデータ(`data/sales.json`)は、次の2つを統合して作られます。

| 種類 | ファイル | 内容 |
|---|---|---|
| **手動** | `data/manual.json` | 自分で書く情報。価格・締切・路線まで細かく載せられる。**編集するのはこちら。** |
| **自動** | (PR TIMES から取得) | プレスリリース由来。タイトル・要約・リンク・日付・種別が自動で入る(価格・締切は空のことが多い)。 |

> ⚠️ `data/sales.json` は自動生成される統合結果です。**直接編集しても次回の自動取得で上書きされます。**手で足したい情報は `data/manual.json` に書いてください。

---

## 1. パソコンで試す(プレビュー)

サーバー経由で開く必要があります(ファイルを直接ダブルクリックだと通知やホーム画面追加が動きません)。Mac には最初から `python3` が入っています。

```bash
cd ~/Desktop/airline-deals
python3 -m http.server 8000
```
ブラウザで **http://localhost:8000** を開く。止めるときは `Control + C`。

### 最新情報を取得してみる(手動実行)
```bash
cd ~/Desktop/airline-deals
python3 scripts/fetch_deals.py
```
PR TIMES から取得し、`data/manual.json` と統合して `data/sales.json` を書き出します。追加インストールは不要です。

---

## 2. 【おすすめ】GitHub でクラウド自動更新＋公開する

Mac を起動していなくても、クラウド上で**1日2回(朝7時・夜7時)自動取得**し、スマホからいつでも見られるようにします。すべて**無料**です。

### 手順
1. **GitHub アカウントを作成**(https://github.com/signup)
2. **新しいリポジトリを作成**(Repositories → New)。名前は例:`airline-deals`。**Public** を選択。
3. **ファイルをアップロード**
   - かんたんなのは公式アプリ **GitHub Desktop**(https://desktop.github.com)。作ったリポジトリを「クローン」し、`airline-deals` フォルダの中身をコピーして「Commit → Push」。
   - もしくは GitHub のWebページでもOK(Add file → Upload files でドラッグ&ドロップ)。※Webの場合、`.github` などの隠しフォルダは GitHub Desktop の方が確実です。
4. **Actions の書き込みを許可**(自動更新の保存に必要)
   - Settings → Actions → General → 一番下 **Workflow permissions** → **Read and write permissions** を選んで Save。
5. **自動更新を有効化**
   - Actions タブを開き、案内が出たら **I understand… enable**。左の「セール情報の自動更新」→ **Run workflow** で今すぐ実行テストもできます。
6. **公開(GitHub Pages)**
   - Settings → Pages → Source を **Deploy from a branch** → Branch を **main / (root)** → Save。
   - 数十秒後に表示される **https://ユーザー名.github.io/airline-deals/** があなたのアプリURLです。
7. **スマホに追加**:そのURLをスマホの Chrome で開き、メニュー(⋮)→ **ホーム画面に追加**。

> メモ:GitHub の定期実行は、リポジトリに60日間まったく更新がないと自動で止まります。時々 push するか手動実行すれば復活します。

---

## 3. 対象の航空会社を増やす

自動取得は `scripts/sources.json` の設定で決まります。初期状態では **JAL・Jetstar Japan・Peach** が有効です。

新しい社を追加するには:
1. https://prtimes.jp でその会社名を検索し、企業ページを開く。
2. URL の末尾の数字(例:`.../company_id/81560` の `81560`)が **company_id**。
3. `scripts/sources.json` に、その ID を入れて `"enabled": true` にする。

```json
{ "airline": "ZIPAIR", "url": "https://prtimes.jp/companyrdf.php?company_id=ここにID", "enabled": true }
```
`airline` 名を `js/app.js` の `AIRLINES` に登録済みの名前(JAL / ANA / Peach / Jetstar Japan / ZIPAIR / Spring Japan / Skymark / Solaseed Air / StarFlyer / AIRDO / Fuji Dream)に合わせると、色付きで表示されます。

> ANA・スカイマークなどは PR TIMES を使わず自社サイト中心のため、初期状態では無効にしてあります(IDが見つかれば有効化できます)。

### 抽出キーワードの調整
「セール/キャンペーン/割引…」等どのリリースを拾うかは、`scripts/fetch_deals.py` 冒頭の
`INCLUDE_KEYWORDS`(拾う語)・`EXCLUDE_KEYWORDS`(除外する語)で調整できます。

---

## 4. 手動で情報を足す

`data/manual.json` の `sales` に1件追加するだけです(価格や締切まで載せたいときに便利)。

```json
{
  "id": "好きな一意のID",
  "airline": "Peach",
  "type": "セール",
  "title": "夏の全路線タイムセール",
  "summary": "国内線が片道1,000円台〜。",
  "url": "https://www.flypeach.com/...",
  "priceFrom": 1290,
  "currency": "JPY",
  "routes": ["成田-札幌", "関西-那覇"],
  "saleStart": "2026-07-14T12:00:00+09:00",
  "saleEnd":   "2026-07-16T23:59:00+09:00",
  "travelPeriod": "2026-09-01〜2026-12-20",
  "postedAt":  "2026-07-11T08:00:00+09:00",
  "tags": ["国内線", "タイムセール"]
}
```
`postedAt` を新しくすると次回起動時に「NEW」バッジ＆通知が出ます。

---

## 通知について(前提)
- 通知は **アプリを開いたときに新着を検知して出す「ローカル通知」** です。
- アプリを閉じている間に自動でプッシュ通知を飛ばすには常時稼働のプッシュサーバーが別途必要で、今回の構成では対象外です(将来追加可能)。

## ファイル構成
```
airline-deals/
├── index.html                画面
├── manifest.webmanifest      PWA設定
├── sw.js                     オフライン&通知
├── css/styles.css            デザイン
├── js/app.js                 メイン処理
├── js/notifications.js       通知処理
├── data/manual.json          ← 手動の情報はここを編集
├── data/sales.json           自動生成(手動+自動の統合結果。直接編集しない)
├── scripts/fetch_deals.py    自動取得スクリプト(標準ライブラリのみ)
├── scripts/sources.json      ← 取得元(航空会社とPR TIMESのID)
├── .github/workflows/update-deals.yml   GitHubの自動更新設定
└── icons/                    アプリアイコン
```

> 自動取得はプレスリリース(PR TIMES)由来のため、価格や締切などの細かい情報は空になることがあります。詳細は各カードの「公式ページで見る」から確認してください。`data/manual.json` の初期サンプルは架空の内容なので、不要になったら削除してください。
