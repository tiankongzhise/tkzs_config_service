package main

import (
	"crypto/hmac"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"io/ioutil"
	"log"
	"net"
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
	storedPwd  string
	configDir  = "."

	// 存储已使用的 nonce，值存储过期时间戳（Unix 秒）
	nonceStore sync.Map

	// IP 黑名单管理器
	ipBanManager *IPBanManager
)

// ---------- 新增：IP 封禁配置结构 ----------
type IPBanConfig struct {
	MinuteWindowSec   int64 // 分钟窗口大小（秒），默认 60
	DayWindowSec      int64 // 天窗口大小（秒），默认 86400
	MinuteFailLimit   int   // 分钟窗口内失败次数触发封禁，默认 5
	DayFailLimit      int   // 天窗口内失败次数触发封禁，默认 10
	BanMinuteDuration int64 // 分钟封禁时长（秒），默认 1800（30分钟）
	BanDayDuration    int64 // 天封禁时长（秒），默认 86400（24小时）
}

// DefaultIPBanConfig 返回默认封禁配置
func DefaultIPBanConfig() IPBanConfig {
	return IPBanConfig{
		MinuteWindowSec:   60,
		DayWindowSec:      86400,
		MinuteFailLimit:   5,
		DayFailLimit:      10,
		BanMinuteDuration: 1800, // 30分钟
		BanDayDuration:    86400, // 24小时
	}
}

// IPBanManager 管理 IP 失败计数和封禁
type IPBanManager struct {
	mu       sync.RWMutex
	failures map[string][]int64   // IP -> 失败时间戳列表（秒）
	bans     map[string]int64     // IP -> 封禁解除时间戳（秒）
	filePath string               // 持久化文件路径
	config   IPBanConfig          // 封禁配置
}

// NewIPBanManager 创建管理器并加载已有数据
func NewIPBanManager(filePath string, config IPBanConfig) *IPBanManager {
	mgr := &IPBanManager{
		failures: make(map[string][]int64),
		bans:     make(map[string]int64),
		filePath: filePath,
		config:   config,
	}
	mgr.loadFromFile()
	// 每分钟自动落盘
	go mgr.periodicSave()
	// 每 10 分钟清理过期失败记录和封禁
	go mgr.periodicCleanup()
	return mgr
}

// loadFromFile 从文件加载封禁数据
func (m *IPBanManager) loadFromFile() {
	m.mu.Lock()
	defer m.mu.Unlock()
	data, err := ioutil.ReadFile(m.filePath)
	if err != nil {
		if !os.IsNotExist(err) {
			log.Printf("Failed to read ban file: %v", err)
		}
		return
	}
	var store struct {
		Failures map[string][]int64 `json:"failures"`
		Bans     map[string]int64   `json:"bans"`
	}
	if err := json.Unmarshal(data, &store); err != nil {
		log.Printf("Failed to parse ban file: %v", err)
		return
	}
	m.failures = store.Failures
	m.bans = store.Bans
	log.Printf("Loaded ban data: %d IPs with failures, %d IPs banned", len(m.failures), len(m.bans))
}

// saveToFile 将数据写入文件
func (m *IPBanManager) saveToFile() {
	m.mu.RLock()
	defer m.mu.RUnlock()
	store := struct {
		Failures map[string][]int64 `json:"failures"`
		Bans     map[string]int64   `json:"bans"`
	}{
		Failures: m.failures,
		Bans:     m.bans,
	}
	data, err := json.MarshalIndent(store, "", "  ")
	if err != nil {
		log.Printf("Failed to marshal ban data: %v", err)
		return
	}
	if err := ioutil.WriteFile(m.filePath, data, 0600); err != nil {
		log.Printf("Failed to write ban file: %v", err)
	}
}

// periodicSave 每分钟保存一次
func (m *IPBanManager) periodicSave() {
	ticker := time.NewTicker(1 * time.Minute)
	defer ticker.Stop()
	for range ticker.C {
		m.saveToFile()
		log.Printf("IP ban data saved to disk")
	}
}

// periodicCleanup 每 10 分钟清理过期的失败记录和封禁
func (m *IPBanManager) periodicCleanup() {
	ticker := time.NewTicker(10 * time.Minute)
	defer ticker.Stop()
	for range ticker.C {
		m.cleanupExpired()
	}
}

// cleanupExpired 清理过期的失败记录（超过1天）和已解封的IP
func (m *IPBanManager) cleanupExpired() {
	m.mu.Lock()
	defer m.mu.Unlock()
	now := time.Now().Unix()
	// 清理失败记录：只保留配置的天窗口内的记录
	for ip, timestamps := range m.failures {
		newTs := make([]int64, 0, len(timestamps))
		for _, ts := range timestamps {
			if now-ts <= m.config.DayWindowSec {
				newTs = append(newTs, ts)
			}
		}
		if len(newTs) == 0 {
			delete(m.failures, ip)
		} else {
			m.failures[ip] = newTs
		}
	}
	// 清理已解封的IP
	for ip, unbanTime := range m.bans {
		if now >= unbanTime {
			delete(m.bans, ip)
		}
	}
	log.Printf("Cleaned expired failure records and bans")
}

// RecordFailure 记录一次认证失败，返回是否需要封禁以及封禁时长（分钟）
func (m *IPBanManager) RecordFailure(ip string) (banned bool, banMinutes int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	now := time.Now().Unix()
	// 获取现有失败记录
	tsList := m.failures[ip]
	// 清理超过配置的天窗口的旧记录
	fresh := make([]int64, 0, len(tsList))
	for _, ts := range tsList {
		if now-ts <= m.config.DayWindowSec {
			fresh = append(fresh, ts)
		}
	}
	// 添加本次失败
	fresh = append(fresh, now)
	m.failures[ip] = fresh

	// 计算分钟窗口内失败次数
	var recentMinute int
	for _, ts := range fresh {
		if now-ts <= m.config.MinuteWindowSec {
			recentMinute++
		}
	}
	// 计算天窗口内失败次数
	var recentDay int
	for _, ts := range fresh {
		if now-ts <= m.config.DayWindowSec {
			recentDay++
		}
	}

	var banDuration int64
	if recentMinute >= m.config.MinuteFailLimit {
		banDuration = m.config.BanMinuteDuration
	} else if recentDay >= m.config.DayFailLimit {
		banDuration = m.config.BanDayDuration
	}
	if banDuration > 0 {
		unbanTime := now + banDuration
		m.bans[ip] = unbanTime
		// 封禁后清空失败记录（避免重复触发）
		delete(m.failures, ip)
		log.Printf("IP %s banned for %d seconds (failures: %d in %ds, %d in %ds)",
			ip, banDuration, recentMinute, m.config.MinuteWindowSec, recentDay, m.config.DayWindowSec)
		return true, int(banDuration / 60)
	}
	return false, 0
}

// IsBanned 检查IP是否被封禁，若封禁则返回剩余秒数
func (m *IPBanManager) IsBanned(ip string) (bool, int64) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	unbanTime, exists := m.bans[ip]
	if !exists {
		return false, 0
	}
	now := time.Now().Unix()
	if now < unbanTime {
		return true, unbanTime - now
	}
	return false, 0
}

// ResetFailures 重置IP的失败计数（成功登录时调用）
func (m *IPBanManager) ResetFailures(ip string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.failures, ip)
	log.Printf("Reset failure count for IP %s (successful auth)", ip)
}

// getClientIP 获取客户端真实IP（支持X-Forwarded-For）
func getClientIP(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		ips := strings.Split(xff, ",")
		return strings.TrimSpace(ips[0])
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func init() {
	// ---------- 修改点：使用配置结构初始化 IP 黑名单管理器 ----------
	banConfig := DefaultIPBanConfig()
	ipBanManager = NewIPBanManager("ip_bans.json", banConfig)

	go cleanExpiredNonces()

	// 加载业务 RSA 私钥
	keyBytes, err := ioutil.ReadFile("server_private_key.pem")
	if err != nil {
		log.Printf("failed to read business private key: %v\n", err)
		panic("failed to read business private key: " + err.Error())
	}
	block, _ := pem.Decode(keyBytes)
	if block == nil || block.Type != "PRIVATE KEY" {
		log.Printf("invalid business private key format\n")
		panic("invalid business private key format")
	}

	key, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		privateKey, err = x509.ParsePKCS1PrivateKey(block.Bytes)
		if err != nil {
			log.Printf("failed to parse business private key: %v\n", err)
			panic("failed to parse business private key: " + err.Error())
		}
	} else {
		var ok bool
		privateKey, ok = key.(*rsa.PrivateKey)
		if !ok {
			log.Printf("not an RSA private key\n")
			panic("not an RSA private key")
		}
	}

	// 从 .env 读取明文密码
	pwdBytes, err := ioutil.ReadFile(".env")
	if err != nil {
		log.Printf("failed to read .env: %v\n", err)
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
		log.Printf("PASSWORD not found in .env\n")
		panic("PASSWORD not found in .env")
	}
}

func main() {
	http.HandleFunc("/get-config", authHandler)
	log.Printf("✅ Server starting successfully on http://0.0.0.0:8443")
	log.Printf("✅ HandleFunc /get-config registered success")

	err := http.ListenAndServe(":8443", nil)
	if err != nil {
		log.Printf("failed to listen and serve http: %v\n", err)
		panic(err)
	}
}

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
		log.Printf("Cleaned expired nonces")
	}
}

func authHandler(w http.ResponseWriter, r *http.Request) {
	clientIP := getClientIP(r)

	if banned, remainSec := ipBanManager.IsBanned(clientIP); banned {
		log.Printf("Blocked request from banned IP %s (remaining %d seconds)", clientIP, remainSec)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	if r.Method != http.MethodPost {
		log.Printf("Method not allowed: %s\n", r.Method)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	encryptedData, err := ioutil.ReadAll(r.Body)
	if err != nil || len(encryptedData) == 0 {
		log.Printf("Bad request: %v, len=%d\n", err, len(encryptedData))
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	decrypted, err := rsa.DecryptPKCS1v15(nil, privateKey, encryptedData)
	if err != nil {
		log.Printf("Decryption failed: %v\n", err)
		if banned, _ := ipBanManager.RecordFailure(clientIP); banned {
			log.Printf("IP %s banned due to decryption failures", clientIP)
		}
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	parts := strings.SplitN(string(decrypted), ":", 5)
	if len(parts) != 5 {
		log.Printf("Invalid format, expected 5 parts, got %d\n", len(parts))
		if banned, _ := ipBanManager.RecordFailure(clientIP); banned {
			log.Printf("IP %s banned due to format errors", clientIP)
		}
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}
	salt, clientHMAC, filename, timestampStr, nonce := parts[0], parts[1], parts[2], parts[3], parts[4]

	ts, err := strconv.ParseInt(timestampStr, 10, 64)
	if err != nil {
		log.Printf("Invalid timestamp: %s, err: %v\n", timestampStr, err)
		if banned, _ := ipBanManager.RecordFailure(clientIP); banned {
			log.Printf("IP %s banned due to invalid timestamp", clientIP)
		}
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}
	now := time.Now().Unix()
	if ts < now-300 || ts > now+300 {
		log.Printf("Timestamp out of window: %d, now: %d\n", ts, now)
		if banned, _ := ipBanManager.RecordFailure(clientIP); banned {
			log.Printf("IP %s banned due to timestamp out of window", clientIP)
		}
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	expiry := now + 600
	if _, loaded := nonceStore.LoadOrStore(nonce, expiry); loaded {
		log.Printf("Replayed nonce: %s\n", nonce)
		if banned, _ := ipBanManager.RecordFailure(clientIP); banned {
			log.Printf("IP %s banned due to nonce replay", clientIP)
		}
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	message := salt + ":" + filename + ":" + timestampStr + ":" + nonce
	h := hmac.New(sha256.New, []byte(storedPwd))
	h.Write([]byte(message))
	expectedHMAC := hex.EncodeToString(h.Sum(nil))
	if !hmac.Equal([]byte(clientHMAC), []byte(expectedHMAC)) {
		log.Printf("HMAC mismatch, client: %s, expected: %s\n", clientHMAC, expectedHMAC)
		if banned, _ := ipBanManager.RecordFailure(clientIP); banned {
			log.Printf("IP %s banned due to HMAC mismatch", clientIP)
		}
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	if strings.Contains(filename, "..") || strings.ContainsAny(filename, "/\\") {
		log.Printf("Invalid filename: %s\n", filename)
		if banned, _ := ipBanManager.RecordFailure(clientIP); banned {
			log.Printf("IP %s banned due to path traversal attempt", clientIP)
		}
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}
	absConfigDir, err := filepath.Abs(configDir)
	if err != nil {
		log.Printf("Failed to get absolute config dir: %v\n", err)
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}
	filePath := filepath.Join(absConfigDir, filename)
	absPath, err := filepath.Abs(filePath)
	if err != nil || !strings.HasPrefix(absPath, absConfigDir+string(os.PathSeparator)) {
		log.Printf("Path traversal attempt: %s -> %s\n", filename, absPath)
		if banned, _ := ipBanManager.RecordFailure(clientIP); banned {
			log.Printf("IP %s banned due to path traversal", clientIP)
		}
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	content, err := ioutil.ReadFile(filePath)
	if err != nil {
		if os.IsNotExist(err) {
			log.Printf("Config file not found: %s\n", filePath)
		} else {
			log.Printf("Read file error: %v\n", err)
		}
		if banned, _ := ipBanManager.RecordFailure(clientIP); banned {
			log.Printf("IP %s banned due to file access error", clientIP)
		}
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	// 认证成功：重置该 IP 的失败计数
	ipBanManager.ResetFailures(clientIP)

	w.Header().Set("Content-Type", "application/octet-stream")
	w.WriteHeader(http.StatusOK)
	w.Write(content)
	log.Printf("Config returned successfully: %s (IP: %s)", filename, clientIP)
}