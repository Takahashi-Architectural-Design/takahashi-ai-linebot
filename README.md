# はるかな — 建築設計事務所・工務店向け AI業務基盤（LINE Bot）

AI社員（ハル・松陰・土方など）が LINE で応答します。
AIエンジンは **Anthropic Claude / OpenAI / Amazon Bedrock / Google Gemini** から
環境変数ひとつで選択でき、顧客の既存IT環境に合わせて差し替えられます。

構成・売り分けの考え方は [`docs/multi-ai-architecture.md`](docs/multi-ai-architecture.md) を参照。

## 構成

| ファイル | 役割 |
|---|---|
| `app.py` | LINE webhook・担当切替・会話履歴 |
| `agents.py` | AI社員（人格・業務知識）の定義。顧客ごとに差し替え可能 |
| `ai_providers.py` | AIエンジン抽象化レイヤー。各社SDKの差を吸収 |
| `examples/agents.sample.json` | 顧客ごとのAI社員定義のサンプル |
| `tests/` | エンジン層・AI社員定義のテスト（SDK不要） |

## セットアップ

```bash
pip install -r requirements.txt
```

必須の環境変数：

```bash
export LINE_CHANNEL_SECRET=...
export LINE_CHANNEL_ACCESS_TOKEN=...
export AI_PROVIDER=anthropic          # anthropic | openai | bedrock | gemini
export ANTHROPIC_API_KEY=...          # 選んだ基盤に対応するキー
```

基盤ごとの必要変数・モデルIDの指定方法は
[`docs/multi-ai-architecture.md`](docs/multi-ai-architecture.md#2-エンジンの切り替え方) にまとめてあります。

その他の任意設定：

| 変数 | 既定 | 内容 |
|---|---|---|
| `AI_MAX_TOKENS` | `1024` | 1回の応答の最大トークン |
| `HISTORY_LIMIT` | `20` | 保持する会話履歴の件数 |
| `HARUKANA_AGENTS_FILE` / `HARUKANA_AGENTS_JSON` | 標準チーム | 顧客ごとのAI社員定義 |

起動：

```bash
gunicorn app:app --bind 0.0.0.0:$PORT   # 本番（Render）
python app.py                            # ローカル
```

`GET /` はヘルスチェックで、現在のAI基盤とAI社員一覧を JSON で返します。

## LINEでの操作

| 送る言葉 | 動作 |
|---|---|
| `松陰` / `土方` / `坂本龍馬` など | 担当のAI社員に切り替え（別名でも可） |
| `メンバー` | AI社員の一覧 |
| `エンジン` | 現在のAI基盤と選択肢を表示 |
| `エンジン:openai` | AI基盤を切り替え |
| `リセット` | 現在の担当との会話履歴を消す |

## テスト

各社SDKはスタブに差し替えているため、SDK未インストールでも実行できます。

```bash
python -m unittest discover -s tests
```

## 注意

会話履歴と担当・基盤の選択はプロセス内メモリで保持しています。
再起動すると消え、複数ワーカー構成では共有されません（現在 `gunicorn.conf.py` は
`workers = 1`）。複数社に展開する際は外部ストア（Redis / DB）への置き換えが必要です。
