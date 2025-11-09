# chat_server/chat_server.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import JSONResponse
from typing import Dict, List
from collections import defaultdict
from datetime import datetime
import json
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

router = APIRouter()

MONGO_URI = "mongodb+srv://zont09:mgdb124536@whms.lczpcgb.mongodb.net/?appName=WHMS"
client = AsyncIOMotorClient(MONGO_URI)
db = client["chatdb"]

rooms: Dict[str, List[WebSocket]] = defaultdict(list)

async def startup_event():
    await db.messages.create_index([("groupId", 1), ("timestamp", -1)])
    print("✅ MongoDB connected and index ensured")

# -------------------
# HTTP: load messages
# -------------------
@router.get("/groups/{group_id}/messages")
async def get_messages(group_id: str, before: str = Query(None), limit: int = Query(50, ge=1, le=200)):
    query = {"groupId": group_id}
    if before:
        try:
            oid = ObjectId(before)
            query["_id"] = {"$lt": oid}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid before param")

    cursor = db.messages.find(query).sort("_id", -1).limit(limit)
    docs = await cursor.to_list(length=limit)
    docs.reverse()

    for d in docs:
        d["_id"] = str(d["_id"])
        d["timestamp"] = d["timestamp"].isoformat()

    return JSONResponse(content=docs)

# -------------------
# WS: realtime chat
# -------------------
@router.websocket("/ws/chat/{group_id}/{username}")
async def chat_socket(websocket: WebSocket, group_id: str, username: str):
    await websocket.accept()
    rooms[group_id].append(websocket)
    print(f"{username} joined {group_id}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except Exception:
                data = {"text": raw}

            text = data.get("text")
            if not text:
                continue

            msg = {
                "groupId": group_id,
                "sender": username,
                "text": text,
                "timestamp": datetime.utcnow(),
            }
            res = await db.messages.insert_one(msg)
            msg["_id"] = str(res.inserted_id)
            msg["timestamp"] = msg["timestamp"].isoformat()

            payload = {"type": "chat", "message": msg}
            await broadcast(group_id, payload)

    except WebSocketDisconnect:
        rooms[group_id].remove(websocket)
        leave_payload = {
            "type": "system",
            "action": "leave",
            "user": username,
            "timestamp": datetime.utcnow().isoformat()
        }
        await broadcast(group_id, leave_payload)
        print(f"{username} left {group_id}")

async def broadcast(group_id: str, payload: dict):
    text = json.dumps(payload)
    for ws in list(rooms[group_id]):
        try:
            await ws.send_text(text)
        except Exception:
            rooms[group_id].remove(ws)
