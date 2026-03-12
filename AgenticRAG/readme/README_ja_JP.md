# AgenticRAG

AgenticRAG は、現在の pipeline に設定された知識ベースを Agent から呼び出せるツールとして公開し、利用可能な KB の確認と必要な情報の検索を可能にします。

## 役割

- `query_knowledge` という 1 つのツールを提供します
- 2 つのアクションをサポートします
  - `list`: 現在の pipeline で利用可能な知識ベースを一覧表示
  - `query`: 1 つまたは複数の知識ベースから関連ドキュメントを検索
- 結果を JSON で返すため、Agent がそのまま後続の推論に利用できます

## 実装の仕組み

このプラグインは新しい RAG バックエンドを実装するものではありません。LangBot にある、`query_id` 単位でスコープされた知識検索 API をツールとして薄くラップしています。

- `list_pipeline_knowledge_bases()`：現在の query がアクセス可能な知識ベースを列挙
- `retrieve_knowledge()`：1 つまたは複数の KB から検索し、統合された top-k 件の結果を取得

ツール実行時には runtime が現在の `query_id` を自動で注入します。`QueryBasedAPIProxy` がこの文脈を保持するため、ツール側で明示的に渡す必要があるのは次の項目です。

- `kb_id` または `kb_ids`
- `query_text`
- `top_k`

基盤の runtime 自体は metadata filter を扱えますが、このプラグインでは現時点で Agent フローのツール呼び出しに raw な metadata filter を公開していません。知識エンジンやベクターバックエンドごとに metadata の項目名、型、値の形式、filter の意味が揃っておらず、Agent 側にその schema を安定して渡す仕組みがまだないためです。

今後、知識ベースごとに利用可能な filter 項目や演算子を統一的に記述できる仕組みが整えば、metadata filter を Agent に開放することは可能です。

## セキュリティ

このツールは、現在の pipeline に設定された知識ベースだけを対象にします。

- LangBot runtime 側でも、`kb_id` が現在の pipeline に属しているか再検証します

そのため、prompt injection だけで pipeline 外の任意の KB を検索することは想定されていません。

## 使い方

1. このプラグインをインストールして有効化します。
2. 現在の pipeline の local agent 設定で、1 つ以上の知識ベースを関連付けます。
3. Agent に `query_knowledge` を呼ばせます。
   - まず `action="list"` で利用可能な KB を確認します
   - 次に `action="query"` で、単一 KB なら `kb_id`、複数 KB を並列検索するなら `kb_ids` を渡します
   - あわせて `query_text` と、必要に応じて統合結果数を表す `top_k` を渡します

## パラメータ

`action="query"` のときに使えるパラメータは以下です。

- `kb_id`：単一 KB 検索時の対象知識ベース UUID
- `kb_ids`：複数 KB を並列検索するための UUID 配列
- `query_text`：検索クエリ
- `top_k`：任意。返す件数。正の整数である必要があり、既定値は `5`。統合後の結果数に適用されます

複数 KB の並列検索で一部だけ失敗した場合、ツールは `results` と `failed_kbs` を持つ JSON オブジェクトを返し、Agent が部分的な成功結果を継続利用できるようにします。

## 典型的な流れ

1. Agent が利用可能な知識ベースを一覧表示します。
2. 名前と説明を見て、適切な 1 つまたは少数の KB を選びます。
3. 明確な検索クエリで検索します。
4. 返却された断片を使って回答または次の推論を行います。
