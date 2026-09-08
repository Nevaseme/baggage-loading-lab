# Agent contract — local simulator reference

2026-09-08にユーザー保有の `simulator/README.md`、Dockerfileと実装を参照して整理したインターフェイス要約です。公式配布物そのものはこの初回リポジトリに同梱していません。新しい配布版がある場合はその実装を優先してください。

## Runtime and calls

Python 3.12。ローカル配布Dockerfileの指定はGymnasium 1.2.3、PyBullet 3.2.7、Pillow 10.3.0、CPU版Torch 2.7.0です。基盤の取り込みツールにはこれらは不要です。

`agent.py` に `Agent` クラスを実装します。

| Call | Input / output |
| --- | --- |
| `Agent(module_path)` | モジュールディレクトリを受け取って初期化 |
| `get_init_states(init_states)` | `optimize`、`lookahead_k`、`container_list` を受け取る |
| `optimize(item_list)` | mode Aの全荷物から順序を決め、荷物の `index` のリストを返す |
| `policy(observation)` | 現在の観測から下記のactionを返す |

観測は `optimize`、`lookahead_k`、`depth_map`、`pool_list`、`container_list`。mode Aは全荷物の事前計画、Bは見えるプールから選択、Cはlookahead 1の逐次判断です。見えていない将来荷物を既知として扱う実装は評価条件と一致しません。

```python
{
    "item_idx": int,
    "container_idx": int,
    "place_pos": numpy.ndarray,  # shape (3,), dtype float32
    "orientation": int,         # 0..5
}
```

`item_idx` は現在の `pool_list` の添字で、荷物の永続的な `index` ではありません。`container_idx` も現在のコンテナリストの添字です。終盤はプールが短くなります。

`place_pos` は荷物の中心位置で、コンテナの `(offset_x, 0, 0)` を原点とする相対座標です。既配置荷物の `pos` は世界座標、`orn` は `(x,y,z,w)` のquaternionであり、物理演算後は軸平行とは限りません。

## Geometry and attributes

コンテナ情報には `length`（X外寸）、`width`（Y奥行）、`height`（Z高さ）、`thickness`、`buffer`、`cut_x`、`cut_y`、`require_shelf`、`is_prioritized`、`packed_items` があります。棚・切り欠き・壁厚を実際の形状として扱います。

荷物には `index`、3辺、`mass`、`is_prioritized`、`is_soft`、配置先、位置・姿勢、摩擦・反発・減衰の属性があります。ソフト荷物には接触剛性などの属性もあります。

6姿勢の定義は配布実装と照合してください。READMEでは0が無回転、1がX90度、2がY90度、3がZ90度、4がY90度→Z90度、5がX90度→Z90度です。既存成果物の実装を比較する際も、数値だけで姿勢の意味を推定しないでください。

最終候補を現在状態で検証します。搬入はY方向からの挿入とX方向移動を含むため、最終位置の非衝突だけでは不十分です。解析近似が公式の離散的な搬入判定と一致するか、物理結果と対応付けて確認します。

## Deadlines and scores

今回参照した配布READMEには、初期化10秒、policy 8秒、optimization 180秒、メモリ12GBと記載されています。プロジェクトのpolicy受入条件は、それより余裕を持つ最大6秒未満・p99 5.5秒未満です。実行対象の設定・配布版も確認します。

Public総合、外部フィードバック成分、ローカル `fill_score` は別の指標です。外部フィードバックの `num_placed_items` は荷物数そのものではなく全体に対する割合です。配置率が低いとfill以外が0になる条件が説明されていますが、未確認の閾値や重みは推測しません。

`is_valid=false` のため配置に進まなかったケースでは、同時に `is_placed_safe=false` でも配置後に崩れた証拠にはなりません。停止理由は実行順序と原文に基づいて分類します。

詳細な提出受入は [評価契約](../docs/evaluation-contract.md) を参照してください。
