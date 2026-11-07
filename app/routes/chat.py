from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.graph import run_assistant
from app.assistant.llm import LlmNotConfigured, Llms, build_llms
from app.database.session import get_db
from app.dependencies import get_current_user
from app.models import ChatConversation, ChatMessage, User
from app.schemas.chat import (
    ChatMessageCreate,
    ChatReply,
    ConversationDetail,
    ConversationRead,
    MessageRead,
)

router = APIRouter(prefix="/chat", tags=["chat"])

HISTORY_TURNS = 6
CONVERSATION_LIMIT = 50


def get_llms() -> Llms:
    try:
        return build_llms()
    except LlmNotConfigured:
        raise HTTPException(status_code=503, detail="The AI assistant is not set up yet.")


def _own_conversation(db: Session, user: User, conversation_id: int) -> ChatConversation:
    """Only ever returns a conversation that belongs to this user."""
    conversation = db.scalar(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user.id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


@router.post("/messages", response_model=ChatReply)
def send_message(
    payload: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llms: Llms = Depends(get_llms),
) -> ChatReply:
    if payload.conversation_id is None:
        conversation = ChatConversation(user_id=current_user.id, title=payload.message[:60])
        db.add(conversation)
        db.flush()
        history: list[dict] = []
    else:
        conversation = _own_conversation(db, current_user, payload.conversation_id)
        history = [
            {"role": m.role, "content": m.content} for m in conversation.messages
        ][-HISTORY_TURNS:]

    conversation_id = conversation.id
    user_message = ChatMessage(
        conversation_id=conversation_id, role="user", content=payload.message
    )
    db.add(user_message)
    db.commit()  # the question is saved even if answering fails

    reply_text = run_assistant(
        db, current_user.id, payload.message, payload.offset_minutes, history, llms
    )

    assistant_message = ChatMessage(
        conversation_id=conversation_id, role="assistant", content=reply_text
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)

    return ChatReply(
        conversation_id=conversation_id,
        user_message=MessageRead.model_validate(user_message),
        assistant_message=MessageRead.model_validate(assistant_message),
    )


@router.get("/conversations", response_model=list[ConversationRead])
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChatConversation]:
    return list(
        db.scalars(
            select(ChatConversation)
            .where(ChatConversation.user_id == current_user.id)
            .order_by(ChatConversation.id.desc())
            .limit(CONVERSATION_LIMIT)
        ).all()
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatConversation:
    return _own_conversation(db, current_user, conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    conversation = _own_conversation(db, current_user, conversation_id)
    db.delete(conversation)
    db.commit()
    return Response(status_code=204)