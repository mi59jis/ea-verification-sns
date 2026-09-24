#!/usr/bin/env python3
"""
ig_poster.py

Instagram Graph API を使った投稿(公式・無料)。
Business/クリエイターアカウント化 + Facebookページ連携 + Meta for Developers
アプリの作成が事前に必要です(手順は README_SNS_AUTOMATION.md 参照)。

必要な環境変数:
  IG_ACCESS_TOKEN        長期(または無期限)ページアクセストークン
  IG_BUSINESS_ACCOUNT_ID InstagramビジネスアカウントのID(数字)
  IMAGE_PUBLIC_BASE_URL  画像を公開しているベースURL
                         例: https://raw.githubusercontent.com/<user>/<repo>/main/sns-automation

Graph APIの画像投稿は「ローカルファイルの直接アップロード」に対応していないため、
画像はインターネット上の公開URLとして渡す必要があります。
このリポジトリを public にして、コミット済みの画像をそのまま
raw.githubusercontent.com 経由で参照するのが最も手軽です。
非公開にしたい場合は、S3やCloudflare R2などの公開バケットに画像を置いてください。

制限事項(2026年時点のGraph API仕様):
  - ストーリーズの投稿は非対応(フィード投稿のみ)
  - 24時間のローリングウィンドウで最大25投稿まで
"""

import os
import time

import requests

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def _public_image_url(image_local_path: str) -> str:
    base_url = os.environ.get("IMAGE_PUBLIC_BASE_URL", "").rstrip("/")
    if not base_url:
        raise RuntimeError(
            "IMAGE_PUBLIC_BASE_URL が設定されていません。"
            "画像を公開URLとして参照できる場所に置き、そのベースURLを設定してください。"
        )
    # sns-automation/ からの相対パスをそのままURLに連結する
    rel_path = os.path.relpath(image_local_path).replace(os.sep, "/")
    # scripts/ 経由で呼ばれても sns-automation ルートからの相対パスに正規化
    if rel_path.startswith("scripts/"):
        rel_path = rel_path[len("scripts/") :]
    return f"{base_url}/{rel_path}"


def post_to_instagram(caption: str, image_local_path: str, max_wait_seconds: int = 60) -> None:
    access_token = os.environ["IG_ACCESS_TOKEN"]
    ig_user_id = os.environ["IG_BUSINESS_ACCOUNT_ID"]

    image_url = _public_image_url(image_local_path)
    print(f"公開画像URL: {image_url}")

    # 1. メディアコンテナを作成
    create_resp = requests.post(
        f"{GRAPH_API_BASE}/{ig_user_id}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": access_token,
        },
        timeout=30,
    )
    create_resp.raise_for_status()
    creation_id = create_resp.json()["id"]
    print(f"メディアコンテナ作成完了: {creation_id}")

    # 2. コンテナの処理完了を待つ(画像フェッチ・エンコードに数秒かかることがある)
    status = "IN_PROGRESS"
    waited = 0
    while status == "IN_PROGRESS" and waited < max_wait_seconds:
        time.sleep(3)
        waited += 3
        status_resp = requests.get(
            f"{GRAPH_API_BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=30,
        )
        status_resp.raise_for_status()
        status = status_resp.json().get("status_code", "FINISHED")

    if status not in ("FINISHED",):
        raise RuntimeError(f"メディアコンテナの処理が完了しませんでした(status={status})")

    # 3. 公開
    publish_resp = requests.post(
        f"{GRAPH_API_BASE}/{ig_user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=30,
    )
    publish_resp.raise_for_status()
    print(f"Instagram投稿完了: {publish_resp.json()}")


if __name__ == "__main__":
    # 単体テスト用: 環境変数とサンプル画像を用意した上で直接実行できる
    post_to_instagram(
        caption="テスト投稿です #EA検証",
        image_local_path=os.path.join(os.path.dirname(__file__), "..", "config", "..", "images", "eyecatch_01_jp.png"),
    )
