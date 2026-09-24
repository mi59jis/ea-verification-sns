#!/usr/bin/env python3
"""
login_once_x.py

【これは自分のPCで、自分の手で1回だけ実行するスクリプトです】
GitHub Actions では実行しません。CIに組み込まないでください。

やること:
1. 実際にブラウザ(表示あり)を開く
2. あなた自身がXにいつも通り手動でログインする(2段階認証・確認コードも
   すべて自分で入力する。このスクリプトはログイン処理には一切関与しない)
3. ログインできたらターミナルに戻ってEnterキーを押す
4. ログイン済みのセッション情報(Cookie等)を x_storage_state.json に保存する

保存されたファイルの中身をそのまま GitHub Secrets の
X_STORAGE_STATE に登録してください(中身をコピペ、または以下の
コマンドでbase64化してから登録してもOKです)。

    # Mac/Linux
    base64 -i x_storage_state.json | pbcopy   # クリップボードにコピー(Mac)
    base64 -i x_storage_state.json             # 出力を手動コピー(Linux)

    # Windows PowerShell
    [Convert]::ToBase64String([IO.File]::ReadAllBytes("x_storage_state.json")) | Set-Clipboard

GitHub Actions 側では、このBase64文字列をデコードして
x_storage_state.json として書き戻してから x_poster.py を実行します
(.github/workflows/sns_auto_post.yml 参照)。

セッションには有効期限があります。数週間〜数ヶ月に一度、投稿が
「セッション切れ」エラーで失敗するようになったら、このスクリプトを
もう一度実行してSecretsを更新してください。
"""

import os

from playwright.sync_api import sync_playwright

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "x_storage_state.json")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://x.com/login")

        print("=" * 60)
        print("ブラウザが開きました。あなた自身の手で普段通りログインしてください。")
        print("(2段階認証・確認コードの入力も、すべてあなた自身が行ってください)")
        print("ログインが完了して、タイムラインが表示されたら")
        print("このターミナルに戻って Enter キーを押してください。")
        print("=" * 60)
        input()

        context.storage_state(path=OUTPUT_PATH)
        browser.close()
        print(f"セッションを保存しました: {OUTPUT_PATH}")
        print("このファイルの中身を GitHub Secrets の X_STORAGE_STATE に登録してください。")


if __name__ == "__main__":
    main()
