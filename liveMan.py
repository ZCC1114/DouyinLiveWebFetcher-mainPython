#!/usr/bin/python
# coding:utf-8
import asyncio
# @FileName:    liveMan.py
# @Time:        2024/1/2 21:51
# @Author:      bubu
# @Project:     douyinLiveWebFetcher

import codecs
import gzip
import hashlib
import random
import re
import string
import subprocess
import threading
import time
import urllib.parse
import json
import uuid
from contextlib import contextmanager
from typing import Optional
from unittest.mock import patch

import requests
import websocket
from py_mini_racer import MiniRacer

from FsBlackRedisVo import FsBlackRedisVo
from TagUserVo import TagUserVo
from protobuf.douyin import *
from redis_helper import redis_client



@contextmanager
def patched_popen_encoding(encoding='utf-8'):
    original_popen_init = subprocess.Popen.__init__
    
    def new_popen_init(self, *args, **kwargs):
        kwargs['encoding'] = encoding
        original_popen_init(self, *args, **kwargs)
    
    with patch.object(subprocess.Popen, '__init__', new_popen_init):
        yield


def generateSignature(wss, script_file='sign.js'):
    """
    出现gbk编码问题则修改 python模块subprocess.py的源码中Popen类的__init__函数参数encoding值为 "utf-8"
    """
    params = ("live_id,aid,version_code,webcast_sdk_version,"
              "room_id,sub_room_id,sub_channel_id,did_rule,"
              "user_unique_id,device_platform,device_type,ac,"
              "identity").split(',')
    wss_params = urllib.parse.urlparse(wss).query.split('&')
    wss_maps = {i.split('=')[0]: i.split("=")[-1] for i in wss_params}
    tpl_params = [f"{i}={wss_maps.get(i, '')}" for i in params]
    param = ','.join(tpl_params)
    md5 = hashlib.md5()
    md5.update(param.encode())
    md5_param = md5.hexdigest()
    
    with codecs.open(script_file, 'r', encoding='utf8') as f:
        script = f.read()
    
    ctx = MiniRacer()
    ctx.eval(script)
    
    try:
        signature = ctx.call("get_sign", md5_param)
        return signature
    except Exception as e:
        print(e)
    
    # 以下代码对应js脚本为sign_v0.js
    # context = execjs.compile(script)
    # with patched_popen_encoding(encoding='utf-8'):
    #     ret = context.call('getSign', {'X-MS-STUB': md5_param})
    # return ret.get('X-Bogus')


def generateMsToken(length=107):
    """
    产生请求头部cookie中的msToken字段，其实为随机的107位字符
    :param length:字符位数
    :return:msToken
    """
    random_str = ''
    base_str = string.ascii_letters + string.digits + '=_'
    _len = len(base_str) - 1
    for _ in range(length):
        random_str += base_str[random.randint(0, _len)]
    return random_str


class DouyinLiveWebFetcher:

    def __init__(self, live_id):
        """
        直播间弹幕抓取对象
        :param live_id: 直播间的直播id，打开直播间web首页的链接如：https://live.douyin.com/261378947940，
                        其中的261378947940即是live_id
        """
        self._closed = False  # ✅ 新增：关闭标志
        self.__ttwid = None
        self.__room_id = None
        self.live_id = live_id
        self.live_url = "https://live.douyin.com/"
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " \
                          "Chrome/120.0.0.0 Safari/537.36"
        self.callback = None  # 消息回调函数


    def start(self, callback):
        self.callback = callback
        threading.Thread(target=self._connectWebSocket, daemon=True).start()

    def stop(self):
        self._closed = True  # 标志关闭
        try:
            if hasattr(self, 'ws'):
                self.ws.close()
        except Exception as e:
            print(f"关闭WebSocket出错: {e}")

    @property
    def ttwid(self):
        """
        产生请求头部cookie中的ttwid字段，访问抖音网页版直播间首页可以获取到响应cookie中的ttwid
        :return: ttwid
        """
        if self.__ttwid:
            return self.__ttwid
        headers = {
            "User-Agent": self.user_agent,
        }
        try:
            response = requests.get(self.live_url, headers=headers)
            response.raise_for_status()
        except Exception as err:
            print("【X】Request the live url error: ", err)
        else:
            self.__ttwid = response.cookies.get('ttwid')
            return self.__ttwid

    @property
    def room_id(self):
        """
        根据直播间的地址获取到真正的直播间roomId，有时会有错误，可以重试请求解决
        :return:room_id
        """
        if self.__room_id:
            return self.__room_id
        url = self.live_url + self.live_id
        headers = {
            "User-Agent": self.user_agent,
            "cookie": f"ttwid={self.ttwid}&msToken={generateMsToken()}; __ac_nonce=0123407cc00a9e438deb4",
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
        except Exception as err:
            print("【X】Request the live room url error: ", err)
        else:
            match = re.search(r'roomId\\":\\"(\d+)\\"', response.text)
            if match is None or len(match.groups()) < 1:
                print("【X】No match found for roomId")

            self.__room_id = match.group(1)

            return self.__room_id

    def get_room_status(self):
        """
        获取直播间开播状态:
        room_status: 2 直播已结束
        room_status: 0 直播进行中
        """
        url = ('https://live.douyin.com/webcast/room/web/enter/?aid=6383'
               '&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&enter_from=web_live'
               '&cookie_enabled=true&screen_width=1536&screen_height=864&browser_language=zh-CN&browser_platform=Win32'
               '&browser_name=Edge&browser_version=133.0.0.0'
               f'&web_rid={self.live_id}'
               f'&room_id_str={self.room_id}'
               '&enter_source=&is_need_double_stream=false&insert_task_id=&live_reason='
               '&msToken=&a_bogus=')
        resp = requests.get(url, headers={
            'User-Agent': self.user_agent,
            'Cookie': f'ttwid={self.ttwid};'
        })
        data = resp.json().get('data')
        if data:
            room_status = data.get('room_status')
            user = data.get('user')
            user_id = user.get('id_str')
            nickname = user.get('nickname')
            print(f"【{nickname}】[{user_id}]直播间：{['正在直播', '已结束'][bool(room_status)]}.")

    def _connectWebSocket(self):
        """
        连接抖音直播间websocket服务器，请求直播间数据
        """
        wss = ("wss://webcast5-ws-web-hl.douyin.com/webcast/im/push/v2/?app_name=douyin_web"
               "&version_code=180800&webcast_sdk_version=1.0.14-beta.0"
               "&update_version_code=1.0.14-beta.0&compress=gzip&device_platform=web&cookie_enabled=true"
               "&screen_width=1536&screen_height=864&browser_language=zh-CN&browser_platform=Win32"
               "&browser_name=Mozilla"
               "&browser_version=5.0%20(Windows%20NT%2010.0;%20Win64;%20x64)%20AppleWebKit/537.36%20(KHTML,"
               "%20like%20Gecko)%20Chrome/126.0.0.0%20Safari/537.36"
               "&browser_online=true&tz_name=Asia/Shanghai"
               "&cursor=d-1_u-1_fh-7392091211001140287_t-1721106114633_r-1"
               f"&internal_ext=internal_src:dim|wss_push_room_id:{self.room_id}|wss_push_did:7319483754668557238"
               f"|first_req_ms:1721106114541|fetch_time:1721106114633|seq:1|wss_info:0-1721106114633-0-0|"
               f"wrds_v:7392094459690748497"
               f"&host=https://live.douyin.com&aid=6383&live_id=1&did_rule=3&endpoint=live_pc&support_wrds=1"
               f"&user_unique_id=7319483754668557238&im_path=/webcast/im/fetch/&identity=audience"
               f"&need_persist_msg_count=15&insert_task_id=&live_reason=&room_id={self.room_id}&heartbeatDuration=0")

        signature = generateSignature(wss)
        wss += f"&signature={signature}"

        headers = {
            "cookie": f"ttwid={self.ttwid}",
            'user-agent': self.user_agent,
        }
        self.ws = websocket.WebSocketApp(wss,
                                         header=headers,
                                         on_open=self._wsOnOpen,
                                         on_message=self._wsOnMessage,
                                         on_error=self._wsOnError,
                                         on_close=self._wsOnClose)
        try:
            self.ws.run_forever()
        except Exception:
            self.stop()
            raise

    def _sendHeartbeat(self):
        while not self._closed:
            try:
                heartbeat = PushFrame(payload_type='hb').SerializeToString()
                self.ws.send(heartbeat, websocket.ABNF.OPCODE_PING)
                print("【√】发送心跳包")
            except Exception as e:
                print("【X】心跳包发送失败: ", e)
                break
            time.sleep(5)

    """
      抖音client连接建立成功
    """
    def _wsOnOpen(self, ws):
        print("【√】WebSocket连接成功.")
        # 连接成功给客户端推送"LIVING"
        self.callback(str('LIVING'))
        threading.Thread(target=self._sendHeartbeat).start()

    """
      监听抖音弹幕client推送的弹幕消息
    """
    def _wsOnMessage(self, ws, message):
        # 根据proto结构体解析对象
        package = PushFrame().parse(message)
        response = Response().parse(gzip.decompress(package.payload))

        # 返回直播间服务器链接存活确认消息，便于持续获取数据
        if response.need_ack:
            ack = PushFrame(log_id=package.log_id,
                            payload_type='ack',
                            payload=response.internal_ext.encode('utf-8')
                            ).SerializeToString()
            ws.send(ack, websocket.ABNF.OPCODE_BINARY)

        # 根据消息类别解析消息体
        for msg in response.messages_list:
            method = msg.method
            try:
                {
                    'WebcastControlMessage': self._parseControlMsg,  # 直播间状态消息
                    'WebcastChatMessage': self._parseChatMsg,  # 聊天消息
                }.get(method)(msg.payload)
            except Exception:
                pass

    """
        [抖音WebSocket] 错误
    """
    def _wsOnError(self, ws, error):
        print("[抖音WebSocket] 错误:", error)
        self._reconnect()

    """
        [抖音WebSocket] 连接关闭
    """
    def _wsOnClose(self, ws, *args):
        self.get_room_status()
        print("[抖音WebSocket] 连接关闭")
        self._reconnect()

    """
       #监听抖音直播间状态变化
    """
    def _parseControlMsg(self, payload):
        message = ControlMessage().parse(payload)
        # 推送直播间状态给客户端
        self.callback(str(message.status))
        if message.status == 3:
            print("直播间已结束")
            self.stop()

    """
      抖音client重连
    """
    def _reconnect(self, delay=3):
        if self._closed:
            return  # 避免关闭后仍重连
        print(f"[抖音WebSocket] 正在尝试重连中...（{delay}秒后）")
        time.sleep(delay)
        try:
            self._connectWebSocket()
        except Exception as e:
            # 可增加重试次数限制，防止无限重试
            print("[抖音WebSocket] 重连失败:", e)

    def _parseChatMsg(self, payload):
        """聊天消息"""
        message = ChatMessage().parse(payload)
        user_name = message.user.nick_name
        user_id = message.user.id
        content = message.content
        dy_live_Id = message.common.room_id
        data = {
            "msgId": str(uuid.uuid4()),
            "dyMsgId": message.common.msg_id,
            "danmuUserId": message.user.id,
            "danmuUserName": message.user.nick_name,
            "danmuContent": message.content,
            "dyRoomId": message.common.room_id
        }

        try:
            # 1.从redis中获取弹幕用户编号信息
            order_key = f"orderUser:dy_room_id_user:{dy_live_Id}:{user_id}"
            tag_user_str = redis_client.get(order_key)
            print(f"【redis里获取的userinfo】{tag_user_str}")
            tag_user = TagUserVo.parse_from_redis(tag_user_str) if tag_user_str else None
            if tag_user:
                data["orderNumber"] = tag_user.orderNumber or ""
            else:
                print(f"⚠️ 无法解析标签信息: {tag_user_str}")
                data["orderNumber"] = ""

            # 2. 获取黑名单信息
            black_str = redis_client.get(f"black:{user_id}")
            print(f"【redis里获取的黑名单info】{black_str}")
            if black_str:
                black_vo = FsBlackRedisVo.parse_from_redis(black_str)
            else:
                black_vo = None

            if black_vo:
                data["blackLevel"] = str(black_vo.blackLevel)
                data["createdUsers"] = black_vo.createdUsers
            else:
                data["blackLevel"] = "0"
                data["createdUsers"] = []

        except Exception as e:
            print(f"❌ 标签信息获取失败: {e}")

        print(f"【聊天msg】[{dy_live_Id}] [] [{user_id}]{user_name}: {content}")

        json_data = json.dumps(data, ensure_ascii=False)  # 转换为JSON字符串
        if self.callback:
            try:
                self.callback(json_data)
            except Exception as e:
                print(f"回调执行失败: {e}")



