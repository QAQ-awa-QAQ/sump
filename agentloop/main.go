// agentloop：SUMP v2 的 LLM 服务（第一批）。
// 单步推理与跳转决策（自我跳转构成循环）；M1 骨架先实现注册与跳转基础设施。
package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"

	"github.com/QAQ-awa-QAQ/sump/agentloop/llm"
	"github.com/QAQ-awa-QAQ/sump/agentloop/loop"
)

func main() {
	name := flag.String("name", "agentloop", "服务名")
	addr := flag.String("addr", "127.0.0.1:9101", "监听地址（host:port）")
	center := flag.String("center", "ws://127.0.0.1:9000/ws", "设置中心 WS 地址")
	memorySvc := flag.String("memory", "memory", "记忆服务名（完全启动链的另一半）")
	imagesSvc := flag.String("images", "images", "图片服务名（推理前取图内联）")
	llmBase := flag.String("llm-base", "https://api.deepseek.com", "LLM API 地址（OpenAI 兼容）")
	llmKey := flag.String("llm-key", os.Getenv("DEEPSEEK_API_KEY"), "LLM API Key（默认取环境变量 DEEPSEEK_API_KEY）")
	llmModel := flag.String("llm-model", "deepseek-chat", "LLM 模型名")
	flag.Parse()

	logger := log.New(os.Stdout, "[agentloop] ", log.LstdFlags|log.Lmicroseconds)
	if *llmKey == "" {
		logger.Printf("警告: 未配置 LLM Key（-llm-key 或环境变量 DEEPSEEK_API_KEY），user_message 将无法推理")
	}
	llmClient := llm.NewDeepSeekClient(*llmBase, *llmKey, *llmModel)

	l := loop.New(loop.Config{Name: *name, Listen: *addr, Center: *center, Memory: *memorySvc, Images: *imagesSvc, LLM: llmClient}, logger)
	if err := l.Start(context.Background()); err != nil {
		logger.Fatalf("启动失败: %v", err)
	}
	defer l.Shutdown()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	<-sig
	logger.Println("退出")
}
