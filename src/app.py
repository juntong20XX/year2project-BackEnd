import json
import os
import re

import pyotp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from iot_hostcomputer import SerialClient, start_server_daemon

app = FastAPI()

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Items
class Items:
    def __init__(self):
        self.server = start_server_daemon()
        self.client = SerialClient()
        self._items_cache = {}

    def items(self) -> tuple[str, int]:
        for path, name in self.client.get_serial_mapping().items():
            # name likes `usb-Arduino__www.arduino.cc__0043_33437363436351408031-if00`
            # name likes `usb-Arduino__www.arduino.cc__0043_243363036333517161C2-if00`
            match_name = re.match(r".+?_\d{4}_(\w+)-if00", name)
            if match_name:
                name = "Arduino " + match_name.group(1)
            yield name, self._items_cache.get(name, 90)

    def get_path_of(self, name: str) -> str:
        for path, n in self.client.get_serial_mapping().items():
            if name == n:
                return path
            number = name.split(" ")[-1]
            if f"usb-Arduino__www.arduino.cc__0043_{number}-if00" == n:
                return path
        raise KeyError

    def __getitem__(self, item):
        return self._items_cache.get(item, 90)

    def __setitem__(self, key, value):
        # assert key in self.client.get_serial_mapping().values(), KeyError("Item not found!", key)
        self.client.add_command(self.get_path_of(key), 0x0131, value)
        self._items_cache[key] = value


items = Items()

# 用户文件路径
USER_FILE = 'user_data.json'


# 确保文件存在
def ensure_files():
    # 创建用户文件（如果不存在）
    if not os.path.exists(USER_FILE):
        with open(USER_FILE, 'wb') as fp:
            fp.write(b"")


ensure_files()


# 数据模型
class UserLogin(BaseModel):
    username: str
    totp_code: str


class ItemUpdate(BaseModel):
    key: str
    value: int


# 用户注册/更新
@app.post("/register")
async def register_user(username: str):
    # 生成 TOTP secret
    totp_secret = pyotp.random_base32()

    # 读取现有用户数据
    with open(USER_FILE, 'r') as f:
        users = json.load(f)

    if len(users) > 1:
        raise HTTPException(status_code=400, detail="user exits")

    users = [username, totp_secret]

    # 写回文件
    with open(USER_FILE, 'w') as f:
        json.dump(users, f, indent=2)

    return {"username": username, "totp_secret": totp_secret}


# 用户登录
@app.post("/login")
async def login_user(user: UserLogin):
    """
    登录 用户在前端输入用户名和 totp
    但是吧, 登录成功了也不会去注册任何东西, 未登录也不影响操作 item 参数. 反正先这样吧.
    :param user:
    :return:
    """
    # 读取用户数据
    with open(USER_FILE, 'r') as f:
        username, totp_secret = json.load(f)

    # 检查用户是否存在
    if user.username != username:
        raise HTTPException(status_code=404, detail="User not found, want `%s`, got `%s`" % (username, user.username))

    # 验证 TOTP
    totp = pyotp.TOTP(totp_secret)
    if not totp.verify(user.totp_code, valid_window=14):
        raise HTTPException(status_code=401, detail="Invalid TOTP code")

    return {"message": "Login successful"}


# 获取 items
@app.get("/items")
async def get_items():
    return [{"key": k, "value": v} for k, v in items.items()]


# 更新 item
@app.put("/items")
async def update_item(item: ItemUpdate):
    # 检查 item 是否存在
    if item.key not in items:
        raise HTTPException(status_code=404, detail="Item not found")

    # 验证值范围
    if item.value < 45 or item.value > 135:
        raise HTTPException(status_code=400, detail="Value must be between 45 and 135")

    # 更新 item
    try:
        items[item.key] = item.value
    except (KeyError, AssertionError):
        raise HTTPException(status_code=404, detail="Item not found")
    else:
        return {"key": item.key, "value": item.value}
