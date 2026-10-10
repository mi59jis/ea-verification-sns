#!/usr/bin/env python3
"""
mt4_dated_posts.py — MT4編の記事の告知を、決めた日時に投稿する(MT4専用の告知枠)。

config/mt4_posts.csv の行(1行 = 1つの記事 × 1つのSNS)を見て、
  - 予定時刻(due)を過ぎていて、status=pending の行を対象にする
  - noteの記事が公開済みのときだけ投稿する(未公開なら投稿せず pending のまま。次の実行で再確認)
  - 予定時刻から48時間たっても公開されなかった行は status=skipped にして、それ以上は告知しない
    (= noteの公開が間に合わなくても、何も壊れない・未公開の記事を告知することもない)
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
GRACE_HOURS = 48
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
    rows, fields = _load()
    if not rows:
        return []
    failures, done_platforms, changed = [], set(), False
    published_cache = {}
    for row in rows:
        if row.get("status", "pending") != "pending":
            continue
        due = datetime.datetime.fromisoformat(row["due"]).replace(tzinfo=JST)
        if due > now:
            continue
        if now - due > datetime.timedelta(hours=GRACE_HOURS):
            print(f"[MT4] {row['id']}: 予定から{GRACE_HOURS}時間たっても公開されなかったため、告知をやめます。")
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
        message = row["text"].replace("{note_url}", url).strip()
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
