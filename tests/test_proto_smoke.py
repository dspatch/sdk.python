"""Verify generated proto types are importable and constructible."""

from dspatch.generated.dspatch_router_pb2 import (
    RegisterRequest,
    RegisterResponse,
    EventStreamRequest,
    RouterEvent,
    UserInputEvent,
    OutputEvent,
    MessageOutput,
    CompleteTurnRequest,
    TalkToRpcRequest,
    TalkToRpcResponse,
    InquireRpcRequest,
    InquireRpcResponse,
    Ack,
)


def test_register_request():
    req = RegisterRequest(name="lead", role="host", capabilities=["talk_to"])
    assert req.name == "lead"
    assert req.role == "host"
    assert req.capabilities == ["talk_to"]


def test_router_event_user_input():
    event = RouterEvent(
        instance_id="lead-0",
        turn_id="turn-1",
        user_input=UserInputEvent(text="hello", history=[]),
    )
    assert event.instance_id == "lead-0"
    assert event.HasField("user_input")
    assert event.user_input.text == "hello"


def test_output_event_message():
    output = OutputEvent(
        instance_id="lead-0",
        message=MessageOutput(
            id="msg-1",
            role="assistant",
            content="Hello",
            is_delta=False,
        ),
    )
    assert output.HasField("message")
    assert output.message.content == "Hello"


def test_talk_to_response_oneof():
    from dspatch.generated.dspatch_router_pb2 import TalkToSuccess, InquiryInterrupt

    # Success variant
    resp = TalkToRpcResponse(
        success=TalkToSuccess(
            request_id="req-1", response="done", conversation_id="conv-1"
        )
    )
    assert resp.HasField("success")

    # Interrupt variant
    resp2 = TalkToRpcResponse(
        interrupt=InquiryInterrupt(
            inquiry_id="inq-1",
            from_agent="coder",
            content_markdown="Need help",
            suggestions=["Yes", "No"],
            priority="normal",
        )
    )
    assert resp2.HasField("interrupt")
