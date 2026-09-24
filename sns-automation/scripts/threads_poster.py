#!/usr/bin/env python3
"""
threads_poster.py

Threads API(Meta公式・無料)を使った投稿。

Instagram Graph APIと違い、Threads APIは以下の条件が不要です:
  - Instagramビジネス/クリエイターアカウント化
  - Facebookページとの連携

つまり、あなた自身のThreadsアカウント(個人アカウントでも可)に対して、
Meta for Developersでアプリを作り、自分自身を「テスター」として追加するだけで
使えます(本審査待ちは不要。手順はREADME_SNS_AUTOMATION.md参照)。

必要な環境変数:
  THREADS_ACCESS_TOKEN   長期アクセストークン
  THREADS_USER_ID        あなたのThreadsユーザーID(数字。/me で取得)

制限事項(2026年時点):
  - レート上限は非常に緩い(最低でも1日48,000コール相当)ので、
    週2回程度の投稿では実質的に気にする必要はありません
  - 1投稿は最大500文字
"""

import os
import time

import requests

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.threads.net/{GRAPH_API_VERSION}"

MAX_CHARS = 500


def post_to_threads(text: str, max_wait_seconds: int = 60) -> None:
    access_token = os.environ["THREADS_ACCESS_TOKEN"]
    user_id = os.environ["THREADS_USER_ID"]

    if len(text) > MAX_CHARS:
        raise RuntimeError(
            f"Threadsの投稿は{MAX_CHARS}文字までです(現在{len(text)}文字)。"
            "テンプレートを短くしてください。"
        )

    # 1. テキストコンテナを作成
    create_resp = requests.post(
        f"{GRAPH_API_BASE}/{user_id}/threads",
        data={
            "media_type": "TEXT",
            "text": text,
            "access_token": access_token,
        },
        timeout=30,
    )
    create_resp.raise_for_status()
    creation_id = create_resp.json()["id"]
    print(f"Threadsコンテナ作成完了: {creation_id}")

    # 2. 処理完了を軽く待つ(テキストのみなので通常は一瞬)
    time.sleep(3)

    # 3. 公開
    publish_resp = requests.post(
        f"{GRAPH_API_BASE}/{user_id}/threads_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=30,
    )
    publish_resp.raise_for_status()
    print(f"Threads投稿完了: {publish_resp.json()}")


if __name__ == "__main__":
    # 単体テスト用
    post_to_threads("テスト投稿です #EA検証")
