#!/usr/bin/env python3
"""
login_once_note.py

【これは自分のPCで、自分の手で1回だけ実行するスクリプトです】
GitHub Actions では実行しません。CIに組み込まないでください。

やること:
1. 実際にブラウザ(表示あり)を開く
2. あなた自身がnote.comにいつも通り手動でログインする(2段階認証等が
   あればそれも含めて、すべて自分で入力する。このスクリプトはログイン
   処理には一切関与しない)
3. ログインできたらターミナルに戻ってEnterキーを押す
4. (自動)note.comの編集画面(editor.note.com)にも一度アクセスして、
   そちらのセッションも確実に確立させる
   (note.com本体とeditor.note.comはサブドメインが異なるため、
   note.com/loginだけではeditor.note.com側のセッションが
   確立されないことがあるための対策)
5. ログイン済みのセッション情報(Cookie等)を note_storage_state.json に保存する

保存されたファイルの中身をそのまま GitHub Secrets の
NOTE_STORAGE_STATE_B64 に登録してください(base64化してから登録します)。

    # Windows PowerShell
    [Convert]::ToBase64String([IO.File]::ReadAllBytes("$PWD\note_storage_state.json")) | Set-Clipboard

    # Mac/Linux
    base64 -i note_storage_state.json | pbcopy   # クリップボードにコピー(Mac)
    base64 -i note_storage_state.json             # 出力を手動コピー(Linux)

GitHub Actions 側では、このBase64文字列をデコードして
note_storage_state.json として書き戻してから note_poster.py を実行します
(.github/workflows/sns_auto_post.yml 参照)。

セッションには有効期限があります。数週間〜数ヶ月に一度、投稿が
「セッション切れ」エラーで失敗するようになったら、このスクリプトを
もう一度実行してSecretsを更新してください。
"""

import os

from playwright.sync_api import sync_playwright

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "note_storage_state.json")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://note.com/login")

        print("=" * 60)
        print("ブラウザが開きました。あなた自身の手で普段通りログインしてください。")
        print("ログインが完了して、note.comのトップ/ダッシュボードが表示されたら")
        print("このターミナルに戻って Enter キーを押してください。")
        print("=" * 60)
        input()

        # note.com本体とeditor.note.comはサブドメインが異なるため、
        # editor.note.com側のセッションも明示的に確立させておく。
        print("編集画面(editor.note.com)のセッションを確認しています...")
        page.goto("https://editor.note.com/", timeout=30000)
        page.wait_for_timeout(3000)
        print(f"editor.note.com アクセス後のURL: {page.url}")

        context.storage_state(path=OUTPUT_PATH)
        browser.close()
        print(f"セッションを保存しました: {OUTPUT_PATH}")
        print("このファイルの中身(base64化したもの)を GitHub Secrets の")
        print("NOTE_STORAGE_STATE_B64 に登録してください。")

if __name__ == "__main__":
    main()
