"""认证和Token管理模块

处理JWT Token的存储、获取和验证，以及用户会话管理。
"""

import json
from pathlib import Path
from typing import Optional
import time

import jwt


class AuthError(Exception):
    """认证相关错误"""
    pass


class TokenManager:
    """JWT Token管理器"""

    DEFAULT_TOKEN_DIR = Path.home() / ".config" / "tkzs_service"
    TOKEN_FILE = "token.json"

    def __init__(self, token_dir: Optional[Path] = None):
        """
        初始化Token管理器

        Args:
            token_dir: Token存储目录，默认为 ~/.config/tkzs_service
        """
        self.token_dir = token_dir or self.DEFAULT_TOKEN_DIR
        self.token_file = self.token_dir / self.TOKEN_FILE

    def save_token(self, access_token: str, expires_in: int, user_id: int, username: str) -> None:
        """
        保存Token到本地文件

        Args:
            access_token: JWT访问令牌
            expires_in: 有效期（秒）
            user_id: 用户ID
            username: 用户名
        """
        self.token_dir.mkdir(parents=True, exist_ok=True)

        # 计算过期时间戳
        expires_at = int(time.time()) + expires_in

        token_data = {
            "access_token": access_token,
            "expires_in": expires_in,
            "expires_at": expires_at,
            "user_id": user_id,
            "username": username
        }

        self.token_file.write_text(json.dumps(token_data, indent=2))
        # 设置文件权限
        self.token_file.chmod(0o600)

    def load_token(self) -> Optional[dict]:
        """
        从本地文件加载Token

        Returns:
            Token数据字典，如果不存在或已过期返回None
        """
        if not self.token_file.exists():
            return None

        try:
            token_data = json.loads(self.token_file.read_text())

            # 检查是否过期
            if token_data.get("expires_at", 0) < int(time.time()):
                self.clear_token()
                return None

            return token_data
        except (json.JSONDecodeError, IOError):
            return None

    def get_token(self) -> Optional[str]:
        """
        获取有效的Token字符串

        Returns:
            Token字符串，如果不存在或已过期返回None
        """
        token_data = self.load_token()
        if token_data:
            return token_data.get("access_token")
        return None

    def get_user_info(self) -> Optional[dict]:
        """
        获取用户信息

        Returns:
            包含user_id和username的字典
        """
        token_data = self.load_token()
        if token_data:
            return {
                "user_id": token_data.get("user_id"),
                "username": token_data.get("username")
            }
        return None

    def clear_token(self) -> None:
        """清除本地存储的Token"""
        if self.token_file.exists():
            self.token_file.unlink()

    def is_authenticated(self) -> bool:
        """
        检查是否已认证（有效的Token）

        Returns:
            是否已认证
        """
        return self.get_token() is not None


def decode_token(token: str) -> dict:
    """
    解码JWT Token（不验证签名）

    Args:
        token: JWT token字符串

    Returns:
        Token payload字典
    """
    try:
        # 不验证签名，只提取payload
        payload = jwt.decode(token, options={"verify_signature": False})
        return payload
    except jwt.exceptions.DecodeError as e:
        raise AuthError(f"Invalid token format: {e}")


def is_token_expired(token: str) -> bool:
    """
    检查Token是否过期

    Args:
        token: JWT token字符串

    Returns:
        是否过期
    """
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        exp = payload.get("exp", 0)
        return int(time.time()) >= exp
    except jwt.exceptions.DecodeError:
        return True
