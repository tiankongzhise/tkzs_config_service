"""API通信模块

封装与服务端的所有HTTP通信，包括注册、登录和配置管理接口。
"""

import json
import logging
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin, quote

import requests
from .config import DEFAULT_CLIENT_CONFIG


class APIError(Exception):
    """API请求错误"""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"API Error {status_code}: {message}")


class APIClient:
    """API客户端"""

    def __init__(self, base_url: str, token_manager, logger: Optional[logging.Logger] = None):
        """
        初始化API客户端

        Args:
            base_url: 服务端基础URL
            token_manager: Token管理器实例
            logger: 日志记录器
        """
        self.base_url = base_url.rstrip("/")
        self.token_manager = token_manager
        self.logger = logger or logging.getLogger(__name__)
        self.timeout = DEFAULT_CLIENT_CONFIG.request_timeout_seconds

    def _get_headers(self, need_auth: bool = True) -> Dict[str, str]:
        """
        获取请求头

        Args:
            need_auth: 是否需要认证

        Returns:
            请求头字典
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        if need_auth:
            token = self.token_manager.get_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        return headers

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """
        处理API响应

        Args:
            response: requests响应对象

        Returns:
            解析后的JSON数据

        Raises:
            APIError: 当响应状态码不为200-299时
        """
        try:
            data = response.json()
        except json.JSONDecodeError:
            raise APIError(response.status_code, f"Invalid JSON response: {response.text[:200]}")

        if not (200 <= response.status_code < 300):
            message = data.get("error") or data.get("message") or "Unknown error"
            raise APIError(response.status_code, message)

        # 兼容服务端统一响应格式: {"success": bool, "message": str, "data": {...}}
        if isinstance(data, dict) and "data" in data:
            payload = data.get("data")
            if isinstance(payload, dict):
                return payload
            return {}

        return data

    def _request(self, method: str, endpoint: str, need_auth: bool = True,
                 **kwargs) -> Dict[str, Any]:
        """
        发送HTTP请求

        Args:
            method: HTTP方法
            endpoint: API端点
            need_auth: 是否需要认证
            **kwargs: 其他requests参数

        Returns:
            解析后的响应数据

        Raises:
            APIError: 请求失败时
        """
        url = urljoin(self.base_url, endpoint)
        headers = self._get_headers(need_auth)

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                timeout=self.timeout,
                **kwargs
            )
            return self._handle_response(response)
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request failed,url: {url}, error: {str(e)}")
            raise APIError(0, f"Request failed: {str(e)}")

    # ============ 用户认证接口 ============

    def register(self, username: str, password: str, public_key: str) -> Dict[str, Any]:
        """
        用户注册

        Args:
            username: 用户名
            password: 密码
            public_key: RSA公钥（PEM格式字符串）

        Returns:
            注册结果，包含user_id
        """
        payload = {
            "username": username,
            "password": password,
            "public_key": public_key
        }

        self.logger.info(f"Registering user: {username}")
        return self._request("POST", "/api/register", need_auth=False, json=payload)

    def login(self, username: str, password: str) -> Dict[str, Any]:
        """
        用户登录

        Args:
            username: 用户名
            password: 密码

        Returns:
            登录结果，包含access_token
        """
        payload = {
            "username": username,
            "password": password
        }

        self.logger.info(f"Logging in user: {username}")
        data = self._request("POST", "/api/login", need_auth=False, json=payload)

        # 保存token
        self.token_manager.save_token(
            access_token=data["access_token"],
            expires_in=data["expires_in"],
            user_id=data["user_id"],
            username=data["username"]
        )

        return data

    def logout(self) -> None:
        """退出登录，清除本地Token"""
        self.token_manager.clear_token()
        self.logger.info("Logged out")

    # ============ 配置管理接口 ============

    def list_configs(self) -> List[Dict[str, Any]]:
        """
        获取配置列表

        Returns:
            配置列表
        """
        self.logger.info("Fetching config list")
        data = self._request("GET", "/api/configs")
        return data.get("configs", [])

    def upload_config(self, config_name: str, encrypted_content: str,
                      encrypted_aes_key: str) -> Dict[str, Any]:
        """
        上传配置

        Args:
            config_name: 配置名称
            encrypted_content: Base64编码的加密内容
            encrypted_aes_key: Base64编码的加密AES密钥

        Returns:
            上传结果
        """
        self.logger.info(f"Uploading config: {config_name}")

        # 使用multipart表单上传
        url = urljoin(self.base_url, "/api/config/upload")
        headers = self._get_headers()
        headers.pop("Content-Type")  # 让requests自动设置multipart的Content-Type

        try:
            response = requests.post(
                url,
                headers=headers,
                timeout=self.timeout,
                files={
                    "config_name": (None, config_name),
                    "encrypted_content": (None, encrypted_content),
                    "encrypted_aes_key": (None, encrypted_aes_key),
                }
            )
            return self._handle_response(response)
        except requests.exceptions.RequestException as e:
            raise APIError(0, f"Request failed: {str(e)}")

    def get_config(self, config_name: str) -> Dict[str, Any]:
        """
        获取配置

        Args:
            config_name: 配置名称

        Returns:
            配置数据，包含加密内容和加密密钥
        """
        self.logger.info(f"Getting config: {config_name}")
        safe_name = quote(config_name, safe="")
        return self._request("GET", f"/api/config?name={safe_name}")

    def update_config(self, config_name: str, encrypted_content: str,
                      encrypted_aes_key: str) -> Dict[str, Any]:
        """
        更新配置

        Args:
            config_name: 配置名称
            encrypted_content: Base64编码的加密内容
            encrypted_aes_key: Base64编码的加密AES密钥

        Returns:
            更新结果
        """
        self.logger.info(f"Updating config: {config_name}")

        # 使用multipart表单上传
        safe_name = quote(config_name, safe="")
        url = urljoin(self.base_url, f"/api/config?name={safe_name}")
        headers = self._get_headers()
        headers.pop("Content-Type")

        try:
            response = requests.put(
                url,
                headers=headers,
                timeout=self.timeout,
                files={
                    "encrypted_content": (None, encrypted_content),
                    "encrypted_aes_key": (None, encrypted_aes_key),
                }
            )
            return self._handle_response(response)
        except requests.exceptions.RequestException as e:
            raise APIError(0, f"Request failed: {str(e)}")

    def delete_config(self, config_name: str) -> Dict[str, Any]:
        """
        删除配置

        Args:
            config_name: 配置名称

        Returns:
            删除结果
        """
        self.logger.info(f"Deleting config: {config_name}")
        safe_name = quote(config_name, safe="")
        return self._request("DELETE", f"/api/config?name={safe_name}")

    # ============ 辅助方法 ============

    def health_check(self) -> bool:
        """
        健康检查

        Returns:
            服务是否正常
        """
        try:
            url = urljoin(self.base_url, "/health")
            response = requests.get(url, timeout=self.timeout)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
