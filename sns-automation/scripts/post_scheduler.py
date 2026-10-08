#!/usr/bin/env python3
"""
post_scheduler.py (v2: 毎日 朝・夜 × 全SNS、EA話題ランダム投稿)

GitHub Actions から cron で呼び出される想定のエントリーポイント。
1. config/schedule.yaml を見て「今がどのスロットか」を判定する
2. スロットの種類に応じて本文を作る
     - template: new_article … config/posts_queue.csv の未投稿行(新記事の告知)。
                              該当行が無い場合は、下の random_ea に自動で切り替える
     - template: random_ea   … config/tips.yaml(教育系)と config/teasers.yaml
                              (公開済み記事の無料部分の数字)をまとめた「ネタ帳」から、
                              ランダムに1件選ぶ
3. platform に応じて x_poster / ig_poster / threads_poster を呼び出す
4. 成功したら記録する(新記事告知は posts_queue.csv の posted=yes、
   全スロット共通で config/last_run.json に「このスロットの今回分は、
   このSNSに投稿済み」を記録)

v2 での主な変更点
- 毎日 朝(08:00 JST)と夜(20:00 JST)の2回、X・Instagram・Threadsすべてに投稿
- ネタ帳からのランダム選択は「シャッフルした順に1周するまで同じ内容を使わない」方式。
  日付と朝/夜から決まるので、同じ回なら3つのSNSで同じ内容になり、
  GitHub側に状態を持たなくても再現できる
- SNSごとに try/except。たとえばXが失敗しても、InstagramとThreadsは投稿される。
  失敗したSNSがあった回は、最後に終了コード1で終わる(Actionsの実行が赤くなって気づける)
- last_run.json で「同じ回を同じSNSに二重投稿しない」ようにした
  (手動実行と定期実行が重なった場合や、同じcronが2回走った場合の対策)

注記(note記事の公開): note.comのbot検知(reCAPTCHA)により、GitHub Actionsからの
自動公開はできないため、note記事自体の公開はnoteの「予約投稿」で行う。
このスクリプトはSNS投稿のみを担当する。
"""

import csv
import datetime
import json
import os
import random
import sys
import urllib.error
import urllib.request

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULE_PATH = os.path.join(BASE_DIR, "config", "schedule.yaml")
TEMPLATES_PATH = os.path.join(BASE_DIR, "config", "templates.yaml")
QUEUE_PATH = os.path.join(BASE_DIR, "config", "posts_queue.csv")
TIPS_PATH = os.path.join(BASE_DIR, "config", "tips.yaml")
TEASERS_PATH = os.path.join(BASE_DIR, "config", "teasers.yaml")
STATE_PATH = os.path.join(BASE_DIR, "config", "last_run.json")

# Instagramで、新記事に紐づかない投稿(random_ea)に使い回す画像(ローテーション)。
TIP_IMAGES = [
    "images/tip_01.png",
    "images/tip_02.png",
    "images/tip_03.png",
    "images/tip_04.png",
    "images/tip_05.png",
]

WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# cron の実行ズレを吸収する許容幅(分)。GitHub Actionsのスケジュール実行は
# 数時間規模で遅れることがあるため、6時間(360分)に設定している。
# 朝(08:00)と夜(20:00)は12時間離れているので、重複マッチは起きない。
TOLERANCE_MINUTES = 360

# ネタ帳の「何回目の投稿か」を数える起点(これより前の日付は使わない)。
EPOCH = datetime.date(2026, 1, 1)


def now_jst() -> datetime.datetime:
    jst = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.now(jst)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── スロット判定 ────────────────────────────────────────────────

def slot_occurrence(slot, now):
    """そのスロットの『直近の該当曜日・時刻(今より前で最も近いもの)』を返す。"""
    target_weekday = WEEKDAY_MAP[slot["weekday"]]
    hh, mm = map(int, slot["time"].split(":"))
    days_since = (now.weekday() - target_weekday) % 7
    candidate = (now - datetime.timedelta(days=days_since)).replace(
        hour=hh, minute=mm, second=0, microsecond=0
    )
    if candidate > now:
        candidate -= datetime.timedelta(days=7)
    return candidate


def find_active_slot(schedule, now):
    """今の時刻から許容幅以内に始まったスロットのうち、最も新しいものを返す。
    戻り値は (slot, 該当回の日時) 。無ければ (None, None)。"""
    best_slot, best_occ, best_diff = None, None, None
    for slot in schedule["slots"]:
        candidate = slot_occurrence(slot, now)
        diff_minutes = (now - candidate).total_seconds() / 60
        if diff_minutes <= TOLERANCE_MINUTES:
            if best_diff is None or diff_minutes < best_diff:
                best_slot, best_occ, best_diff = slot, candidate, diff_minutes
    return best_slot, best_occ


# ── 投稿済みの記録(二重投稿防止) ─────────────────────────────────

def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def state_key(slot_id, platform):
    return f"{slot_id}|{platform}"


# ── 新記事告知(posts_queue.csv) ───────────────────────────────

def is_note_published(url):
    """noteの記事が、誰でも読める状態(公開済み)かを確認する。
    公開前の下書きのURLは、ログインしていない状態ではアクセスできず404になる。
    確認できない場合(通信エラーなど)は、安全側に倒して「未公開」として扱い、
    その回は告知せず、次のスロットで再確認する。
    """
    key = url.strip().rstrip("/").split("/")[-1]
    api = f"https://note.com/api/v3/notes/{key}"
    req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0 (ea-verification-sns)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status == 200
    except urllib.error.HTTPError as e:
        print(f"[公開確認] {key}: HTTP {e.code} → 未公開として扱います。")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"[公開確認] {key}: 確認に失敗({type(e).__name__}: {e}) → 未公開として扱います。")
        return False


def load_queue_row(slot_id):
    if not os.path.exists(QUEUE_PATH):
        return None, []
    with open(QUEUE_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    for row in rows:
        if row["slot_id"] in (slot_id, "any") and row.get("posted", "no") == "no":
            # note_url が未設定('yyyyyyyy' などの仮置き含む)の行は、告知に使わない
            url = (row.get("note_url") or "").strip()
            if not url or "yyyy" in url:
                continue
            # 公開済みの記事だけを告知する(未公開なら、次の行・次のスロットへ)
            if not is_note_published(url):
                continue
            return row, rows
    return None, rows


def mark_posted(slot_id, report_no, rows):
    for row in rows:
        if row["slot_id"] in (slot_id, "any") and row["report_no"] == report_no:
            row["posted"] = "yes"
    fieldnames = list(rows[0].keys())
    with open(QUEUE_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def render(template_str, row):
    safe_row = {k: (v if v is not None else "") for k, v in row.items()}
    return template_str.format(**safe_row)


def build_message(templates, platform, template_key, row):
    platform_templates = templates.get(platform) or {}
    body = platform_templates.get(template_key) or templates["x"][template_key]
    row = dict(row)
    row["hashtags_core"] = templates.get("hashtags_core", "")
    row["hashtags_extra"] = templates.get("hashtags_extra", "")
    message = render(body, row).strip()

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


# ── ランダム投稿(ネタ帳) ──────────────────────────────────────

def load_bank(occ_date):
    """tips.yaml と teasers.yaml をまとめたネタ帳を返す(その日に使えるものだけ)。"""
    bank = []
    if os.path.exists(TIPS_PATH):
        for t in load_yaml(TIPS_PATH).get("tips", []):
            bank.append({"text": str(t).strip(), "kind": "tip"})
    if os.path.exists(TEASERS_PATH):
        for item in load_yaml(TEASERS_PATH).get("teasers", []):
            if isinstance(item, str):
                item = {"text": item}
            start = item.get("from")
            if start is not None:
                if isinstance(start, str):
                    start = datetime.date.fromisoformat(start)
                if start > occ_date:
                    continue  # まだ公開前の記事のネタは使わない
            bank.append({"text": str(item["text"]).strip(), "kind": "teaser"})
    return bank


def occurrence_index(occ):
    """朝(正午より前)=0、夜=1 として、起点からの通算の回数を返す。"""
    return (occ.date() - EPOCH).days * 2 + (1 if occ.hour >= 12 else 0)


def pick_random_item(bank, occ):
    """シャッフルした順に1周するまで、同じ内容を使わない選び方(状態を持たない)。"""
    n = occurrence_index(occ)
    cycle, pos = divmod(n, len(bank))
    order = list(range(len(bank)))
    random.Random(cycle).shuffle(order)
    return order[pos], bank[order[pos]], n


def build_random_message(templates, platform, occ):
    bank = load_bank(occ.date())
    if not bank:
        return None, None
    idx, item, n = pick_random_item(bank, occ)

    hashtags = templates.get("hashtags_core", "")
    if platform == "instagram":
        extra = templates.get("hashtags_extra", "")
        if extra:
            hashtags = f"{hashtags} {extra}"
    message = f"{item['text']}\n\n{hashtags}".strip()

    image_path = None
    if platform == "instagram" and TIP_IMAGES:
        image_path = TIP_IMAGES[n % len(TIP_IMAGES)]
    return message, image_path


# ── 投稿の実行 ────────────────────────────────────────────────

def post_one(platform, message, image_path):
    if platform == "x":
        from x_poster import post_to_x
        post_to_x(message)
    elif platform == "instagram":
        from ig_poster import post_to_instagram
        if not image_path:
            raise RuntimeError("Instagram投稿には画像が必須です(image_path が空です)。")
        post_to_instagram(message, image_path)
    elif platform == "threads":
        from threads_poster import post_to_threads
        post_to_threads(message)
    else:
        raise RuntimeError(f"未対応のプラットフォームです: {platform}")


def main():
    schedule = load_yaml(SCHEDULE_PATH)
    templates = load_yaml(TEMPLATES_PATH)
    now = now_jst()

    slot, occ = find_active_slot(schedule, now)
    if slot is None:
        print(f"[{now.isoformat()}] 現在アクティブなスロットはありません。何もせず終了します。")
        return 0

    print(f"[{now.isoformat()}] アクティブスロット: {slot['id']} ({slot['platform']}) 該当回={occ.isoformat()}")

    # 新記事告知の枠で、告知できる記事がまだ無いときは、ランダム投稿に切り替える
    mode = slot["template"]
    row, rows = (None, None)
    if mode != "random_ea":
        row, rows = load_queue_row(slot["id"])
        if row is None:
            print(f"スロット {slot['id']} 向けの告知できる記事(note_urlあり・未投稿)がありません。"
                  "代わりにEAに関するランダム投稿を行います。")
            mode = "random_ea"

    raw_platform = slot["platform"]
    if raw_platform == "both":
        platforms = ["x", "instagram"]
    elif isinstance(raw_platform, list):
        platforms = raw_platform
    else:
        platforms = [raw_platform]

    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    state = load_state()
    occ_label = occ.strftime("%Y-%m-%dT%H:%M")
    failures = []
    any_success = False

    for platform in platforms:
        key = state_key(slot["id"], platform)
        if not dry_run and state.get(key) == occ_label:
            print(f"[{platform}] この回({occ_label})は投稿済みのためスキップします。")
            continue

        if mode == "random_ea":
            message, image_path = build_random_message(templates, platform, occ)
            if message is None:
                print("ネタ帳が空です。tips.yaml / teasers.yaml を確認してください。")
                failures.append(platform)
                continue
        else:
            message = build_message(templates, platform, mode, row)
            image_path = row.get("image_path") or None
            # Instagramは画像が必須。告知用の画像が未設定の行は、汎用のブランド画像で代用する
            if not image_path and platform == "instagram" and TIP_IMAGES:
                image_path = TIP_IMAGES[occurrence_index(occ) % len(TIP_IMAGES)]

        if image_path:
            image_path = os.path.join(BASE_DIR, image_path)

        print(f"--- {platform} 投稿本文 ---\n{message}\n---------------------")

        if dry_run:
            print(f"[DRY_RUN] {platform} への投稿をスキップしました。")
            continue

        try:
            post_one(platform, message, image_path)
        except Exception as e:  # noqa: BLE001  1つのSNSの失敗で他のSNSを止めない
            print(f"[{platform}] 投稿に失敗しました: {type(e).__name__}: {e}")
            failures.append(platform)
            continue

        any_success = True
        state[key] = occ_label
        save_state(state)  # 1つ成功するたびに記録(途中で落ちても二重投稿しない)
        print(f"[{platform}] 投稿しました。")

    if mode != "random_ea" and not dry_run and any_success and not failures:
        mark_posted(slot["id"], row["report_no"], rows)
        print("posts_queue.csv を更新しました(posted=yes)。")
    elif mode != "random_ea" and failures:
        print("一部のSNSで失敗したため、posts_queue.csv は更新しません"
              "(再実行すると、投稿済みのSNSはスキップされ、失敗したSNSだけ再試行されます)。")

    if failures:
        print(f"失敗したSNS: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
    sys.exit(main())
