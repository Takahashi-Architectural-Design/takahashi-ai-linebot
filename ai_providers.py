"""
はるかな AIエンジン抽象化レイヤー

AI基盤（Anthropic / OpenAI / Amazon Bedrock / Google Gemini）を
環境変数だけで差し替えられるようにするためのモジュール。

    AI_PROVIDER=anthropic   # anthropic | openai | bedrock | gemini

アプリ側はこのモジュールの `generate()` だけを呼ぶ。各SDKのimportは
実際に使うときまで遅延させているので、使わない基盤のSDKを
インストールする必要はない。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Type

# 会話メッセージの共通フォーマット
#   {"role": "user" | "assistant", "content": "本文"}
Message = Dict[str, str]

DEFAULT_MAX_TOKENS = int(os.environ.get("AI_MAX_TOKENS", "1024"))


class ProviderError(RuntimeError):
    """AI基盤の設定不足・SDK未インストールなど、運用者向けのエラー。"""


class AIProvider:
    """AI基盤の共通インターフェース。"""

    key = ""
    label = ""
    # モデルIDを指定する環境変数名
    model_env = ""
    # 既定モデル（Noneの場合は model_env での明示指定が必須）
    default_model: Optional[str] = None
    # SDKのpipパッケージ名（エラーメッセージ用）
    package = ""

    def __init__(self, model: Optional[str] = None):
        self.model = model or os.environ.get(self.model_env) or self.default_model
        if not self.model:
            raise ProviderError(
                f"{self.label} を使うには環境変数 {self.model_env} にモデルIDを設定してください。"
                f"（例は docs/multi-ai-architecture.md を参照）"
            )
        self._client = None

    # --- 各基盤で実装 -------------------------------------------------
    def _build_client(self):
        raise NotImplementedError

    def generate(self, system: str, messages: List[Message], max_tokens: int) -> str:
        raise NotImplementedError

    # --- 共通 ---------------------------------------------------------
    @property
    def client(self):
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _import(self, module: str):
        """SDKを遅延importし、未インストールなら分かりやすいエラーにする。"""
        try:
            return __import__(module, fromlist=["_"])
        except ImportError as exc:  # pragma: no cover - 環境依存
            raise ProviderError(
                f"{self.label} を使うには `pip install {self.package}` が必要です。({exc})"
            ) from exc

    def _env(self, name: str) -> str:
        value = os.environ.get(name)
        if not value:
            raise ProviderError(
                f"{self.label} を使うには環境変数 {name} を設定してください。"
            )
        return value

    def describe(self) -> str:
        return f"{self.label} / {self.model}"


class AnthropicProvider(AIProvider):
    key = "anthropic"
    label = "Anthropic Claude"
    model_env = "ANTHROPIC_MODEL"
    default_model = "claude-sonnet-4-6"
    package = "anthropic"

    def _build_client(self):
        anthropic = self._import("anthropic")
        return anthropic.Anthropic(api_key=self._env("ANTHROPIC_API_KEY"))

    def generate(self, system: str, messages: List[Message], max_tokens: int) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )


class OpenAIProvider(AIProvider):
    key = "openai"
    label = "OpenAI"
    model_env = "OPENAI_MODEL"
    package = "openai"

    # 新しいモデルは max_completion_tokens、旧モデル／互換エンドポイントは
    # max_tokens。最初の呼び出しで通った方を覚える。
    _token_param = "max_completion_tokens"

    def _build_client(self):
        openai = self._import("openai")
        return openai.OpenAI(
            api_key=self._env("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL") or None,
        )

    def generate(self, system: str, messages: List[Message], max_tokens: int) -> str:
        payload = [{"role": "system", "content": system}] + list(messages)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=payload,
                **{self._token_param: max_tokens},
            )
        except Exception as exc:  # 互換エンドポイント向けのフォールバック
            if not self._is_token_param_error(exc):
                raise
            self._token_param = (
                "max_tokens" if self._token_param == "max_completion_tokens"
                else "max_completion_tokens"
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=payload,
                **{self._token_param: max_tokens},
            )
        return response.choices[0].message.content or ""

    @staticmethod
    def _is_token_param_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "max_tokens" in text or "max_completion_tokens" in text


class BedrockProvider(AIProvider):
    """Amazon Bedrock（Converse API）。

    Converse APIはモデル横断の共通インターフェースなので、
    Amazon Nova でも Bedrock 上の Claude でも同じコードで動く。
    AWSをすでに使っている顧客向けの基盤。
    """

    key = "bedrock"
    label = "Amazon Bedrock"
    model_env = "BEDROCK_MODEL"
    package = "boto3"

    def _build_client(self):
        boto3 = self._import("boto3")
        return boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "ap-northeast-1"),
        )

    def generate(self, system: str, messages: List[Message], max_tokens: int) -> str:
        response = self.client.converse(
            modelId=self.model,
            system=[{"text": system}],
            messages=[
                {"role": m["role"], "content": [{"text": m["content"]}]}
                for m in messages
            ],
            inferenceConfig={"maxTokens": max_tokens},
        )
        blocks = response["output"]["message"]["content"]
        return "".join(b["text"] for b in blocks if "text" in b)


class GeminiProvider(AIProvider):
    key = "gemini"
    label = "Google Gemini"
    model_env = "GEMINI_MODEL"
    package = "google-genai"

    def _build_client(self):
        genai = self._import("google.genai")
        return genai.Client(api_key=self._env("GEMINI_API_KEY"))

    def generate(self, system: str, messages: List[Message], max_tokens: int) -> str:
        types = self._import("google.genai.types")
        contents = [
            types.Content(
                # Geminiでは assistant ロールを "model" と呼ぶ
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in messages
        ]
        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )
        return response.text or ""


PROVIDERS: Dict[str, Type[AIProvider]] = {
    cls.key: cls
    for cls in (AnthropicProvider, OpenAIProvider, BedrockProvider, GeminiProvider)
}

DEFAULT_PROVIDER = os.environ.get("AI_PROVIDER", "anthropic").strip().lower()

# 生成済みプロバイダのキャッシュ（SDKクライアントを毎回作らない）
_cache: Dict[tuple, AIProvider] = {}


def available_providers() -> List[str]:
    return list(PROVIDERS)


def get_provider(key: Optional[str] = None, model: Optional[str] = None) -> AIProvider:
    """基盤名（省略時は AI_PROVIDER）からプロバイダを取得する。"""
    key = (key or DEFAULT_PROVIDER).strip().lower()
    if key not in PROVIDERS:
        raise ProviderError(
            f"未対応のAI基盤です: {key}（利用可能: {', '.join(PROVIDERS)}）"
        )
    cache_key = (key, model)
    if cache_key not in _cache:
        _cache[cache_key] = PROVIDERS[key](model=model)
    return _cache[cache_key]


def generate(
    system: str,
    messages: List[Message],
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """設定された（または指定された）AI基盤で応答を生成する。"""
    return get_provider(provider, model).generate(system, messages, max_tokens)
