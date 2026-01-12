# video_server/server.py - ENHANCED VERSION with Chat Support
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from typing import Dict, List, Optional
import json
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


# Enhanced connection tracking
class Connection:
    def __init__(self, websocket: WebSocket, client_id: str, user_id: str, room_id: str):
        self.websocket = websocket
        self.client_id = client_id  # Random ID cho WebRTC
        self.user_id = user_id  # Real user ID từ database
        self.room_id = room_id


# rooms[room_id] = [Connection, Connection, ...]
rooms: Dict[str, List[Connection]] = defaultdict(list)

# Mapping để tra cứu nhanh
client_to_user: Dict[str, str] = {}  # client_id -> user_id
user_to_client: Dict[str, str] = {}  # user_id -> client_id


@router.websocket("/ws/{room_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, user_id: str):
    # Generate client_id for WebRTC (hoặc nhận từ client)
    import secrets
    client_id = secrets.token_urlsafe(16)

    connection = None

    try:
        # Accept connection
        await websocket.accept()
        logger.info(f"✅ User {user_id} (clientId={client_id}) connected to room {room_id}")

        # Create connection object
        connection = Connection(websocket, client_id, user_id, room_id)
        rooms[room_id].append(connection)

        # Store mappings
        client_to_user[client_id] = user_id
        user_to_client[user_id] = client_id

        logger.info(f"👥 Room {room_id} now has {len(rooms[room_id])} peers")

        # Send client_id back to user (để họ dùng cho WebRTC)
        await websocket.send_text(json.dumps({
            "type": "client_id",
            "client_id": client_id,
            "user_id": user_id
        }))

        # Notify others about new peer
        join_msg = json.dumps({
            "type": "join",
            "from": client_id,
            "user_id": user_id  # ✅ Thêm user_id
        })

        for conn in rooms[room_id]:
            if conn != connection:
                try:
                    await conn.websocket.send_text(join_msg)
                except Exception as e:
                    logger.error(f"❌ Failed to send join message: {e}")

        # Send list of current peers to new joiner
        peer_list = [
            {"client_id": conn.client_id, "user_id": conn.user_id}
            for conn in rooms[room_id]
            if conn != connection
        ]
        if peer_list:
            await websocket.send_text(json.dumps({
                "type": "peers_list",
                "peers": peer_list
            }))

        # Main message loop
        while True:
            try:
                data = await websocket.receive_text()
                msg = json.loads(data)
                msg_type = msg.get("type", "unknown")
                target = msg.get("to")

                logger.info(f"📨 Received {msg_type} from {user_id} ({client_id}) to {target or 'all'}")

                # ✅ Thêm user_id vào message nếu chưa có
                if "user_id" not in msg:
                    msg["user_id"] = user_id

                # Handle chat messages - broadcast to all in room
                if msg_type == "chat":
                    logger.info(f"💬 Chat message from {user_id}: {msg.get('chat_data', {}).get('message', '')}")
                    # Broadcast chat to all peers in the room (including sender for echo)
                    for conn in rooms[room_id]:
                        if conn != connection:  # Don't send back to sender
                            try:
                                await conn.websocket.send_text(json.dumps(msg))
                            except Exception as e:
                                logger.error(f"❌ Failed to broadcast chat: {e}")

                elif target:
                    # Send to specific target by client_id
                    sent = False
                    for conn in rooms[room_id]:
                        if conn.client_id == target:
                            try:
                                await conn.websocket.send_text(json.dumps(msg))
                                sent = True
                                break
                            except Exception as e:
                                logger.error(f"❌ Failed to send to target: {e}")

                    if not sent:
                        logger.warning(f"⚠️ Target {target} not found in room")
                else:
                    # Broadcast to all except sender
                    for conn in rooms[room_id]:
                        if conn != connection:
                            try:
                                await conn.websocket.send_text(json.dumps(msg))
                            except Exception as e:
                                logger.error(f"❌ Failed to broadcast: {e}")

            except WebSocketDisconnect:
                logger.info(f"🔌 User {user_id} disconnected")
                break
            except json.JSONDecodeError as e:
                logger.error(f"❌ Invalid JSON from {user_id}: {e}")
            except Exception as e:
                logger.error(f"❌ Error in message loop: {e}")
                break

    except Exception as e:
        logger.error(f"❌ WebSocket error for {user_id}: {e}")
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except:
            pass

    finally:
        # Cleanup
        if connection and room_id in rooms and connection in rooms[room_id]:
            rooms[room_id].remove(connection)
            logger.info(f"🧹 Removed {user_id} from room {room_id}")

            # Remove mappings
            if client_id in client_to_user:
                del client_to_user[client_id]
            if user_id in user_to_client:
                del user_to_client[user_id]

            # Notify remaining peers
            leave_msg = json.dumps({
                "type": "leave",
                "from": client_id,
                "user_id": user_id  # ✅ Thêm user_id
            })

            for conn in rooms[room_id]:
                try:
                    await conn.websocket.send_text(leave_msg)
                except Exception as e:
                    logger.error(f"❌ Failed to send leave message: {e}")

            # Clean up empty rooms
            if len(rooms[room_id]) == 0:
                del rooms[room_id]
                logger.info(f"🗑️ Deleted empty room: {room_id}")


@router.get("/rooms/{room_id}")
async def get_room_info(room_id: str):
    """Get information about a specific room"""
    if room_id in rooms:
        return {
            "room_id": room_id,
            "peer_count": len(rooms[room_id]),
            "peers": [
                {
                    "client_id": conn.client_id,
                    "user_id": conn.user_id
                }
                for conn in rooms[room_id]
            ],
            "exists": True
        }
    return {
        "room_id": room_id,
        "peer_count": 0,
        "peers": [],
        "exists": False
    }


@router.get("/rooms")
async def list_rooms():
    """List all active rooms"""
    return {
        "rooms": [
            {
                "room_id": room_id,
                "peer_count": len(peers),
                "peers": [
                    {"client_id": conn.client_id, "user_id": conn.user_id}
                    for conn in peers
                ]
            }
            for room_id, peers in rooms.items()
        ]
    }