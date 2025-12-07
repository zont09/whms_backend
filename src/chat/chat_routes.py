from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, Response
from .db import messages_col, fs_bucket, db
from .models import MessageIn
from bson import ObjectId
from datetime import datetime
from collections import defaultdict
from typing import Dict, Optional
import json, asyncio
import base64
from PIL import Image
import io

router = APIRouter()
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


def generate_image_thumbnail(image_data: bytes, max_size: int = 300) -> bytes:
    """Generate thumbnail for image with max width/height"""
    try:
        img = Image.open(io.BytesIO(image_data))

        # Convert RGBA to RGB if necessary
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Calculate thumbnail size maintaining aspect ratio
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        # Save to bytes
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        return output.getvalue()
    except Exception as e:
        print(f"Error generating thumbnail: {e}")
        return image_data


@router.post("/chats/{conversation_id}/messages")
async def send_message(conversation_id: str, body: MessageIn):
    """HTTP endpoint to post a message into a conversation"""
    doc = {
        "conversation_id": conversation_id,
        "sender_id": body.sender_id,
        "content": body.content or "",
        "attachments": [a.dict() for a in (body.attachments or [])],
        "created_at": datetime.utcnow()
    }

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

    # broadcast to websocket clients
    async with rooms_lock:
        for ws in list(rooms.get(conversation_id, {}).values()):
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                pass

    return JSONResponse(content={"ok": True, "message_id": str(res.inserted_id)})


@router.get("/chats/{conversation_id}/messages")
async def load_messages(conversation_id: str, limit: int = 50, before_id: Optional[str] = None):
    """Load messages with pagination"""
    q = {"conversation_id": conversation_id}
    if before_id:
        try:
            obj = ObjectId(before_id)
            ref = await messages_col.find_one({"_id": obj})
            if ref and "created_at" in ref:
                q["created_at"] = {"$lt": ref["created_at"]}
            else:
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
    Upload a file. For images, store in MongoDB files collection.
    For other files, use GridFS.
    """
    data = await file.read()

    # Get MIME type from file or detect from extension
    mime_type = file.content_type
    if not mime_type or mime_type == "application/octet-stream":
        # Try to detect from filename
        filename_lower = file.filename.lower() if file.filename else ""
        if filename_lower.endswith(('.jpg', '.jpeg')):
            mime_type = "image/jpeg"
        elif filename_lower.endswith('.png'):
            mime_type = "image/png"
        elif filename_lower.endswith('.gif'):
            mime_type = "image/gif"
        elif filename_lower.endswith('.webp'):
            mime_type = "image/webp"
        elif filename_lower.endswith(('.mp4', '.mov')):
            mime_type = "video/mp4"
        else:
            mime_type = "application/octet-stream"

    print(f"Uploading file: {file.filename}, mime: {mime_type}, size: {len(data)} bytes")

    # Check if it's an image
    if mime_type.startswith('image/'):
        try:
            # Generate thumbnail
            thumbnail_data = generate_image_thumbnail(data)

            # Store in MongoDB files collection (NOT GridFS)
            files_col = db['files']
            file_doc = {
                "filename": file.filename,
                "mime": mime_type,
                "data": base64.b64encode(data).decode('utf-8'),
                "thumbnail": base64.b64encode(thumbnail_data).decode('utf-8'),
                "conversation_id": conversation_id,
                "sender_id": sender_id,
                "created_at": datetime.utcnow(),
                "size": len(data)
            }
            result = await files_col.insert_one(file_doc)
            file_id = str(result.inserted_id)

            print(f"Image saved to MongoDB files collection with ID: {file_id}")

            return JSONResponse(content={
                "ok": True,
                "file_id": file_id,
                "filename": file.filename,
                "mime": mime_type,
                "url": f"/files/{file_id}",
                "thumbnail_url": f"/files/{file_id}/thumbnail",
                "size": len(data)
            })
        except Exception as e:
            print(f"Error uploading image: {e}")
            raise HTTPException(status_code=500, detail=f"Error uploading image: {str(e)}")
    else:
        # For non-images, use GridFS
        try:
            file_id = await fs_bucket.upload_from_stream(
                file.filename,
                data,
                metadata={
                    "conversation_id": conversation_id,
                    "sender_id": sender_id,
                    "mime": mime_type,
                    "size": len(data)
                }
            )
            print(f"File saved to GridFS with ID: {file_id}")

            return JSONResponse(content={
                "ok": True,
                "file_id": str(file_id),
                "filename": file.filename,
                "mime": mime_type,
                "url": f"/files/{file_id}",
                "size": len(data)
            })
        except Exception as e:
            print(f"Error uploading file to GridFS: {e}")
            raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")


@router.get("/files/{file_id}")
async def get_file(file_id: str):
    """Get file - images from MongoDB, others from GridFS"""
    print(f"Getting file: {file_id}")

    try:
        # Try MongoDB files collection first (for images)
        files_col = db['files']
        try:
            file_doc = await files_col.find_one({"_id": ObjectId(file_id)})
        except Exception as e:
            print(f"Error querying MongoDB files: {e}")
            file_doc = None

        if file_doc:
            print(f"Found image in MongoDB files collection: {file_doc.get('filename')}")
            try:
                # Decode base64 to bytes
                image_data = base64.b64decode(file_doc['data'])
                print(f"Decoded image data, size: {len(image_data)} bytes")

                return Response(
                    content=image_data,
                    media_type=file_doc.get('mime', 'image/jpeg'),
                    headers={
                        "Cache-Control": "public, max-age=31536000, immutable",
                        "Content-Disposition": f'inline; filename="{file_doc["filename"]}"',
                        "ETag": f'"{file_id}"',
                        "Access-Control-Allow-Origin": "*"
                    }
                )
            except Exception as e:
                print(f"Error decoding image data: {e}")
                raise HTTPException(status_code=500, detail=f"Error decoding image: {str(e)}")
        else:
            # Try GridFS for other files
            print(f"Image not found in files collection, trying GridFS...")
            try:
                grid_out = await fs_bucket.open_download_stream(ObjectId(file_id))
                print(f"Found file in GridFS: {grid_out.filename}")

                async def iterfile():
                    while True:
                        chunk = await grid_out.readchunk()
                        if not chunk:
                            break
                        yield chunk

                return StreamingResponse(
                    iterfile(),
                    media_type=grid_out.metadata.get("mime", "application/octet-stream"),
                    headers={
                        "content-disposition": f'attachment; filename="{grid_out.filename}"',
                        "Cache-Control": "public, max-age=31536000, immutable",
                        "ETag": f'"{file_id}"',
                        "Access-Control-Allow-Origin": "*"
                    }
                )
            except Exception as e:
                print(f"File not found in GridFS: {e}")
                raise HTTPException(status_code=404, detail="file not found")

    except Exception as e:
        print(f"Error getting file: {e}")
        raise HTTPException(status_code=404, detail=f"file not found: {str(e)}")


@router.get("/files/{file_id}/thumbnail")
async def get_thumbnail(file_id: str):
    """Get thumbnail for image files"""
    print(f"Getting thumbnail: {file_id}")

    try:
        files_col = db['files']
        file_doc = await files_col.find_one({"_id": ObjectId(file_id)})

        if not file_doc:
            print(f"Thumbnail not found for file_id: {file_id}")
            raise HTTPException(status_code=404, detail="file not found")

        # Return thumbnail if available, otherwise return original
        thumbnail_data = file_doc.get('thumbnail', file_doc.get('data'))
        if not thumbnail_data:
            raise HTTPException(status_code=404, detail="thumbnail not found")

        image_data = base64.b64decode(thumbnail_data)
        print(f"Returning thumbnail, size: {len(image_data)} bytes")

        return Response(
            content=image_data,
            media_type=file_doc.get('mime', 'image/jpeg'),
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "Content-Disposition": f'inline; filename="thumb_{file_doc["filename"]}"',
                "ETag": f'"{file_id}-thumb"',
                "Access-Control-Allow-Origin": "*"
            }
        )
    except Exception as e:
        print(f"Error getting thumbnail: {e}")
        raise HTTPException(status_code=404, detail=f"thumbnail not found: {str(e)}")


@router.websocket("/ws/chat/{conversation_id}/{client_id}")
async def websocket_chat(ws: WebSocket, conversation_id: str, client_id: str):
    """WebSocket endpoint for real-time chat"""
    print(f"WebSocket connection: {client_id} joined {conversation_id}")
    await ws.accept()
    async with rooms_lock:
        rooms[conversation_id][client_id] = ws

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            if msg.get("type") == "message":
                sender = msg.get("sender_id", client_id)
                content = msg.get("content", "")
                attachments = msg.get("attachments", []) or []
                reply_to = msg.get("reply_to")

                doc = {
                    "conversation_id": conversation_id,
                    "sender_id": sender,
                    "content": content,
                    "attachments": attachments,
                    "created_at": datetime.utcnow()
                }

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

                print(f"Broadcasting message {doc_id} to {len(rooms[conversation_id])} clients")

                async with rooms_lock:
                    for cws in list(rooms[conversation_id].values()):
                        try:
                            await cws.send_text(json.dumps(payload))
                        except Exception:
                            pass

    except WebSocketDisconnect:
        print(f"WebSocket disconnected: {client_id} left {conversation_id}")
        async with rooms_lock:
            rooms[conversation_id].pop(client_id, None)