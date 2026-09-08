# Conservative Extreme-Point Packing

既配置荷物の辺・上面・コンテナ境界から3D候補点を作り、6姿勢について内包・衝突・支持率・搬入経路を判定します。低重心、奥詰め、支持面積、優先・ソフト荷物保護を重み付き評価して逐次配置し、オフラインでは仮想積付で荷物順序を調整します。

ユーザー提供の手法説明では、安全重視の局所ヒューリスティック型であり、空き空間自体を管理しないため後半のデッドスペースが課題とされています。この説明は設計上の解釈であり、Public低下の単一原因を証明するものではありません。

Public **29.74350010538** はユーザー申告の正確値で、初回移行の最高値。外部結果statusは途中停止です。元の提出ZIPは未発見で、保存済み `high_score/agent.py` のバイト列を [source](source/agent.py) に保存しました。source IDはZIPのハッシュではありません。

[manifest](manifest.json) / [evaluation](../../evaluations/evaluation-4509997d8de80585a45f09429d5828f97234bbf34ae958bc9fbd0be095fb5a04/record.json)
