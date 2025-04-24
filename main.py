import asyncio
import json
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, Set
from starlette.middleware.cors import CORSMiddleware
from liveMan import DouyinLiveWebFetcher
from redis_helper import redis_client

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.fetchers: Dict[str, DouyinLiveWebFetcher] = {}
        self.lock = threading.Lock()
        self.loop = asyncio.get_event_loop()

    async def connect(self, websocket: WebSocket, live_id: str):
        await websocket.accept()

        with self.lock:
            if live_id not in self.active_connections:
                self.active_connections[live_id] = set()
                # 仅当没有抓取器时才创建新实例
                if live_id not in self.fetchers:
                    self.fetchers[live_id] = DouyinLiveWebFetcher(live_id)
                    self.fetchers[live_id].start(
                        callback=lambda msg: asyncio.run_coroutine_threadsafe(
                            self.broadcast(live_id, msg),  # 确保传入的是dict
                            self.loop
                        )
                    )

            self.active_connections[live_id].add(websocket)
            # print(f"🟢 新客户端连接 ({len(self.active_connections[live_id])}个): {live_id}")

    async def broadcast(self, live_id: str, message: str):  # 注意参数类型改为dict
        if live_id not in self.active_connections:
            print(f"⚠️ 无活跃连接: {live_id}")
            return

        clients = list(self.active_connections[live_id])
        # print(f"📢 准备向 {len(clients)} 个客户端广播消息")

        for connection in clients:
            try:
                # 确保转换为JSON字符串
                # json_message = json.dumps(message, ensure_ascii=False)
                # print(f"✉️ 发送消息: {json_message[:100]}...")  # 打印前100字符
                await connection.send_text(message)
                # print("✅ 发送成功")
            except Exception as e:
                print(f"❌ 发送失败: {str(e)[:200]}")  # 截断长错误信息
                await self.remove(connection, live_id)

    async def remove(self, websocket: WebSocket, live_id: str):
        with self.lock:
            if live_id in self.active_connections:
                self.active_connections[live_id].discard(websocket)
                if not self.active_connections[live_id]:
                    print(f"💤 没有客户端了，关闭 {live_id} 的抓取器")
                    self.fetchers[live_id].stop()
                    del self.fetchers[live_id]
                    del self.active_connections[live_id]

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()

@app.websocket("/")
async def reject_root(websocket: WebSocket):
    await websocket.accept()
    await websocket.close(code=4001)

@app.websocket("/ws/{live_id}")
async def websocket_endpoint(websocket: WebSocket, live_id: str):
    await manager.connect(websocket, live_id)
    try:
        while True:
            # 维持连接活跃
            print(f"================")
            data = await websocket.receive_text()
            print(f"收到客户端心跳: {data}")
            # 心跳处理逻辑
            if data == "ping":
                print(f"收到客户端[{live_id}]心跳ping")
                await websocket.send_text("pong")  # 发送pong响应
                continue
    except WebSocketDisconnect:
        print("前端客户端主动断开")
        await manager.remove(websocket, live_id)
    except Exception as e:
        print(f"前端连接异常: {e}")
        await manager.remove(websocket, live_id)



@app.on_event("startup")
def init_redis_check():
    try:
        redis_client.ping()
        print("✅ Redis 连接成功")
    except Exception as e:
        print("❌ Redis 连接失败:", e)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)