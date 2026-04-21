package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
)

// AESKeySize AES密钥大小
const AESKeySize = 32 // 256 bits

// EncryptedData 加密数据结果
type EncryptedData struct {
	EncryptedContent []byte `json:"encrypted_content"`
	EncryptedAESKey []byte `json:"encrypted_aes_key"`
}

// EncryptWithPublicKey 使用RSA公钥加密数据
func EncryptWithPublicKey(publicKey *rsa.PublicKey, plaintext []byte) ([]byte, error) {
	// 使用OAEP填充进行加密
	ciphertext, err := rsa.EncryptOAEP(
		sha256.New(),
		rand.Reader,
		publicKey,
		plaintext,
		nil,
	)
	if err != nil {
		return nil, fmt.Errorf("RSA encryption failed: %w", err)
	}
	return ciphertext, nil
}

// EncryptWithPublicKeyChunked 使用RSA公钥分块加密数据（用于较大明文）
func EncryptWithPublicKeyChunked(publicKey *rsa.PublicKey, plaintext []byte) ([]byte, error) {
	keyBytes := publicKey.Size()
	hashSize := sha256.Size
	maxChunkSize := keyBytes - 2*hashSize - 2
	if maxChunkSize <= 0 {
		return nil, errors.New("invalid RSA key size for OAEP")
	}

	encrypted := make([]byte, 0, ((len(plaintext)+maxChunkSize-1)/maxChunkSize)*keyBytes)
	for offset := 0; offset < len(plaintext); offset += maxChunkSize {
		end := offset + maxChunkSize
		if end > len(plaintext) {
			end = len(plaintext)
		}

		block, err := EncryptWithPublicKey(publicKey, plaintext[offset:end])
		if err != nil {
			return nil, err
		}
		encrypted = append(encrypted, block...)
	}
	return encrypted, nil
}

// DecryptWithPrivateKey 使用RSA私钥解密数据
func DecryptWithPrivateKey(privateKey *rsa.PrivateKey, ciphertext []byte) ([]byte, error) {
	plaintext, err := rsa.DecryptOAEP(
		sha256.New(),
		rand.Reader,
		privateKey,
		ciphertext,
		nil,
	)
	if err != nil {
		return nil, fmt.Errorf("RSA decryption failed: %w", err)
	}
	return plaintext, nil
}

// GenerateAESKey 生成随机AES密钥
func GenerateAESKey() ([]byte, error) {
	key := make([]byte, AESKeySize)
	if _, err := io.ReadFull(rand.Reader, key); err != nil {
		return nil, fmt.Errorf("failed to generate AES key: %w", err)
	}
	return key, nil
}

// AESEncrypt 使用AES-GCM加密数据
func AESEncrypt(plaintext, key []byte) ([]byte, error) {
	if len(key) != AESKeySize {
		return nil, errors.New("invalid AES key size")
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("failed to create cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("failed to create GCM: %w", err)
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, fmt.Errorf("failed to generate nonce: %w", err)
	}

	// 格式: nonce + ciphertext
	ciphertext := gcm.Seal(nonce, nonce, plaintext, nil)
	return ciphertext, nil
}

// AESDecrypt 使用AES-GCM解密数据
func AESDecrypt(ciphertext, key []byte) ([]byte, error) {
	if len(key) != AESKeySize {
		return nil, errors.New("invalid AES key size")
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("failed to create cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("failed to create GCM: %w", err)
	}

	nonceSize := gcm.NonceSize()
	if len(ciphertext) < nonceSize {
		return nil, errors.New("ciphertext too short")
	}

	nonce, ciphertext := ciphertext[:nonceSize], ciphertext[nonceSize:]
	plaintext, err := gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return nil, fmt.Errorf("AES decryption failed: %w", err)
	}

	return plaintext, nil
}

// EncryptForUser 加密数据供特定用户使用
// 1. 生成随机AES密钥
// 2. 使用AES加密内容
// 3. 使用用户公钥加密AES密钥
func EncryptForUser(publicKey *rsa.PublicKey, content []byte) (*EncryptedData, error) {
	// 生成AES密钥
	aesKey, err := GenerateAESKey()
	if err != nil {
		return nil, err
	}

	// 使用AES加密内容
	encryptedContent, err := AESEncrypt(content, aesKey)
	if err != nil {
		return nil, fmt.Errorf("AES encryption failed: %w", err)
	}

	// 使用RSA公钥加密AES密钥
	encryptedAESKey, err := EncryptWithPublicKey(publicKey, aesKey)
	if err != nil {
		return nil, fmt.Errorf("RSA key encryption failed: %w", err)
	}

	return &EncryptedData{
		EncryptedContent: encryptedContent,
		EncryptedAESKey:  encryptedAESKey,
	}, nil
}

// DecryptForUser 解密用户数据
// 1. 使用RSA私钥解密AES密钥
// 2. 使用AES密钥解密内容
func DecryptForUser(privateKey *rsa.PrivateKey, encryptedContent, encryptedAESKey []byte) ([]byte, error) {
	// 使用RSA私钥解密AES密钥
	aesKey, err := DecryptWithPrivateKey(privateKey, encryptedAESKey)
	if err != nil {
		return nil, fmt.Errorf("AES key decryption failed: %w", err)
	}

	// 使用AES密钥解密内容
	plaintext, err := AESDecrypt(encryptedContent, aesKey)
	if err != nil {
		return nil, fmt.Errorf("content decryption failed: %w", err)
	}

	return plaintext, nil
}
