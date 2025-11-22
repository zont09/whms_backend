from pydantic import BaseModel
from typing import Optional, List


class Attachment(BaseModel):
    filename: Optional[str]
    file_id: Optional[str]
    mime: Optional[str]
    url: Optional[str]


class MessageIn(BaseModel):
    sender_id: str
    conversation_id: str
    content: Optional[str] = None
    attachments: Optional[List[Attachment]] = None


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    content: Optional[str]
    attachments: Optional[List[Attachment]]
    created_at: str  # ISO8601 + Z
