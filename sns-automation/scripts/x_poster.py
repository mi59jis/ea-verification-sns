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
  (9回目の修正で、この「ダイアログが閉じた=成功」という判定自体が
  誤検知の原因だったことが判明した。)

2026-09-28 修正(8回目・真の原因を特定: 不要なEscapeキーが投稿ダイアログ
自体を閉じていた):
- 7回目の修正を投入した直後の実行ログを詳しく確認したところ、例外は
  Control+Enter を送る前の「投稿欄への再クリック」の時点で発生しており、
  Playwrightのクリック再試行ログに
  「ポストを保存しますか？」というテキストと、それを覆う
  `data-testid="mask"` の要素が pointer events を遮っている旨が記録
  されていた。これはXの「下書きを保存しますか？」という確認ダイアログ
  であり、投稿欄を閉じようとしたときにだけ表示されるものである。
- 5回目の修正で「オートコンプリートのドロップダウンを閉じる」ために
  本文挿入直後に追加した `page.keyboard.press("Escape")` が、実際には
  insert_text() ではオートコンプリートのドロップダウン自体がほぼ開かない
  ため、ドロップダウンではなく投稿ダイアログそのものを閉じる操作として
  Xに解釈されていたと判明した。その結果、本文入力済みのまま投稿欄が
  閉じられかけて「下書きを保存しますか？」の確認マスクが画面を覆い、
  以後のクリック操作がすべてブロックされていた
  (4〜6回目で見られた「投稿ボタンが disabled のまま」という症状も、
  実際にはこの見えないマスクによる干渉が一因だった可能性が高い)。
- 対策として、本文挿入直後の `Escape` 押下を完全に削除した。また、
  Control+Enter 送信前に行っていた投稿欄への再クリックも、二重に
  フォーカスを取り直す必要はないため削除し、insert_text 直後の
  フォーカス状態のまま短い待機だけを挟んで Control+Enter を送信する
  ようにした。

2026-09-28 修正(9回目・「投稿完了」の誤検知を修正: 実際には0件のまま
投稿されていなかった):
- 8回目の修正版を実行したところ、ジョブ全体は失敗(instagram/threads側の
  問題)したが、Xの処理自体は例外を出さず「Xへの投稿が完了しました。」と
  ログに出力されていた。ところが、ログをよく見ると
  「投稿欄に反映された文字数: 1 (元の文字数: 240)」となっており、
  実際には本文がほぼ入力されていなかった。それにもかかわらず
  Control+Enter 送信後にダイアログが閉じたため、「ダイアログが閉じた
  =投稿成功」という判定ロジックが誤って成功と判断していた。
  実際にXアカウント(@eakensholab)を確認したところ投稿数は0件のままで
  あり、投稿は一切行われていなかった(=誤字脱字や空投稿が公開される
  実害はなかったが、「成功した」という誤った報告をしてしまっていた)。
- 対策として、以下の2点を追加した。
  1. 本文挿入後に反映文字数を確認し、想定文字数と一致しない場合は
     投稿欄への再クリック→insert_textを最大3回までリトライする
     (タイミングのずれで挿入が失敗するケースへの対策)。それでも
     一致しない場合は、投稿を試みず例外を出して失敗として扱う。
  2. Control+Enter送信後、単に「ダイアログが閉じたか」だけで成功と
     判定するのをやめ、実際にXのホームタイムライン
     (https://x.com/home)を開いて、投稿した本文の先頭部分が
     タイムライン上に実際に表示されているかどうかを確認してから
     初めて「投稿が完了しました」とログに出すようにした。この確認が
     取れない場合は、成功と誤報告せず例外を送出する。

2026-09-28 修正(10回目・Control+Enterショートカットが実際には機能して
いなかったことが判明):
- 9回目の修正で追加したホームタイムライン確認により、初めて正確な実態が
  わかった。ログ上は「[試行1] 投稿欄に反映された文字数: 244 (元の文字数:
  240)」と本文入力は完全に成功していたにもかかわらず、Control+Enter
  送信後にXアカウント(@eakensholab)を実際に確認すると投稿数は0件の
  ままだった。7回目の修正で導入した「投稿ボタンのクリックをやめて
  Control+Enterショートカットで送信する」という方針そのものが誤りで、
  この投稿欄ではControl+Enterによる送信が機能していなかったと判明した。
- 対策として、送信方法を「投稿ボタンのクリックを優先し、失敗した場合の
  みControl+Enterをフォールバックとして試す」方式に戻した。6回目の
  修正で確立した「投稿ボタンの祖先ダイアログの中だけで投稿欄を探す」
  という構造的な対応付けにより、ボタンと投稿欄の取り違えは既に解消
  されているため、あとはボタンの有効化(disabled解除)を
  post_button.click(timeout=8000) のPlaywright標準の自動リトライに
  任せることで、本文入力後の有効化ラグを吸収する。クリックが成功した
  かどうかに関わらず、最終的な成否判定は9回目で追加したホームタイム
  ライン確認によって行うため、万一この10回目の対策でも投稿できて
  いなければ、誤って「成功」と報告することはない。

2026-09-28 修正(11回目・真の根本原因を特定: insert_text()はDOM上の
見た目は更新するがXの内部状態を更新しない):
- 10回目の修正版を実行した結果、診断ログで
  「[試行1] 投稿欄に反映された文字数: 244 (元の文字数: 240)」と本文は
  正しく見えているにもかかわらず、post_button.click(timeout=8000) が
  以下のログとともにタイムアウトしていることが判明した。
    waiting for locator("button[data-testid=\"tweetButton\"]")
    - locator resolved to <button disabled ... aria-disabled="true" ...>
    - element is not enabled (retry attempt #1, #2, ... タイムアウトまで)
  つまり、投稿欄のDOM上のテキスト(innerText)は正しく反映されている
  のに、投稿ボタンの活性化を判定しているXの内部状態(Reactのcontrolled
  な入力管理)は「本文なし」のままだった。これは、6回目でボタンと
  投稿欄の取り違えが解消された後も、7〜10回目を通じて一貫して
  観測されていた「ボタンがdisabledのまま」という症状すべてに共通する
  真の根本原因だったと考えられる。5回目の修正で1文字ずつのtype()を
  やめてinsert_text()に切り替えたことが、この不具合の直接の原因
  だった: insert_text() はCDP経由でDOMに直接文字列を挿入するだけで、
  Xの入力欄(Draft.js/React製)が内部状態を更新するために必要な
  本物のキー入力イベント列(keydown/beforeinput/input等)を発生させて
  いなかった。
- 対策として、本文入力の方式を1文字ずつ本物のキーイベントを発生させる
  page.keyboard.type(text, delay=15) に戻した。5回目の修正時に
  type() をやめた理由(#ハッシュタグのオートコンプリートドロップダウン
  による干渉)への対策として、本文入力後に
  div[role="listbox"] (オートコンプリートの候補一覧) が実際に画面上に
  開いている場合に限り Escape を送ってドロップダウンだけを閉じる
  ようにした(8回目の修正で判明した通り、ドロップダウンが開いていない
  状態でEscapeを送ると投稿ダイアログ自体が閉じてしまうため、必ず
  開いていることを確認してから送る)。これにより、内部状態を正しく
  更新しつつ、オートコンプリートの干渉も安全に回避できる。
  文字入力中(type()の最中)はEscapeを送らないため、ハッシュタグの後に
  改行やスペースが続いても、ドロップダウンの候補選択として誤解釈
  される心配もない。
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

            # 11回目の修正: insert_text() はDOM上の見た目(innerText)は
            # 正しく更新するが、Xの入力欄(Draft.js/React製)が投稿ボタンを
            # 活性化させるために必要な内部状態を更新しない(本物のキー
            # イベント列が発生しないため)ことが判明した。そのため、
            # 1文字ずつ本物のキーイベントを発生させる page.keyboard.type()
            # に戻す。5回目の修正で type() をやめた理由だった「#ハッシュ
            # タグのオートコンプリートドロップダウンによる干渉」には、
            # 入力完了後にドロップダウンが実際に開いている場合にだけ
            # Escapeを送る(開いていなければ何もしない)ことで対処する。
            #
            # 9回目の修正: タイミングのずれにより入力が本文の一部(1文字
            # など)しか反映しないことがあったため、反映文字数を確認し、
            # 一致しなければ再クリック→再入力を最大3回まで試みる。
            entered_len = 0
            for attempt in range(1, 4):
                textbox.click()
                page.wait_for_timeout(200)
                # 前回の入力が中途半端に残っている可能性があるため、
                # 選択→削除してから入力し直す。
                page.keyboard.press("Control+A")
                page.keyboard.press("Delete")
                page.wait_for_timeout(200)
                page.keyboard.type(text, delay=15)
                page.wait_for_timeout(500)
                # オートコンプリートのドロップダウン(候補一覧)が実際に
                # 開いている場合のみ、Escapeで閉じる。開いていない状態で
                # Escapeを送ると投稿ダイアログ自体が閉じてしまう
                # (8回目の修正で判明済み)ため、必ず存在確認してから送る。
                try:
                    if page.locator('div[role="listbox"]').count() > 0:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(300)
                except Exception as e:  # noqa: BLE001
                    print(f"[試行{attempt}] ドロップダウン確認に失敗:", e)
                try:
                    entered_len = textbox.evaluate("el => el.innerText.length")
                except Exception as e:  # noqa: BLE001
                    print(f"[試行{attempt}] 投稿欄の内容確認に失敗:", e)
                    entered_len = 0
                print(
                    f"[試行{attempt}] 投稿欄に反映された文字数: {entered_len} "
                    f"(元の文字数: {len(text)})"
                )
                # 改行の扱いなどで innerText.length が元の文字数と完全一致
                # しないことがあるため、大幅に足りない(半分未満)場合のみ
                # 失敗とみなしてリトライする。
                if entered_len >= len(text) * 0.5:
                    break
                print(f"[試行{attempt}] 文字数が大幅に不足しているためリトライします。")
            else:
                pass

            if entered_len < len(text) * 0.5:
                raise RuntimeError(
                    f"本文の入力に失敗しました(反映文字数: {entered_len} / "
                    f"元の文字数: {len(text)})。3回リトライしても改善しなかった"
                    "ため、投稿を中止します。"
                )

            # 認証チャレンジ・電話番号確認などが出ていないか軽くチェック
            if page.locator("text=confirm your identity").count() > 0 or page.locator(
                "text=本人確認"
            ).count() > 0:
                raise RuntimeError(
                    "本人確認/認証チャレンジが表示されました。自動投稿を中断します。"
                    "ブラウザで手動ログインして状態を確認してください(自動での突破は行いません)。"
                )

            # 10回目の修正: 9回目の実行結果、本文は正しく(244/240文字)
            # 反映されていたにもかかわらず、Control+Enter では実際には
            # 投稿されていなかったことがホームタイムライン確認で判明した
            # (Xアカウントの投稿数が0件のままだった)。Control+Enter という
            # ショートカット自体がこの投稿欄では機能していない可能性が高い
            # ため、まず本来の投稿ボタンのクリックを試み、有効化されるまで
            # Playwrightの自動リトライ(最大8秒)に任せる。それでも失敗
            # した場合にのみ Control+Enter をフォールバックとして試す。
            button_click_succeeded = False
            try:
                post_button.click(timeout=8000)
                button_click_succeeded = True
                print("投稿ボタンのクリックに成功しました。")
            except Exception as e:  # noqa: BLE001
                print("投稿ボタンのクリックに失敗(タイムアウトの可能性):", e)

            if not button_click_succeeded:
                print(
                    "投稿ボタンのクリックが失敗したため、"
                    "フォールバックとして Control+Enter での送信を試みます。"
                )
                page.keyboard.press("Control+Enter")

            page.wait_for_timeout(2500)

            # 9回目の修正: 「ダイアログが閉じた」だけでは投稿成功の証拠に
            # ならない(実際には本文がほぼ空のまま送信され、ダイアログだけ
            # 閉じて0件投稿だったケースが確認された)。ホームタイムラインを
            # 開き、投稿した本文の先頭部分が実際に表示されているかどうかを
            # 確認してから、初めて成功と判断する。
            # 10回目の修正: 改行や絵文字混じりの長い断片だとテキスト一致の
            # 判定が不安定になりうるため、本文の1行目(先頭の短い一意な
            # 部分)だけを使うようにした。
            verify_snippet = text.strip().split("\n")[0].strip()[:15]
            posted_confirmed = False
            try:
                page.goto("https://x.com/home", timeout=20000)
                page.wait_for_timeout(3000)
                for _ in range(4):
                    if page.locator(f"text={verify_snippet}").count() > 0:
                        posted_confirmed = True
                        break
                    page.wait_for_timeout(1500)
            except Exception as e:  # noqa: BLE001
                print("投稿確認(ホームタイムライン確認)に失敗:", e)

            if not posted_confirmed:
                raise RuntimeError(
                    "投稿完了を確認できませんでした(ホームタイムラインに"
                    f"本文の先頭「{verify_snippet}」が見つかりません)。"
                    "実際には投稿されていない可能性があるため、失敗として扱います。"
                )
        except Exception:
            _dump_diagnostics(page, "投稿処理中の失敗")
            browser.close()
            raise

        # 送信完了の反映を待つ
        time.sleep(3)
        context.storage_state(path=STORAGE_STATE_PATH)  # セッションを最新化して保存
        browser.close()
        print("Xへの投稿が完了しました。(ホームタイムラインで反映を確認済み)")


if __name__ == "__main__":
    sample_text = sys.argv[1] if len(sys.argv) > 1 else "テスト投稿です #EA検証"
    post_to_x(sample_text)
