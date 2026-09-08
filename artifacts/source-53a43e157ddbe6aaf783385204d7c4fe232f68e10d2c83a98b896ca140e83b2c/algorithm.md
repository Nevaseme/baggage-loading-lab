# Surface Frontier Extreme Backfill

床・棚・既配置荷物の上面を利用可能な支持面（Surface Frontier）として毎ステップ再構築し、その上から候補を生成します。Y方向搬入→X方向横移動とデプスマップを使う経路判定を組み合わせます。

ユーザー提供の手法説明では、序盤に重く硬い荷物で低い支持構造を形成し、後半にソフト・優先・小型荷物を残余空間へ配置します。オフラインのExtreme Point計画を現在の物理状態で再検証し、計画が崩れればSurface Frontier探索へ戻るハイブリッドです。

Publicはユーザーの**約11点**という申告のみで、正確値は不明です。外部statusは途中停止。元の提出ZIPは未発見で、保存ソース2ファイルのバイト列を登録しています。低得点をオンライン方策の最終品質だけに帰属させる根拠はありません。

[manifest](manifest.json) / [evaluation](../../evaluations/evaluation-aab03856884857c2254c2b654262ac8067b112cc6108b7860ebc7784a31168b1/record.json)
