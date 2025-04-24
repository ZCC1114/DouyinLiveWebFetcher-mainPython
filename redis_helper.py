# redis_helper.py
import redis

# 全局 redis 客户端（单例）
redis_client = redis.StrictRedis(
    host='139.224.193.122',
    port=6379,
    password='fastSort8888',
    decode_responses=True
)
