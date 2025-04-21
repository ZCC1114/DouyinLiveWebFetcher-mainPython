from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocket

app = FastAPI()

# 添加 CORS 中间件（允许所有来源，仅限开发环境）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 或指定前端地址如 ["http://localhost:8080"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket 路由
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()  # 必须调用 accept() 完成握手
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"收到消息: {data}")
    except Exception as e:
        print(f"连接异常: {e}")
    finally:
        await websocket.close()

# 添加服务器启动代码
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)  # 确保端口未被占用