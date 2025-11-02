# video_server/server.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List
import uvicorn
import json
from collections import defaultdict

app = FastAPI()
rooms: Dict[str, List[WebSocket]] = defaultdict(list)

@app.websocket("/ws/{room_id}/{client_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, client_id: str):
    await websocket.accept()
    rooms[room_id].append(websocket)
    try:
        join_msg = json.dumps({"type":"join","from":client_id})
        for peer in rooms[room_id]:
            if peer is not websocket:
                await peer.send_text(join_msg)
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            target = msg.get("to")
            if target:
                for peer in rooms[room_id]:
                    await peer.send_text(json.dumps(msg))
            else:
                for peer in rooms[room_id]:
                    if peer is not websocket:
                        await peer.send_text(json.dumps(msg))
    except WebSocketDisconnect:
        rooms[room_id].remove(websocket)
        leave_msg = json.dumps({"type":"leave","from":client_id})
        for peer in rooms[room_id]:
            await peer.send_text(leave_msg)

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000)
