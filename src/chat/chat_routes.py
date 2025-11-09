from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from .db import messages_col, fs_bucket
from .models import MessageIn
from bson import ObjectId
from datetime import datetime
from collections import defaultdict
from typing import Dict, Optional, List
import json, asyncio

router = APIRouter()
rooms: Dict[str, Dict[str, WebSocket]] = defaultdict(dict)
rooms_lock = asyncio.Lock()

def oid_str(doc):
    if not doc: return doc
    doc = dict(doc)
    if "_id" in doc: doc["_id"] = str(doc["_id"])
    return doc

@router.post("/chats/{room_id}/messages")
async def send_message(room_id: str, body: MessageIn):
    doc = {
        "room_id": room_id,
        "sender_id": body.sender_id,
        "content": body.content or "",
        "attachments": body.attachments or [],
        "created_at": datetime.utcnow()
    }
    res = await messages_col.insert_one(doc)
    doc["_id"] = str(res.inserted_id)

    payload = {
        "type": "message",
        "message": {
            **doc, "created_at": doc["created_at"].isoformat() + "Z"
        }
    }

    async with rooms_lock:
        for ws in list(rooms.get(room_id, {}).values()):
            try:
                await ws.send_text(json.dumps(payload))
            except: pass

    return {"ok": True, "message_id": doc["_id"]}

@router.get("/chats/{room_id}/messages")
async def load_messages(room_id: str, limit: int = 20, before_id: Optional[str] = None):
    q = {"room_id": room_id}
    if before_id:
        try:
            obj = ObjectId(before_id)
            ref = await messages_col.find_one({"_id": obj})
            if ref:
                q["created_at"] = {"$lt": ref["created_at"]}
        except: raise HTTPException(400, "invalid before_id")

    cursor = messages_col.find(q).sort("created_at", -1).limit(limit)
    docs = [oid_str(d) async for d in cursor]
    docs.reverse()
    for d in docs:
        if "created_at" in d: d["created_at"] = d["created_at"].isoformat() + "Z"
    return {"ok": True, "messages": docs}

@router.post("/chats/{room_id}/upload")
async def upload_file(room_id: str, file: UploadFile = File(...), sender_id: Optional[str] = None):
    data = await file.read()
    file_id = await fs_bucket.upload_from_stream(file.filename, data,
                metadata={"room_id": room_id, "sender_id": sender_id, "mime": file.content_type})
    return {"ok": True, "file_id": str(file_id), "filename": file.filename,
            "mime": file.content_type, "url": f"/files/{file_id}"}

@router.get("/files/{file_id}")
async def get_file(file_id: str):
    try:
        grid_out = await fs_bucket.open_download_stream(ObjectId(file_id))
    except:
        raise HTTPException(404, "file not found")

    async def iterfile():
        while True:
            chunk = await grid_out.readchunk()
            if not chunk: break
            yield chunk

    return StreamingResponse(iterfile(),
        media_type=grid_out.metadata.get("mime", "application/octet-stream"),
        headers={"content-disposition": f'attachment; filename="{grid_out.filename}"'})

@router.websocket("/ws/chat/{room_id}/{client_id}")
async def websocket_chat(ws: WebSocket, room_id: str, client_id: str):
    await ws.accept()
    async with rooms_lock:
        rooms[room_id][client_id] = ws
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "message":
                msg["sender_id"] = msg.get("sender_id", client_id)
                msg["created_at"] = datetime.utcnow().isoformat() + "Z"
                payload = {"type": "message", "message": msg}
                async with rooms_lock:
                    for cws in rooms[room_id].values():
                        await cws.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        async with rooms_lock:
            rooms[room_id].pop(client_id, None)
