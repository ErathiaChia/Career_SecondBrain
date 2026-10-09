"""Local-first policy for the auditor's LLM client: local endpoints only unless
AUDITOR_CLOUD_OPTIN is set explicitly."""
from __future__ import annotations

import unittest
from unittest import mock

from auditor import openai_client
from auditor.config import OpenAIConfig, is_private_url


class _Cfg:
    def __init__(self, **kw):
        self.openai = OpenAIConfig(**kw)


class PrivateUrlTests(unittest.TestCase):
    def test_private_hosts(self):
        for url in ("http://localhost:11434/v1", "http://127.0.0.1:11434", "http://192.168.1.20:11434",
                    "http://10.0.0.5", "http://172.20.1.1:8080", "http://100.100.1.1:11434",
                    "http://mac.tailnet.ts.net:11434", "http://host.docker.internal:11434"):
            self.assertTrue(is_private_url(url), url)

    def test_public_hosts(self):
        for url in ("https://api.openai.com/v1", "http://8.8.8.8", "https://example.com/v1"):
            self.assertFalse(is_private_url(url), url)


class ClientPolicyTests(unittest.TestCase):
    def test_local_default_needs_no_key(self):
        with mock.patch.dict("os.environ", {}, clear=False), \
             mock.patch.object(openai_client, "OpenAI") as fake:
            openai_client.OpenAIClient(_Cfg(base_url="http://localhost:11434/v1", cloud_optin=False))
            fake.assert_called_once()
            self.assertEqual(fake.call_args.kwargs["base_url"], "http://localhost:11434/v1")

    def test_public_url_refused_without_optin(self):
        with mock.patch.object(openai_client, "OpenAI"):
            with self.assertRaises(RuntimeError):
                openai_client.OpenAIClient(_Cfg(base_url="https://api.openai.com/v1", cloud_optin=False))

    def test_optin_requires_key(self):
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}), \
             mock.patch.object(openai_client, "OpenAI"):
            with self.assertRaises(RuntimeError):
                openai_client.OpenAIClient(_Cfg(base_url="https://api.openai.com/v1", cloud_optin=True))

    def test_optin_with_key_allowed(self):
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}), \
             mock.patch.object(openai_client, "OpenAI") as fake:
            openai_client.OpenAIClient(_Cfg(base_url="https://api.openai.com/v1", cloud_optin=True))
            self.assertEqual(fake.call_args.kwargs["api_key"], "sk-test")


if __name__ == "__main__":
    unittest.main()
