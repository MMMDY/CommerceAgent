from src.orchestration.conversational_fallback import response_for


def test_social_chat_warmly_handles_positive_mood() -> None:
    response = response_for(intent="social_chat", content="我今天心情很好，你夸一夸我")

    assert "好心情" in response
    assert "阳光" in response


def test_fallback_stays_within_supported_commerce_scope() -> None:
    response = response_for(intent="unsupported_low_risk", content="给我讲一个长篇历史故事")

    assert "主要提供订单、物流、商品和售后政策服务" in response
