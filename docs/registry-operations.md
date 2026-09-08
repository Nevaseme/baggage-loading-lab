# ZIPと結果の記録手順

通常はCodexへ「実際に提出したZIPと、この結果を記録して」と依頼すれば十分です。本書はCodexと手動操作のための運用手順です。同期先は非公開の `Nevaseme/baggage-loading-lab` です。

## 取り込み

最新のmainを読み、作業中の変更との競合を確認します。以下の `ARTIFACT_ID` は取り込み結果の値をそのまま使用します。

```powershell
python -m tools.lab --root . ingest --zip C:/path/to/technique-name.zip --name technique_name
python -m tools.lab --root . record --artifact ARTIFACT_ID --result C:/path/to/result.txt --public-score '42.123456789'
python -m tools.lab --root . render
python -m tools.lab --root . validate
```

`--public-score` はユーザーが明示した正確値を**引用符付き文字列**で指定します。PowerShellで引用符を省くと、長い小数がCLIへ渡る前に丸められる場合があります。原文に値が入っていれば省略可能です。約11点なら `--rounded-public '11'`、総合不明なら両方省略します。スクリーンショットしかないときは画像の原本も評価の `raw/` に添付し、読み取れた値と出典を文書に残します。CLIが画像をOCRする機能はありません。

同じZIPは再投入しても同じartifact IDです。同じ証拠と指定値は重複登録されません。同一ZIPを再提出した別評価は、判明している `--submission-id` を付けます。ID不明でも結果が異なれば別記録ですが、同じ結果の再投稿か新しい評価回かが曖昧なら確認します。

訂正は `--supersedes EVALUATION_ID` で新しい記録から旧記録へリンクします。誤った過去の記録や原文を消す方式ではありません。生成一覧を読んだAIは訂正リンクを確認してください。

原本がない歴史資料に限り `import-source --source PATH --name technique_name` を使います。これは元のZIPの同一性を証明せず、提出可能ZIPの再作成でもありません。

## 説明と証拠

成果物の `algorithm.md` に手法、比較元、変更点、測定済み／未測定を簡潔に追記します。評価の `analysis.md` には観測、解釈、次の検証を分けて記録します。構造化manifestとrecordを直接編集する代わりに、訂正は新しい評価で表します。

初版のmanifestにある `source_commit` は**取り込み時の台帳リポジトリHEAD**です。アルゴリズム生成元のcommitや、未commit変更を含むことの証明ではありません。設計元・親候補が判明したら説明書に出典付きで記載します。

`num_placed_items` などは外部原文の数値を保ちます。小数比率が返った場合、分母不明のまま個数へ換算しません。status未取得、成分未取得、未実施テストはそれぞれ不明／未実施です。

## GitHub同期

1. ZIP内コードを実行せず取り込み、テストとvalidateを通す。
2. 対象のコード・原文・台帳・説明・生成ビューだけをcommitし、既存Git認証でpushする。
3. 原本ZIPのあるartifactは、artifact IDに対応するReleaseの下書きへ `.lab/assets/<sha256>.zip` とmanifestを添付する。提出時の元ファイル名はmanifestに保持される。
4. Releaseにハッシュと用途を記載して確定し、リモートのassetのdigestまたは再取得バイト列を照合する。GitHub自動生成のSource code ZIPは提出原本として使わない。
5. 同期先commit、Release URL、照合方法・結果を `knowledge/sync/` の記録へ追記し、pushする。

Gitとassetは別々に同期されます。途中で失敗したときは、既存ID・ハッシュ・下書きを確認して再開し、未確認のassetを同期済みとは扱いません。ローカル `.lab/` はcacheであり、Gitに含めません。認証の追加許可が必要な場合はその操作だけユーザーに依頼します。

Gitへの追加と引き継ぎ前に、選択したファイルに認証情報・無関係な個人データが含まれていないかを確認します。exporterのファイル名フィルターは補助策であり、ソースや文章へ埋め込まれた任意の秘密を自動検出する保証ではありません。

## Webへ渡す資料

```powershell
python -m tools.lab --root . export-context --output .lab/exports/design-context.zip
```

生成ZIPの `REGISTRY.json` と `FILE_HASHES.json` が版とファイル一覧の照合用です。WebへはこのZIPと、START_HEREから読み、読めたrevisionを示して設計するよう伝えます。WebのGitHub連携で直接読めるならそちらを使えます。接続の可否とZIP生成・物理検証の能力は別に確認します。
