# Baggage Loading Lab

提出したアルゴリズム、その結果、次の設計に使う証拠を共有する非公開研究リポジトリです。

**AIも人も、まず [START_HERE.md](START_HERE.md) を読んでください。**

目的はPublic 60点以上を目指す設計・実装・検証の反復です。このリポジトリへの登録や基盤テスト成功は、提出アルゴリズムの品質保証とは別です。

## 普段の使い方

1. ChatGPT WebまたはCodexに、このリポジトリと `START_HERE.md` を渡して次の設計・コード・ZIPを作成させます。
2. 必要な提出前検証を行い、あなたがSIGNATEへZIPを提出します。
3. **実際に提出したZIP＋Public値＋取得できた結果原文**をCodexへ渡し、「このZIPと結果を記録して」と依頼します。
4. Codexが同一性を確認し、台帳と比較表を更新して、このリポジトリに保存します。

Public値しか分からなくても記録できます。実行statusや成分が不明な場合は不明のまま保存します。Web版でZIP生成できることはユーザー確認済みです。物理検証を実行していない場合は、その事実も一緒に引き継ぎます。

## 記録の役割

| 場所 | 内容 |
| --- | --- |
| `artifacts/` | ZIP由来のコード、ハッシュ、手法説明。原本欠落も明記 |
| `evaluations/` | 評価原文、Publicの精度・出典、各成分、対応する成果物 |
| `progress.md` | 台帳から再生成する比較表 |
| `knowledge/CURRENT.md` | 現状と証拠への入口 |
| `knowledge/lessons/` | 観測と仮説を区別した設計上の知見 |
| `contracts/` | Agentインターフェイスと提出時の注意 |
| `tools/lab/` | コードを実行せずにZIP・結果を取り込むローカルツール |
| GitHub Releases | 確認できた提出ZIP原本。GitHub自動生成のSource code ZIPとは別 |

同じZIPに複数の評価を記録できます。同名でも中身が違うZIPは別の成果物です。訂正は元の証拠を残して追加します。

接続できないWebチャットには、Codexから現状・コード・台帳をまとめた引き継ぎZIPを渡せます。通常のGit認証とWebのGitHub連携は別の接続なので、それぞれの読み取り確認が必要です。

## ローカルでの確認

取り込み・訂正・同期・Webへの引き継ぎは [運用手順](docs/registry-operations.md) を参照してください。

Python 3.12の標準ライブラリで基盤を動かします。

```powershell
python -m unittest discover -s tests -p 'test_lab*.py' -v
python -m tools.lab --root . validate
python -m tools.lab --help
```

既存PCでは `simulator/.signate_venv/Scripts/python.exe` も利用できます。新しいcloneで台帳の確認だけをする場合、PyBulletやSIGNATEの認証は不要です。

公式シミュレータ・配布データは初回公開対象に含めていません。[インターフェイス要約](contracts/agent-interface.md)を参照し、物理試験にはユーザーが保有する公式環境を使います。
