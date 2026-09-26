// agentloop：SUMP v2 的 LLM 服务（第一批）。
// 单步推理与跳转决策（自我跳转构成循环）；M1 骨架先实现注册与跳转基础设施。
package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"

	"github.com/QAQ-awa-QAQ/sump/agentloop/loop"
)

func main() {
	name := flag.String("name", "agentloop", "服务名")
	addr := flag.String("addr", "127.0.0.1:9101", "监听地址（host:port）")
	center := flag.String("center", "ws://127.0.0.1:9000/ws", "设置中心 WS 地址")
	flag.Parse()

	logger := log.New(os.Stdout, "[agentloop] ", log.LstdFlags|log.Lmicroseconds)

	l := loop.New(loop.Config{Name: *name, Listen: *addr, Center: *center}, logger)
	if err := l.Start(context.Background()); err != nil {
		logger.Fatalf("启动失败: %v", err)
	}
	defer l.Shutdown()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	<-sig
	logger.Println("退出")
}
