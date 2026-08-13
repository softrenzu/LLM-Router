# Contributing

Issueには、期待するルーティング判断、入力のデータ区分、再現可能な最小設定を含めてください。実データやAPIキーは含めないでください。

変更前後で次を実行します。

```bash
python -m compileall -q src tests evals examples
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python evals/run_policy_eval.py --config router.example.json
```

新しいルーティング機能には、正常系だけでなく、機密データ、費用上限、障害注入、監査証跡のテストを追加してください。性能を主張するPull Requestには、比較対象と同じ問題、予算、ツール、タイムアウト、試行回数を使った結果を添付してください。

