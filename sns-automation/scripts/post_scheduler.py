#!/usr/bin/env python3
"""
post_scheduler.py

GitHub Actions から cron で呼び出される想定のエントリーポイント。
1. config/schedule.yaml を見て「今がどのスロットか」を判定する
2. config/posts_queue.csv からそのスロット用の未投稿(posted=no)行を1件取る
3. config/templates.yaml のテンプレに値を埋め込んで本文を作る
4. platform に応じて x_poster / ig_poster を呼び出す
5. 成功したら posts_queue.csv の該当行を posted=yes に更新する

実行タイミングは GitHub Actions 側の cron で決めるので、このスクリプト自体は
「今の時刻に一致するスロットが1つもなければ何もせず終了する」だけのシンプルな
作りにしてあります。多少の実行タイミングのズレ(±15分程度)は許容します。
"""

import csv
import datetime
import os
import sys

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULE_PATH = os.path.join(BASE_DIR, "config", "schedule.yaml")
TEMPLATES_PATH = os.path.join(BASE_DIR, "config", "templates.yaml")
QUEUE_PATH = os.path.join(BASE_DIR, "config", "posts_queue.csv")

WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# cron の実行ズレを吸収する許容幅(分)。GitHub Actions の cron は数分〜十数分
# 遅れて発火することがあるため、前後15分は「そのスロット」とみなす。
TOLERANCE_MINUTES = 20


def now_jst() -> datetime.datetime:
    jst = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.now(jst)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_active_slot(schedule, now):
    today_idx = now.weekday()
    for slot in schedule["slots"]:
        if WEEKDAY_MAP[slot["weekday"]] != today_idx:
            continue
        hh, mm = map(int, slot["time"].split(":"))
        slot_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        diff_minutes = abs((now - slot_dt).total_seconds()) / 60
        if diff_minutes <= TOLERANCE_MINUTES:
            return slot
    return None


def load_queue_row(slot_id):
    with open(QUEUE_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    for row in rows:
        if row["slot_id"] == slot_id and row.get("posted", "no") == "no":
            return row, rows
    return None, rows


def mark_posted(slot_id, report_no, rows):
    for row in rows:
        if row["slot_id"] == slot_id and row["report_no"] == report_no:
            row["posted"] = "yes"
    fieldnames = list(rows[0].keys())
    with open(QUEUE_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def render(template_str, row):
    # 空欄のセルは "" のまま埋め込む(未使用フィールドはテンプレ側で使わない前提)
    safe_row = {k: (v if v is not None else "") for k, v in row.items()}
    return template_str.format(**safe_row)


def build_message(templates, platform, template_key, row):
    # そのプラットフォーム専用のテンプレが無ければ x 用のテンプレで代用する
    # (例: threads に hook_single 等の専用テンプレをまだ用意していない場合)
    platform_templates = templates.get(platform) or {}
    body = platform_templates.get(template_key) or templates["x"][template_key]
    row = dict(row)
    row["hashtags_core"] = templates.get("hashtags_core", "")
    row["hashtags_extra"] = templates.get("hashtags_extra", "")
    message = render(body, row).strip()

    # GumroadもPayhipも「商品の作成・公開」用の公式APIが無いため手動公開。
    # posts_queue.csv の gumroad_url / payhip_url が埋まっていれば、新記事告知の
    # 投稿にだけ海外版へのリンクを追記する。両方あれば2行、片方だけなら1行、
    # どちらも空なら何も追記しない。
    overseas_links = []
    gumroad_url = (row.get("gumroad_url") or "").strip()
    if gumroad_url:
        overseas_links.append(f"Gumroad: {gumroad_url}")
    payhip_url = (row.get("payhip_url") or "").strip()
    if payhip_url:
        overseas_links.append(f"Payhip: {payhip_url}")

    if overseas_links and template_key == "new_article":
        message += "\n\n🌍 English / overseas version\n" + "\n".join(overseas_links)

    return message


def main():
    schedule = load_yaml(SCHEDULE_PATH)
    templates = load_yaml(TEMPLATES_PATH)
    now = now_jst()

    slot = find_active_slot(schedule, now)
    if slot is None:
        print(f"[{now.isoformat()}] 現在アクティブなスロットはありません。何もせず終了します。")
        return 0

    print(f"[{now.isoformat()}] アクティブスロット: {slot['id']} ({slot['platform']})")

    row, rows = load_queue_row(slot["id"])
    if row is None:
        print(f"スロット {slot['id']} 向けの未投稿キューがありません。キュー(posts_queue.csv)を確認してください。")
        return 0

    raw_platform = slot["platform"]
    if raw_platform == "both":  # 後方互換(旧設定)
        platforms = ["x", "instagram"]
    elif isinstance(raw_platform, list):
        platforms = raw_platform
    else:
        platforms = [raw_platform]

    for platform in platforms:
        message = build_message(templates, platform, slot["template"], row)
        image_path = row.get("image_path") or None
        if image_path:
            image_path = os.path.join(BASE_DIR, image_path)

        print(f"--- {platform} 投稿本文 ---\n{message}\n---------------------")

        if os.environ.get("DRY_RUN", "false").lower() == "true":
            print(f"[DRY_RUN] {platform} への投稿をスキップしました。")
            continue

        if platform == "x":
            from x_poster import post_to_x
            post_to_x(message)
        elif platform == "instagram":
            from ig_poster import post_to_instagram
            if not image_path:
                print("Instagram投稿には image_path が必須です。posts_queue.csv を確認してください。")
                continue
            post_to_instagram(message, image_path)
        elif platform == "threads":
            from threads_poster import post_to_threads
            post_to_threads(message)
        else:
            print(f"未対応のプラットフォームです: {platform}(スキップします)")

    mark_posted(slot["id"], row["report_no"], rows)
    print("posts_queue.csv を更新しました(posted=yes)。")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
    sys.exit(main())
