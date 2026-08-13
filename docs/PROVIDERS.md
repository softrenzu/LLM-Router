# プロバイダー設定

各モデルはOpenAI互換の `POST {base_url}/chat/completions` を提供すれば接続できます。特定ベンダーのSDKは使いません。

```json
{
  "id": "jp-local-reasoner",
  "provider": "local-vllm",
  "base_url": "http://vllm.internal:8000/v1",
  "model": "your-model-id",
  "api_key_env": "LOCAL_LLM_API_KEY",
  "deployment": "local",
  "regions": ["JP"],
  "capabilities": ["chat", "tools", "json", "reasoning", "code"],
  "context_window": 131072,
  "max_output_tokens": 32768,
  "max_data_class": "restricted",
  "input_cost_per_million": 0,
  "output_cost_per_million": 0,
  "latency_ms": 1800,
  "quality": {
    "general": 0.72,
    "code": 0.80,
    "math": 0.78,
    "research": 0.70
  }
}
```

## フィールド

| フィールド | 意味 |
|---|---|
| `id` | ルーター内で一意の公開しやすい名前 |
| `provider` | 同一障害・誤り相関を判断するプロバイダー群 |
| `base_url` | `/v1`までを含むOpenAI互換URL |
| `model` | 上流へ渡す実モデルID |
| `api_key_env` | APIキーを読む環境変数名。キー本体は書かない |
| `deployment` | `local` または `cloud` |
| `regions` | 処理可能な地域。`global` は全地域扱い |
| `capabilities` | `chat`、`tools`、`json`、`vision`、`audio`等 |
| `max_data_class` | そのモデルへ送信できる最高機密区分 |
| `quality` | 0から1のタスク別事前品質。未指定タスクは`general` |

## vLLM、NVIDIA NIM、TGI、Ollama

それぞれOpenAI互換エンドポイントを有効にし、その `/v1` URLを `base_url` へ指定します。製品固有の認証ヘッダーが必要な場合は `headers` を追加できます。ただし秘密情報は `headers` へ直接書かず、リバースプロキシまたは環境変数ベースのBearer認証を利用してください。

## クラウドLLM

プロバイダーのOpenAI互換URLとモデルIDを指定します。データ保持、学習利用、リージョン、契約上の取扱いを確認してから `max_data_class` を設定してください。初期値の `internal` を安全保証として扱わず、自社契約に合わせて厳しく設定します。

## 品質事前値の校正

最初は保守的な値を入れ、実運用に近い検証セットでタスク別成功率を測定します。利用者フィードバックは事前値を上書きせず、事前強度4の平滑化付き事後平均として徐々に反映されます。

