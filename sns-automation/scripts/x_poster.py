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

2026-09-28 修正(1回目):
- 投稿欄のロケータ(div[data-testid="tweetTextarea_0"])が、Xの画面構成に
  よっては同じ属性を持つ要素が2つ同時にDOM上に存在し、Playwrightの
  strict modeでエラーになる不具合(strict mode violation: resolved to
  2 elements)を修正。`:visible`で実際に見えている要素だけに絞り込み、
  さらに`.first`で万一複数残っても先頭要素を使うようにした。

2026-09-28 修正(2回目):
- 1回目の修正後、「投稿ボタンが disabled のまま」でタイムアウトする
  不具合が発生。原因は /compose/post がモーダル(role="dialog")として
  投稿画面を開く一方、背景のホームタイムラインにも同じ testid を持つ
  投稿欄が存在しており、`:visible`+`.first` では稀に背景側(非アクティブ)
  の投稿欄を選んでしまうことがあったため。本文はそちらに入力されるが、
  実際にクリックする投稿ボタンはモーダル側にあり「本文が空」と判定され
  disabled のままになっていた。
  対策として、まず role="dialog" の中に検索範囲を絞り込み、モーダルが
  見つからない場合のみページ全体にフォールバックするようにした。
  こうすることで投稿欄・投稿ボタンともに必ずモーダル内の実際に操作対象
  となる要素1つに定まるようにしている。
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

        # /compose/post はモーダル(role="dialog")として開くため、
        # 背景のホームタイムライン上の投稿欄と誤って混同しないよう、
        # まずダイアログ内に検索範囲を絞り込む(見つからない場合のみ
        # ページ全体にフォールバック)。
        dialog = page.locator('div[role="dialog"]')
        try:
            dialog.first.wait_for(state="visible", timeout=10000)
            scope = dialog.first
        except Exception:
            scope = page

        textbox = scope.locator('div[data-testid="tweetTextarea_0"]:visible').first
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

        post_button = scope.locator('button[data-testid="tweetButton"]:visible').first
        post_button.wait_for(state="visible", timeout=15000)
        # 本文入力後、ボタンの活性化(disabled解除)に一瞬ラグがあることが
        # あるため、クリック前に短く待つ。
        post_button.wait_for(state="attached", timeout=15000)
        page.wait_for_timeout(500)
        post_button.click()

        # 送信完了の反映を待つ
        time.sleep(3)
        context.storage_state(path=STORAGE_STATE_PATH)  # セッションを最新化して保存
        browser.close()
        print("Xへの投稿が完了しました。")


if __name__ == "__main__":
    sample_text = sys.argv[1] if len(sys.argv) > 1 else "テスト投稿です #EA検証"
    post_to_x(sample_text)
