# Resource テスト用 fixture

`valid/` は検証・展開テスト用の小さなリポジトリです。実際の課題や
Docker ビルド用ファイルには依存しません。Dockerfile の digest と
manifest の lock はテスト用のダミー値で、イメージのビルドには使いません。
`ready=True` の正常系テストでは入力ハッシュを計算して lock を設定します。

`invalid/<ケース名>/` には、そのケースで置き換える完全な YAML 定義を
保存します。テストは一時ディレクトリへ `valid/` をコピーした後、ケースの
ファイルを上書きして `validate()` に渡します。YAML の内容は加工しません。
存在しない期待出力は `missing.txt` の参照で、重複キーは YAML 自体で表現します。

ケースを追加するときは `invalid/` に定義を置き、
`tests/test_resources.py` の `test_invalid_definitions` に期待するエラーを追加します。
symlink、ビルド入力の変更、ファイルモードなどのファイル操作はテスト内で行います。
