package main

import (
	"database/sql"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sync"

	_ "modernc.org/sqlite"
)

// 数据库全局变量
var (
	db   *sql.DB
	dbMu sync.RWMutex
)

// 数据库初始化
func initDatabase() error {
	dbMu.Lock()
	defer dbMu.Unlock()

	// 确保配置目录存在
	configsDir := "configs"
	if err := os.MkdirAll(configsDir, 0755); err != nil {
		return fmt.Errorf("failed to create configs directory: %w", err)
	}

	// 打开或创建数据库
	var err error
	db, err = sql.Open("sqlite", "./tkzs_service.db")
	if err != nil {
		return fmt.Errorf("failed to open database: %w", err)
	}

	// 测试连接
	if err = db.Ping(); err != nil {
		return fmt.Errorf("failed to ping database: %w", err)
	}

	// 创建表
	if err = createTables(); err != nil {
		return fmt.Errorf("failed to create tables: %w", err)
	}

	log.Printf("✅ Database initialized successfully")
	return nil
}

// 创建必要的表
func createTables() error {
	// 用户表
	userTableSQL := `
	CREATE TABLE IF NOT EXISTS users (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		username TEXT UNIQUE NOT NULL,
		password_hash TEXT NOT NULL,
		public_key TEXT NOT NULL,
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);`

	if _, err := db.Exec(userTableSQL); err != nil {
		return fmt.Errorf("failed to create users table: %w", err)
	}

	// 配置表
	configTableSQL := `
	CREATE TABLE IF NOT EXISTS configs (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		user_id INTEGER NOT NULL,
		config_name TEXT NOT NULL,
		aes_key_encrypted_with_public_key BLOB NOT NULL,
		encrypted_content BLOB NOT NULL,
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		FOREIGN KEY (user_id) REFERENCES users(id),
		UNIQUE(user_id, config_name)
	);`

	if _, err := db.Exec(configTableSQL); err != nil {
		return fmt.Errorf("failed to create configs table: %w", err)
	}

	log.Printf("✅ Database tables created/verified")
	return nil
}

// ============ 用户相关操作 ============

// User 用户结构
type User struct {
	ID           int64
	Username     string
	PasswordHash string
	PublicKey    string
	CreatedAt    string
}

// CreateUser 创建用户
func CreateUser(username, passwordHash, publicKey string) (int64, error) {
	dbMu.Lock()
	defer dbMu.Unlock()

	// 检查用户名是否已存在
	var exists int
	err := db.QueryRow("SELECT COUNT(*) FROM users WHERE username = ?", username).Scan(&exists)
	if err != nil {
		return 0, fmt.Errorf("failed to check username: %w", err)
	}
	if exists > 0 {
		return 0, fmt.Errorf("username already exists")
	}

	// 插入用户
	result, err := db.Exec(
		"INSERT INTO users (username, password_hash, public_key) VALUES (?, ?, ?)",
		username, passwordHash, publicKey,
	)
	if err != nil {
		return 0, fmt.Errorf("failed to insert user: %w", err)
	}

	userID, err := result.LastInsertId()
	if err != nil {
		return 0, fmt.Errorf("failed to get last insert id: %w", err)
	}

	// 创建用户配置目录
	userDir := filepath.Join("configs", fmt.Sprintf("%d", userID))
	if err := os.MkdirAll(userDir, 0755); err != nil {
		return 0, fmt.Errorf("failed to create user directory: %w", err)
	}

	log.Printf("✅ User created: %s (ID: %d)", username, userID)
	return userID, nil
}

// GetUserByUsername 根据用户名获取用户
func GetUserByUsername(username string) (*User, error) {
	dbMu.RLock()
	defer dbMu.RUnlock()

	user := &User{}
	err := db.QueryRow(
		"SELECT id, username, password_hash, public_key, created_at FROM users WHERE username = ?",
		username,
	).Scan(&user.ID, &user.Username, &user.PasswordHash, &user.PublicKey, &user.CreatedAt)

	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("failed to get user: %w", err)
	}
	return user, nil
}

// GetUserByID 根据ID获取用户
func GetUserByID(userID int64) (*User, error) {
	dbMu.RLock()
	defer dbMu.RUnlock()

	user := &User{}
	err := db.QueryRow(
		"SELECT id, username, password_hash, public_key, created_at FROM users WHERE id = ?",
		userID,
	).Scan(&user.ID, &user.Username, &user.PasswordHash, &user.PublicKey, &user.CreatedAt)

	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("failed to get user: %w", err)
	}
	return user, nil
}

// ============ 配置相关操作 ============

// Config 配置结构
type Config struct {
	ID                                 int64
	UserID                             int64
	ConfigName                         string
	AESKeyEncryptedWithPublicKey       []byte
	EncryptedContent                   []byte
	CreatedAt                          string
	UpdatedAt                          string
}

// CreateConfig 创建配置
func CreateConfig(userID int64, configName string, encryptedAESKey, encryptedContent []byte) (int64, error) {
	dbMu.Lock()
	defer dbMu.Unlock()

	// 检查配置是否已存在
	var exists int
	err := db.QueryRow(
		"SELECT COUNT(*) FROM configs WHERE user_id = ? AND config_name = ?",
		userID, configName,
	).Scan(&exists)
	if err != nil {
		return 0, fmt.Errorf("failed to check config: %w", err)
	}
	if exists > 0 {
		return 0, fmt.Errorf("config already exists, use update instead")
	}

	result, err := db.Exec(
		"INSERT INTO configs (user_id, config_name, aes_key_encrypted_with_public_key, encrypted_content) VALUES (?, ?, ?, ?)",
		userID, configName, encryptedAESKey, encryptedContent,
	)
	if err != nil {
		return 0, fmt.Errorf("failed to insert config: %w", err)
	}

	configID, err := result.LastInsertId()
	if err != nil {
		return 0, fmt.Errorf("failed to get last insert id: %w", err)
	}

	// 保存文件到用户目录
	if err := saveConfigFile(userID, configName, encryptedContent); err != nil {
		return 0, err
	}

	log.Printf("✅ Config created: %s for user %d (ID: %d)", configName, userID, configID)
	return configID, nil
}

// UpdateConfig 更新配置
func UpdateConfig(userID int64, configName string, encryptedAESKey, encryptedContent []byte) error {
	dbMu.Lock()
	defer dbMu.Unlock()

	result, err := db.Exec(
		"UPDATE configs SET aes_key_encrypted_with_public_key = ?, encrypted_content = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND config_name = ?",
		encryptedAESKey, encryptedContent, userID, configName,
	)
	if err != nil {
		return fmt.Errorf("failed to update config: %w", err)
	}

	rowsAffected, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rowsAffected == 0 {
		return fmt.Errorf("config not found or not owned by user")
	}

	// 更新文件
	if err := saveConfigFile(userID, configName, encryptedContent); err != nil {
		return err
	}

	log.Printf("✅ Config updated: %s for user %d", configName, userID)
	return nil
}

// GetConfig 获取配置
func GetConfig(userID int64, configName string) (*Config, error) {
	dbMu.RLock()
	defer dbMu.RUnlock()

	config := &Config{}
	err := db.QueryRow(
		"SELECT id, user_id, config_name, aes_key_encrypted_with_public_key, encrypted_content, created_at, updated_at FROM configs WHERE user_id = ? AND config_name = ?",
		userID, configName,
	).Scan(&config.ID, &config.UserID, &config.ConfigName, &config.AESKeyEncryptedWithPublicKey, &config.EncryptedContent, &config.CreatedAt, &config.UpdatedAt)

	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("failed to get config: %w", err)
	}
	return config, nil
}

// DeleteConfig 删除配置
func DeleteConfig(userID int64, configName string) error {
	dbMu.Lock()
	defer dbMu.Unlock()

	// 先获取配置ID以删除文件
	var configID int64
	err := db.QueryRow(
		"SELECT id FROM configs WHERE user_id = ? AND config_name = ?",
		userID, configName,
	).Scan(&configID)
	if err == sql.ErrNoRows {
		return fmt.Errorf("config not found or not owned by user")
	}
	if err != nil {
		return fmt.Errorf("failed to get config: %w", err)
	}

	// 从数据库删除
	_, err = db.Exec("DELETE FROM configs WHERE user_id = ? AND config_name = ?", userID, configName)
	if err != nil {
		return fmt.Errorf("failed to delete config: %w", err)
	}

	// 删除文件
	userDir := filepath.Join("configs", fmt.Sprintf("%d", userID))
	configFile := filepath.Join(userDir, configName)
	if err := os.Remove(configFile); err != nil && !os.IsNotExist(err) {
		log.Printf("Warning: failed to delete config file: %v", err)
	}

	log.Printf("✅ Config deleted: %s for user %d (ID: %d)", configName, userID, configID)
	return nil
}

// ListConfigs 列出用户所有配置
func ListConfigs(userID int64) ([]Config, error) {
	dbMu.RLock()
	defer dbMu.RUnlock()

	rows, err := db.Query(
		"SELECT id, user_id, config_name, created_at, updated_at FROM configs WHERE user_id = ? ORDER BY updated_at DESC",
		userID,
	)
	if err != nil {
		return nil, fmt.Errorf("failed to list configs: %w", err)
	}
	defer rows.Close()

	var configs []Config
	for rows.Next() {
		var c Config
		if err := rows.Scan(&c.ID, &c.UserID, &c.ConfigName, &c.CreatedAt, &c.UpdatedAt); err != nil {
			return nil, fmt.Errorf("failed to scan config: %w", err)
		}
		configs = append(configs, c)
	}

	return configs, nil
}

// 辅助函数：保存配置文件到用户目录
func saveConfigFile(userID int64, configName string, content []byte) error {
	userDir := filepath.Join("configs", fmt.Sprintf("%d", userID))
	if err := os.MkdirAll(userDir, 0755); err != nil {
		return fmt.Errorf("failed to create user directory: %w", err)
	}

	configFile := filepath.Join(userDir, configName)
	if err := os.WriteFile(configFile, content, 0600); err != nil {
		return fmt.Errorf("failed to write config file: %w", err)
	}
	return nil
}

// 关闭数据库
func closeDatabase() {
	if db != nil {
		db.Close()
	}
}
