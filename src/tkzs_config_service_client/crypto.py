"""加密工具模块

提供RSA密钥生成、AES加密/解密功能，用于配置文件的安全传输。
"""

import base64
import secrets
from pathlib import Path
from typing import Tuple

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend


class CryptoError(Exception):
    """加密相关错误"""
    pass


class RSACrypto:
    """RSA加密工具类"""

    KEY_SIZE = 2048  # RSA密钥大小

    @staticmethod
    def generate_keypair() -> Tuple[bytes, bytes]:
        """
        生成RSA密钥对

        Returns:
            Tuple[私钥PEM, 公钥PEM]
        """
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=RSACrypto.KEY_SIZE,
            backend=default_backend()
        )
        public_key = private_key.public_key()

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        return private_pem, public_pem

    @staticmethod
    def load_private_key(private_key_pem: bytes) -> rsa.RSAPrivateKey:
        """
        加载RSA私钥

        Args:
            private_key_pem: 私钥PEM数据

        Returns:
            RSA私钥对象
        """
        return serialization.load_pem_private_key(
            private_key_pem,
            password=None,
            backend=default_backend()
        )

    @staticmethod
    def load_public_key(public_key_pem: bytes) -> rsa.RSAPublicKey:
        """
        加载RSA公钥

        Args:
            public_key_pem: 公钥PEM数据

        Returns:
            RSA公钥对象
        """
        return serialization.load_pem_public_key(
            public_key_pem,
            backend=default_backend()
        )

    @staticmethod
    def encrypt(public_key: rsa.RSAPublicKey, plaintext: bytes) -> bytes:
        """
        使用RSA公钥加密数据（OAEP填充）

        Args:
            public_key: RSA公钥
            plaintext: 明文数据

        Returns:
            密文数据
        """
        ciphertext = public_key.encrypt(
            plaintext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        return ciphertext

    @staticmethod
    def decrypt(private_key: rsa.RSAPrivateKey, ciphertext: bytes) -> bytes:
        """
        使用RSA私钥解密数据（OAEP填充）

        Args:
            private_key: RSA私钥
            ciphertext: 密文数据

        Returns:
            明文数据
        """
        plaintext = private_key.decrypt(
            ciphertext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        return plaintext


class AESCrypto:
    """AES加密工具类"""

    KEY_SIZE = 32  # 256 bits
    NONCE_SIZE = 12  # 96 bits for GCM

    @staticmethod
    def generate_key() -> bytes:
        """
        生成随机AES密钥

        Returns:
            32字节的AES密钥
        """
        return secrets.token_bytes(AESCrypto.KEY_SIZE)

    @staticmethod
    def encrypt(plaintext: bytes, key: bytes) -> bytes:
        """
        使用AES-GCM加密数据

        Args:
            plaintext: 明文数据
            key: 32字节AES密钥

        Returns:
            加密后的数据（包含nonce）
        """
        if len(key) != AESCrypto.KEY_SIZE:
            raise CryptoError(f"Invalid AES key size: {len(key)}, expected {AESCrypto.KEY_SIZE}")

        aesgcm = AESGCM(key)
        nonce = secrets.token_bytes(AESCrypto.NONCE_SIZE)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    @staticmethod
    def decrypt(ciphertext: bytes, key: bytes) -> bytes:
        """
        使用AES-GCM解密数据

        Args:
            ciphertext: 加密数据（包含nonce）
            key: 32字节AES密钥

        Returns:
            解密后的明文
        """
        if len(key) != AESCrypto.KEY_SIZE:
            raise CryptoError(f"Invalid AES key size: {len(key)}, expected {AESCrypto.KEY_SIZE}")

        if len(ciphertext) < AESCrypto.NONCE_SIZE:
            raise CryptoError("Ciphertext too short")

        nonce = ciphertext[:AESCrypto.NONCE_SIZE]
        actual_ciphertext = ciphertext[AESCrypto.NONCE_SIZE:]

        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, actual_ciphertext, None)
        return plaintext


def save_private_key(private_key_pem: bytes, path: Path) -> None:
    """
    保存私钥到文件

    Args:
        private_key_pem: 私钥PEM数据
        path: 保存路径
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(private_key_pem)
    # 设置文件权限为所有者可读写
    path.chmod(0o600)


def load_private_key(path: Path) -> bytes:
    """
    从文件加载私钥

    Args:
        path: 私钥文件路径

    Returns:
        私钥PEM数据
    """
    return path.read_bytes()
