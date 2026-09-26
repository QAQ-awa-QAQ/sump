// memory：SUMP v2 的记忆服务（第一批）。
// 会话历史存储 + 上下文组装：recall 收到 llm 托管的任务上下文 →
// 注入记忆后以 resume 发回（触发 llm 的“完全启动”）。
package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"

	"github.com/QAQ-awa-QAQ/sump/memory/server"
	"github.com/QAQ-awa-QAQ/sump/memory/store"
)

func main() {
	name := flag.String("name", "memory", "服务名")
	addr := flag.String("addr", "127.0.0.1:9201", "监听地址（host:port）")
	center := flag.String("center", "ws://127.0.0.1:9000/ws", "设置中心 WS 地址")
	dbPath := flag.String("db", "memory.db", "SQLite 数据文件路径")
	history := flag.Int("history", 12, "recall 返回的最近消息条数")
	flag.Parse()

	logger := log.New(os.Stdout, "[memory] ", log.LstdFlags|log.Lmicroseconds)

	st, err := store.Open(*dbPath)
	if err != nil {
		logger.Fatalf("打开数据库失败: %v", err)
	}
	defer st.Close()

	s := server.New(server.Config{
		Name:         *name,
		Listen:       *addr,
		Center:       *center,
		Store:        st,
		HistoryLimit: *history,
	}, logger)
	if err := s.Start(context.Background()); err != nil {
		logger.Fatalf("启动失败: %v", err)
	}
	defer s.Shutdown()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	<-sig
	logger.Println("退出")
}
