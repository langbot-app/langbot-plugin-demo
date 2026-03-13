# LongTermMemory

LangBot 向けの長期記憶プラグインです。二層構造の記憶モデルを採用しています。

- L1 コアプロフィール: system prompt に注入
- L2 エピソード記憶: KnowledgeEngine 経由で検索して注入

## 役割

- `remember` ツールでエピソード記憶を書き込みます
- `recall_memory` ツールで制御された条件付きの記憶検索を行います
- `update_profile` ツールで安定したプロフィール情報を更新します
- EventListener でプロフィールと現在の話者情報を自動注入します
- KnowledgeEngine によりモデル呼び出し前に関連する記憶を検索します
- `!memory` コマンドで状態確認とデバッグができます

## 設計

このプラグインは、LangBot の既存拡張ポイントをなるべくそのまま使う方針です。追加のコア改修を前提にしていません。

- L1 プロフィールはプラグインストレージに JSON として保存
- L2 エピソード記憶はベクターデータベースに保存
- pipeline にこの KnowledgeEngine を紐付けることで明示的に有効化
- 現在は 1 つのプラグインインスタンスにつき 1 つの memory KB を想定し、metadata で隔離

現在の実装は既存の LangBot / SDK API を前提に成り立っています。将来、LangBot に memory 専用 API、session identity API、KB 登録 API などが追加されれば実装はさらに簡潔にできますが、今の設計自体を作り直す必要はありません。

## なぜ Agent に metadata filter を開放していないのか

基盤の runtime は metadata filter を扱えますが、このプラグインでは現時点で Agent フローに任意の raw metadata filter を公開していません。

理由は次の通りです。

- 知識エンジンやベクターバックエンドごとに metadata schema が統一されていない
- filter の項目名、値の形式、使える演算子が異なる可能性がある
- Agent 側に、正しい filter を組み立てるための安定した schema 情報源がまだない

将来、LangBot が知識ベースごとの filterable metadata schema を統一的に提供できるようになれば、より汎用的な Agent 側 metadata filter の導入は可能です。

一方で、この長期記憶プラグイン自身の memory schema は安定しているため、現在でも `recall_memory` という制御されたツール面を通じて、話者や時間範囲などの固定パラメータで記憶を検索できます。モデルに raw filter 構文を直接渡す必要はありません。

## 隔離モデル

2 つの隔離モードをサポートします。

- `session`: グループチャットや個人チャットごとに独立
- `bot`: 同一 bot 配下の全セッションで共有

現在の運用前提では、プラグインインスタンスは通常特定の LangBot ランタイムや bot に紐づくため、このモデルで十分なことが多いです。

## 使い方

1. このプラグインをインストールして有効化します。
2. このプラグインの KnowledgeEngine を使って memory knowledge base を 1 つ作成します。
3. 次の項目を設定します。
   - `embedding_model_uuid`
   - `isolation`
   - 任意で `max_results`
4. Agent には次を使わせます。
   - `remember`: イベント、予定、状況的な事実の保存
   - `recall_memory`: 自動想起が不十分なときの能動的な記憶検索
   - `update_profile`: 安定した好みやプロフィール情報の保存
5. `!memory`、`!memory profile`、`!memory search <query>` で状態を確認します。

## コンポーネント

- KnowledgeEngine: [`memory_engine.py`](/home/yhh/workspace/langbot-plugin-memory/components/knowledge_engine/memory_engine.py)
- EventListener: [`memory_injector.py`](/home/yhh/workspace/langbot-plugin-memory/components/event_listener/memory_injector.py)
- Tools: [`remember.py`](/home/yhh/workspace/langbot-plugin-memory/components/tools/remember.py), [`recall_memory.py`](/home/yhh/workspace/langbot-plugin-memory/components/tools/recall_memory.py), [`update_profile.py`](/home/yhh/workspace/langbot-plugin-memory/components/tools/update_profile.py)
- Command: [`memory.py`](/home/yhh/workspace/langbot-plugin-memory/components/commands/memory.py)

## いま不足していたもの

`langbot-plugin-demo` の他プラグインと比べると、主に不足していたのは利用者向けドキュメントです。

- ルートの `README.md`
- `readme/` 配下の多言語ドキュメント

manifest、アイコン、tool YAML、command YAML、KnowledgeEngine schema 自体はすでに揃っています。
