from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from .db import messages_col, fs_bucket  # your db module must provide these
from .models import MessageIn
from bson import ObjectId
from datetime import datetime
from collections import defaultdict
from typing import Dict, Optional, List
import json, asyncio

router = APIRouter()
# rooms: conversation_id -> mapping client_id -> WebSocket
rooms: Dict[str, Dict[str, WebSocket]] = defaultdict(dict)
rooms_lock = asyncio.Lock()


def oid_to_id(doc):
    if not doc:
        return doc
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc["_id"])
        del doc["_id"]
    return doc


@router.post("/chats/{conversation_id}/messages")
async def send_message(conversation_id: str, body: MessageIn):
    """
    HTTP endpoint to post a message into a conversation (useful for mobile/cron).
    Saves message and broadcasts to connected WS clients.
    """
    doc = {
        "conversation_id": conversation_id,
        "sender_id": body.sender_id,
        "content": body.content or "",
        "attachments": [a.dict() for a in (body.attachments or [])],
        "created_at": datetime.utcnow()
    }

    # Add reply_to if provided
    if body.reply_to:
        doc["reply_to"] = body.reply_to

    res = await messages_col.insert_one(doc)
    doc["_id"] = res.inserted_id

    payload = {
        "type": "message",
        "message": {
            "id": str(res.inserted_id),
            "conversation_id": conversation_id,
            "sender_id": doc["sender_id"],
            "content": doc["content"],
            "attachments": doc["attachments"],
            "created_at": doc["created_at"].isoformat() + "Z"
        }
    }

    if "reply_to" in doc:
        payload["message"]["reply_to"] = doc["reply_to"]

    # broadcast to websocket clients in conversation
    async with rooms_lock:
        for ws in list(rooms.get(conversation_id, {}).values()):
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                # ignore failures but try to keep rooms clean
                pass

    return JSONResponse(content={"ok": True, "message_id": str(res.inserted_id)})


@router.get("/chats/{conversation_id}/messages")
async def load_messages(conversation_id: str, limit: int = 20, before_id: Optional[str] = None):
    """
    Load messages, paginated by before_id (ObjectId). Returns newest -> oldest limited, then reversed to chronological.
    """
    q = {"conversation_id": conversation_id}
    if before_id:
        try:
            obj = ObjectId(before_id)
            # find the referenced doc to get its created_at (optional)
            ref = await messages_col.find_one({"_id": obj})
            if ref and "created_at" in ref:
                q["created_at"] = {"$lt": ref["created_at"]}
            else:
                # fallback to by _id if ref not found
                q["_id"] = {"$lt": obj}
        except Exception:
            raise HTTPException(status_code=400, detail="invalid before_id")

    cursor = messages_col.find(q).sort("created_at", -1).limit(limit)
    docs = [oid_to_id(d) async for d in cursor]
    docs.reverse()
    for d in docs:
        if "created_at" in d and d["created_at"]:
            d["created_at"] = d["created_at"].isoformat() + "Z"
    return JSONResponse(content={"ok": True, "messages": docs})


@router.post("/chats/{conversation_id}/upload")
async def upload_file(conversation_id: str, file: UploadFile = File(...), sender_id: Optional[str] = None):
    """
    Upload a file to GridFS (fs_bucket). fs_bucket must implement async upload_from_stream(filename, bytes, metadata=...).
    Return file metadata and file id (string).
    """
    data = await file.read()
    file_id = await fs_bucket.upload_from_stream(
        file.filename,
        data,
        metadata={
            "conversation_id": conversation_id,
            "sender_id": sender_id,
            "mime": file.content_type
        }
    )
    return JSONResponse(content={
        "ok": True,
        "file_id": str(file_id),
        "filename": file.filename,
        "mime": file.content_type,
        "url": f"/files/{file_id}"
    })


@router.get("/files/{file_id}")
async def get_file(file_id: str):
    try:
        grid_out = await fs_bucket.open_download_stream(ObjectId(file_id))
    except Exception:
        raise HTTPException(status_code=404, detail="file not found")

    async def iterfile():
        while True:
            chunk = await grid_out.readchunk()
            if not chunk:
                break
            yield chunk

    return StreamingResponse(
        iterfile(),
        media_type=grid_out.metadata.get("mime", "application/octet-stream"),
        headers={"content-disposition": f'attachment; filename="{grid_out.filename}"'}
    )


@router.websocket("/ws/chat/{conversation_id}/{client_id}")
async def websocket_chat(ws: WebSocket, conversation_id: str, client_id: str):
    origin = ws.headers.get("origin")
    print("WebSocket Origin:", origin)
    await ws.accept()
    async with rooms_lock:
        rooms[conversation_id][client_id] = ws

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                # skip invalid json
                continue

            if msg.get("type") == "message":
                # standardize and add created_at
                sender = msg.get("sender_id", client_id)
                content = msg.get("content", "")
                attachments = msg.get("attachments", []) or []
                reply_to = msg.get("reply_to")

                # persist message into DB
                doc = {
                    "conversation_id": conversation_id,
                    "sender_id": sender,
                    "content": content,
                    "attachments": attachments,
                    "created_at": datetime.utcnow()
                }

                # Add reply_to if provided
                if reply_to:
                    doc["reply_to"] = reply_to

                res = await messages_col.insert_one(doc)
                doc_id = str(res.inserted_id)

                # prepare payload
                payload = {
                    "type": "message",
                    "message": {
                        "id": doc_id,
                        "conversation_id": conversation_id,
                        "sender_id": sender,
                        "content": content,
                        "attachments": attachments,
                        "created_at": doc["created_at"].isoformat() + "Z"
                    }
                }

                if reply_to:
                    payload["message"]["reply_to"] = reply_to

                # broadcast
                async with rooms_lock:
                    for cws in list(rooms[conversation_id].values()):
                        try:
                            await cws.send_text(json.dumps(payload))
                        except Exception:
                            # ignore send errors
                            pass

    except WebSocketDisconnect:
        async with rooms_lock:
            rooms[conversation_id].pop(client_id, None)