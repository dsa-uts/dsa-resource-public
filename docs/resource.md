# Resource 仕様

課題定義 (`resource.yaml`) の書式と実行規則を定める。manifest・イメージ管理・インポートは[リポジトリ契約](resource-contract.md)を参照。

このリポジトリは定義の検証・展開を実装する。以下の実行、採点、権限制御、Submission の正規化は、別の Backend・Judge が実装する仕様。

## Resource YAML

Resource YAML (`resource.yaml`) は Project の表示名、Workflow、Job、Step、Artifact handoff、課題説明文、Preset file を定義する。Sandbox Image は root `resources.yaml` の定義を Job から ID で参照する。

### YAML 例

`default` イメージを定義済みの場合の最小例。実際の課題説明・Preset・Artifact を含む例は [ex1/resource.yaml](../ex1/resource.yaml) を参照。

```yaml
resource:
  id: example
  name: Example
  version: 1
workflows:
  judge:
    jobs:
      test:
        visibility: public
        sandbox-image: default
        limits:
          memory: 512MiB
          step-timeout: "10s"
        steps:
          - run: 'printf "AC\n"'
            expected:
              stdout:
                match: exact
                value: "AC\n"
```

### 基本規則

- map key は機械 ID、`name` は表示名。`schema-version` は持たない。
- `resource.version` は必須の正の整数。公開する変更では登録済みの最大値より大きい値を指定する（欠番可）。同じ値のまま編集しても公開済みの版は変わらない。[Version登録](resource-contract.md#resource-version)を参照。
- 相対 path の字句規則は[リポジトリ契約](resource-contract.md#path-の共通規則)に従い、下表の root 外を指してはいけない。

| path | 基準となる root |
| --- | --- |
| `description-path`、`presets.files[].source`、`stdin.path`、`expected.*.path` | `resource.yaml` を置いた Resource directory |
| `presets.files[].path` | fixed read-only `/preset` mount |
| `artifacts.*[].path` | Sandbox Workspace |

## Submission path normalization

Submission archive entry path は、Sandbox Workspace へ配置する前に canonical POSIX relative path へ正規化する。Resource YAML の path とは異なり、Submission 側は受講者環境の差を吸収するため、安全に正規化できる場合は正規化後の path を使う。この正規化は Normalized Submission Identity の前提であり、content hash は正規化後の file tree に対して計算する。

Normalization rules:

- `\` は path separator として扱い、`/` に正規化してよい。
- 正規化後の path が空 path、`.`、絶対 path、`..` component、NUL byte を含む場合は validation error。
- Windows drive path(`C:\...`)と UNC path(`\\server\share\...`)は validation error。
- 正規化後に同じ path へ衝突する複数 entry がある場合は validation error。
- symlink、hardlink、device、FIFO、socket は validation error。
- archive extraction は host filesystem path に対して直接行わない。正規化と validation を in-memory filesystem または sandbox 用一時領域で完了してから workspace copy を作成する。

## Top-level

| field | required | description |
| --- | --- | --- |
| `resource.id` | yes | Resource の安定 ID。root manifest の `id` と一致する。 |
| `resource.name` | yes | Project の表示名。 |
| `resource.version` | yes | 明示的な公開版の番号。正の整数で、登録済みの最大値以上。 |
| `workflows` | yes | Workflow ID を key にした、1個以上の Workflow の map。 |

## Sandbox Image

Job の `sandbox-image` は [resources.yaml](../resources.yaml) に定義された ID を指定する。イメージ定義の制約は[リポジトリ契約](resource-contract.md#sandbox-image)を参照。

### Sandbox hardening

sandbox は gVisor(runsc) RuntimeClass を指定した k8s Pod として専用 Namespace で実行する。以下は platform 側の固定設定であり、Resource YAML では変更できない:

- network egress の既定 deny
- Linux capabilities は全て drop
- `no_new_privileges`
- `/bin/bash` を提供
- fixed non-root user で Step を実行
- read-only root filesystem。書き込み可能領域は platform が許可した Sandbox Workspace 等に限定
- 監査ログを必須とする

CPU / memory / pids / 実行時間 / stdout・stderr size の上限は Job の `limits` で宣言する。

## Workflow

| field | required | description |
| --- | --- | --- |
| `name` | no | 表示名。 |
| `description-path` | no | 課題説明 Markdown などの path。 |
| `presets.files` | no | Workflow 実行前に read-only `/preset` mount へ配置する Resource file。 |
| `jobs` | yes | Job ID を key にした map。 |

## Preset file

```yaml
presets:
  files:
    - source: presets/Makefile
      path: Makefile
```

| field | required | description |
| --- | --- | --- |
| `source` | yes | Resource root からの相対 path。 |
| `path` | yes | fixed read-only `/preset` mount 内の配置先 path。 |

同一 Workflow の `presets.files` 内で `path` が重複する場合は validation error。

Preset file は sandbox 内から読み込み可能だが、sandbox user から変更・削除・置換できない。Preset directory は platform 固定の `/preset` であり、Resource YAML では変更できない。writable な Sandbox Workspace へ配置してはならない(親 directory が writable だと unlink / rename で置換されうるため、file 単体の permission 変更では不十分)。

Preset file は secret ではない。private test data は `stdin.path` で Judge から stream し、Preset file には置かない。

## Job

Job は独立 sandbox 実行単位。同一 Job 内の Step は同じ workspace を共有するが、Job 間で workspace は共有しない(Isolated Job Workspace)。

| field | required | description |
| --- | --- | --- |
| `name` | no | 表示名。 |
| `visibility` | no | `public` または `private`。省略時 `private`(Private-by-Default)。 |
| `depends` | no | 先行して完了している必要がある Job ID 配列。省略時 `[]`。 |
| `sandbox-image` | yes | root `resources.yaml` の `sandbox-images` の ID。未定義 ID は validation error。 |
| `working-directory` | no | Step 実行時の working directory。省略時 `/workspace`。 |
| `limits` | yes | resource limit と timeout。 |
| `artifacts` | no | Job 間で明示的に受け渡す Artifact。 |
| `steps` | yes | 実行 Step。順序を持つ配列。 |

`visibility: private` の Job は Manager / Admin の Request でのみ実行できる。隠しテストケースや採点用 Job に使う。Validation Request は `public` Job のみ実行する。

`private` Job の CI Result と Artifact は Manager / Admin のみ参照できる。一般 User には stdout / stderr / status を含めて表示しない。

## Artifact handoff

Job 間の受け渡しは宣言された Artifact file のみ。次は Artifact 設定の抜粋（Job の必須項目は省略）。

```yaml
jobs:
  build:
    visibility: public
    artifacts:
      outputs:
        - name: program
          path: build/program
        - name: diagram
          path: out/diagram.png
          visibility: public
          content-type: image/png

  hidden-test:
    depends: [build]
    artifacts:
      inputs:
        - from-job: build
          name: program
          path: build/program
```

| field | required | description |
| --- | --- | --- |
| `artifacts.inputs[].from-job` | yes | Artifact producer Job ID。同一 Workflow 内のみ指定可。 |
| `artifacts.inputs[].name` | yes | producer Job の output Artifact name。 |
| `artifacts.inputs[].path` | yes | Sandbox Workspace 内の配置先 regular file path。 |
| `artifacts.outputs[].name` | yes | 同一 Job 内で一意な Artifact name。 |
| `artifacts.outputs[].path` | yes | Sandbox Workspace 内の回収元 regular file path。 |
| `artifacts.outputs[].visibility` | no | `public` または `private`。省略時 `private`(Private-by-Default)。 |
| `artifacts.outputs[].content-type` | public のとき yes | 配信時の `Content-Type`。`private` では指定禁止。 |

### Public Artifact

`visibility: public` の Artifact はクライアントに配信されうる。`content-type` は次の許可リストのみ:

- `image/png`
- `image/jpeg`
- `text/plain`
- `application/json`

SVG は script を実行できるため(stored XSS)public Artifact として許可しない。

### Dependency rules

- Workflow 内の Job は `depends` から作る dependency graph に従って実行する。Judge は ready Job を 1 つずつ、valid topological order で実行する。依存関係のない Job 間の実行順は意味を持たない。
- `depends` は同一 Workflow 内の Job ID 配列。存在しない Job ID、自分自身、cycle は validation error。
- `public` Job は `private` Job に `depends` してはいけない。`private` Job は `public` / `private` どちらの Job にも `depends` できる。
- `artifacts.inputs[].from-job` は現在の Job の `depends` に直接含まれていなければならない。`depends` していない Job、未実行 Job、自分自身の Artifact 参照は validation error。
- `public` Job は `private` Job が生成した Artifact を入力にできない。`private` Job は `public` Job が生成した Artifact を入力にできる。

### Capture rules

- Artifact output は Job の Step 実行後、sandbox cleanup 前に Judge が回収する。
- Artifact output path が存在する場合のみ回収する。存在しない場合は CI Result に Artifact capture status として記録する。
- Artifact input が参照する Artifact が存在しない場合、その Job は sandbox 開始前に setup failure とする。
- CI Result は setup failure、timeout、Step failure、Artifact capture failure のいずれでも回収・保存する。
- 保存上限は 1 Artifact file あたり `limits.artifact-size`。超過した Artifact file は保存せず、CI Result に Artifact capture status として記録する。
- Artifact の mode は regular executable bit のみ維持する。保存時は executable なら `0755`、それ以外は `0644` とし、owner / group / suid / sgid / sticky bit は維持しない。
- Artifact は regular file のみ。directory path は Artifact capture failure または setup failure とする。
- symlink、hardlink、device、FIFO、socket は Submission / Preset file / Artifact のいずれでも validation error。
- Artifact は sandbox 由来の untrusted data として扱う。Judge は host 上で Artifact を実行しない。

## Filesystem

Filesystem write isolation は platform 側の固定設定とする。Resource YAML では変更できない。

Filesystem lifecycle:

1. Job 開始時に clean な Sandbox Workspace を作成する(Isolated Job Workspace)。
2. Submission file と Artifact input file を writable regular file copy として配置する。
3. Preset file を read-only `/preset` mount に配置する。
4. Step は同一 Job 内で workspace を共有する。Step 間では cleanup しない。
5. Job 終了時に CI Result を必ず回収し、存在する Artifact output file を回収する。
6. Sandbox Workspace を cleanup する。

sandbox 内の Submission は canonical Submission ではなく writable copy であり、compile / test 中に変更されても永続化されない。

`stdin.path` と `expected.*.path` が参照する file は Sandbox Workspace に配置しない。

## Limits

```yaml
limits:
  cpu: 1
  memory: 512MiB
  pids: 128
  step-timeout: "10s"
  stdout-size: 1MiB
  stderr-size: 1MiB
  workspace-size: 256MiB
  artifact-size: 1MiB
```

| field | required | description |
| --- | --- | --- |
| `cpu` | no | 当面 `1` 固定。指定する場合も `1` のみ許可。 |
| `memory` | yes | Job 最大 RAM capacity。例: `512MiB`。 |
| `pids` | no | 最大 process 数。 |
| `step-timeout` | yes | Step timeout の既定値。例: `"2s"`、`"300ms"`。 |
| `stdout-size` | no | stdout capture 上限。 |
| `stderr-size` | no | stderr capture 上限。 |
| `workspace-size` | no | Sandbox Workspace の容量上限。省略時 `256MiB`。 |
| `artifact-size` | no | 1 Artifact file あたりの保存上限。省略時 `1MiB`。 |

### Timeout 計算

timeout は正の整数に `s`（秒）または `ms`（ミリ秒）を付けた文字列で指定する（例: `"2s"`、`"300ms"`）。数値のみ、0、負数、小数、空白付きの指定は許可しない。

Step の実効 timeout は `step.timeout`、省略時は `job.limits.step-timeout`。`limits.step-timeout` は全 Step に上書きがあっても必須。
Job の実効 timeout は全 Step の実効 timeout の合計＋buffer とする。buffer は Judge 内部の値で、既定値は10秒。

`resource.yaml` で指定できる timeout は `job.limits.step-timeout` と `step.timeout` のみ。`job.limits.timeout-seconds` と `job.limits.timeout-buffer-seconds` は許可せず、指定時は validation error。

例: Step の実効 timeout が 30 秒、10 秒、10 秒の場合、Job の実効 timeout は既定の buffer を含めて 60 秒になる。計算と実行時の制限は Judge が適用する。

## Step

```yaml
steps:
  - name: Test
    run: "make test"
    timeout: "60s"
    expected:
      exit-code: 0
      stdout:
        match: exact
        path: expected/test.stdout
      stderr:
        match: exact
        value: ""
```

| field | required | description |
| --- | --- | --- |
| `name` | no | 表示名。 |
| `run` | yes | Bash script 文字列。複数行可。空・空白のみ・NUL byte・argv 配列は禁止。 |
| `compile` | no | boolean。省略時 `false`。`true` の Step が失敗した場合は CE (Compilation Error) として記録する。 |
| `stdin` | no | Step の標準入力。 |
| `timeout` | no | Step wall time timeout。例: `"2s"`、`"300ms"`。省略時は `limits.step-timeout`。 |
| `expected` | no | 期待結果。 |

`compile: true` は失敗時のステータスを CE にする指定であり、`expected` 等による成功・失敗の判定条件は変更しない。`false` または省略時は通常の失敗判定を使う。ステータスの判定・記録は Judge が行う。

`expected.exit-code` は省略時 `0`。`expected.stdout` と `expected.stderr` は省略時、比較しない。

### Bash 実行

Judge は sandbox 内で `/bin/bash -e -o pipefail -c <run文字列>` を実行する。script は単一の引数としてそのまま渡し、Judge 側では分割・展開しない。Sandbox Image は `/bin/bash` を提供しなければならない。
shell expansion、pipe、redirect、glob を Bash が解釈する。script 内のコマンドは sandbox の `PATH` で解決し、絶対 path / 相対 path も許可する。
`-e` により通常のコマンドの失敗で停止し、`pipefail` により pipeline は右端の非0終了コードを返す。`if`、`&&`、`||` 等には Bash の `-e` の例外規則が適用される。
Step の終了コードは Bash の終了コード。working-directory、stdin、stdout/stderr、timeout の既存規則は script 全体に適用する。

YAML の `|` による複数行の script と pipe・redirect の例:

```yaml
run: |
  make
  ./main < input.txt | sort > result.txt
```

この例の `input.txt` は workspace 内の file。`stdin.path` は Judge が読み込む入力であり、workspace に file を配置する指定ではない。
`make` の失敗では後続行を実行しない。pipeline 内の失敗も Step の非0終了コードになる。

### Step stdin

```yaml
stdin:
  path: input/sample.txt
```

| field | required | description |
| --- | --- | --- |
| `value` | `path` と排他 | インライン標準入力。 |
| `path` | `value` と排他 | Resource root からの標準入力 file path。 |

`value` と `path` の同時指定は禁止。どちらもない場合は validation error。

`stdin.path` で参照される file は Judge 側で bytes として読み込み、Step process の stdin に stream する。Sandbox Workspace には配置しない。

### Expected stream

```yaml
expected:
  stdout:
    match: exact
    value: "AC\n"
  stderr:
    match: easy
    path: expected/stderr.txt
```

| field | required | description |
| --- | --- | --- |
| `match` | yes | `exact`, `easy`, `sorted` のいずれか。 |
| `value` | `path` と排他 | インライン期待値。 |
| `path` | `value` と排他 | Resource root からの期待値 file path。 |

`value` と `path` の同時指定は禁止。どちらもない場合は validation error。

`path` で参照される期待値 file は Judge 側でのみ使用する。Sandbox Workspace には配置しない。

## Output checker

stdout / stderr は UTF-8 text として扱う。UTF-8 として decode できない場合、その stream の check は失敗する。

### `exact`

完全一致。正規化しない。最後の改行も比較対象。

### `easy`

行ごとに要素列を比較する checker。

正規化:

1. 出力全体と期待値全体から、末尾にある 1 個の line ending を取り除く。対象は `\n`, `\r\n`, `\r`。
2. 行に分割する。
3. 各行の先頭・末尾の Unicode whitespace を trim する。
4. 各行を 1 文字以上の Unicode whitespace で分割し、要素列にする。

比較:

- 行数が同じであること。
- 各行の要素数が同じであること。
- 各行の要素が同じ順序で完全一致すること。

例:

```text
"  A\tB  \nC　D\n"
```

は次と同じ。

```text
"A B\nC D"
```

### `sorted`

`easy` と同じ正規化をした後、各行の要素列を辞書順で sort してから比較する。

比較:

- 行順は維持する。
- 各行内の要素順だけを無視する。
- sort は正規化後の要素文字列の昇順。

例:

```text
"B A\n3 2 1"
```

は次と同じ。

```text
"A B\n1 2 3"
```
