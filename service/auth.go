package main

import (
	"context"
	"crypto/rsa"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"
)

// JWT配置
var (
	jwtSecret     = []byte("tkzs-config-service-jwt-secret-key-2024") // 生产环境应从环境变量读取
	jwtExpiration = 24 * time.Hour                                    // Token有效期24小时
)

// Claims JWT Claims
type Claims struct {
	UserID   int64  `json:"user_id"`
	Username string `json:"username"`
	jwt.RegisteredClaims
}

// HashPassword 使用bcrypt加密密码
func HashPassword(password string) (string, error) {
	bytes, err := bcrypt.GenerateFromPassword([]byte(password), 12)
	if err != nil {
		return "", fmt.Errorf("failed to hash password: %w", err)
	}
	return string(bytes), nil
}

// CheckPassword 验证密码
func CheckPassword(password, hash string) bool {
	err := bcrypt.CompareHashAndPassword([]byte(hash), []byte(password))
	return err == nil
}

// GenerateToken 生成JWT Token
func GenerateToken(userID int64, username string) (string, error) {
	expirationTime := time.Now().Add(jwtExpiration)

	claims := &Claims{
		UserID:   userID,
		Username: username,
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(expirationTime),
			IssuedAt:  jwt.NewNumericDate(time.Now()),
			Issuer:    "tkzs-config-service",
		},
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenString, err := token.SignedString(jwtSecret)
	if err != nil {
		return "", fmt.Errorf("failed to sign token: %w", err)
	}

	return tokenString, nil
}

// ValidateToken 验证JWT Token
func ValidateToken(tokenString string) (*Claims, error) {
	claims := &Claims{}

	token, err := jwt.ParseWithClaims(tokenString, claims, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return jwtSecret, nil
	})

	if err != nil {
		return nil, fmt.Errorf("failed to parse token: %w", err)
	}

	if !token.Valid {
		return nil, errors.New("invalid token")
	}

	return claims, nil
}

// GetTokenFromHeader 从请求头获取Token
func GetTokenFromHeader(r *http.Request) (string, error) {
	authHeader := r.Header.Get("Authorization")
	if authHeader == "" {
		return "", errors.New("authorization header not found")
	}

	parts := strings.SplitN(authHeader, " ", 2)
	if len(parts) != 2 || strings.ToLower(parts[0]) != "bearer" {
		return "", errors.New("invalid authorization header format")
	}

	return parts[1], nil
}

// JWTAuthMiddleware JWT认证中间件
func JWTAuthMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		tokenString, err := GetTokenFromHeader(r)
		if err != nil {
			log.Printf("JWT Auth failed: %v", err)
			sendJSONError(w, http.StatusUnauthorized, "Unauthorized: "+err.Error())
			return
		}

		claims, err := ValidateToken(tokenString)
		if err != nil {
			log.Printf("JWT Validation failed: %v", err)
			sendJSONError(w, http.StatusUnauthorized, "Invalid or expired token")
			return
		}

		// 将用户信息注入到请求context
		r = r.WithContext(withUserClaims(r.Context(), claims))
		next.ServeHTTP(w, r)
	}
}

// UserClaimsKey 用户claims的context key
type contextKey string

const userClaimsKey contextKey = "userClaims"

// withUserClaims 将用户claims存入context
func withUserClaims(ctx context.Context, claims *Claims) context.Context {
	return context.WithValue(ctx, userClaimsKey, claims)
}

// GetUserFromRequest 从请求中获取用户信息
func GetUserFromRequest(r *http.Request) *Claims {
	claims, ok := r.Context().Value(userClaimsKey).(*Claims)
	if !ok {
		return nil
	}
	return claims
}

// LoginResponse 登录响应
type LoginResponse struct {
	AccessToken string `json:"access_token"`
	ExpiresIn   int64  `json:"expires_in"`
	TokenType   string `json:"token_type"`
	UserID      int64  `json:"user_id"`
	Username    string `json:"username"`
}

// RegisterRequest 注册请求
type RegisterRequest struct {
	Username  string `json:"username"`
	Password  string `json:"password"`
	PublicKey string `json:"public_key"`
}

// LoginRequest 登录请求
type LoginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// JSONResponse JSON响应结构
type JSONResponse struct {
	Success bool        `json:"success"`
	Message string      `json:"message,omitempty"`
	Data    interface{} `json:"data,omitempty"`
	Error   string      `json:"error,omitempty"`
}

// ConfigListItem 配置列表项
type ConfigListItem struct {
	ID        int64  `json:"id"`
	ConfigName string `json:"config_name"`
	CreatedAt string `json:"created_at"`
	UpdatedAt string `json:"updated_at"`
}

// sendJSONResponse 发送JSON响应
func sendJSONResponse(w http.ResponseWriter, statusCode int, message string, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	resp := JSONResponse{
		Success: statusCode < 400,
		Message: message,
		Data:    data,
	}
	if statusCode >= 400 {
		resp.Error = message
	}
	json.NewEncoder(w).Encode(resp)
}

// sendJSONError 发送JSON错误响应
func sendJSONError(w http.ResponseWriter, statusCode int, message string) {
	sendJSONResponse(w, statusCode, message, nil)
}

// ParsePublicKey 解析RSA公钥
func ParsePublicKey(pemStr string) (*rsa.PublicKey, error) {
	// 清理PEM字符串
	pemStr = strings.TrimSpace(pemStr)

	// 添加PEM头尾如果缺失
	if !strings.Contains(pemStr, "-----BEGIN") {
		pemStr = "-----BEGIN PUBLIC KEY-----\n" + pemStr + "\n-----END PUBLIC KEY-----"
	}

	// 解码base64
	block, _ := pemDecode([]byte(pemStr))
	if block == nil {
		return nil, errors.New("failed to decode PEM")
	}

	// 解析公钥
	pubInterface, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err != nil {
		// 尝试PKCS1格式
		pubInterface, err = x509.ParsePKCS1PublicKey(block.Bytes)
		if err != nil {
			return nil, fmt.Errorf("failed to parse public key: %w", err)
		}
	}

	pubKey, ok := pubInterface.(*rsa.PublicKey)
	if !ok {
		return nil, errors.New("not an RSA public key")
	}

	return pubKey, nil
}

// pemDecode 简单的PEM解码
func pemDecode(data []byte) (*pemBlock, []byte) {
	var lines []string
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "-----") {
			continue
		}
		lines = append(lines, line)
	}

	decoded := make([]byte, base64.StdEncoding.DecodedLen(len(strings.Join(lines, ""))))
	n, err := base64.StdEncoding.Decode(decoded, []byte(strings.Join(lines, "")))
	if err != nil {
		return nil, data
	}

	return &pemBlock{Bytes: decoded[:n]}, data
}

type pemBlock struct {
	Bytes []byte
}
