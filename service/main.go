package main

import (
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	// 初始化数据库
	if err := initDatabase(); err != nil {
		log.Printf("❌ Failed to initialize database: %v", err)
		panic(err)
	}
	defer closeDatabase()

	// 设置路由
	setupRoutes()

	// 端口配置
	port := ":8443"
	if p := os.Getenv("PORT"); p != "" {
		port = ":" + p
	}

	// 优雅关闭
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		<-quit
		log.Printf("\n🛑 Shutting down server...")
		closeDatabase()
		os.Exit(0)
	}()

	log.Printf("✅ tkzs-config-service starting on http://0.0.0.0%s", port)
	log.Printf("✅ API Endpoints:")
	log.Printf("   POST   /api/register        - Register new user")
	log.Printf("   POST   /api/login            - Login")
	log.Printf("   GET    /api/configs          - List configs (JWT)")
	log.Printf("   DELETE /api/user/deactivate  - Deactivate current user (JWT)")
	log.Printf("   POST   /api/config/upload    - Upload config (JWT)")
	log.Printf("   GET    /api/config/{name}   - Get config (JWT)")
	log.Printf("   PUT    /api/config/{name}   - Update config (JWT)")
	log.Printf("   DELETE /api/config/{name}   - Delete config (JWT)")
	log.Printf("   GET    /health               - Health check")

	if err := http.ListenAndServe(port, nil); err != nil {
		log.Printf("❌ Server error: %v", err)
		panic(err)
	}
}
