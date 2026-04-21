package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"path/filepath"
	"strings"
)

// setupRoutes 设置所有路由
func setupRoutes() {
	// 公开接口
	http.HandleFunc("/api/register", handleRegister)
	http.HandleFunc("/api/login", handleLogin)

	// 需要JWT认证的接口
	http.HandleFunc("/api/configs", JWTAuthMiddleware(handleListConfigs))
	http.HandleFunc("/api/config/upload", JWTAuthMiddleware(handleUploadConfig))
	http.HandleFunc("/api/config", JWTAuthMiddleware(handleConfigOperation))
	http.HandleFunc("/api/config/", JWTAuthMiddleware(handleConfigOperation))

	// 健康检查
	http.HandleFunc("/health", handleHealth)

	log.Printf("✅ Routes registered successfully")
}

// handleHealth 健康检查
func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "healthy",
		"service": "tkzs-config-service",
	})
}

// handleRegister 处理用户注册
func handleRegister(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		sendJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		sendJSONError(w, http.StatusBadRequest, "Failed to read request body")
		return
	}

	var req RegisterRequest
	if err := json.Unmarshal(body, &req); err != nil {
		sendJSONError(w, http.StatusBadRequest, "Invalid JSON format")
		return
	}

	// 验证请求
	if strings.TrimSpace(req.Username) == "" {
		sendJSONError(w, http.StatusBadRequest, "Username is required")
		return
	}
	if len(req.Password) < 6 {
		sendJSONError(w, http.StatusBadRequest, "Password must be at least 6 characters")
		return
	}
	if strings.TrimSpace(req.PublicKey) == "" {
		sendJSONError(w, http.StatusBadRequest, "Public key is required")
		return
	}

	// 验证公钥格式
	pubKey, err := ParsePublicKey(req.PublicKey)
	if err != nil {
		log.Printf("Invalid public key: %v", err)
		sendJSONError(w, http.StatusBadRequest, "Invalid public key format")
		return
	}
	_ = pubKey // 公钥已验证，稍后存储

	// 加密密码
	passwordHash, err := HashPassword(req.Password)
	if err != nil {
		log.Printf("Failed to hash password: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Failed to process password")
		return
	}

	// 创建用户
	userID, err := CreateUser(req.Username, passwordHash, req.PublicKey)
	if err != nil {
		log.Printf("Failed to create user: %v", err)
		sendJSONError(w, http.StatusConflict, err.Error())
		return
	}

	log.Printf("✅ User registered: %s (ID: %d)", req.Username, userID)
	sendJSONResponse(w, http.StatusCreated, "User registered successfully", map[string]interface{}{
		"user_id":  userID,
		"username": req.Username,
	})
}

// handleLogin 处理用户登录
func handleLogin(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		sendJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		sendJSONError(w, http.StatusBadRequest, "Failed to read request body")
		return
	}

	var req LoginRequest
	if err := json.Unmarshal(body, &req); err != nil {
		sendJSONError(w, http.StatusBadRequest, "Invalid JSON format")
		return
	}

	// 验证请求
	if strings.TrimSpace(req.Username) == "" {
		sendJSONError(w, http.StatusBadRequest, "Username is required")
		return
	}
	if req.Password == "" {
		sendJSONError(w, http.StatusBadRequest, "Password is required")
		return
	}

	// 获取用户
	user, err := GetUserByUsername(req.Username)
	if err != nil {
		log.Printf("Failed to get user: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	if user == nil {
		sendJSONError(w, http.StatusUnauthorized, "Invalid username or password")
		return
	}

	// 验证密码
	if !CheckPassword(req.Password, user.PasswordHash) {
		log.Printf("Password mismatch for user: %s", req.Username)
		sendJSONError(w, http.StatusUnauthorized, "Invalid username or password")
		return
	}

	// 生成JWT Token
	token, err := GenerateToken(user.ID, user.Username)
	if err != nil {
		log.Printf("Failed to generate token: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Failed to generate token")
		return
	}

	log.Printf("✅ User logged in: %s (ID: %d)", user.Username, user.ID)
	sendJSONResponse(w, http.StatusOK, "Login successful", LoginResponse{
		AccessToken: token,
		ExpiresIn:   int64(jwtExpiration.Seconds()),
		TokenType:   "Bearer",
		UserID:      user.ID,
		Username:    user.Username,
	})
}

// handleListConfigs 处理配置列表
func handleListConfigs(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		sendJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}

	claims := GetUserFromRequest(r)
	if claims == nil {
		sendJSONError(w, http.StatusUnauthorized, "User not authenticated")
		return
	}

	configs, err := ListConfigs(claims.UserID)
	if err != nil {
		log.Printf("Failed to list configs: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Failed to list configs")
		return
	}

	items := make([]ConfigListItem, 0, len(configs))
	for _, c := range configs {
		items = append(items, ConfigListItem{
			ID:         c.ID,
			ConfigName: c.ConfigName,
			CreatedAt:  c.CreatedAt,
			UpdatedAt:  c.UpdatedAt,
		})
	}

	sendJSONResponse(w, http.StatusOK, "Configs retrieved successfully", map[string]interface{}{
		"configs": items,
		"count":   len(items),
	})
}

// handleUploadConfig 处理配置上传
func handleUploadConfig(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		sendJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}

	claims := GetUserFromRequest(r)
	if claims == nil {
		sendJSONError(w, http.StatusUnauthorized, "User not authenticated")
		return
	}

	// 解析 multipart 表单
	if err := r.ParseMultipartForm(32 << 20); err != nil { // 32MB
		sendJSONError(w, http.StatusBadRequest, "Failed to parse form data")
		return
	}

	configName := r.FormValue("config_name")
	if configName == "" {
		sendJSONError(w, http.StatusBadRequest, "config_name is required")
		return
	}

	// 验证文件名安全性
	if strings.Contains(configName, "..") || strings.ContainsAny(configName, "/\\") {
		sendJSONError(w, http.StatusBadRequest, "Invalid config name")
		return
	}

	// 获取加密的内容和密钥
	encryptedContentStr := r.FormValue("encrypted_content")
	encryptedAESKeyStr := r.FormValue("encrypted_aes_key")

	if encryptedContentStr == "" || encryptedAESKeyStr == "" {
		sendJSONError(w, http.StatusBadRequest, "encrypted_content and encrypted_aes_key are required")
		return
	}

	// 解码base64
	encryptedContent, err := base64Decode(encryptedContentStr)
	if err != nil {
		sendJSONError(w, http.StatusBadRequest, "Invalid encrypted_content format")
		return
	}

	encryptedAESKey, err := base64Decode(encryptedAESKeyStr)
	if err != nil {
		sendJSONError(w, http.StatusBadRequest, "Invalid encrypted_aes_key format")
		return
	}

	// 获取用户公钥进行二次加密（分块RSA，避免长度超限）
	user, err := GetUserByID(claims.UserID)
	if err != nil || user == nil {
		sendJSONError(w, http.StatusInternalServerError, "Failed to get user info")
		return
	}

	userPubKey, err := ParsePublicKey(user.PublicKey)
	if err != nil {
		log.Printf("Failed to parse user public key: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Failed to process public key")
		return
	}

	doubleEncryptedAESKey, err := EncryptWithPublicKeyChunked(userPubKey, encryptedAESKey)
	if err != nil {
		log.Printf("Failed to double encrypt AES key: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Failed to encrypt data")
		return
	}

	configID, err := CreateConfig(claims.UserID, configName, doubleEncryptedAESKey, encryptedContent)
	if err != nil {
		if strings.Contains(err.Error(), "already exists") {
			sendJSONError(w, http.StatusConflict, "Config already exists, use update instead")
			return
		}
		log.Printf("Failed to create config: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Failed to save config")
		return
	}

	log.Printf("✅ Config uploaded: %s by user %s (ID: %d)", configName, claims.Username, claims.UserID)
	sendJSONResponse(w, http.StatusCreated, "Config uploaded successfully", map[string]interface{}{
		"config_id":   configID,
		"config_name": configName,
	})
}

// handleConfigOperation 处理配置的GET/PUT/DELETE操作
func handleConfigOperation(w http.ResponseWriter, r *http.Request) {
	claims := GetUserFromRequest(r)
	if claims == nil {
		sendJSONError(w, http.StatusUnauthorized, "User not authenticated")
		return
	}

	// 兼容两种方式：
	// 1) 路径参数: /api/config/{name}
	// 2) 查询参数: /api/config?name={name}
	var configName string
	if r.URL.Path == "/api/config" || r.URL.Path == "/api/config/" {
		configName = strings.TrimSpace(r.URL.Query().Get("name"))
	} else {
		path := strings.TrimPrefix(r.URL.Path, "/api/config/")
		configName = strings.TrimSuffix(path, "/")
	}

	if configName == "" {
		sendJSONError(w, http.StatusBadRequest, "Config name is required")
		return
	}

	// 验证文件名安全性
	if strings.Contains(configName, "..") || strings.ContainsAny(configName, "/\\") {
		sendJSONError(w, http.StatusBadRequest, "Invalid config name")
		return
	}

	switch r.Method {
	case http.MethodGet:
		handleGetConfig(w, r, claims.UserID, configName)
	case http.MethodPut:
		handleUpdateConfig(w, r, claims.UserID, claims.Username, configName)
	case http.MethodDelete:
		handleDeleteConfig(w, r, claims.UserID, configName)
	default:
		sendJSONError(w, http.StatusMethodNotAllowed, "Method not allowed")
	}
}

// handleGetConfig 处理获取配置
func handleGetConfig(w http.ResponseWriter, r *http.Request, userID int64, configName string) {
	config, err := GetConfig(userID, configName)
	if err != nil {
		log.Printf("Failed to get config: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Failed to get config")
		return
	}
	if config == nil {
		sendJSONError(w, http.StatusNotFound, "Config not found")
		return
	}

	// 返回加密的数据和二次加密的AES密钥
	sendJSONResponse(w, http.StatusOK, "Config retrieved successfully", map[string]interface{}{
		"config_id":                   config.ID,
		"config_name":                 config.ConfigName,
		"encrypted_content":           base64Encode(config.EncryptedContent),
		"encrypted_aes_key":           base64Encode(config.AESKeyEncryptedWithPublicKey),
		"created_at":                  config.CreatedAt,
		"updated_at":                  config.UpdatedAt,
	})
}

// handleUpdateConfig 处理更新配置
func handleUpdateConfig(w http.ResponseWriter, r *http.Request, userID int64, username, configName string) {
	// 解析表单
	if err := r.ParseMultipartForm(32 << 20); err != nil {
		sendJSONError(w, http.StatusBadRequest, "Failed to parse form data")
		return
	}

	encryptedContentStr := r.FormValue("encrypted_content")
	encryptedAESKeyStr := r.FormValue("encrypted_aes_key")

	if encryptedContentStr == "" || encryptedAESKeyStr == "" {
		sendJSONError(w, http.StatusBadRequest, "encrypted_content and encrypted_aes_key are required")
		return
	}

	// 解码base64
	encryptedContent, err := base64Decode(encryptedContentStr)
	if err != nil {
		sendJSONError(w, http.StatusBadRequest, "Invalid encrypted_content format")
		return
	}

	encryptedAESKey, err := base64Decode(encryptedAESKeyStr)
	if err != nil {
		sendJSONError(w, http.StatusBadRequest, "Invalid encrypted_aes_key format")
		return
	}

	user, err := GetUserByID(userID)
	if err != nil || user == nil {
		sendJSONError(w, http.StatusInternalServerError, "Failed to get user info")
		return
	}

	userPubKey, err := ParsePublicKey(user.PublicKey)
	if err != nil {
		log.Printf("Failed to parse user public key: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Failed to process public key")
		return
	}

	doubleEncryptedAESKey, err := EncryptWithPublicKeyChunked(userPubKey, encryptedAESKey)
	if err != nil {
		log.Printf("Failed to double encrypt AES key: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Failed to encrypt data")
		return
	}

	if err := UpdateConfig(userID, configName, doubleEncryptedAESKey, encryptedContent); err != nil {
		if strings.Contains(err.Error(), "not found") {
			sendJSONError(w, http.StatusNotFound, "Config not found")
			return
		}
		log.Printf("Failed to update config: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Failed to update config")
		return
	}

	log.Printf("✅ Config updated: %s by user %s", configName, username)
	sendJSONResponse(w, http.StatusOK, "Config updated successfully", map[string]interface{}{
		"config_name": configName,
	})
}

// handleDeleteConfig 处理删除配置
func handleDeleteConfig(w http.ResponseWriter, r *http.Request, userID int64, configName string) {
	if err := DeleteConfig(userID, configName); err != nil {
		if strings.Contains(err.Error(), "not found") {
			sendJSONError(w, http.StatusNotFound, "Config not found")
			return
		}
		log.Printf("Failed to delete config: %v", err)
		sendJSONError(w, http.StatusInternalServerError, "Failed to delete config")
		return
	}

	log.Printf("✅ Config deleted: %s by user %d", configName, userID)
	sendJSONResponse(w, http.StatusOK, "Config deleted successfully", nil)
}

// base64编码辅助函数
func base64Encode(data []byte) string {
	return base64.StdEncoding.EncodeToString(data)
}

// base64解码辅助函数
func base64Decode(data string) ([]byte, error) {
	// 清理空白字符
	data = strings.TrimSpace(data)
	return base64.StdEncoding.DecodeString(data)
}

// getConfigFilePath 获取用户配置文件的绝对路径
func getConfigFilePath(userID int64, configName string) string {
	userDir := filepath.Join("configs", fmt.Sprintf("%d", userID))
	return filepath.Join(userDir, configName)
}
