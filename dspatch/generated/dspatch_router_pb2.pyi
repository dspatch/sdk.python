from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RegisterRequest(_message.Message):
    __slots__ = ("name", "role", "capabilities")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    name: str
    role: str
    capabilities: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, name: _Optional[str] = ..., role: _Optional[str] = ..., capabilities: _Optional[_Iterable[str]] = ...) -> None: ...

class RegisterResponse(_message.Message):
    __slots__ = ("ok", "router_version")
    OK_FIELD_NUMBER: _ClassVar[int]
    ROUTER_VERSION_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    router_version: str
    def __init__(self, ok: bool = ..., router_version: _Optional[str] = ...) -> None: ...

class Ack(_message.Message):
    __slots__ = ("ok",)
    OK_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    def __init__(self, ok: bool = ...) -> None: ...

class EventStreamRequest(_message.Message):
    __slots__ = ("name", "instance_id")
    NAME_FIELD_NUMBER: _ClassVar[int]
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    name: str
    instance_id: str
    def __init__(self, name: _Optional[str] = ..., instance_id: _Optional[str] = ...) -> None: ...

class RouterEvent(_message.Message):
    __slots__ = ("instance_id", "turn_id", "user_input", "talk_to_request", "inquiry_request", "drain", "terminate", "interrupt")
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    USER_INPUT_FIELD_NUMBER: _ClassVar[int]
    TALK_TO_REQUEST_FIELD_NUMBER: _ClassVar[int]
    INQUIRY_REQUEST_FIELD_NUMBER: _ClassVar[int]
    DRAIN_FIELD_NUMBER: _ClassVar[int]
    TERMINATE_FIELD_NUMBER: _ClassVar[int]
    INTERRUPT_FIELD_NUMBER: _ClassVar[int]
    instance_id: str
    turn_id: str
    user_input: UserInputEvent
    talk_to_request: TalkToRequestEvent
    inquiry_request: InquiryRequestEvent
    drain: DrainSignal
    terminate: TerminateSignal
    interrupt: InterruptSignal
    def __init__(self, instance_id: _Optional[str] = ..., turn_id: _Optional[str] = ..., user_input: _Optional[_Union[UserInputEvent, _Mapping]] = ..., talk_to_request: _Optional[_Union[TalkToRequestEvent, _Mapping]] = ..., inquiry_request: _Optional[_Union[InquiryRequestEvent, _Mapping]] = ..., drain: _Optional[_Union[DrainSignal, _Mapping]] = ..., terminate: _Optional[_Union[TerminateSignal, _Mapping]] = ..., interrupt: _Optional[_Union[InterruptSignal, _Mapping]] = ...) -> None: ...

class UserInputEvent(_message.Message):
    __slots__ = ("text", "history")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    HISTORY_FIELD_NUMBER: _ClassVar[int]
    text: str
    history: _containers.RepeatedCompositeFieldContainer[HistoryMessage]
    def __init__(self, text: _Optional[str] = ..., history: _Optional[_Iterable[_Union[HistoryMessage, _Mapping]]] = ...) -> None: ...

class TalkToRequestEvent(_message.Message):
    __slots__ = ("request_id", "caller_agent", "text")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    CALLER_AGENT_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    caller_agent: str
    text: str
    def __init__(self, request_id: _Optional[str] = ..., caller_agent: _Optional[str] = ..., text: _Optional[str] = ...) -> None: ...

class InquiryRequestEvent(_message.Message):
    __slots__ = ("inquiry_id", "from_agent", "content_markdown", "suggestions", "priority")
    INQUIRY_ID_FIELD_NUMBER: _ClassVar[int]
    FROM_AGENT_FIELD_NUMBER: _ClassVar[int]
    CONTENT_MARKDOWN_FIELD_NUMBER: _ClassVar[int]
    SUGGESTIONS_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    inquiry_id: str
    from_agent: str
    content_markdown: str
    suggestions: _containers.RepeatedScalarFieldContainer[str]
    priority: str
    def __init__(self, inquiry_id: _Optional[str] = ..., from_agent: _Optional[str] = ..., content_markdown: _Optional[str] = ..., suggestions: _Optional[_Iterable[str]] = ..., priority: _Optional[str] = ...) -> None: ...

class HistoryMessage(_message.Message):
    __slots__ = ("id", "role", "content")
    ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    id: str
    role: str
    content: str
    def __init__(self, id: _Optional[str] = ..., role: _Optional[str] = ..., content: _Optional[str] = ...) -> None: ...

class DrainSignal(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class TerminateSignal(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class InterruptSignal(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class OutputEvent(_message.Message):
    __slots__ = ("instance_id", "message", "activity", "log", "usage", "files", "prompt_received")
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ACTIVITY_FIELD_NUMBER: _ClassVar[int]
    LOG_FIELD_NUMBER: _ClassVar[int]
    USAGE_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    PROMPT_RECEIVED_FIELD_NUMBER: _ClassVar[int]
    instance_id: str
    message: MessageOutput
    activity: ActivityOutput
    log: LogOutput
    usage: UsageOutput
    files: FilesOutput
    prompt_received: PromptReceivedOutput
    def __init__(self, instance_id: _Optional[str] = ..., message: _Optional[_Union[MessageOutput, _Mapping]] = ..., activity: _Optional[_Union[ActivityOutput, _Mapping]] = ..., log: _Optional[_Union[LogOutput, _Mapping]] = ..., usage: _Optional[_Union[UsageOutput, _Mapping]] = ..., files: _Optional[_Union[FilesOutput, _Mapping]] = ..., prompt_received: _Optional[_Union[PromptReceivedOutput, _Mapping]] = ...) -> None: ...

class MessageOutput(_message.Message):
    __slots__ = ("id", "role", "content", "is_delta", "model", "input_tokens", "output_tokens", "sender_name")
    ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IS_DELTA_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    INPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    SENDER_NAME_FIELD_NUMBER: _ClassVar[int]
    id: str
    role: str
    content: str
    is_delta: bool
    model: str
    input_tokens: int
    output_tokens: int
    sender_name: str
    def __init__(self, id: _Optional[str] = ..., role: _Optional[str] = ..., content: _Optional[str] = ..., is_delta: bool = ..., model: _Optional[str] = ..., input_tokens: _Optional[int] = ..., output_tokens: _Optional[int] = ..., sender_name: _Optional[str] = ...) -> None: ...

class ActivityOutput(_message.Message):
    __slots__ = ("id", "event_type", "content", "is_delta", "data")
    ID_FIELD_NUMBER: _ClassVar[int]
    EVENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IS_DELTA_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    id: str
    event_type: str
    content: str
    is_delta: bool
    data: str
    def __init__(self, id: _Optional[str] = ..., event_type: _Optional[str] = ..., content: _Optional[str] = ..., is_delta: bool = ..., data: _Optional[str] = ...) -> None: ...

class LogOutput(_message.Message):
    __slots__ = ("level", "message")
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    level: str
    message: str
    def __init__(self, level: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...

class UsageOutput(_message.Message):
    __slots__ = ("model", "input_tokens", "output_tokens", "cost_usd")
    MODEL_FIELD_NUMBER: _ClassVar[int]
    INPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    COST_USD_FIELD_NUMBER: _ClassVar[int]
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    def __init__(self, model: _Optional[str] = ..., input_tokens: _Optional[int] = ..., output_tokens: _Optional[int] = ..., cost_usd: _Optional[float] = ...) -> None: ...

class FilesOutput(_message.Message):
    __slots__ = ("files",)
    FILES_FIELD_NUMBER: _ClassVar[int]
    files: _containers.RepeatedCompositeFieldContainer[FileEntry]
    def __init__(self, files: _Optional[_Iterable[_Union[FileEntry, _Mapping]]] = ...) -> None: ...

class FileEntry(_message.Message):
    __slots__ = ("path", "action")
    PATH_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    path: str
    action: str
    def __init__(self, path: _Optional[str] = ..., action: _Optional[str] = ...) -> None: ...

class PromptReceivedOutput(_message.Message):
    __slots__ = ("content", "sender_name")
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    SENDER_NAME_FIELD_NUMBER: _ClassVar[int]
    content: str
    sender_name: str
    def __init__(self, content: _Optional[str] = ..., sender_name: _Optional[str] = ...) -> None: ...

class CompleteTurnRequest(_message.Message):
    __slots__ = ("instance_id", "turn_id", "result")
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    instance_id: str
    turn_id: str
    result: str
    def __init__(self, instance_id: _Optional[str] = ..., turn_id: _Optional[str] = ..., result: _Optional[str] = ...) -> None: ...

class TalkToRpcRequest(_message.Message):
    __slots__ = ("instance_id", "target_agent", "text", "continue_conversation")
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_AGENT_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    CONTINUE_CONVERSATION_FIELD_NUMBER: _ClassVar[int]
    instance_id: str
    target_agent: str
    text: str
    continue_conversation: bool
    def __init__(self, instance_id: _Optional[str] = ..., target_agent: _Optional[str] = ..., text: _Optional[str] = ..., continue_conversation: bool = ...) -> None: ...

class TalkToRpcResponse(_message.Message):
    __slots__ = ("success", "error", "interrupt")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    INTERRUPT_FIELD_NUMBER: _ClassVar[int]
    success: TalkToSuccess
    error: TalkToError
    interrupt: InquiryInterrupt
    def __init__(self, success: _Optional[_Union[TalkToSuccess, _Mapping]] = ..., error: _Optional[_Union[TalkToError, _Mapping]] = ..., interrupt: _Optional[_Union[InquiryInterrupt, _Mapping]] = ...) -> None: ...

class TalkToSuccess(_message.Message):
    __slots__ = ("request_id", "response", "conversation_id")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    response: str
    conversation_id: str
    def __init__(self, request_id: _Optional[str] = ..., response: _Optional[str] = ..., conversation_id: _Optional[str] = ...) -> None: ...

class TalkToError(_message.Message):
    __slots__ = ("request_id", "reason")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    reason: str
    def __init__(self, request_id: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...

class InquiryInterrupt(_message.Message):
    __slots__ = ("inquiry_id", "from_agent", "content_markdown", "suggestions", "priority")
    INQUIRY_ID_FIELD_NUMBER: _ClassVar[int]
    FROM_AGENT_FIELD_NUMBER: _ClassVar[int]
    CONTENT_MARKDOWN_FIELD_NUMBER: _ClassVar[int]
    SUGGESTIONS_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    inquiry_id: str
    from_agent: str
    content_markdown: str
    suggestions: _containers.RepeatedScalarFieldContainer[str]
    priority: str
    def __init__(self, inquiry_id: _Optional[str] = ..., from_agent: _Optional[str] = ..., content_markdown: _Optional[str] = ..., suggestions: _Optional[_Iterable[str]] = ..., priority: _Optional[str] = ...) -> None: ...

class ResumeTalkToRequest(_message.Message):
    __slots__ = ("instance_id", "request_id", "inquiry_response_text", "inquiry_suggestion_index")
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    INQUIRY_RESPONSE_TEXT_FIELD_NUMBER: _ClassVar[int]
    INQUIRY_SUGGESTION_INDEX_FIELD_NUMBER: _ClassVar[int]
    instance_id: str
    request_id: str
    inquiry_response_text: str
    inquiry_suggestion_index: int
    def __init__(self, instance_id: _Optional[str] = ..., request_id: _Optional[str] = ..., inquiry_response_text: _Optional[str] = ..., inquiry_suggestion_index: _Optional[int] = ...) -> None: ...

class InquireRpcRequest(_message.Message):
    __slots__ = ("instance_id", "content_markdown", "suggestions", "file_paths", "priority")
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_MARKDOWN_FIELD_NUMBER: _ClassVar[int]
    SUGGESTIONS_FIELD_NUMBER: _ClassVar[int]
    FILE_PATHS_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    instance_id: str
    content_markdown: str
    suggestions: _containers.RepeatedScalarFieldContainer[str]
    file_paths: _containers.RepeatedScalarFieldContainer[str]
    priority: str
    def __init__(self, instance_id: _Optional[str] = ..., content_markdown: _Optional[str] = ..., suggestions: _Optional[_Iterable[str]] = ..., file_paths: _Optional[_Iterable[str]] = ..., priority: _Optional[str] = ...) -> None: ...

class InquireRpcResponse(_message.Message):
    __slots__ = ("success", "error", "interrupt")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    INTERRUPT_FIELD_NUMBER: _ClassVar[int]
    success: InquireSuccess
    error: InquireError
    interrupt: InquiryInterrupt
    def __init__(self, success: _Optional[_Union[InquireSuccess, _Mapping]] = ..., error: _Optional[_Union[InquireError, _Mapping]] = ..., interrupt: _Optional[_Union[InquiryInterrupt, _Mapping]] = ...) -> None: ...

class InquireSuccess(_message.Message):
    __slots__ = ("inquiry_id", "response_text", "suggestion_index")
    INQUIRY_ID_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_TEXT_FIELD_NUMBER: _ClassVar[int]
    SUGGESTION_INDEX_FIELD_NUMBER: _ClassVar[int]
    inquiry_id: str
    response_text: str
    suggestion_index: int
    def __init__(self, inquiry_id: _Optional[str] = ..., response_text: _Optional[str] = ..., suggestion_index: _Optional[int] = ...) -> None: ...

class InquireError(_message.Message):
    __slots__ = ("inquiry_id", "reason")
    INQUIRY_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    inquiry_id: str
    reason: str
    def __init__(self, inquiry_id: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...

class ResumeInquireRequest(_message.Message):
    __slots__ = ("instance_id", "inquiry_id", "inquiry_response_text", "inquiry_suggestion_index")
    INSTANCE_ID_FIELD_NUMBER: _ClassVar[int]
    INQUIRY_ID_FIELD_NUMBER: _ClassVar[int]
    INQUIRY_RESPONSE_TEXT_FIELD_NUMBER: _ClassVar[int]
    INQUIRY_SUGGESTION_INDEX_FIELD_NUMBER: _ClassVar[int]
    instance_id: str
    inquiry_id: str
    inquiry_response_text: str
    inquiry_suggestion_index: int
    def __init__(self, instance_id: _Optional[str] = ..., inquiry_id: _Optional[str] = ..., inquiry_response_text: _Optional[str] = ..., inquiry_suggestion_index: _Optional[int] = ...) -> None: ...
