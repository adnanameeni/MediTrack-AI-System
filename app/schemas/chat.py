from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatMessageCreate(BaseModel):
    """What the browser sends. The user id is never accepted from the client."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=1000)
    conversation_id: int | None = None
    # Minutes east of UTC (for example 300 for UTC+05:00); used for "today", "this week", etc.
    offset_minutes: int = Field(default=0, ge=-840, le=840)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead]


class ChatReply(BaseModel):
    conversation_id: int
    user_message: MessageRead
    assistant_message: MessageRead