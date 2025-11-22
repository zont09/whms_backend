from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import JSONResponse
from typing import Dict, List
from collections import defaultdict
from datetime import datetime
import json
from bson import ObjectId
# import the shared DB objects from your db module
from .db import messages_col  # messages_col should be an AsyncIOMotorCollection

router = APIRouter()

# rooms: mapping conversation_id -> list of websockets
rooms: Dict[str, List[WebSocket]] = defaultdict(list)

# Startup: ensure index on conversation_id + created_at
async def startup_event():
    # create index if not exists
    await messages_col.create_index([("conversation_id", 1), ("created_at", -1)])
    print("✅ MongoDB connected and index ensured")

# -------------------
# HTTP: load messages
# -------------------
@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    before: str = Query(None),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Return messages for a conversation, paginated by ObjectId (`before` = message id).
    Returns messages in chronological order (oldest -> newest).
    """
    query = {"conversation_id": conversation_id}
    if before:
        try:
            oid = ObjectId(before)
            # find messages with _id < provided id (older)
            query["_id"] = {"$lt": oid}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid before param")

    cursor = messages_col.find(query).sort("_id", -1).limit(limit)
    docs = await cursor.to_list(length=limit)
    docs.reverse()  # oldest -> newest

    result = []
    for d in docs:
        result.append({
            "id": str(d["_id"]),
            "conversation_id": d.get("conversation_id"),
            "sender_id": d.get("sender_id"),
            "content": d.get("content"),
            "attachments": d.get("attachments", []),
            "created_at": d.get("created_at").isoformat() + "Z" if d.get("created_at") else None,
        })

    return JSONResponse(content={"ok": True, "messages": result})

# -------------------
# WS: realtime chat
# -------------------
@router.websocket("/ws/chat/{conversation_id}/{client_id}")
async def chat_socket(websocket: WebSocket, conversation_id: str, client_id: str):
    """
    Simple websocket endpoint:
    - clients send JSON messages like {"type":"message","content":"hello","sender_id":"..."}
    - server persists and broadcasts to all clients in the conversation
    """
    await websocket.accept()
    rooms[conversation_id].append(websocket)
    print(f"{client_id} joined {conversation_id}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except Exception:
                # if plain text, wrap it
                data = {"type": "message", "content": raw}

            # only handle message type
            if data.get("type") != "message":
                # ignore unknown types for now
                continue

            sender_id = data.get("sender_id", client_id)
            content = data.get("content", "")
            attachments = data.get("attachments", []) or []

            # build doc to save
            doc = {
                "conversation_id": conversation_id,
                "sender_id": sender_id,
                "content": content,
                "attachments": attachments,
                "created_at": datetime.utcnow()
            }

            res = await messages_col.insert_one(doc)
            doc_id = str(res.inserted_id)

            # payload to broadcast
            msg_out = {
                "type": "message",
                "message": {
                    "id": doc_id,
                    "conversation_id": conversation_id,
                    "sender_id": sender_id,
                    "content": content,
                    "attachments": attachments,
                    "created_at": doc["created_at"].isoformat() + "Z"
                }
            }

            # broadcast (synchronous loop; keep simple)
            text = json.dumps(msg_out)
            for ws in list(rooms[conversation_id]):
                try:
                    await ws.send_text(text)
                except Exception:
                    try:
                        rooms[conversation_id].remove(ws)
                    except ValueError:
                        pass

    except WebSocketDisconnect:
        try:
            rooms[conversation_id].remove(websocket)
        except ValueError:
            pass
        leave_payload = {
            "type": "system",
            "action": "leave",
            "user": client_id,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        # broadcast leave
        text = json.dumps(leave_payload)
        for ws in list(rooms[conversation_id]):
            try:
                await ws.send_text(text)
            except Exception:
                try:
                    rooms[conversation_id].remove(ws)
                except ValueError:
                    pass
        print(f"{client_id} left {conversation_id}")
