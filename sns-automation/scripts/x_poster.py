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
- 1回目の修正後、「投稿ボタンが disabled のまま」でタイムアウトする不具合
  が発生。role="dialog" の中に検索範囲を絞り込む対策を試したが、それでも
  同じ場所で同じ現象が再発した(ログを見る限りダイアログが見つからず
  ページ全体にフォールバックしていたとみられ、根本原因の特定に至って
  いなかった)。

2026-09-28 修正(3回目):
- これ以上ロケータを推測だけで直すのは非効率なため、投稿欄・投稿ボタンへの
  絞り込みロジックはいったんシンプルな形(:visible + .first のみ)に戻し、
  失敗時には該当要素の件数・可視性・disabled状態・HTML断片をログに出力
  する診断機能を追加した。

2026-09-28 修正(4回目・診断ログにより原因確定):
- 診断ログにより、実際には role="dialog" の要素が2つDOM上に存在し、
  1つ目(.first で選ばれる方)は常に非表示(visible=False)、2つ目だけが
  実際に画面に表示されているモーダル(visible=True)であることが判明した。
  投稿欄(tweetTextarea_0)も2つ存在するが、うち1つは非表示ダイアログに、
  もう1つは表示中のダイアログに属している。2回目の修正で
  `div[role="dialog"]` を `.first` で選んだ際、非表示の1つ目を10秒待って
  タイムアウトし、結局ページ全体へフォールバックしていたため、
  本文が非表示側(無関係)の投稿欄に入力され、実際にクリックする投稿ボタン
  (表示中のダイアログに1つだけ存在)は本文なしのまま disabled になって
  いた。
  対策として、ダイアログの絞り込みに `:visible` を付け(非表示のものを
  除外してから `.first` で選ぶ)、その表示中のダイアログの中だけで投稿欄・
  投稿ボタンを探すようにした。

2026-09-28 修正(5回目):
- 4回目の修正後も同じ「投稿ボタンが disabled のまま」が再発。診断ログの
  構成(件数・表示状態)は前回と同じだったため、ダイアログ選択自体は
  問題なかったとみられる。本文に # (ハッシュタグ) が複数含まれており、
  1文字ずつ打鍵する type() だと、Xの入力補完(オートコンプリート)
  ドロップダウンが途中で反応し、本文が編集欄の内部状態に正しく反映され
  ず、投稿ボタンが「本文なし」と判定され続けていた可能性が高い。
  対策として、1文字ずつの type() をやめ、本文をまとめて挿入する
  keyboard.insert_text() に変更し、直後に Escape でドロップダウンを
  閉じるようにした。また、実際に入力欄へ反映された文字数をログに出力
  するようにし、次回以降も検証できるようにしている。

2026-09-28 修正(6回目・根本原因を確定):
- 5回目の修正後、診断ログで「投稿欄には本文244文字が正しく反映された」
  ことを確認できたにもかかわらず、投稿ボタンは disabled のままだった。
  これは、文字を入力した投稿欄と、実際にクリックしていた投稿ボタンが、
  DOM上の別々のコンテナ(別のダイアログ)に属していたためと判明した。
  投稿欄(tweetTextarea_0)は画面構成によって複数存在しうるが、投稿ボタン
  (tweetButton)は毎回の診断ログで必ず1個だけであることが確認できている。
  そこで発想を転換し、「投稿欄側から表示中のものを推測で選ぶ」のではなく、
  先に一意な投稿ボタンを特定し、その祖先要素(role="dialog")の中だけで
  投稿欄を探すようにした。ボタンと投稿欄が必ず同じDOMツリーに属する
  ことが保証されるため、これまでのような取り違えが構造的に起こらない。

2026-09-28 修正(7回目・ボタンクリックをやめてキーボードショートカットに変更):
- 6回目の修正後も、診断ログでは「投稿欄には本文244文字が正しく反映された」
  ことが確認できているにもかかわらず、投稿ボタン(tweetButton)は
  aria-disabled="true" のままで、post_button.click() がタイムアウトして
  いた。つまり問題はもはや「どの要素を選ぶか」ではなく、CDP経由の
  insert_text() によるテキスト挿入では、Xの投稿ボタンを活性化させる
  React側の内部状態(入力欄の内部管理値)が更新されていない、という
  ボタン要素そのものの限界に突き当たっていた。
- そこで方針を転換し、投稿ボタンを探してクリックすることは一切やめ、
  Xが標準でサポートしているキーボードショートカット
  (Windows/Linuxでは Control+Enter、Macでは Meta(Cmd)+Enter)で
  投稿を送信するようにした。このショートカットは「現在フォーカスして
  いる投稿欄」を対象に動作するため、投稿ボタン要素を特定する処理自体が
  不要になり、これまで繰り返し発生していたボタンの取り違え・
  disabledのまま、という問題が構造的に起こらなくなる。
- 投稿欄への文字入力そのものは、244文字が正しく反映されることを
  過去のログで確認済みのため、6回目のロジック(insert_text)をそのまま
  流用している。送信後は、投稿欄(ダイアログ)が閉じたことを確認する
  ことで送信成功を判定し、閉じない場合はフォールバックとして投稿ボタン
  のクリックを試みたうえで、それでも失敗したら診断情報を出力する。
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


def _dump_diagnostics(page, label: str) -> None:
    """失敗時に、実際の画面構成をログへ出力する(次回の調査用)。"""
    print(f"=== 診断情報開始: {label} ===")
    try:
        print("page.url:", page.url)
    except Exception as e:  # noqa: BLE001
        print("page.url の取得に失敗:", e)

    for selector, label2 in (
        ('div[data-testid="tweetTextarea_0"]', "投稿欄(tweetTextarea_0)"),
        ('button[data-testid="tweetButton"]', "投稿ボタン(tweetButton)"),
        ('div[role="dialog"]', "ダイアログ(role=dialog)"),
    ):
        try:
            loc = page.locator(selector)
            n = loc.count()
            print(f"{label2} 件数: {n} (selector={selector})")
            for i in range(min(n, 5)):
                try:
                    el = loc.nth(i)
                    visible = el.is_visible()
                    aria_disabled = el.get_attribute("aria-disabled")
                    html = el.evaluate("el => el.outerHTML.slice(0, 250)")
                    print(
                        f"  [{i}] visible={visible} aria-disabled={aria_disabled} "
                        f"html={html}"
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"  [{i}] 要素情報の取得に失敗: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"{label2} の調査に失敗: {e}")

    print(f"=== 診断情報終了: {label} ===")


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

        try:
            # 投稿欄(tweetTextarea_0)は画面構成によってDOM上に複数存在する
            # ことがあるが、投稿ボタン(tweetButton)は毎回必ず1個しか存在
            # しないことが診断ログで確認できている。そのため、投稿欄側から
            # 「表示されているものを推測で選ぶ」のではなく、先に一意な
            # 投稿ボタンを特定し、そのボタンの祖先(ダイアログ)の中だけで
            # 投稿欄を探す。こうすることで、ボタンと投稿欄が必ず同じ
            # コンテナに属する(=取り違えが構造的に起こらない)ようにする。
            #
            # 送信自体は post_button.click() ではなく、キーボードショート
            # カット(Control+Enter / Meta+Enter)で行う。7回目の修正で
            # 判明した通り、本文が正しく入力欄に反映されていても投稿ボタン
            # の disabled が解除されない場合があり、ボタン要素への依存を
            # なくすことで根本的に回避する。
            post_button = page.locator('button[data-testid="tweetButton"]')
            post_button.wait_for(state="visible", timeout=15000)

            container = post_button.locator('xpath=ancestor::div[@role="dialog"]').first
            try:
                container.wait_for(state="visible", timeout=5000)
                scope = container
            except Exception:
                # ダイアログの祖先が見つからない画面構成の場合はページ全体
                scope = page

            textbox = scope.locator('div[data-testid="tweetTextarea_0"]').first
            textbox.wait_for(state="visible", timeout=15000)
            textbox.click()
            # 本文に # (ハッシュタグ) を含むため、1文字ずつ type() すると
            # Xの入力補完(オートコンプリート)ドロップダウンが途中で反応し、
            # 入力が正しく確定しないことがある。
            # 1文字ずつではなく、1回でまとめて挿入する insert_text を使う。
            page.keyboard.insert_text(text)
            # オートコンプリートのドロップダウンが開いたままだと送信の
            # 邪魔になる可能性があるため、念のため閉じておく。
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

            # 本文が実際に入力欄に反映されたかどうかをログに残す(次回調査用)
            try:
                entered_len = textbox.evaluate("el => el.innerText.length")
                print(f"投稿欄に反映された文字数: {entered_len} (元の文字数: {len(text)})")
            except Exception as e:  # noqa: BLE001
                print("投稿欄の内容確認に失敗:", e)

            # 認証チャレンジ・電話番号確認などが出ていないか軽くチェック
            if page.locator("text=confirm your identity").count() > 0 or page.locator(
                "text=本人確認"
            ).count() > 0:
                raise RuntimeError(
                    "本人確認/認証チャレンジが表示されました。自動投稿を中断します。"
                    "ブラウザで手動ログインして状態を確認してください(自動での突破は行いません)。"
                )

            # 投稿欄に確実にフォーカスを戻してから送信ショートカットを送る
            textbox.click()
            page.wait_for_timeout(300)
            page.keyboard.press("Control+Enter")
            page.wait_for_timeout(2000)

            # 送信が成功していれば、投稿欄(ダイアログ)が閉じているはず
            dialog_still_open = False
            try:
                dialog_still_open = container.is_visible()
            except Exception:
                try:
                    dialog_still_open = textbox.is_visible()
                except Exception:
                    dialog_still_open = False

            if dialog_still_open:
                print(
                    "Control+Enter 送信後もダイアログが開いたままのため、"
                    "フォールバックとして投稿ボタンのクリックを試みます。"
                )
                page.wait_for_timeout(500)
                post_button.click(timeout=10000)
        except Exception:
            _dump_diagnostics(page, "投稿処理中の失敗")
            browser.close()
            raise

        # 送信完了の反映を待つ
        time.sleep(3)
        context.storage_state(path=STORAGE_STATE_PATH)  # セッションを最新化して保存
        browser.close()
        print("Xへの投稿が完了しました。")


if __name__ == "__main__":
    sample_text = sys.argv[1] if len(sys.argv) > 1 else "テスト投稿です #EA検証"
    post_to_x(sample_text)
