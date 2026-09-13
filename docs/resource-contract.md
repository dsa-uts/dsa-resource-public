# Resource リポジトリ契約

manifest・イメージ管理・検証・Backendへの取り込みを定めます。課題定義と実行規則は [Resource仕様](resource.md) を参照してください。

このリポジトリは [JSON Schema](../schemas/) と [scripts/resources.py](../scripts/resources.py) による検証・展開、[scripts/build_images.py](../scripts/build_images.py) によるイメージ公開、および [scripts/publish_versions.py](../scripts/publish_versions.py) によるResource Version登録を実装します。Backendのインポート・利用Versionの選択とJudgeの実行処理は別実装です。

## Manifest

rootの [resources.yaml](../resources.yaml) にResource一覧と共通Sandbox Imageを定義します。各Resourceは専用directoryに `resource.yaml`、課題説明、Preset、期待出力を持ちます。

```yaml
resources:
  - id: ex1
    path: ex1/resource.yaml
    versions: []
sandbox-images:
  default:
    build:
      context: sandbox
      dockerfile: sandbox/Dockerfile
      image: ghcr.io/dsa-uts/dsa-resource-public-sandbox
      platforms: [linux/amd64]
    lock: null
```

`resources` の `id` と `path` はそれぞれ一意で、`path` は専用directoryの `resource.yaml` を指します。空配列は全Projectのarchiveを表すため許可します。

## Resource Version

各 `resource.yaml` の `resource.version` に正の整数を明示します。新規Resourceは例えば `1` から始めます。公開する変更では登録済みの最大値より大きい値を指定し、欠番は許容します。同じ値なら登録はno-op、小さい値は検証エラーです。複数のコミットをまとめ、公開の準備ができたところでversionを上げられます。

CIは内容の変更やversionの上げ忘れを検出しません。説明文・Preset・テスト・実行設定・共通イメージの変更を公開する場合、対象Resourceのversionを明示的に上げます。共通イメージが更新されても、versionを上げないResourceの公開済み版は以前のイメージを使い続けます。

root manifestの各Resourceに、botが次の履歴を昇順で追記します。`versions` の省略と空配列は未登録を表します。

```yaml
resources:
  - id: ex1
    path: ex1/resource.yaml
    versions:
      - version: 1
        commit: "1111111111111111111111111111111111111111"
      - version: 3
        commit: "3333333333333333333333333333333333333333"
```

`commit` はそのResourceの素材と全イメージlockがready検証に通ったコミットの40桁SHAです。履歴を書き込むbotコミット自身のSHAではありません。登録済みの `version → commit` は固定し、同じversionで後から修正しても参照先は変えません。修正を公開するには新しいversionを指定します。

履歴はbotの管理対象です。PR・main更新のCIは基準コミットと比較して、残っているResourceの履歴の手編集・追記・削除を拒否します。Resource自体の削除は従来どおり許容し、その履歴は過去のGitコミットに残ります。

### Path の共通規則

相対pathはclean POSIX形式とし、空path、`.`、`..` component、絶対path、backslash、NUL、colon、空componentを禁止します。参照先は基準root内に限定し、fileはregular fileのみでsymlink・hardlinkを拒否します。課題素材の基準rootは [Resource仕様](resource.md#基本規則) を参照してください。

buildのpathはrepository root基準です。`build.context` に限り `.` を字句上許可しますが、実際のcontextは `.git` やmanifestを含まない専用directoryにします。生成lockが自身のビルド入力になる循環を防ぎます。

## Sandbox Image

`sandbox-images` はroot manifestでのみ定義します。`resource.yaml` 内の `sandbox-images` は空mapを含めて拒否し、個別のDockerfile・build・lockは定義できません。Jobは `sandbox-image` に定義済みIDを指定します。イメージ名・Dockerfileの直接指定は拒否します。

| field | required | description |
| --- | --- | --- |
| `build.context` | yes | Docker build context。 |
| `build.dockerfile` | yes | Dockerfile path。contextではなくrepository root基準。 |
| `build.image` | yes | GHCRのpush先repository。tag/digestは含めない。 |
| `build.platforms` | yes | 空でない `linux/amd64` / `linux/arm64` の配列。 |
| `lock` | yes | 初回ビルド前は `null`。確定後は後述の全lock項目。 |

DockerfileはDebian slim系など承認済みbaseをtag＋digestで固定した単一FROMを使い、追加fileはcontext内のCOPYで取り込みます。ADD・外部frontend・追加build args/secret/contextは未対応です。FROM固定でもAPTなどRUN内の外部入力の完全再現は保証せず、完成イメージのdigestで実行環境を固定します。

現在の構成は [resources.yaml](../resources.yaml)、[コンパイル用Dockerfile](../sandbox/Dockerfile)、[実行用Dockerfile](../sandbox-runner/Dockerfile) を参照してください。contextを分けているため、片方の変更はもう片方の入力ハッシュに影響しません。

### Lockと入力ハッシュ

確定済みlockは次の全項目を持ちます。tagはcommit・Actions Run ID・attempt・イメージ連番を含み、同じGHCR repositoryを使う複数イメージでも衝突させません。

```yaml
lock:
  tag: <build-commit>-<actions-run-id>-<attempt>-<image-index>
  digest: sha256:<64-hex>
  input-hash: sha256:<64-hex>
  source-ref: <build-commit-40-hex>
  actions-run-id: "123456789"
```

`source-ref` はbuild開始コミットです。tag・digestをGitに保存し、Backend metadataにも取り込み時点の値を保持します。実行時は `image@sha256:...` をpullします。

入力ハッシュはSHA-256です。各要素を8-byte big-endian長＋bytesで順に連結します。
先頭はbuild mapをキー順・空白なしJSONにしたUTF-8 bytes。
続いてcontextの全entryを相対POSIX path順で列挙し、path、種類（directory=`d`、実行可能file=`x`、その他file=`f`）、fileの場合は内容を追加します。最後にDockerfile bytes、Dockerfile固有ignore file（`<dockerfile>.dockerignore`）のbytesを追加します。固有ignore fileが存在しなければ空bytesです。
`.dockerignore` で無視されるfileも含め、追加・削除・実行bit変更・空directoryを検知します。mtime、生成lock、Actions Run時刻は含めません。

lockのハッシュは入力との対応付けであり、信頼できない作者に対する署名ではありません。Admin管理のGitとActionsが信頼境界です。

## Actionsによる公開

[Actions設定](../.github/workflows/resources.yml) はPRとmain更新時に定義検証と回帰テストを実行します。mainでは未ビルド・入力ハッシュが変わったイメージだけをbuild / GHCR pushし、生成lockを `resources.yaml` へ直接コミットします。説明文・テストだけの変更では共通build入力が変わらず、digestを維持します。

手動実行の `rebuild`（既定true）で全イメージを再ビルドできます。FROMのdigestは変更しません。

公開Jobはmain専用・直列で、開始時の最新mainをcheckoutし再検証します。ビルド中にmainが進んだ場合は結果をコミットせず失敗とし、後続Runで最新mainを処理します。push直前の競合も通常のfast-forward pushで拒否します。

イメージlockのコミット・pushとready検証の後、同じ公開Jobで `scripts/publish_versions.py` を実行します。未登録のversionだけ、その時点のHEADを指す履歴として追記し、別のbotコミットでpushします。イメージに変更がなければlockコミットを作らず、現在のHEADを使います。初回登録も自動です。

登録処理はcleanなcheckoutを要求し、履歴の書き込み前に最新mainとの一致を確認します。pushまでの競合はfast-forward pushで拒否し、生成履歴をrebaseしません。後続Runは最新mainから処理し直します。登録済みversionは再実行しても追記しません。手動のイメージ再ビルドだけではResourceのversionを変更しません。

生成PRやBackend API呼び出しは行いません。生成コミットは `GITHUB_TOKEN` でpushし、新たなActions Runを起動しません。生成後のready検証は同じRun内で実行します。

必要な権限は検証に `contents: read`、公開に `contents: write` と `packages: write` です。mainのルールセットがbotの直接pushを許可し、GHCR packageへのActions書き込み権限が必要です。DHI認証やBackend用Secretは使いません。

GHCR packageは初回登録時にprivateになります。初回のimages Job完了後、
[package設定](https://github.com/orgs/dsa-uts/packages/container/dsa-resource-public-sandbox/settings)
の「Change visibility」で「Public」に変更してください。これはリポジトリの公開設定とは独立しています。
以降のタグも同じ公開packageに登録されます。
Dockerfileの `org.opencontainers.image.source` labelでこのリポジトリに関連付けます。

`public-images` JobはGitHubへのログイン情報を渡さず、lockのdigestを指定して全イメージをpullします。
初回はpackageをpublicにするまで失敗します。公開設定後に失敗したJobを再実行してください。
このJobの成功で、利用側がGitHub tokenなしでイメージを取得できることを確認します。

## 検証と展開

ローカル環境の準備と通常の検証コマンドは [README](../README.md#ローカル検証) を参照してください。

`validate` はJSON Schemaに加え、参照file、path境界、イメージID、Job依存関係、Artifact、timeout、ビルド入力を検証します。通常の検証は未確定・古いlockを許容するため、成功してもインポート可能とは限りません。

インポート前は対象コミットのcheckoutで次を実行します。

```sh
uv run --locked scripts/resources.py validate --ready
uv run --locked scripts/resources.py expand > /tmp/resolved-resources.yaml
```

`--ready` と通常の `expand` は、root manifestの全イメージ（Job未参照分も含む）に現在の入力ハッシュと一致するlockを要求します。未ビルド、失敗したbuild、digest未反映、stale lockのコミットは公開版の取得元にできません。readyは素材とイメージの条件であり、version履歴への登録完了を意味しません。JSON Schema単独の検証ではこれらの条件を保証できません。

`validate --history-base <40桁SHA>` は、そのコミットの履歴と比較して手編集を検出します。通常のローカル検証は現在のファイルだけを検証します。

`expand` は次の規則でYAMLを標準出力に出します。

- Resource一覧と `resource.version`・Workflow・Job構造を維持し、各Jobの `resolved-image` に `image`、`tag`、`digest` を追加する。imageのbuild・lock定義とversion履歴は含めない。
- map keyは辞書順、配列は定義順とし、時刻を含めない。
- `run` は元の文字列を保持し、argvへの変換や実行をしない。イメージのpullもしない。
- 明示された `compile`、Stepの `timeout`、Jobの `limits.step-timeout` を保持し、省略値の補完やJob timeoutの計算はしない。

`--allow-unbuilt` は未確定・古いlockを許容するレビュー用の展開です。生成YAML自体は元Resource用Schemaの入力ではありません。`expand` はcheckoutされた内容を展開し、登録済みversionのSHAへ自動的に移動しません。

## 手動インポート

以下はBackend側が実装する契約です。

1. Adminが手動でsource repositoryのmain更新を取得します。取得したmanifestのコミットを固定し、各Resourceの `versions` の最後の登録を最新候補とします。履歴が空のResourceには公開版がありません。現在の `resource.yaml` のversion値だけで未登録版を候補にしません。
2. 未取得の最新版について、記録された `commit` からmanifestを取得し、同じResource IDの当時のpathを解決して定義・素材・イメージlockを読みます。現在のmainのファイルを混ぜてはいけません。そのSHAがmain履歴上にあること、ID・versionが登録と一致すること、ready検証相当の条件を確認します。記録SHAのmanifestには、その版の履歴がまだなくても正常です。
3. repository・Resource ID・versionで取り込み済みかを判定し、同じ版の再取得はno-opとします。同じ識別子に異なるSHAが来た場合は上書きせずエラーにします。取得間隔の途中に公開された版まで取り込む必要はありません。
4. 取り込み済みの旧版を保持し、新版を選択候補に追加します。取得だけでは利用Versionを切り替えず、Adminが選択してupgradeします。Resourceがmanifestから削除されても、取得済みの版は保持します。
5. repository、一覧を取得したコミット、Resourceごとの登録SHA・version、実行Admin、build source-ref、Actions Run ID、image tag/digestを監査記録します。
