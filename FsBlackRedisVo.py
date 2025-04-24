
from pydantic import BaseModel, Field
from typing import List, Optional, Annotated

class FsBlackRedisVo(BaseModel):
    orderNameId: Optional[str]
    blackLevel: int = 0
    createdUsers: Annotated[List[str], Field(default_factory=list)]

    @classmethod
    def parse_from_redis(cls, json_str: str):
        import json
        try:
            raw = json.loads(json_str)

            # createdUsers 是 ["java.util.ArrayList", [list]]
            users = raw.get("createdUsers", [])
            if isinstance(users, list) and len(users) == 2 and isinstance(users[1], list):
                users_list = users[1]
            else:
                users_list = []

            return cls(
                orderNameId=raw.get("orderNameId"),
                blackLevel=raw.get("blackLevel", 0),
                createdUsers=users_list
            )
        except Exception as e:
            print(f"❌ FsBlackRedisVo 解析失败: {e}")
            return None
