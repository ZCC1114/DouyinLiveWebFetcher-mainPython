import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, Set
import uvicorn
import threading
import json

from starlette.middleware.cors import CORSMiddleware

from liveMan import DouyinLiveWebFetcher

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        # 结构：{live_id: {websocket1, websocket2}}
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # 结构：{live_id: DouyinLiveWebFetcher实例}
        self.fetchers: Dict[str, DouyinLiveWebFetcher] = {}

    async def connect(self, websocket: WebSocket, live_id: str):
        print(f"🟢 新客户端连接，直播间ID: {live_id}")  # 调试打印
        await websocket.accept()
        if live_id not in self.active_connections:
            print(f"初始化直播间 {live_id} 的连接池")
            self.active_connections[live_id] = set()
            self.fetchers[live_id] = DouyinLiveWebFetcher(live_id)
            self.fetchers[live_id].start(callback=lambda msg: asyncio.create_task(self.broadcast(live_id, msg)))
        self.active_connections[live_id].add(websocket)
        print(f"当前活跃连接数: {len(self.active_connections[live_id])}")  # 打印连接数

    def remove(self, websocket: WebSocket, live_id: str):
        if live_id in self.active_connections:
            self.active_connections[live_id].discard(websocket)
            # 如果没有客户端则停止抓取
            if not self.active_connections[live_id]:
                self.fetchers[live_id].stop()
                del self.fetchers[live_id]
                del self.active_connections[live_id]

    async def broadcast(self, live_id: str, message: str):
        print(f"🔵 尝试广播到直播间 {live_id}")
        if live_id not in self.active_connections:
            print(f"❌ 错误：直播间 {live_id} 无活跃连接")
            return

        clients = list(self.active_connections[live_id])
        print(f"📡 准备向 {len(clients)} 个客户端发送消息")

        for connection in clients:
            try:
                print(f"✉️ 发送消息: {message[:50]}...")  # 打印消息前50字符
                await connection.send_text(message)
                print("✅ 发送成功")
            except Exception as e:
                print(f"❌ 发送失败: {e}")
                self.remove(connection, live_id)

manager = ConnectionManager()

# 添加 CORS 中间件（允许所有来源，仅限开发环境）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 或指定前端地址如 ["http://localhost:8080"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket 路由
@app.websocket("/ws/{live_id}")
async def websocket_endpoint(websocket: WebSocket, live_id: str):
    await manager.connect(websocket, live_id)
    try:
        while True:
            # 保持连接活跃
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.remove(websocket, live_id)

# 添加服务器启动代码
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)  # 确保端口未被占用