# 初回移行の出典と範囲

保存先：非公開 `Nevaseme/baggage-loading-lab`。本記録は初回移行の出典説明で、同期完了証明は別の完了記録を参照します。

## 元データの対応

| 手法 | 元フォルダ（ローカル） | Publicの出典 | ZIP原本 |
| --- | --- | --- | --- |
| Conservative Extreme-Point Packing | `submit/Conservative Extreme-Point Packing_score29.7` | ユーザーが正確値29.74350010538と明示 | 未発見 |
| Guarded Extreme-Point Beam | `submit/highscore_guarded_20260813_score12.6` | ユーザーが正確値12.622949582873819と明示 | `simulator/submissions/highscore_guarded_20260813.zip`、10ファイル全一致 |
| Ingress-Preserving Column Scaffold | `submit/ingress_preserving_column_scaffold` | 不明 | 未発見 |
| Surface Frontier Extreme Backfill | `submit/surface_frontier_extreme_backfill_score11` | ユーザーによる約11点の申告。正確値不明 | 未発見 |

各フォルダの `result-log.txt` を評価の `raw/result.json` に原バイトのまま保存しました。外部成分とstatusはこれらの保存原文、Public総合は上記ユーザー申告が出典です。SIGNATEから今回取得し直した結果ではありません。申告によるPublicをCLIの明示値として記録し、原文の成分から総合を計算していません。

初回取り込みの検証で、PowerShellへ引用符なしで渡した12.622949582873819が、CLI到達前に12.6229495828738へ丸められていたことを検出しました。未公開の誤入力レコードはローカル `.lab/migration-errors/` に監査用保存し、正確な文字列で再登録しました。これは外部スコアの訂正や再評価ではなく、移行時の入力ミスの修正です。今後のコマンド例は引用符を必須とし、移行検証でユーザー提供値との文字列一致を確認します。

4件とも保存原文のstatusは `Stopped in the middle` で `is_placed_safe`・`is_valid` が含まれます。失敗step、全scene内訳、submission ID、評価日時は不明です。`num_placed_items` は0〜1の小数値で、分母・集計単位が不明なため個数に換算していません。

`submit/algorithm.zip` は4系統と結果・キャッシュを含むバックアップです。単独の提出原本として登録していません。別のbaseline ZIPも結果との対応が確定していないため、点数を付けていません。

## 保存と権限

元の提出物、結果原文、ローカルシミュレータは変更していません。root `progress.md` は原文を `knowledge/history/` に保存後、構造化台帳からの生成ビューへ移行しました。

Windowsでは初回取り込みの一時ディレクトリが保護されたアクセス権を持っていました。ユーザーの明示許可後、今回作成した4成果物・4評価フォルダだけにTAKUMIアカウントの読み書き権限（Modify、子へ継承）を追加しました。親フォルダ、他の提出物、所有者、公開範囲は変更していません。通常ユーザーのGitによる8フォルダの読み取りと登録準備を確認しました。
