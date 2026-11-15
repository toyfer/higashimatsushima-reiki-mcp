# 東松島市例規 静的 API & Remote MCP サーバー

東松島市が公開している例規集の公式 HTML を日次で監視・構造化し、**GitHub Pages 上の読み取り専用静的 JSON API** と、それをラップした **Cloudflare Workers 上のステートレス Remote MCP サーバー** として提供するプロジェクトです。

- **一次情報**: [東松島市例規集（公式 HTML）](https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_menu.html) — 正本は常に市公式サイトです。本 API・MCP の出力は公開ページからの機械抽出データであり、重要な判断・対外案内では応答に含まれる `source_url` から原文も確認してください。
- **公開静的 API 入口**: `https://toyfer.github.io/higashimatsushima-reiki-mcp/`
- **Remote MCP エンドポイント**: `https://higashimatsushima-reiki-mcp.toys-master.dev/mcp`

## プロジェクトの現在地と方向性

初期構想では Cloudflare D1 への格納も視野に入れていましたが、維持コストとデータ同期の不整合をなくすため、現在は **「GitHub Pages 静的 JSON ＋ ビッググラム TF-IDF シャード ＋ ステートレス Cloudflare Worker」** を正式な本番アーキテクチャとして採用し、すでに全自動パイプラインで運用しています。

- **目指すゴール**: LLM / MCP クライアントが東松島市の現行例規（1,192 件）を、最小限のトークン消費かつハルシネーションなしで検索し、一次情報 URL・内容現在日・データ版数付きの根拠としてそのまま引用できる実用 MCP を安定運用すること。
- **スコープ境界（やらないこと）**:
  - **過去時点スナップショット（`asof`）**: 公式 HTML が現在版のみを掲載しているため非対応とし、明確なエラーで拒否します。
  - **外部ファイル（RTF / PNG）の本文自動抽出**: ダウンロード形式の別表・様式は OCR や RTF 変換を行わず、`content_status: "external_resource_only"` と一次資料リンク（`resource`）を返して本文欠落の誤認を防ぎます。
- **今後のロードマップ・設計記録**: アーキテクチャ判断、LLM 視点の UX 改善基準、および対応を進めた課題（`#110`〜`#112`, `#115`）の全体像は [`docs/roadmap-and-llm-ux.md`](docs/roadmap-and-llm-ux.md) にまとめています。

## 使う側（LLM / MCP クライアント）向けガイド

### エンドポイント

| パス | 用途 |
|---|---|
| `GET /` | サービス概要、公開ツール一覧、接続先 Pages ベース URL |
| `GET /live` | Worker 単体の生存確認（Pages 取得なし、常に HTTP 200） |
| `GET /health` | 公開静的 API（`api/health.json`）を含めた稼働確認（異常時は HTTP 503） |
| `GET /mcp` | MCP エンドポイントの説明情報 |
| `POST /mcp` | MCP（Streamable HTTP / stateless JSON-RPC 2.0）エンドポイント |

`AUTH_TOKEN` が設定された環境では、`POST /mcp` に対して `Authorization: Bearer <token>` ヘッダが必要です（`GET /`, `/live`, `/health`, `/mcp` は認証なしで参照可能です）。

### MCP ツール一覧（7 ツール）

| ツール名 | 主な用途 | 主な入力 | 参照する静的ファイル |
|---|---|---|---|
| `reiki_status` | 公開データの鮮度・版・検索索引状態の取得 | なし | `api/meta.json`, `api/health.json`, `api/search/manifest.json` |
| `search_laws_by_title` | 例規名・例規番号・分類・ID による検索（要旨のみ） | `query`, `limit` | `api/search/title-index.json` |
| `search_laws_by_content` | 2段階本文検索（bigram 候補抽出＋厳密語句照合） | `query`, `limit`, `law_id`, `operator`, `scope`, `group_by`, `exact`, `snippet_chars` | `api/search/manifest.json`, `postings-*.json`, `chunks-*.json`（`law_id` 指定時は個別 JSON のみ 1 fetch） |
| `get_toc` | 条文見出し一覧、章節構造、前文・別表・附則の規模確認 | `law_id`, `offset`, `limit` | `api/laws/{law_id}.json` |
| `get_article` | 条・項・号を指定した確定本文の取得（条番号の表記ゆれ正規化、`source_url` 返却） | `law_id`, `article_label`, `paragraph`, `item`, `include_plain_text` | `api/laws/{law_id}.json` |
| `get_unit` | 別表（`appendix_table` / `beppyo`）、附則（`supplement` / `suppl`）または様式（`appendix_style` / `style`）の個別取得 | `law_id`, `kind`, `n` | `api/laws/{law_id}.json` |
| `get_law` | 1 例規の全文 JSON 取得（小規模例規・要綱向け） | `law_id` | `api/laws/{law_id}.json` |

ツール引数の詳細仕様は [`worker/README.md`](worker/README.md) を参照してください。

### LLM から正確・低トークンで使うための推奨フロー

1. **入口は `search_laws_by_title` または `search_laws_by_content` を使う**
   - 名称や番号が分かっている場合は軽量な `search_laws_by_title`（NFKC 正規化・空白区切り AND 対応）を使います。
   - 制度内容・金額・条件から探す場合は `search_laws_by_content` を使います。検索結果の `snippet` は前後抜粋（既定 280 文字）のため、**回答や引用の根拠として確定する前に必ず `get_article` / `get_unit` / 小規模例規の `get_law` で一次本文を確認してください**。
2. **原則 `get_toc` を挟んでから必要な条・単位だけを取得する**
   - 大規模条例にいきなり `get_law` を呼ぶと応答が極端に大きくなります（例：`r122RG00000066` 東松島市市税条例は約 834 KB / 36.4 万文字）。
   - まず `get_toc` で `source_url`、`article_count`、`has_body_text`、`appendix_table_count`、`appendix_style_count`、`supplement_count` を確認し、条文がある場合は `get_article`（必要に応じて `paragraph` / `item` 指定）や `get_unit` を使います。
   - 要綱・ガイドラインなど `article_count === 0` かつ `has_body_text === true` の例規や、数条のみの短い例規を読む場合に限り `get_law` が適しています。
3. **本文検索の仕様と制約を踏まえて判定する**
   - **2 文字以上必須**: インデックスが 2-gram のみのため、1 文字（例: `税`）は検索対象外です。
   - **厳密一致と数値境界**: 既定の `exact: true` では `600点`＋`500万円` による `600万円` 誤一致や、`3,600万円` の中での `600万円` 誤一致を除外します。表記ゆれも含めて広げたい場合のみ `exact: false` を使います。
   - **網羅性と欠落の確認**: 応答の `completeness`（今回の fetch / 走査予算に対する `complete` / `partial`）、`index_cap_reached`、`capped_terms`、`completeness_note`、`truncation_reasons`、`index_caps`（1 語最大 50 posting・1 例規最大 3 posting・1 回最大 46 fetch / 300 候補）および別表の `content_status`（`external_resource_only`）を確認し、上限到達や外部ファイル未収録を「該当なし」と誤認しないようにします。

## アーキテクチャと静的 API

### システム構成

| レイヤー | 役割 |
|---|---|
| 東松島市公式サイト | 例規集の公式 HTML。常に一次情報源として扱う |
| GitHub Actions `daily-reiki-check.yml` | 毎日 03:17 JST にメニューページのハッシュと内容現在日を確認。変更時のみ目次を再クロールし、ステータス更新・通知 Issue 作成・Pages フルビルド起動を行う |
| GitHub Actions `pages.yml` | `site/api/` 以下に静的 JSON と検索インデックスを生成し、整合性検証のうえ GitHub Pages へデプロイする（コード変更 push・週次定期・日次変更検知から実行） |
| GitHub Pages | 読み取り専用静的 API（`api/meta.json`, `api/laws/*.json`, `api/search/*`）の配信基盤 |
| Cloudflare Worker（`worker/`） | 静的 API をエッジキャッシュ付きでラップし、MCP エンドポイント（`/mcp`）と `/health` を提供する |
| MCP クライアント（LLM） | Worker の `/mcp` を呼び出す（GitHub Pages を直接取得しない） |

### 公開静的 API エンドポイント（`site/api/`）

| パス | 内容 |
|---|---|
| `api/meta.json` | 生成日時、内容現在日、メニューハッシュ、`data_version`、例規件数、警告・失敗情報 |
| `api/health.json` | ビルド健全性（`ok`, `law_count`, `expected_count`, `failure_count`, `validation_problems`, `data_version`, `commit_sha`） |
| `api/laws/index.json` | 全例規メタデータ一覧（ID・名称・発令日・例規番号・体系分類・条数・先頭条文・警告） |
| `api/laws/{law_id}.json` | 1 例規の構造化 JSON（条・項・号・附則・別表・様式テキスト・外部リソース対応表・沿革・`content_current_date`・`data_version`） |
| `api/search/title-index.json` | タイトル検索用の軽量インデックス |
| `api/search/manifest.json` | 本文検索インデックスのマニフェスト（`bigram-tfidf`、件数、シャードファイル一覧） |
| `api/search/chunks-{000..NNN}.json` | 本文検索チャンク（500 チャンク/シャード。見出し、ラベル、スニペット、検証用全文 `text`、`content_status`） |
| `api/search/postings-{00..NN}.json` | 用語ハッシュで分割した bigram TF-IDF ポスティング（16 シャード） |

### 別表と外部リソースの扱い

`resources[]` には別表と様式（`form`）のダウンロードリンク（RTF / PNG）が混在するため、単純な配列位置ではなく `appendix_table_resource_index` によって別表と外部リソースを厳密に対応付けています（`appendix_table_resource_index[0] === 2` なら 1 番目の別表に対応する資料は `resources[2]`、該当なしは `null`）。また、様式本文は `appendix_styles` へ分離され、見出しのみで実体が RTF/PNG にある別表・様式には `content_status: "external_resource_only"` が付与され、Worker は相対 `href` / `image_url` に加えて解決済み `href_url` / `image_full_url` を返します。様式は `get_toc` の `appendix_style_count` / `appendix_styles` で把握し、`get_unit` の `kind: "appendix_style"` で個別取得できます。

### 本文検索インデックスの実測値

`api/search/manifest.json` に記録される bigram TF-IDF インデックスは、Pages ビルド時に生成されます（Worker はリクエスト時にコーパス全体を走査しません）。

| 項目 | 現行値・実測（`data_version: d1db3e79d19f85e2` 時点） |
|---|---|
| 対象例規数 / チャンク数 | `1,192` 例規 / `19,619` チャンク |
| チャンクシャード / ポスティングシャード | `40` チャンクシャード（`chunk_shard_size: 500`） + `16` ポスティングシャード = 計 `56` シャード（`manifest.json` 含め `57` ファイル） |
| 総サイズ / 最大シャード | `31.5 MiB` / チャンク最大 `916 KiB`（`chunks-002.json`）・ポスティング最大 `614 KiB`（`postings-15.json`） |
| インデックス上限 | 1 ターム最大 `50` postings（1 例規・1 ターム最大 `3` postings） |
| Worker 呼び出し上限 | 1 リクエスト最大 `46` Pages fetches / `300` 候補検証 / `10` posting shards |

## ワークフローとローカル開発

### GitHub Actions 構成

- **`daily-reiki-check.yml`**: 毎日 `18:17 UTC`（`03:17 JST`）に実行。`mode=check` ではメニューページのみを確認し、ハッシュまたは内容現在日が変化したときだけ体系目次をクロールして `data/status/latest.json` を更新し、`pages.yml`（`full_build=true`）を呼び出します。
- **`pages.yml`**: `site/**`・ビルダー系スクリプト・ステータスファイル・自身の変更を含む `main` push、週次スケジュール（土曜 `19:17 UTC` = 日曜 `04:17 JST`）、日次チェックからの `workflow_call`、または手動実行で静的 API を構築・検証して GitHub Pages へ公開します。公開済み API が 5 件超の状態で誤って 5 件サンプルビルドで上書きしないよう、Sample downgrade guard（`allow_sample_overwrite=false` 既定）を実装しています。市サイトへ負荷をかけないよう、開発中に全量ビルドを連続実行しないでください。
- **`search-eval.yml`**: `pages.yml` の成功後に自動実行され、`tools/search_eval.mjs` で公開インデックスに対するゴールデンセット回帰テストを実行します。
- **`deploy-worker.yml`**: `worker/**` への `main` push または手動実行で Worker テストを実行し、公開済み検索インデックスの存在を確認したうえで Cloudflare Workers へデプロイ・疎通確認を行います。
- **`test.yml`**: PR および `main` push 時に Python 単体テスト・Worker 構文チェック・Worker テストを実行します（デプロイ処理は一切含みません）。

詳細は [`docs/github-actions.md`](docs/github-actions.md) および [`docs/search-eval.md`](docs/search-eval.md) を参照してください。

### ローカル実行コマンド

```bash
# Python テスト（ネットワーク不要）
python3 -m unittest discover -s tests -v

# Worker テスト（ネットワーク不要）
cd worker && npm ci && npm run check && npm test

# メニュー変更確認 / 5件サンプル静的 API ビルド / 単体 ID ビルド
python3 scripts/daily_check.py --mode check
python3 scripts/build_static_api.py --limit 5 --delay 0.1
python3 scripts/build_static_api.py --only-id r122RG00000002 --delay 0.1

# 検索インデックス計測 / 公式 HTML との構造突合 / 公開インデックス検索評価
python3 scripts/measure_search_index.py
python3 tools/verify_structure.py --sample 10
node tools/search_eval.mjs
```

### デプロイ順序と確認手順

Worker は GitHub Pages 上の静的 API と検索インデックスを参照するため、**必ず GitHub Pages の公開を先に完了させてから Worker をデプロイ**します（`deploy-worker.yml` でもデプロイ前に公開インデックスの存在を検証しています）。

```bash
# 1. 静的 API と検索インデックスを全量公開（Pages ワークフロー手動実行時）
#    full_build=true, allow_sample_overwrite=false, delay_seconds=0.35

# 2. 公開インデックスと健全性の確認
curl -fsS "https://toyfer.github.io/higashimatsushima-reiki-mcp/api/search/manifest.json"
curl -fsS "https://toyfer.github.io/higashimatsushima-reiki-mcp/api/health.json"

# 3. Worker デプロイ（worker/** 更新または Deploy Worker workflow 実行）後、稼働確認
curl -fsS "https://higashimatsushima-reiki-mcp.toys-master.dev/health"
```

## リポジトリ構成

| パス | 役割 |
|---|---|
| `README.md` | プロジェクト全体の案内、方向性、LLM 利用ガイド、構成一覧 |
| `docs/roadmap-and-llm-ux.md` | 設計方針（非 D1 構成・非目標）、LLM UX 改善基準、Open Issue マップ |
| `docs/github-actions.md` | 日次チェックと Pages ビルド・ガード設計の詳細 |
| `docs/search-eval.md` | 検索ゴールデンセットの目的とケース仕様 |
| `worker/README.md` | MCP Worker エンドポイントと 7 ツールの詳細仕様 |
| `scripts/` | 変更検知（`daily_check.py`）、HTML 解析（`parse_honbun.py`）、静的 API 構築（`build_static_api.py`）、索引生成（`search_index.py`） |
| `worker/` | ステートレス MCP Worker（`src/index.js`）と単体・契約テスト（`test/`） |
| `tools/` | 構造突合（`verify_structure.py`）、検索ゴールデンセット評価（`search_eval.mjs`）、検索探索プローブ（`search_probe.mjs`） |
| `tests/` | パーサー・ビルダー・索引・ワークフロー不変条件のユニットテスト |
| `data/status/latest.json` | 最新のメニューハッシュ、内容現在日、例規 URL 一覧 |
| `site/index.html` | 静的 API の人間向け案内ページ |
