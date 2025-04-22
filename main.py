# main.py
import asyncio
import json

from fastapi import FastAPI, WebSocket
from typing import Dict, Set

from starlette.websockets import WebSocketDisconnect

from liveMan import DouyinLiveWebFetcher

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.fetchers: Dict[str, DouyinLiveWebFetcher] = {}
        self.loop = asyncio.get_event_loop()  # ✅ 记录主线程的loop

    async def connect(self, websocket: WebSocket, live_id: str):
        if live_id not in self.active_connections:
            self.active_connections[live_id] = set()
            self.fetchers[live_id] = DouyinLiveWebFetcher(live_id)
            self.fetchers[live_id].start(
                callback=lambda msg: asyncio.run_coroutine_threadsafe(self.broadcast(live_id, msg), self.loop)
            )
            self.active_connections[live_id].add(websocket)

    async def broadcast(self, live_id: str, message: dict):
        for ws in self.active_connections.get(live_id, set()).copy():
            try:
                await ws.send_text(json.dumps(message))  # ✅ 用 send_text 发送 JSON字符串
            except:
                self.remove(ws, live_id)

    def remove(self, websocket: WebSocket, live_id: str):
        self.active_connections[live_id].discard(websocket)
        if not self.active_connections[live_id]:
            self.fetchers[live_id].stop()
            del self.fetchers[live_id], self.active_connections[live_id]

manager = ConnectionManager()

@app.websocket("/")
async def reject_root(websocket: WebSocket):
    await websocket.accept()
    await websocket.close(code=4001)

@app.websocket("/ws/{live_id}")
async def valid_endpoint(websocket: WebSocket, live_id: str):
    await websocket.accept()  # 关键：必须先调用 accept()
    try:
        await manager.connect(websocket, live_id)
        while True:
            await websocket.receive_text()  # 维持连接
    except WebSocketDisconnect:
        manager.remove(websocket, live_id)
    except Exception as e:
        print(f"连接异常: {e}")