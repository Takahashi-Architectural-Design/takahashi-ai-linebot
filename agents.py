"""
はるかな AI社員（エージェント）定義

AI社員のプロフィールはコードから切り離してある。顧客ごとの
チーム構成は環境変数で差し替えられる:

    HARUKANA_AGENTS_FILE=/etc/harukana/agents.json
    HARUKANA_AGENTS_JSON='{"default": "ハル", "agents": {...}}'

JSONの形式（agentsの各値）:
    {
      "name": "一条ハル",          # 表示名
      "role": "個人秘書",          # 肩書
      "system": "システムプロンプト",
      "aliases": ["はる", "haru"], # 呼び出し用の別名（任意）
      "provider": "openai",        # このAI社員だけ別基盤を使う場合（任意）
      "model": "..."               # 同上（任意）
    }
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional, Tuple

Agent = Dict[str, object]

# 髙橋建築設計事務所の標準チーム（デフォルト）
DEFAULT_AGENTS: Dict[str, Agent] = {
    "ハル": {
        "name": "一条ハル",
        "role": "個人秘書",
        "aliases": ["はる", "haru"],
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
        "aliases": ["りんりん"],
        "system": (
            "あなたは髙橋裕昭社長専属の全権限秘書「リンリン」です。"
            "会社・経営・個人すべての業務をサポートします。"
            "LINEで話しかけられています。簡潔に、スマホで読みやすい返答をしてください。"
        ),
    },
    "土方": {
        "name": "土方歳三",
        "role": "監理室長",
        "aliases": ["ひじかた", "土方歳三"],
        "system": (
            "あなたは有限会社髙橋建築設計事務所の監理室長「土方歳三」です。"
            "工事監理・現場管理・監理写真AIが専門です。"
            "LINEで話しかけられています。簡潔に、スマホで読みやすい返答をしてください。"
        ),
    },
    "松陰": {
        "name": "吉田松陰",
        "role": "JC室長",
        "aliases": ["しょういん", "吉田松陰"],
        "system": (
            "あなたは有限会社髙橋建築設計事務所のJC担当「吉田松陰」です。"
            "仙台青年会議所の活動・議案・アワードをサポートします。"
            "LINEで話しかけられています。簡潔に、スマホで読みやすい返答をしてください。"
        ),
    },
    "龍馬": {
        "name": "坂本龍馬",
        "role": "経営戦略室長",
        "aliases": ["りょうま", "坂本龍馬"],
        "system": (
            "あなたは有限会社髙橋建築設計事務所の経営戦略室長「坂本龍馬」です。"
            "経営戦略・入札・新規事業をサポートします。"
            "LINEで話しかけられています。簡潔に、スマホで読みやすい返答をしてください。"
        ),
    },
}

DEFAULT_AGENT_KEY = "ハル"


class AgentConfigError(ValueError):
    """agents.json の内容が不正なときのエラー。"""


def _normalize(agents: Dict[str, Agent]) -> Dict[str, Agent]:
    if not agents:
        raise AgentConfigError("AI社員が1人も定義されていません。")
    normalized: Dict[str, Agent] = {}
    for key, agent in agents.items():
        if not isinstance(agent, dict):
            raise AgentConfigError(f"AI社員「{key}」の定義がオブジェクトではありません。")
        if not agent.get("system"):
            raise AgentConfigError(f"AI社員「{key}」に system（人格定義）がありません。")
        normalized[key] = {
            "name": agent.get("name", key),
            "role": agent.get("role", ""),
            "system": agent["system"],
            "aliases": list(agent.get("aliases", [])),
            "provider": agent.get("provider"),
            "model": agent.get("model"),
        }
    return normalized


def load_agents() -> Tuple[Dict[str, Agent], str]:
    """環境変数の設定があればそれを、なければ標準チームを読み込む。"""
    raw: Optional[str] = os.environ.get("HARUKANA_AGENTS_JSON")
    path = os.environ.get("HARUKANA_AGENTS_FILE")
    if not raw and path:
        with open(path, encoding="utf-8") as fp:
            raw = fp.read()

    if not raw:
        return _normalize(DEFAULT_AGENTS), DEFAULT_AGENT_KEY

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AgentConfigError(f"AI社員定義のJSONを読み込めません: {exc}") from exc

    if not isinstance(data, dict):
        raise AgentConfigError("AI社員定義のJSONはオブジェクトである必要があります。")

    agents = data.get("agents", data)
    normalized = _normalize(agents)
    default_key = data.get("default") if isinstance(data.get("default"), str) else None
    if default_key not in normalized:
        default_key = next(iter(normalized))
    return normalized, default_key


AGENTS, DEFAULT_AGENT = load_agents()


def resolve_agent(text: str) -> Optional[str]:
    """入力がAI社員の呼び出し（キー・表示名・別名）ならそのキーを返す。"""
    needle = text.strip()
    if not needle:
        return None
    if needle in AGENTS:
        return needle
    lowered = needle.lower()
    for key, agent in AGENTS.items():
        if lowered == str(agent["name"]).lower():
            return key
        if any(lowered == str(alias).lower() for alias in agent["aliases"]):
            return key
    return None


def get_agent(key: str) -> Agent:
    return AGENTS[key]


def roster() -> str:
    """AI社員一覧を人が読める形で返す。"""
    return "\n".join(
        f"・{key}（{agent['name']}／{agent['role']}）" if agent["role"]
        else f"・{key}（{agent['name']}）"
        for key, agent in AGENTS.items()
    )
