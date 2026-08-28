"""
はるかな - 髙橋建築設計事務所 AI社員 LINE Bot

AI社員（ハル・松陰・土方など）が LINE で応答する。名前を送ると担当が
切り替わる。AIエンジンは Anthropic / OpenAI / Amazon Bedrock / Gemini から
環境変数（AI_PROVIDER）で選択でき、LINE から `エンジン:openai` のように
切り替えることもできる。
"""

import os

from flask import Flask, jsonify, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

import agents
import ai_providers

app = Flask(__name__)

# 環境変数から取得
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]

handler = WebhookHandler(LINE_CHANNEL_SECRET)
line_config = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

# 会話履歴の保持件数（user+assistantで1往復2件）
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "20"))
# LINEのテキストメッセージ上限
LINE_TEXT_LIMIT = 4900

# ユーザーごとの状態（簡易版・プロセス内メモリ）
user_agent = {}      # user_id -> AI社員キー
user_engine = {}     # user_id -> AI基盤キー（未設定なら既定）
user_history = {}    # (user_id, AI社員キー) -> メッセージ履歴

ENGINE_PREFIXES = ("エンジン", "engine", "ＡＩ基盤", "ai基盤")
ENGINE_SEPARATORS = ":：= 　"
RESET_WORDS = ("リセット", "reset", "履歴クリア")
ROSTER_WORDS = ("メンバー", "社員", "一覧", "members")


def resolve_engine(user_id: str, agent: dict):
    """使用するAI基盤とモデルを決める。

    優先順位: ユーザーがLINEで切り替えた基盤 > AI社員ごとの指定 > 環境変数の既定。
    """
    if user_id in user_engine:
        return user_engine[user_id], None
    return agent.get("provider"), agent.get("model")


def engine_command(user_id: str, message: str):
    """`エンジン` / `エンジン:openai` を処理する。対象外なら None。"""
    stripped = message.strip()
    lowered = stripped.lower()
    for prefix in ENGINE_PREFIXES:
        if not lowered.startswith(prefix.lower()):
            continue
        rest = stripped[len(prefix):]
        # 「エンジン」単体、または「エンジン:openai」のように区切り文字が続く場合のみ
        if rest and rest[0] not in ENGINE_SEPARATORS:
            continue
        argument = rest.lstrip(ENGINE_SEPARATORS).strip().lower()
        if not argument:
            current = user_engine.get(user_id, ai_providers.DEFAULT_PROVIDER)
            return (
                f"🤖 現在のAI基盤：{current}\n"
                f"切替可能：{', '.join(ai_providers.available_providers())}\n"
                "例）エンジン:openai"
            )
        if argument not in ai_providers.available_providers():
            return (
                f"⚠️ 「{argument}」は未対応のAI基盤です。\n"
                f"利用可能：{', '.join(ai_providers.available_providers())}"
            )
        user_engine[user_id] = argument
        try:
            described = ai_providers.get_provider(argument).describe()
        except ai_providers.ProviderError as exc:
            del user_engine[user_id]
            return f"⚠️ {argument} に切り替えられません。\n{exc}"
        return f"✅ AI基盤を切り替えました：{described}"
    return None


def get_ai_response(user_id: str, user_message: str) -> str:
    text = user_message.strip()

    # AI社員の切り替え
    switched = agents.resolve_agent(text)
    if switched:
        user_agent[user_id] = switched
        user_history.pop((user_id, switched), None)
        agent = agents.get_agent(switched)
        role = f"（{agent['role']}）" if agent["role"] else ""
        return f"✅ {agent['name']}{role}に切り替えました。\n何でもどうぞ。"

    # AI基盤の切り替え・確認
    engine_reply = engine_command(user_id, text)
    if engine_reply:
        return engine_reply

    if text in ROSTER_WORDS:
        return f"👥 AI社員一覧\n{agents.roster()}"

    current = user_agent.get(user_id, agents.DEFAULT_AGENT)
    agent = agents.get_agent(current)

    if text in RESET_WORDS:
        user_history.pop((user_id, current), None)
        return f"🧹 {agent['name']}との会話履歴をリセットしました。"

    # 会話履歴
    key = (user_id, current)
    history = user_history.get(key, [])
    history = history + [{"role": "user", "content": user_message}]
    if len(history) > HISTORY_LIMIT:
        history = history[-HISTORY_LIMIT:]

    provider, model = resolve_engine(user_id, agent)
    try:
        reply = ai_providers.generate(
            system=agent["system"],
            messages=history,
            provider=provider,
            model=model,
        )
    except ai_providers.ProviderError as exc:
        app.logger.error("AI基盤の設定エラー: %s", exc)
        return f"⚠️ AI基盤の設定に問題があります。\n{exc}"
    except Exception as exc:  # APIエラーでLINEに応答が返らないのを防ぐ
        app.logger.exception("AI応答の生成に失敗しました")
        return f"⚠️ AIの応答に失敗しました。少し時間をおいて試してください。\n（{type(exc).__name__}）"

    if not reply.strip():
        return "⚠️ AIから空の応答が返りました。もう一度お試しください。"

    history.append({"role": "assistant", "content": reply})
    user_history[key] = history[-HISTORY_LIMIT:]

    return reply[:LINE_TEXT_LIMIT]


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

    reply_text = get_ai_response(user_id, user_message)

    with ApiClient(line_config) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )


@app.route("/", methods=["GET"])
def health():
    return jsonify(
        status="ok",
        service="はるかな LINE Bot",
        ai_provider=ai_providers.DEFAULT_PROVIDER,
        available_providers=ai_providers.available_providers(),
        agents=list(agents.AGENTS),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
