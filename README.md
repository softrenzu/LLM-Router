# Rooomtech LLM Router

品質だけでなく、費用、遅延、障害、機密区分、リージョン、プロバイダー相関まで同時に判断する、説明可能なマルチLLMルーターです。OpenAI互換の Chat Completions API と Responses API を提供し、vLLM、NVIDIA NIM、TGI、Ollama、クラウドLLMを同じモデルプールとして扱えます。

> 開発状況: `v0.1.0-alpha`。公開仕様上の機能範囲では Sakana Fugu の制約を超える設計ですが、SWE-Bench Pro等における総合性能の優位性はまだ実測していません。比較可能な評価ハーネスを同梱し、結果が出る前に性能を誇張しない方針です。

## 何が新しいか

- **Sovereignty Lattice** — リクエスト単位で `public / internal / confidential / restricted` を判定し、クラウド流出をポリシーで遮断
- **Transparent Route Receipt** — 選定候補、除外理由、評価値、実行モデル、費用、遅延を記録し、HMAC署名で改ざんを検知
- **Adaptive Topology** — `direct`、`cascade`、`draft_verify`、`parallel_consensus` を難易度とリスクに応じて切替
- **Correlated-error Defense** — 合議時は可能な限り異なるプロバイダーを選び、同系列モデルの誤り相関を抑制
- **Continuous Bandit Learning** — `/v1/feedback` の結果をSQLiteへ反映し、再学習を待たず次のルーティングから改善
- **Hard Policy Gates** — データ区分、利用地域、必要能力、コンテキスト長、費用上限、遅延上限をスコア計算前に強制
- **Counterfactual Planning** — `/v1/route/plan` で実行せずに候補、点数、除外理由、予定費用を確認
- **Air-gap First** — 実行時依存パッケージなし。Python標準ライブラリだけで動作し、閉域のOpenAI互換推論基盤へ接続可能

## Sakana Fuguとの差分

2026年8月13日時点の[Sakana Fugu公式ページ](https://sakana.ai/fugu/)と[Technical Report](https://arxiv.org/abs/2606.21228)に基づく比較です。

| 項目 | Sakana Fuguの公開仕様 | Rooomtech LLM Router |
|---|---|---|
| 通常ルーティング | Fuguは入力ごとに1ワーカーを選択 | 単体、順次フォールバック、独立検証、並列合議 |
| 高性能ルーティング | Ultraは最大5ステップ、固定プール | 任意のOpenAI互換モデル、プロバイダー分散、設定可能な並列数 |
| 選定の透明性 | 使用モデルと協調方法は非公開 | 全候補の点数、除外理由、実行経路をAPIで取得 |
| ポリシー | Fuguはモデル除外可、Ultraのプールは固定 | テナント別かつリクエスト別の機密・地域・費用・遅延制約 |
| 更新 | 新モデル追加時は約2週間の学習・評価予定 | 設定追加は即時、利用フィードバックは次回から反映 |
| 閉域・オンプレ | 公開サービスAPIが中心 | vLLM/NIM/TGI/Ollamaを完全閉域で利用可能 |
| 監査 | リクエスト費用は確認可能、経路は非公開 | プロンプト非保存の署名付きRoute Receipt |
| 提供地域 | EU/EEAでは未提供 | 自社運用のためデプロイ先を利用者が決定 |
| 実装 | オーケストレーターは非公開 | Apache-2.0の公開実装 |

詳しい根拠と、比較できていない項目は[docs/FUGU_COMPARISON.md](docs/FUGU_COMPARISON.md)に分離しています。

## 30秒で動かす

Dockerがある場合は、ルーターと3つのモックLLMをまとめて起動できます。

```bash
docker compose up --build
```

別ターミナルからリクエストします。

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rooomtech-auto",
    "messages": [{"role": "user", "content": "3案を比較し、誤りを検証して結論を出して"}],
    "routing": {
      "data_class": "public",
      "high_stakes": true,
      "max_cost_usd": 0.25,
      "max_latency_ms": 60000
    }
  }'
```

レスポンスには通常のOpenAI互換フィールドに加えて、次が入ります。

```json
{
  "rooomtech_route": {
    "id": "rt_...",
    "topology": "parallel_consensus",
    "models": ["cloud-scientist", "local-reasoner", "cloud-coder"],
    "synthesizer": "cloud-scientist",
    "estimated_cost_usd": 0.042,
    "actual_cost_usd": 0.038,
    "receipt_sha256": "...",
    "receipt_signature": "sha256=...",
    "explain_url": "/v1/routes/rt_..."
  }
}
```

### Dockerを使わない起動

Python 3.11以上だけで動きます。

```bash
cp router.example.json router.json
python examples/mock_provider.py --port 9101 --name local-reasoner
python examples/mock_provider.py --port 9102 --name cloud-coder
python examples/mock_provider.py --port 9103 --name cloud-scientist
PYTHONPATH=src python -m rooomtech_router --config router.json
```

最初の3コマンドは別ターミナルで起動してください。実際のLLMへ接続する場合はモックを起動せず、`base_url` と `model` を対象のOpenAI互換エンドポイントへ変更します。

## OpenAIクライアントから使う

既存クライアントの `base_url` を差し替えるだけです。

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="router-key",
)

response = client.chat.completions.create(
    model="rooomtech-auto",
    messages=[{"role": "user", "content": "この設計をレビューして"}],
)
print(response.choices[0].message.content)
```

次の仮想モデル名で挙動を固定できます。

| モデル名 | 動作 |
|---|---|
| `rooomtech-auto` | 難易度、リスク、予算から自動選択 |
| `rooomtech-direct` | 最高得点の適格モデルを1つ選択 |
| `rooomtech-verified` | ドラフトを別モデルが検証・修正 |
| `rooomtech-consensus` | 独立並列回答を最終モデルが検証・統合 |
| 設定内のモデルID | ポリシー適格時のみ、そのモデルへ固定 |

## API

| メソッドとパス | 用途 |
|---|---|
| `POST /v1/chat/completions` | Chat Completions互換。SSEも受け付ける |
| `POST /v1/responses` | Responses互換の基本的なテキスト入出力 |
| `GET /v1/models` | 仮想モデル一覧 |
| `POST /v1/route/plan` | LLMを呼ばずルートを事前説明 |
| `GET /v1/routes/{route_id}` | 署名付き監査証跡と全候補の評価を取得 |
| `POST /v1/feedback` | `0.0`から`1.0`の報酬でオンライン更新 |
| `GET /healthz` / `GET /readyz` | 死活・準備状態 |
| `GET /metrics` | Prometheusテキスト形式のカウンター |

ルーティング制約はJSONの `routing` またはHTTPヘッダーで渡せます。

| JSON | HTTPヘッダー | 例 |
|---|---|---|
| `tenant_id` | `X-Rooomtech-Tenant` | `airgap` |
| `data_class` | `X-Rooomtech-Data-Class` | `restricted` |
| `region` | `X-Rooomtech-Region` | `JP` |
| `mode` | `X-Rooomtech-Mode` | `draft_verify` |
| `max_cost_usd` | `X-Rooomtech-Max-Cost-USD` | `0.25` |
| `max_latency_ms` | `X-Rooomtech-Max-Latency-Ms` | `60000` |
| `high_stakes` | JSONのみ | `true` |
| `required_capabilities` | JSONのみ | `["vision", "json"]` |

## フィードバックで継続改善

```bash
curl http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "route_id": "rt_...",
    "reward": 0.9,
    "category": "human_review"
  }'
```

モデルごと・タスク種別ごとの事前品質と実績をベイズ平滑化し、探索ボーナスを加えて選択します。品質の低いモデルを即時に永久排除せず、新バージョンの再評価機会も残します。

## セキュリティと閉域

- Route ReceiptとSQLiteにはプロンプト本文・回答本文を保存しません。監査用にはSHA-256だけを残します。
- `cache_ttl_seconds` を有効にした場合だけ、応答キャッシュへ回答本文が保存されます。機密環境では既定値 `0` のままにしてください。
- `ROOOMTECH_ROUTER_API_KEYS` にカンマ区切りのキーを設定するとBearer認証を有効化できます。本番では `require_auth: true` を指定します。
- `ROOOMTECH_RECEIPT_SECRET` を設定するとRoute ReceiptへHMAC-SHA256署名を付与します。
- APIキーは設定ファイルへ直接書かず、各モデルの `api_key_env` で環境変数を参照します。
- 自動検知した認証情報、カード番号らしき値、機密マーカーはデータ区分を引き上げます。DLP製品の代替ではないため、本番では上流DLPとの併用を推奨します。

詳しくは[SECURITY.md](SECURITY.md)を参照してください。

## テストと評価

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python evals/run_policy_eval.py --config router.example.json
```

任意のOpenAI互換APIに対する同一条件評価も実行できます。

```bash
PYTHONPATH=src python evals/run_live_benchmark.py \
  --endpoint http://localhost:8080 \
  --model rooomtech-consensus
```

実際に「Fuguより高性能」と判定するには、同一問題、同一ツール、同一タイムアウト、同一費用上限でFuguと本ルーターを評価する必要があります。現在はその結果を捏造せず、評価器と記録形式までを実装しています。

## 現在の制約

- SSEは互換形式ですが、v0.1では複数モデルの処理完了後に分割送信するバッファ型です。
- Responses APIは基本的なテキスト、画像入力の転送、ツール定義を扱いますが、全イベント型を網羅していません。
- プロセス内Circuit Breakerの状態は複数レプリカ間で共有されません。大規模運用ではRedis等の共有状態へ差し替える余地があります。
- 品質事前値は設定値です。本番データで校正してから意思決定に利用してください。

## ドキュメント

- [アーキテクチャ](docs/ARCHITECTURE.md)
- [Sakana Fuguとの根拠付き比較](docs/FUGU_COMPARISON.md)
- [プロバイダー設定](docs/PROVIDERS.md)
- [コントリビューション](CONTRIBUTING.md)

## License

Apache License 2.0

