# main.py
import asyncio
import json
import threading

from fastapi import FastAPI, WebSocket
from typing import Dict, Set

from starlette.websockets import WebSocketDisconnect

from liveMan import DouyinLiveWebFetcher

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.fetchers: Dict[str, DouyinLiveWebFetcher] = {}
        self.lock = threading.Lock()  # 新增：锁
        self.loop = asyncio.get_event_loop()

    async def connect(self, websocket: WebSocket, live_id: str):
        print(f"🟢 新客户端连接，直播间ID: {live_id}")  # 调试打印
        if live_id not in self.active_connections:
            self.active_connections[live_id] = set()
            self.fetchers[live_id] = DouyinLiveWebFetcher(live_id)
            self.fetchers[live_id].start(
                callback=lambda msg: asyncio.run_coroutine_threadsafe(self.broadcast(live_id, msg), self.loop)
            )
            self.active_connections[live_id].add(websocket)
            print(f"当前活跃连接数: {len(self.active_connections[live_id])}")

    async def broadcast(self, live_id: str, message: dict):
        if live_id not in self.active_connections:
            return
        tasks = []
        for ws in list(self.active_connections[live_id]):
            tasks.append(self._safe_send(ws, live_id, message))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_send(self, websocket: WebSocket, live_id: str, message: dict):
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            print(f"发送失败，移除连接: {e}")
            with self.lock:
                self.remove(websocket, live_id)

    def remove(self, websocket: WebSocket, live_id: str):
        if live_id in self.active_connections:
            self.active_connections[live_id].discard(websocket)
            if not self.active_connections[live_id]:
                print(f"💤 没有客户端了，关闭 {live_id} 的抓取器")
                self.fetchers[live_id].stop()
                del self.fetchers[live_id]
                del self.active_connections[live_id]

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