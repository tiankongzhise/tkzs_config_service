package main

import (
	"crypto/hmac"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/pem"
	"log"
	"io/ioutil"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

var (
	privateKey *rsa.PrivateKey
	storedPwd  string // 明文密码（生产环境建议改为 bcrypt 哈希存储）
	configDir  = "."

	// 存储已使用的 nonce，值存储过期时间戳（Unix 秒）
	nonceStore sync.Map
)

func init() {
	// 启动一个 goroutine 每 10 分钟清理过期的 nonce
	go cleanExpiredNonces()

	// ----- 修改点：加载业务 RSA 私钥（错误输出到 stderr）-----
	keyBytes, err := ioutil.ReadFile("server_private_key.pem")
	if err != nil {
		log.Printf("failed to read business private key: %v\n", err)
		panic("failed to read business private key: " + err.Error())
	}
	block, _ := pem.Decode(keyBytes)
	if block == nil || block.Type != "PRIVATE KEY" {
		log.Printf( "invalid business private key format\n")
		panic("invalid business private key format")
	}

	key, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		privateKey, err = x509.ParsePKCS1PrivateKey(block.Bytes)
		if err != nil {
			log.Printf( "failed to parse business private key: %v\n", err)
			panic("failed to parse business private key: " + err.Error())
		}
	} else {
		var ok bool
		privateKey, ok = key.(*rsa.PrivateKey)
		if !ok {
			log.Printf( "not an RSA private key\n")
			panic("not an RSA private key")
		}
	}

	// 从 .env 读取明文密码
	pwdBytes, err := ioutil.ReadFile(".env")
	if err != nil {
		log.Printf( "failed to read .env: %v\n", err)
		panic("failed to read .env: " + err.Error())
	}
	lines := strings.Split(string(pwdBytes), "\n")
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			continue
		}
		parts := strings.SplitN(trimmed, "=", 2)
		if len(parts) == 2 && strings.TrimSpace(parts[0]) == "PASSWORD" {
			storedPwd = strings.TrimSpace(parts[1])
			break
		}
	}
	if storedPwd == "" {
		log.Printf( "PASSWORD not found in .env\n")
		panic("PASSWORD not found in .env")
	}
}

func main() {
	http.HandleFunc("/get-config", authHandler)
	// 使用 log 输出启动信息
	log.Printf("✅ Server starting successfully on http://0.0.0.0:8443")
	log.Printf("✅ HandleFunc /get-config registered success")

	err := http.ListenAndServe(":8443", nil)
	if err != nil {
		log.Printf( "failed to listen and serve http: %v\n", err)
		panic(err)
	}
}

// cleanExpiredNonces 每 10 分钟清理一次过期的 nonce
func cleanExpiredNonces() {
	ticker := time.NewTicker(10 * time.Minute)
	defer ticker.Stop()
	for range ticker.C {
		now := time.Now().Unix()
		nonceStore.Range(func(key, value interface{}) bool {
			expiry := value.(int64)
			if now > expiry {
				nonceStore.Delete(key)
			}
			return true
		})
		// 内部清理记录，不暴露给客户端
		log.Printf("Cleaned expired nonces")
	}
}

func authHandler(w http.ResponseWriter, r *http.Request) {
	// ----- 修改点：统一对外返回 Unauthorized，内部记录详细错误 -----
	if r.Method != http.MethodPost {
		log.Printf( "Method not allowed: %s\n", r.Method)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	encryptedData, err := ioutil.ReadAll(r.Body)
	if err != nil || len(encryptedData) == 0 {
		log.Printf( "Bad request: %v, len=%d\n", err, len(encryptedData))
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	// 业务 RSA 解密
	decrypted, err := rsa.DecryptPKCS1v15(nil, privateKey, encryptedData)
	if err != nil {
		log.Printf( "Decryption failed: %v\n", err)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	// ----- 修改点：解析格式改为 salt:hmac:filename:timestamp:nonce -----
	parts := strings.SplitN(string(decrypted), ":", 5)
	if len(parts) != 5 {
		log.Printf( "Invalid format, expected 5 parts, got %d\n", len(parts))
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}
	salt, clientHMAC, filename, timestampStr, nonce := parts[0], parts[1], parts[2], parts[3], parts[4]

	// ----- 修改点：校验时间戳（允许前后5分钟误差）-----
	ts, err := strconv.ParseInt(timestampStr, 10, 64)
	if err != nil {
		log.Printf( "Invalid timestamp: %s, err: %v\n", timestampStr, err)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}
	now := time.Now().Unix()
	if ts < now-300 || ts > now+300 {
		log.Printf( "Timestamp out of window: %d, now: %d\n", ts, now)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	// ----- 修改点：防重放 - 检查 nonce 是否已使用 -----
	expiry := now + 600 // 10分钟有效期
	if _, loaded := nonceStore.LoadOrStore(nonce, expiry); loaded {
		log.Printf( "Replayed nonce: %s\n", nonce)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	// ----- 修改点：使用 HMAC-SHA256 验证 -----
	message := salt + ":" + filename + ":" + timestampStr + ":" + nonce
	h := hmac.New(sha256.New, []byte(storedPwd))
	h.Write([]byte(message))
	expectedHMAC := hex.EncodeToString(h.Sum(nil))
	if !hmac.Equal([]byte(clientHMAC), []byte(expectedHMAC)) {
		log.Printf( "HMAC mismatch, client: %s, expected: %s\n", clientHMAC, expectedHMAC)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	// ----- 修改点：增强路径校验，防止目录遍历 -----
	if strings.Contains(filename, "..") || strings.ContainsAny(filename, "/\\") {
		log.Printf( "Invalid filename: %s\n", filename)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}
	absConfigDir, err := filepath.Abs(configDir)
	if err != nil {
		log.Printf( "Failed to get absolute config dir: %v\n", err)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}
	filePath := filepath.Join(absConfigDir, filename)
	absPath, err := filepath.Abs(filePath)
	if err != nil || !strings.HasPrefix(absPath, absConfigDir+string(os.PathSeparator)) {
		log.Printf( "Path traversal attempt: %s -> %s\n", filename, absPath)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	content, err := ioutil.ReadFile(filePath)
	if err != nil {
		if os.IsNotExist(err) {
			log.Printf( "Config file not found: %s\n", filePath)
		} else {
			log.Printf( "Read file error: %v\n", err)
		}
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	w.Header().Set("Content-Type", "application/octet-stream")
	w.WriteHeader(http.StatusOK)
	w.Write(content)
	// 内部记录成功，不暴露敏感信息
	log.Printf( "Config returned successfully: %s\n", filename)
}