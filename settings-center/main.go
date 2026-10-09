// settings-center：SUMP v2 的设置中心服务（第一批）。
// 职责：服务注册 · 全局信息分发 · 设置与调度（见 DESIGN.md §3）。
package main

import (
	"flag"
	"log"
	"os"
	"os/signal"

	"github.com/QAQ-awa-QAQ/sump/settings-center/server"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:9000", "监听地址（host:port）")
	settingsPath := flag.String("settings", "data/settings.json", "设置覆盖值文件路径（空 = 不落盘）")
	flag.Parse()

	logger := log.New(os.Stdout, "[settings-center] ", log.LstdFlags|log.Lmicroseconds)

	s, err := server.Start(*addr, *settingsPath, logger)
	if err != nil {
		logger.Fatalf("启动失败: %v", err)
	}
	_ = s

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	<-sig
	logger.Println("退出")
}
