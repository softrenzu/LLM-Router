# Sakana Fuguとの比較根拠

確認日: 2026年8月13日

この文書は「公開情報から確認できる機能差」と「まだ証明していない性能差」を分離します。Sakana AIの非公開内部仕様を推測して断定しません。

## 確認した一次情報

- [Sakana Fugu公式ページ](https://sakana.ai/fugu/)
- [Sakana Fugu Technical Report, arXiv:2606.21228v2](https://arxiv.org/abs/2606.21228)
- [SakanaAI/fugu 公式GitHub](https://github.com/SakanaAI/fugu)
- [Fugu-Ultra v1.1公式発表](https://sakana.ai/fugu-1-1-claude-code-interface/)

## 公開仕様から確認できること

1. Fuguは複数LLMを1つのOpenAI互換APIとして提供する。
2. 通常のFuguは、入力ごとに1つのワーカーモデルを選ぶ低遅延構成である。
3. Fugu-Ultraは自然言語でエージェントワークフローを生成し、Technical Reportの学習設定では最大5ステップ、Gemini、Claude、GPT系の3モデルを利用する。
4. Fuguでは一部モデルを除外できるが、Fugu-Ultraのモデルプールは固定と説明されている。
5. 各クエリで実際に使った基盤モデルや協調方法は、独自技術のため公開しないとFAQに明記されている。
6. 新しいフロンティアモデル公開後、更新版の学習と評価に約2週間を見込むと説明されている。
7. リクエストごとのトークンと費用は確認できる。
8. EU/EEAでは現時点でサービスを提供していない。
9. 2026年7月24日のv1.1で、Claude Code互換インターフェースと評価値の改善が発表された。

## 本実装が機能範囲で上回る点

| 差分 | 実装箇所 | 検証方法 |
|---|---|---|
| ルーティング判断の全面開示 | `planner.py`、`/v1/route/plan` | 候補点数と除外理由を取得 |
| 実行経路の署名付き証明 | `receipts.py`、`/v1/routes/{id}` | SHA-256とHMACを再計算 |
| リクエスト単位のデータ主権 | `policy.py`、`planner.py` | restrictedケースでクラウドが除外されるテスト |
| ローカル・閉域モデル | 汎用OpenAI互換Provider | 外部通信なしのvLLM/NIMへ接続 |
| 継続的なオンライン適応 | `store.py`、`/v1/feedback` | 次回計画の事後品質が変化 |
| 費用・遅延の事前制約 | `RouteConstraints` | 上限超過モデルを実行前に拒否 |
| 障害時の自動縮退 | `circuit.py`、`cascade` | 障害注入テストで次モデルへ移行 |
| プロバイダー相関の低減 | `parallel_consensus` | 異なるproviderを優先選定 |

## まだ上回ったと主張しない項目

- SWE-Bench Pro、Terminal Bench、GPQA-Diamond等の最終スコア
- 同一費用における回答品質
- 同一品質における平均・p95遅延
- 長時間エージェント作業の完遂率
- Fugu Cyberとのサイバーセキュリティ性能

これらはモデルプールそのものの能力、推論設定、ツールハーネス、費用上限に強く依存します。`evals/run_live_benchmark.py`を使い、比較対象にも同じ問題、ツール、試行回数、タイムアウト、予算を適用した結果だけを公開対象とします。

## 結論

本リポジトリは、Fuguの価値である「複数モデルを1モデルとして使う」を維持しつつ、公開仕様上の弱点であるブラックボックス性、固定プール、クラウド依存、更新待ち、リクエスト単位ポリシー不足を埋めています。現段階で正しく言えるのは「機能と運用統制では上回る設計・実装」であり、「全ベンチマークでFuguより高性能」ではありません。

