from __future__ import annotations

from src.telemetry.trace import TraceStore


def test_trace_store_removes_credentials_tokens_pii_and_hidden_reasoning() -> None:
    store = TraceStore()
    record = store.append(
        kind="tool_observed",
        payload={
            "api_key": "should-never-appear",
            "confirmation_token": "token-value",
            "reasoning": "private thought",
            "summary": "联系号码 13800138000",
            "nested": {"authorization": "Bearer should-never-appear"},
        },
    )
    serialized = str(record.payload)
    assert "should-never-appear" not in serialized
    assert "token-value" not in serialized
    assert "private thought" not in serialized
    assert "13800138000" not in serialized
    assert record.payload["summary"] == "联系号码 [PHONE_REDACTED]"
    assert record.payload_hash.startswith("sha256:")


def test_trace_store_is_append_only_and_returns_a_copy() -> None:
    store = TraceStore()
    store.append(kind="decision", payload={"type": "respond"})
    copied = store.records()
    copied[0].payload["type"] = "modified"
    assert store.records()[0].payload["type"] == "respond"


def test_trace_store_redacts_address_email_and_payment_values() -> None:
    record = TraceStore().append(
        kind="tool_observed",
        payload={
            "address": "上海市浦东新区测试路 20 号",
            "text": "邮件 a@example.com 卡 4111 1111 1111 1111",
        },
    )
    assert record.payload["address"] == "[REDACTED]"
    assert "a@example.com" not in record.payload["text"]
    assert "4111" not in record.payload["text"]
