from pydantic import BaseModel
from typing import Optional, List


class Attachment(BaseModel):
    filename: Optional[str] = None
    file_id: Optional[str] = None
    mime: Optional[str] = None
    url: Optional[str] = None


class MessageIn(BaseModel):
    sender_id: str
    conversation_id: str
    content: Optional[str] = None
    attachments: Optional[List[Attachment]] = None
    reply_to: Optional[str] = None  # ID của tin nhắn được reply


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    content: Optional[str]
    attachments: Optional[List[Attachment]]
    created_at: str  # ISO8601 + Z
    reply_to: Optional[str] = None  # ID của tin nhắn được reply