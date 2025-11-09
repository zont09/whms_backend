from pydantic import BaseModel
from typing import Optional, List

class MessageIn(BaseModel):
    sender_id: str
    content: Optional[str] = None
    attachments: Optional[List[dict]] = None
