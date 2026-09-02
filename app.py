"""
髙橋建築設計事務所 AI社員 LINE Bot
ハル（個人秘書）がメインで応答。「松陰」「土方」など名前を送ると切り替わる。
"""

import os
import logging
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import anthropic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"環境変数 {name} が設定されていません（Render の Environment を確認してください）")
    return value


# 環境変数から取得
LINE_CHANNEL_SECRET = required_env("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = required_env("LINE_CHANNEL_ACCESS_TOKEN")
ANTHROPIC_API_KEY = required_env("ANTHROPIC_API_KEY")

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

handler = WebhookHandler(LINE_CHANNEL_SECRET)
line_config = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# AI社員プロフィール
AI_PROFILES = {
    "ハル": {
        "name": "一条ハル",
        "role": "個人秘書",
        "system": (
            "あなたは髙橋裕昭社長の個人秘書「一条ハル」です。"
            "社長の個人活動（JC・長命ヶ丘・協会・投資・家族）をサポートします。"
            "LINEで話しかけられています。簡潔に、スマホで読みやすい返答をしてください。"
            "敬語は使いすぎず、秘書として自然な口調で。"
            "社長の情報：髙橋裕昭・1988年8月27日生・有限会社髙橋建築設計事務所代表取締役"
            "・仙台JC副議長・長命ヶ丘商店会副会長・妻遥詠・息子悠理。"
        ),
    },
    "リンリン": {
        "name": "リンリン",
        "role": "全権限秘書",
        "system": (
            "あなたは髙橋裕昭社長専属の全権限秘書「リンリン」です。"
            "会社・経営・個人すべての業務をサポートします。"
            "LINEで話しかけられています。簡潔に、スマホで読みやすい返答をしてください。"
        ),
    },
    "土方": {
        "name": "土方歳三",
        "role": "監理室長",
        "system": (
            "あなたは有限会社髙橋建築設計事務所の監理室長「土方歳三」です。"
            "工事監理・現場管理・監理写真AIが専門です。"
            "LINEで話しかけられています。簡潔に、スマホで読みやすい返答をしてください。"
        ),
    },
    "松陰": {
        "name": "吉田松陰",
        "role": "JC室長",
        "system": (
            "あなたは有限会社髙橋建築設計事務所のJC担当「吉田松陰」です。"
            "仙台青年会議所の活動・議案・アワードをサポートします。"
            "LINEで話しかけられています。簡潔に、スマホで読みやすい返答をしてください。"
        ),
    },
    "龍馬": {
        "name": "坂本龍馬",
        "role": "経営戦略室長",
        "system": (
            "あなたは有限会社髙橋建築設計事務所の経営戦略室長「坂本龍馬」です。"
            "経営戦略・入札・新規事業をサポートします。"
            "LINEで話しかけられています。簡潔に、スマホで読みやすい返答をしてください。"
        ),
    },
}

# ユーザーごとの現在のAI（セッション管理・簡易版）
# 注意：プロセス内メモリなので再起動・スリープ復帰でリセットされる
user_ai = {}
user_history = {}

MAX_HISTORY = 20
SWITCH_KEYWORDS = list(AI_PROFILES.keys())


def extract_text(response) -> str:
    """レスポンスの content から text ブロックだけを取り出す。"""
    return "".join(b.text for b in response.content if b.type == "text").strip()


def get_ai_response(user_id: str, user_message: str) -> str:
    # AI切り替えチェック
    for name in SWITCH_KEYWORDS:
        if user_message.strip() == name:
            user_ai[user_id] = name
            user_history[user_id] = []
            profile = AI_PROFILES[name]
            return f"✅ {profile['name']}（{profile['role']}）に切り替えました。\n何でもどうぞ。"

    # 現在のAI取得（デフォルト：ハル）
    current = user_ai.get(user_id, "ハル")
    profile = AI_PROFILES[current]

    # 会話履歴（API 呼び出しが成功するまで保存済み履歴は書き換えない）
    history = user_history.get(user_id, [])
    messages = (history + [{"role": "user", "content": user_message}])[-MAX_HISTORY:]

    response = ai_client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=profile["system"],
        output_config={"effort": "low"},
        messages=messages,
    )
    reply = extract_text(response)
    if not reply:
        logger.warning("空のレスポンス stop_reason=%s", response.stop_reason)
        return "うまく返答を作れませんでした。もう一度お願いします。"

    user_history[user_id] = (messages + [{"role": "assistant", "content": reply}])[-MAX_HISTORY:]

    return reply


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text

    try:
        reply_text = get_ai_response(user_id, user_message)
    except Exception:
        logger.exception("AI応答の生成に失敗しました")
        reply_text = "申し訳ありません、只今応答できませんでした。少し時間をおいてもう一度お試しください。"

    try:
        with ApiClient(line_config) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text[:4900])],
                )
            )
    except Exception:
        # 返信トークン期限切れなどで失敗しても webhook は 200 を返す（LINE の再送を防ぐ）
        logger.exception("LINEへの返信に失敗しました")


@app.route("/", methods=["GET"])
def health():
    return "LINE Bot 稼働中"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
