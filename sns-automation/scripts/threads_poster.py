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

GRAPH_API_VERSION = "v1.0"
GRAPH_API_BASE = f"https://graph.threads.net/{GRAPH_API_VERSION}"

MAX_CHARS = 500


def post_to_threads(text: str, image_local_path: str = None, max_wait_seconds: int = 60) -> None:
    access_token = os.environ["THREADS_ACCESS_TOKEN"]
    user_id = os.environ["THREADS_USER_ID"]

    if len(text) > MAX_CHARS:
        raise RuntimeError(
            f"Threadsの投稿は{MAX_CHARS}文字までです(現在{len(text)}文字)。"
            "テンプレートを短くしてください。"
        )

    # 1. コンテナを作成(画像があれば画像つき。画像は Instagram と同じく公開URLで渡す)
    data = {"media_type": "TEXT", "text": text, "access_token": access_token}
    if image_local_path:
        from ig_poster import _public_image_url
        data.update(media_type="IMAGE", image_url=_public_image_url(image_local_path))
        print(f"公開画像URL: {data['image_url']}")
    create_resp = requests.post(f"{GRAPH_API_BASE}/{user_id}/threads", data=data, timeout=30)
    if create_resp.status_code >= 400:
        print(f"APIエラー応答本文: {create_resp.text}")

    create_resp.raise_for_status()
    creation_id = create_resp.json()["id"]
    print(f"Threadsコンテナ作成完了: {creation_id}")

    # 2. 処理完了を待つ(テキストのみなら一瞬。画像つきは取り込みが終わるまで待つ)
    time.sleep(3)
    waited = 3
    while image_local_path and waited < max_wait_seconds:
        status_resp = requests.get(
            f"{GRAPH_API_BASE}/{creation_id}",
            params={"fields": "status", "access_token": access_token},
            timeout=30,
        )
        status_resp.raise_for_status()
        status = status_resp.json().get("status", "FINISHED")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Threadsの画像の取り込みに失敗しました(status={status})")
        time.sleep(3)
        waited += 3

    # 3. 公開
    publish_resp = requests.post(
        f"{GRAPH_API_BASE}/{user_id}/threads_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=30,
    )
    if publish_resp.status_code >= 400:
        print(f"APIエラー応答本文: {publish_resp.text}")

    publish_resp.raise_for_status()
    print(f"Threads投稿完了: {publish_resp.json()}")


if __name__ == "__main__":
    # 単体テスト用
    post_to_threads("テスト投稿です #EA検証")
