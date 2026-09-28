#!/usr/bin/env python3
"""
note_poster.py

note.comの下書き記事を、公式APIを使わずブラウザ操作(Playwright)で公開する。
ログイン処理はこのスクリプトでは行わない。事前に scripts/login_once_note.py を
「自分のPCで手動」実行し、ログイン済みのセッション(note_storage_state.json)を
作っておき、それを読み込んで使うだけの設計にしている(x_poster.py と同じ方針)。

重要な注意:
- note.com もブラウザ操作による自動投稿を利用規約で明確には想定しておらず、
  検知された場合はアカウントへの影響が出るリスクがある(公式には非推奨)。
  この点を理解した上で、自己責任で利用すること。
- 本スクリプトは「ログイン試行」を自動化するものではない
  (パスワード入力は一切行わない)。既存の認証済みセッションを読み込んで、
  下書きの公開設定(ハッシュタグ・有料設定)を行い、投稿ボタンを押すだけ。
- タイトル・本文が空、想定より極端に短い、ログインセッション切れ、など
  想定と違う状態を検知した場合は、絶対に公開を強行せずエラーで終了する
  (有料記事のため、誤った状態での公開は取り返しがつかない)。
- 初回利用前に、必ずテスト用の下書き(無料・捨てても良い内容)で
  一度動作確認してから、本番の記事に使うこと。
- ローカルでの動作確認時は環境変数 NOTE_POSTER_HEADLESS=false を設定すると
  実際にブラウザが表示され、何が起きているか目視で確認できる
  (GitHub Actions側は表示なし環境のため、常にheadless=trueで動く)。
"""

import os

from playwright.sync_api import sync_playwright

STORAGE_STATE_PATH = os.environ.get(
    "NOTE_STORAGE_STATE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "note_storage_state.json"),
)

HEADLESS = os.environ.get("NOTE_POSTER_HEADLESS", "true").lower() != "false"

# 全記事共通で付けるハッシュタグ(下書きに既に付いているタグは自動でスキップする)
NOTE_HASHTAGS = [
    "EA", "投資", "資産運用", "FX", "為替", "自動売買",
    "FX自動売買", "システムトレード", "バックテスト", "MT5", "無料EA", "EA検証",
]

PRICE_JPY = "1000"
MIN_BODY_LENGTH = 100  # これより本文が短い場合は異常とみなして中止する


def publish_note_draft(draft_id: str) -> str:
    if not os.path.exists(STORAGE_STATE_PATH):
        raise RuntimeError(
            f"{STORAGE_STATE_PATH} が見つかりません。"
            "先に login_once_note.py を自分のPCで実行してセッションを作成し、"
            "GitHub Secrets の NOTE_STORAGE_STATE_B64 に登録してください。"
        )

    edit_url = f"https://editor.note.com/notes/{draft_id}/edit/"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=200 if not HEADLESS else 0)
        context = browser.new_context(storage_state=STORAGE_STATE_PATH)
        page = context.new_page()
        page.goto(edit_url, timeout=30000)
        page.wait_for_timeout(2500)

        if "login" in page.url or "note.com/login" in page.url:
            current_url = page.url
            if not HEADLESS:
                print("[DEBUG] ログイン画面と判定されたページで一時停止します。ブラウザを確認してください。")
                page.wait_for_timeout(15000)
            browser.close()
            raise RuntimeError(
                "noteのセッションが切れているようです(ログイン画面にリダイレクトされました)。"
                f"リダイレクト先URL: {current_url} "
                "login_once_note.py を再実行してセッションを更新してください。"
            )

        # --- 安全確認: 本文が極端に短くないこと(空 or テスト文字列などの誤検知防止) ---
        body_locator = page.locator(".ProseMirror").first
        body_locator.wait_for(state="visible", timeout=15000)
        body_text = body_locator.inner_text()
        if len(body_text.strip()) < MIN_BODY_LENGTH:
            browser.close()
            raise RuntimeError(
                f"本文が短すぎます(検出文字数: {len(body_text.strip())})。"
                "下書きの内容が想定と異なる可能性があるため、公開を中止します。"
            )

        # --- 公開設定画面へ ---
        page.get_by_text("公開に進む", exact=True).click()
        page.wait_for_timeout(1500)

        if "/publish" not in page.url:
            browser.close()
            raise RuntimeError(
                "公開設定画面に遷移しませんでした(タイトル・本文が未入力の可能性)。公開を中止します。"
            )

        # --- ハッシュタグを追加(既存タグは重複スキップ) ---
        tag_input = page.get_by_placeholder("ハッシュタグを追加する")
        tag_input.wait_for(state="visible", timeout=15000)
        for tag in NOTE_HASHTAGS:
            existing = set(
                t.strip().lstrip("#")
                for t in page.locator("text=/^#/").all_inner_texts()
            )
            if tag in existing:
                continue
            tag_input.click()
            tag_input.fill(tag)
            page.wait_for_timeout(900)
            suggestion = page.get_by_text(f"#{tag}", exact=True).first
            if suggestion.count() > 0:
                suggestion.click()
            else:
                # 候補が出なければ入力欄をクリアして次のタグへ(無理に追加しない)
                tag_input.fill("")
                page.keyboard.press("Escape")
            page.wait_for_timeout(400)

        # --- 有料設定 ---
        page.get_by_text("有料", exact=True).first.click()
        page.wait_for_timeout(800)
        price_field = page.locator("text=価格").locator("xpath=following::input[1]")
        if price_field.count() > 0:
            price_field.fill(PRICE_JPY)
        page.wait_for_timeout(500)

        # --- 公開実行 ---
        publish_button = page.get_by_role("button", name="投稿する")
        publish_button.wait_for(state="visible", timeout=15000)
        publish_button.click()
        page.wait_for_timeout(4000)

        final_url = page.url
        context.storage_state(path=STORAGE_STATE_PATH)  # セッションを最新化して保存
        browser.close()
        print(f"noteの記事を公開しました: {final_url}")
        return final_url


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("使い方: python note_poster.py <draft_id>")
        sys.exit(1)
    publish_note_draft(sys.argv[1])
