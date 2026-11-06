#!/usr/bin/env python3
"""
mt4_dated_posts.py — MT4編の記事の告知を、決めた日時に投稿する(MT4専用の告知枠)。

config/mt4_posts.csv の行(1行 = 1つの記事 × 1つのSNS)を見て、
  - 予定時刻(due)を過ぎていて、status=pending の行を対象にする
  - noteの記事が公開済みのときだけ投稿する(未公開なら投稿せず pending のまま。次の実行で再確認)
  - 公開が予定より遅れても取りやめない。公開された次の実行で告知する(2026-11-03 変更)
  - 記事の告知(ON_PUBLISH の行)は、予定の日より早く公開されたときも、予定の日を待たずに告知する(2026-11-04 変更)
  - 期限のある告知(EXPIRING の行。お試し価格など)だけは、予定時刻から24時間たったら status=skipped にする
  - 夜23時〜朝7時(JST)の実行では告知を出さない(2026-11-04 追加)
  - 投稿の直前に禁止語(BANNED)を確かめ、見つかったら直してから投稿する。直せなければ status=held にして出さない(2026-11-06 追加)
  - 1回の実行で、1つのSNSにつき1件まで(遅れて公開した記事がまとめて流れないように)

post_scheduler.py の main() から、通常のスロット処理とは別に毎回呼ばれる。
ここで失敗しても、MT5側の通常の投稿は止めない。

実際に投稿するのは config/mt4_posts_enabled.txt の中身が "true" のときだけ。
それ以外(false・ファイルなし)のときは、「告知するはずの内容」をログに表示するだけで、
投稿も mt4_posts.csv の更新もしない(本番前の確認用)。
"""

import csv
import datetime
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MT4_PATH = os.path.join(BASE_DIR, "config", "mt4_posts.csv")
ENABLED_PATH = os.path.join(BASE_DIR, "config", "mt4_posts_enabled.txt")
ON_PUBLISH = ("article_mt4_", "guide_mt4_", "free_n")  # 予定の日を待たず、公開されたら告知する記事のid
EXPIRING = ("re_mt4_01",)  # 文面に期限が入っている告知のid
GRACE_HOURS = 24
QUIET_FROM, QUIET_UNTIL = 23, 7  # この時間帯(JST)は告知を出さず、次の実行に回す
# 告知に使わない言葉(記事の生成と同じ一覧 + 「必ず」)。投稿の直前に確かめる(2026-11-06 追加)
BANNED = ["おすすめ", "推奨", "優秀", "最強", "必勝", "稼げる", "安全", "危険", "詐欺", "買うべき", "避けるべき", "合格", "不合格", "必ず"]
# 1行目(題名の行)に入っていた場合の言い換え
REWORD = {"おすすめしません": "控えたほうがよいです", "おすすめ": "よく使われる", "危険": "注意が必要", "安全": "心配ない", "必ず": "いつも"}


def clean_text(text, need_url=True):
    """禁止語を取り除いた文面を返す。直せないときは None(投稿しない)。
    1行目以外で禁止語を含む行は、その行ごと外す。1行目は言い換える。
    need_url=True のときは、{note_url} の行が残っていることも確かめる(通常の枠はURLが入った後の文面なので False)。"""
    lines = text.split("\n")
    out = [lines[0]] + [ln for ln in lines[1:] if not any(w in ln for w in BANNED)]
    for a, b in REWORD.items():
        out[0] = out[0].replace(a, b)
    fixed = "\n".join(out)
    if any(w in fixed for w in BANNED) or (need_url and "{note_url}" not in fixed):
        return None
    return fixed
JST = datetime.timezone(datetime.timedelta(hours=9))


def _load():
    if not os.path.exists(MT4_PATH):
        return [], []
    with open(MT4_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames


def _save(rows, fields):
    with open(MT4_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def enabled():
    try:
        with open(ENABLED_PATH, "r", encoding="utf-8") as f:
            return f.read().strip().lower() == "true"
    except OSError:
        return False


def run(now, dry_run, is_note_published, post_one):
    """戻り値: 失敗したSNSのリスト(空なら問題なし)。"""
    if not enabled():
        print("[MT4] mt4_posts_enabled.txt が true ではないため、MT4の告知は内容の表示だけで、投稿しません。")
        dry_run = True
    if now.hour >= QUIET_FROM or now.hour < QUIET_UNTIL:
        print(f"[MT4] {now:%H:%M} は夜中のため告知を出しません({QUIET_UNTIL}時以降の実行に回します)。")
        return []
    rows, fields = _load()
    if not rows:
        return []
    failures, done_platforms, changed = [], set(), False
    published_cache = {}
    for row in rows:
        if row.get("status", "pending") != "pending":
            continue
        due = datetime.datetime.fromisoformat(row["due"]).replace(tzinfo=JST)
        if due > now and not row["id"].startswith(ON_PUBLISH):
            continue
        if row["id"].startswith(EXPIRING) and now - due > datetime.timedelta(hours=GRACE_HOURS):
            print(f"[MT4] {row['id']}: 予定から{GRACE_HOURS}時間たったため、期限のある告知をやめます。")
            row["status"] = "skipped"
            changed = True
            continue
        platform = row["platform"]
        if platform in done_platforms:
            continue
        url = row["note_url"]
        if url not in published_cache:
            published_cache[url] = is_note_published(url)
        if not published_cache[url]:
            print(f"[MT4] {row['id']}: noteがまだ公開されていないため、今回は告知しません(次の実行で再確認)。")
            continue
        text = row["text"]
        if any(w in text for w in BANNED):
            fixed = clean_text(text)
            if fixed is None:
                print(f"[MT4] {row['id']}: 禁止語 {[w for w in BANNED if w in text]} を直せないため、投稿しません(status=held)。")
                row["status"] = "held"
                changed = True
                failures.append(f"mt4-banned-{row['id']}")
                continue
            print(f"[MT4] {row['id']}: 禁止語 {[w for w in BANNED if w in text]} があったため、直してから投稿します。")
            text = fixed
        message = text.replace("{note_url}", url).strip()
        image = os.path.join(BASE_DIR, row["image"]) if row.get("image") else None
        print(f"--- [MT4] {platform} 投稿本文({row['id']}) ---\n{message}\n---------------------")
        if dry_run:
            print(f"[DRY_RUN][MT4] {platform} への投稿をスキップしました。")
            done_platforms.add(platform)
            continue
        try:
            post_one(platform, message, image)
        except Exception as e:  # noqa: BLE001
            print(f"[MT4] {platform} 投稿に失敗しました: {type(e).__name__}: {e}")
            failures.append(f"mt4-{platform}")
            done_platforms.add(platform)
            continue
        row["status"] = "posted"
        row["posted_at"] = now.strftime("%Y-%m-%dT%H:%M")
        done_platforms.add(platform)
        changed = True
        _save(rows, fields)  # 1件ごとに保存(途中で落ちても二重投稿しない)
        print(f"[MT4] {platform} に投稿しました。")
    if changed and not dry_run:  # 表示だけのときは、48時間経過の取りやめも記録しない
        _save(rows, fields)
    return failures
