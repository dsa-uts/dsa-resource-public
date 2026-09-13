# DSA Resource Public

課題定義は [resources.yaml](resources.yaml) を入口にGitで管理します。
このリポジトリは `dsa-uts/dsa-resource` のコミット
`fb19745dd7e1f7c8e918238cad7918ff9ab0136a` をコピーした、課題1の公開スナップショットです。
元リポジトリとの自動同期は行いません。

コンテナイメージは `ghcr.io/dsa-uts/dsa-resource-public-sandbox` に登録します。
公開後はリポジトリの取得・イメージのpullにGitHub tokenは不要です。
CIの公開処理は自動発行される `GITHUB_TOKEN` を使い、PATの設定は不要です。
初回登録時の公開設定は[Actionsによる公開](docs/resource-contract.md#actionsによる公開)を参照してください。

- [課題定義と実行の仕様](docs/resource.md): Workflow・Job・Step、Artifact、採点規則。
- [リポジトリ契約](docs/resource-contract.md): イメージ管理、Actions、Backendへのインポート。
- [課題定義の実例](ex1/resource.yaml): コンパイルと公開・非公開テスト。

Jobのイメージは、コンパイル用の [`default`](sandbox/Dockerfile)、ビルド済みプログラムの実行用の [`runner`](sandbox-runner/Dockerfile) から選びます。

課題の変更を公開するときは、対象の `resource.yaml` の `resource.version` を登録済みの最大値より大きい整数に変更します。mainのCIがイメージlockを確定・検証した後、`resources.yaml` にversionと取得元コミットSHAを自動登録します。履歴は手編集しません。同じversionのままの変更は公開済みの版に反映されません。詳細は[Resource Version](docs/resource-contract.md#resource-version)を参照してください。

## ローカル検証

[uv](https://docs.astral.sh/uv/) を使用します。

```sh
uv sync --locked
uv run --locked scripts/resources.py validate
uv run --locked python -m unittest discover -s tests -v
uv run --locked scripts/resources.py expand --allow-unbuilt
```

`validate` は定義と参照の検証、`expand --allow-unbuilt` はレビュー用の展開です。
`tests/` は検証・展開とイメージ公開処理の回帰テストで、課題のコマンド実行や模範解答のAC確認は行いません。

Backendへのインポート前の確認は[ready検証](docs/resource-contract.md#検証と展開)を参照してください。
