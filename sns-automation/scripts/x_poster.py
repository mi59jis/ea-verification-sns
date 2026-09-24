#!/usr/bin/env python3
"""
x_poster.py

X(旧Twitter)への投稿を、公式APIを使わずブラウザ操作(Playwright)で行う。
ユーザー名やパスワードをこのスクリプトで直接入力することはしない。
事前に scripts/login_once_x.py を「自分のPCで手動」実行し、ログイン済みの
セッション(storage_state.json)を作っておき、それを読み込んで使うだけの
設計にしている(理由は README_SNS_AUTOMATION.md 参照)。

重要な注意:
- X はブラウザ操作による自動投稿を利用規約で明確には想定しておらず、
  検知された場合はアカウント制限・凍結のリスクがある(公式には非推奨)。
- 本スクリプトは「ログイン試行」を自動化するものではない
  (=パスワード入力は行わない)。あくまで既存の認証済みセッションを
  読み込んで、投稿フォームに文字を入力し送信するだけ。
- 認証チャレンジ(電話番号確認・CAPTCHA等)が出た場合、このスクリプトは
  それを突破しようとせず、そのまま失敗として終了する。表示された場合は
  自動投稿を一時停止し、ブラウザで手動ログインし直してから
  login_once_x.py を再実行すること。
"""

import os
import sys
import time

from playwright.sync_api import sync_playwright

STORAGE_STATE_PATH = os.environ.get(
    "X_STORAGE_STATE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "x_storage_state.json"),
)

COMPOSE_URL = "https://x.com/compose/post"


def post_to_x(text: str) -> None:
    if not os.path.exists(STORAGE_STATE_PATH):
        raise RuntimeError(
            f"{STORAGE_STATE_PATH} が見つかりません。"
            "先に login_once_x.py を自分のPCで実行してセッションを作成し、"
            "GitHub Secrets の X_STORAGE_STATE に登録してください。"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=STORAGE_STATE_PATH)
        page = context.new_page()
        page.goto(COMPOSE_URL, timeout=30000)

        # ログインが切れている場合はログイン画面に飛ばされる
        if "login" in page.url or "flow/login" in page.url:
            browser.close()
            raise RuntimeError(
                "Xのセッションが切れているようです(ログイン画面にリダイレクトされました)。"
                "login_once_x.py を再実行してセッションを更新してください。"
            )

        textbox = page.locator('div[data-testid="tweetTextarea_0"]')
        textbox.wait_for(state="visible", timeout=15000)
        textbox.click()
        # 1文字ずつ打鍵するより自然な挙動にするため type() を使う
        textbox.type(text, delay=15)

        # 認証チャレンジ・電話番号確認などが出ていないか軽くチェック
        if page.locator("text=confirm your identity").count() > 0 or page.locator(
            "text=本人確認"
        ).count() > 0:
            browser.close()
            raise RuntimeError(
                "本人確認/認証チャレンジが表示されました。自動投稿を中断します。"
                "ブラウザで手動ログインして状態を確認してください(自動での突破は行いません)。"
            )

        post_button = page.locator('button[data-testid="tweetButton"]')
        post_button.wait_for(state="visible", timeout=15000)
        post_button.click()

        # 送信完了の反映を待つ
        time.sleep(3)
        context.storage_state(path=STORAGE_STATE_PATH)  # セッションを最新化して保存
        browser.close()
        print("Xへの投稿が完了しました。")


if __name__ == "__main__":
    sample_text = sys.argv[1] if len(sys.argv) > 1 else "テスト投稿です #EA検証"
    post_to_x(sample_text)
