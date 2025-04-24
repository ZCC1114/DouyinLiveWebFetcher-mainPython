import json

from pydantic import BaseModel
from typing import Optional

class TagUserVo(BaseModel):
    id: Optional[str]
    orderNameId: Optional[str]
    orderNumber: Optional[str]
    orderAmounts: Optional[str]

    @classmethod
    def parse_from_redis(cls, json_str: str):
        import json
        try:
            if not json_str or not isinstance(json_str, str):
                return None

            # 解码两层（如果是双重 JSON 编码）
            first_pass = json.loads(json_str)  # 第一次解码，变成内层 JSON 字符串
            if isinstance(first_pass, str):
                first_pass = json.loads(first_pass)  # 第二次解码，变成字典

            if not isinstance(first_pass, dict):
                raise ValueError("最终解码结果不是 dict")

            return cls.model_validate(first_pass)

        except Exception as e:
            print(f"❌ 标签用户模型解析失败: {e}")
            print(f"❌ 原始字符串: {json_str}")
            return None

