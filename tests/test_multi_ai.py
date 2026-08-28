"""マルチAI基盤対応のテスト（各社SDKはスタブに差し替えて実行する）。"""

import importlib
import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agents  # noqa: E402
import ai_providers  # noqa: E402


class StubModule(types.ModuleType):
    def __init__(self, name, **attrs):
        super().__init__(name)
        for key, value in attrs.items():
            setattr(self, key, value)


def install_module(test_case, name, module):
    """テストの間だけ sys.modules にスタブSDKを入れる。"""
    patcher = mock.patch.dict(sys.modules, {name: module})
    patcher.start()
    test_case.addCleanup(patcher.stop)
    return module


class AgentRegistryTest(unittest.TestCase):
    def tearDown(self):
        importlib.reload(agents)

    def test_default_team_is_loaded(self):
        self.assertEqual(agents.DEFAULT_AGENT, "ハル")
        self.assertIn("松陰", agents.AGENTS)

    def test_resolve_by_key_display_name_and_alias(self):
        self.assertEqual(agents.resolve_agent("松陰"), "松陰")
        self.assertEqual(agents.resolve_agent("坂本龍馬"), "龍馬")
        self.assertEqual(agents.resolve_agent("ひじかた"), "土方")
        self.assertIsNone(agents.resolve_agent("見積もりを出して"))

    def test_agents_can_be_replaced_by_env(self):
        config = {
            "default": "設計",
            "agents": {
                "設計": {
                    "name": "設計アシスタント",
                    "role": "意匠設計",
                    "system": "あなたは意匠設計担当です。",
                    "provider": "openai",
                    "model": "test-model",
                }
            },
        }
        with mock.patch.dict(os.environ, {"HARUKANA_AGENTS_JSON": json.dumps(config)}):
            importlib.reload(agents)
            self.assertEqual(list(agents.AGENTS), ["設計"])
            self.assertEqual(agents.DEFAULT_AGENT, "設計")
            self.assertEqual(agents.get_agent("設計")["provider"], "openai")

    def test_agent_without_system_prompt_is_rejected(self):
        with mock.patch.dict(
            os.environ, {"HARUKANA_AGENTS_JSON": json.dumps({"agents": {"X": {}}})}
        ):
            # reload後はクラスオブジェクトが作り直されるため基底の ValueError で判定する
            with self.assertRaises(ValueError):
                importlib.reload(agents)


class ProviderRegistryTest(unittest.TestCase):
    def setUp(self):
        ai_providers._cache.clear()

    def test_all_four_engines_are_registered(self):
        self.assertEqual(
            sorted(ai_providers.available_providers()),
            ["anthropic", "bedrock", "gemini", "openai"],
        )

    def test_unknown_engine_raises(self):
        with self.assertRaises(ai_providers.ProviderError):
            ai_providers.get_provider("watson")

    def test_missing_model_id_raises_with_env_var_name(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ai_providers.ProviderError) as ctx:
                ai_providers.get_provider("openai")
        self.assertIn("OPENAI_MODEL", str(ctx.exception))

    def test_missing_api_key_raises(self):
        install_module(self, "anthropic", StubModule("anthropic", Anthropic=lambda **kw: None))
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = ai_providers.get_provider("anthropic")
            with self.assertRaises(ai_providers.ProviderError) as ctx:
                _ = provider.client
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_missing_sdk_raises_with_pip_hint(self):
        with mock.patch.dict(sys.modules, {"boto3": None}):
            with mock.patch.dict(os.environ, {"BEDROCK_MODEL": "amazon.nova-pro-v1:0"}):
                provider = ai_providers.get_provider("bedrock")
                with self.assertRaises(ai_providers.ProviderError) as ctx:
                    _ = provider.client
        self.assertIn("pip install boto3", str(ctx.exception))

    def test_provider_instances_are_cached(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_MODEL": "claude-sonnet-4-6"}):
            first = ai_providers.get_provider("anthropic")
            second = ai_providers.get_provider("anthropic")
        self.assertIs(first, second)


class AnthropicProviderTest(unittest.TestCase):
    def setUp(self):
        ai_providers._cache.clear()
        self.captured = {}

        text_block = types.SimpleNamespace(type="text", text="こんにちは、ハルです。")
        thinking_block = types.SimpleNamespace(type="thinking", thinking="…")

        def create(**kwargs):
            self.captured.update(kwargs)
            return types.SimpleNamespace(content=[thinking_block, text_block])

        client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
        install_module(
            self, "anthropic", StubModule("anthropic", Anthropic=lambda **kw: client)
        )

    def test_generate_returns_text_blocks_only(self):
        with mock.patch.dict(
            os.environ, {"ANTHROPIC_API_KEY": "k", "ANTHROPIC_MODEL": "claude-sonnet-4-6"}
        ):
            reply = ai_providers.generate(
                "あなたは秘書です。",
                [{"role": "user", "content": "おはよう"}],
                provider="anthropic",
                max_tokens=256,
            )
        self.assertEqual(reply, "こんにちは、ハルです。")
        self.assertEqual(self.captured["model"], "claude-sonnet-4-6")
        self.assertEqual(self.captured["system"], "あなたは秘書です。")
        self.assertEqual(self.captured["max_tokens"], 256)


class OpenAIProviderTest(unittest.TestCase):
    def setUp(self):
        ai_providers._cache.clear()
        self.calls = []

    def _install(self, create):
        client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
        )
        install_module(self, "openai", StubModule("openai", OpenAI=lambda **kw: client))

    @staticmethod
    def _reply(text):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))]
        )

    def test_system_prompt_becomes_first_message(self):
        def create(**kwargs):
            self.calls.append(kwargs)
            return self._reply("OpenAIからの返答")

        self._install(create)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k", "OPENAI_MODEL": "m"}):
            reply = ai_providers.generate(
                "あなたは秘書です。",
                [{"role": "user", "content": "おはよう"}],
                provider="openai",
            )
        self.assertEqual(reply, "OpenAIからの返答")
        self.assertEqual(
            self.calls[0]["messages"][0],
            {"role": "system", "content": "あなたは秘書です。"},
        )
        self.assertIn("max_completion_tokens", self.calls[0])

    def test_falls_back_to_max_tokens_on_compatible_endpoints(self):
        def create(**kwargs):
            self.calls.append(kwargs)
            if "max_completion_tokens" in kwargs:
                raise ValueError("Unsupported parameter: 'max_completion_tokens'")
            return self._reply("互換エンドポイントからの返答")

        self._install(create)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k", "OPENAI_MODEL": "m"}):
            reply = ai_providers.generate(
                "s", [{"role": "user", "content": "hi"}], provider="openai"
            )
        self.assertEqual(reply, "互換エンドポイントからの返答")
        self.assertEqual(len(self.calls), 2)
        self.assertIn("max_tokens", self.calls[1])

    def test_unrelated_errors_are_not_retried(self):
        def create(**kwargs):
            self.calls.append(kwargs)
            raise ValueError("rate limit exceeded")

        self._install(create)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k", "OPENAI_MODEL": "m"}):
            with self.assertRaises(ValueError):
                ai_providers.generate(
                    "s", [{"role": "user", "content": "hi"}], provider="openai"
                )
        self.assertEqual(len(self.calls), 1)


class BedrockProviderTest(unittest.TestCase):
    def setUp(self):
        ai_providers._cache.clear()
        self.captured = {}

        def converse(**kwargs):
            self.captured.update(kwargs)
            return {"output": {"message": {"content": [{"text": "Bedrockからの返答"}]}}}

        def client(service, **kwargs):
            self.captured["service"] = service
            self.captured["region_name"] = kwargs.get("region_name")
            return types.SimpleNamespace(converse=converse)

        install_module(self, "boto3", StubModule("boto3", client=client))

    def test_converse_payload_shape(self):
        with mock.patch.dict(
            os.environ,
            {"BEDROCK_MODEL": "apac.amazon.nova-pro-v1:0", "AWS_REGION": "ap-northeast-1"},
        ):
            reply = ai_providers.generate(
                "あなたは秘書です。",
                [
                    {"role": "user", "content": "おはよう"},
                    {"role": "assistant", "content": "おはようございます"},
                ],
                provider="bedrock",
                max_tokens=512,
            )
        self.assertEqual(reply, "Bedrockからの返答")
        self.assertEqual(self.captured["service"], "bedrock-runtime")
        self.assertEqual(self.captured["region_name"], "ap-northeast-1")
        self.assertEqual(self.captured["system"], [{"text": "あなたは秘書です。"}])
        self.assertEqual(
            self.captured["messages"],
            [
                {"role": "user", "content": [{"text": "おはよう"}]},
                {"role": "assistant", "content": [{"text": "おはようございます"}]},
            ],
        )
        self.assertEqual(self.captured["inferenceConfig"], {"maxTokens": 512})


class GeminiProviderTest(unittest.TestCase):
    def setUp(self):
        ai_providers._cache.clear()
        self.captured = {}

        def generate_content(**kwargs):
            self.captured.update(kwargs)
            return types.SimpleNamespace(text="Geminiからの返答")

        client = types.SimpleNamespace(
            models=types.SimpleNamespace(generate_content=generate_content)
        )

        class Part:
            def __init__(self, text):
                self.text = text

            @classmethod
            def from_text(cls, text):
                return cls(text)

        class Content:
            def __init__(self, role, parts):
                self.role = role
                self.parts = parts

        stub_types = StubModule(
            "google.genai.types",
            Part=Part,
            Content=Content,
            GenerateContentConfig=lambda **kw: kw,
        )
        stub_genai = StubModule(
            "google.genai", Client=lambda **kw: client, types=stub_types
        )
        google_pkg = StubModule("google", genai=stub_genai)
        install_module(self, "google", google_pkg)
        install_module(self, "google.genai", stub_genai)
        install_module(self, "google.genai.types", stub_types)

    def test_assistant_role_is_mapped_to_model(self):
        with mock.patch.dict(
            os.environ, {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "gemini-test"}
        ):
            reply = ai_providers.generate(
                "あなたは秘書です。",
                [
                    {"role": "user", "content": "おはよう"},
                    {"role": "assistant", "content": "おはようございます"},
                ],
                provider="gemini",
            )
        self.assertEqual(reply, "Geminiからの返答")
        self.assertEqual(
            [c.role for c in self.captured["contents"]], ["user", "model"]
        )
        self.assertEqual(
            self.captured["config"]["system_instruction"], "あなたは秘書です。"
        )


if __name__ == "__main__":
    unittest.main()
