package main

import (
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/pem"
	"io/ioutil"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"log"
)

var (
	privateKey *rsa.PrivateKey
	storedPwd  string
	configDir  = "."
)

func init() {
	// 加载业务 RSA 私钥（用于解密客户端发来的加密密码）
	keyBytes, err := ioutil.ReadFile("server_private_key.pem") // 业务私钥
	if err != nil {
		log.Printf("failed to read business private key: %v", err)
		panic("failed to read business private key: " + err.Error())
	}
	block, _ := pem.Decode(keyBytes)
	if block == nil || block.Type != "PRIVATE KEY" {
		log.Printf("[ERROR]invalid business private key format")
		panic("invalid business private key format")
	}

	// 修复：正确解析 PKCS8 私钥 + 类型断言
	key, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		// 尝试解析 PKCS1
		privateKey, err = x509.ParsePKCS1PrivateKey(block.Bytes)
		if err != nil {
			log.Printf("failed to parse business private key: %v", err)
			panic("failed to parse business private key: " + err.Error())
		}
	} else {
		// 断言为 *rsa.PrivateKey
		var ok bool
		privateKey, ok = key.(*rsa.PrivateKey)
		if !ok {
			log.Printf("not an RSA private key")
			panic("not an RSA private key")
		}
	}

	// 从 .env 读取明文密码（生产环境建议哈希存储）
	pwdBytes, err := ioutil.ReadFile(".env")
	if err != nil {
		log.Printf("failed to read .env: %v", err)
		panic("failed to read .env: " + err.Error())
	}
	lines := strings.Split(string(pwdBytes), "\n")
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			continue
		}

		// ========== 终极修复：自动切割 = 两边的空格 ==========
		parts := strings.SplitN(trimmed, "=", 2)
		if len(parts) == 2 && strings.TrimSpace(parts[0]) == "PASSWORD" {
			storedPwd = strings.TrimSpace(parts[1])
			break
		}
	}

	if storedPwd == "" {
		log.Printf("[ERROR]PASSWORD not found in .env")
		panic("PASSWORD not found in .env")
	}
}

func main() {
	http.HandleFunc("/get-config", authHandler)
	// 先打印日志，再启动服务
	log.Println("✅ Server starting successfully on http://0.0.0.0:8443")
	log.Println("✅ HandleFunc /get-config registered success")

	err := http.ListenAndServe(":8443", nil)
	if err != nil {
		log.Printf("failed to listen and serve http: %v", err)
		panic(err)
	}
	log.Println("✅ HandleFunc /get-config registered shutdown")

}

func authHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		log.Printf("http error Method not allowed ", http.StatusMethodNotAllowed)
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	encryptedData, err := ioutil.ReadAll(r.Body)
	if err != nil || len(encryptedData) == 0 {
		log.Printf("Bad request: %v", err)
		http.Error(w, "Bad request", http.StatusBadRequest)
		return
	}

	// 业务 RSA 解密
	decrypted, err := rsa.DecryptPKCS1v15(nil, privateKey, encryptedData)
	if err != nil {
		log.Printf("Decryption failed: %v", err)
		http.Error(w, "Decryption failed", http.StatusBadRequest)
		return
	}

	// 解析格式: salt:hash:filename
	parts := strings.SplitN(string(decrypted), ":", 3)
	if len(parts) < 2 {
		log.Printf("[ERROR]Invalid format: ", http.StatusBadRequest)
		http.Error(w, "Invalid format", http.StatusBadRequest)
		return
	}
	salt, clientHash := parts[0], parts[1]
	filename := "config.toml"
	if len(parts) >= 3 && parts[2] != "" {
		filename = parts[2]
	}

	// 验证密码
	hash := sha256.Sum256([]byte(salt + storedPwd))
	expectedHash := hex.EncodeToString(hash[:])
	if clientHash != expectedHash {
		log.Printf("[ERROR]Password error: ", http.StatusUnauthorized)
		http.Error(w, "Password error", http.StatusUnauthorized)
		return
	}

	// 安全校验文件名
	if strings.Contains(filename, "..") || strings.ContainsAny(filename, "/\\") {
		log.Printf("[ERROR]Invalid filename: ", http.StatusBadRequest)
		http.Error(w, "Invalid filename", http.StatusBadRequest)
		return
	}

	filePath := filepath.Join(configDir, filename)
	content, err := ioutil.ReadFile(filePath)
	if err != nil {
		if os.IsNotExist(err) {
			log.Printf("[ERROR]Config file not found: ", http.StatusNotFound)
			http.Error(w, "Config file not found", http.StatusNotFound)
		} else {
			log.Printf("[ERROR]Internal server error: ", http.StatusInternalServerError)
			http.Error(w, "Internal server error", http.StatusInternalServerError)
		}
		return
	}

	w.Header().Set("Content-Type", "application/octet-stream")
	w.WriteHeader(http.StatusOK)
	w.Write(content)
	log.Printf("config return success: ", filename)
}