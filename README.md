# SUMP v2

> 状态：M2 完成（单步推理链端到端跑通，含真 DeepSeek 验证） · 设计文档：[DESIGN.md](./DESIGN.md)

SUMP v2 是一个“服务的互联网”式的智能体系统。每个服务独立运行（独立进程、独立数据库、任意语言），通过 WebSocket 按地址互相访问；智能体循环由 LLM 服务在服务网络之上自由跳转、组装。

## 与 v1 的关系

- 本仓库（`sump`）是 **v2 主线**，承载当前全部开发。
- **v1 已停止开发**：完整源码与版本历史归档于 [sump-v1](https://github.com/QAQ-awa-QAQ/sump-v1)（main + v0.1.0 ~ v1.0 全部 tag）；本地开发目录为 `../1`，其 origin 已指向该归档仓库。
- 重构原因：v1 是单进程 Python 单体，进程内共享状态 + 并发触发严重竞态；v2 用“服务隔离 + 网络通信 + 无驻留循环”从根上消除共享状态问题。

## 设计要点

- **一个文件夹 = 一个服务**；各服务自带 `tests/`，根目录有总 `tests/`（跨服务端到端）
- **WebSocket 通信**：默认短连接、按访问频率自适应保活；服务间点对点直连
- **设置中心**：注册 · 全局信息 · 设置与调度——不是中央交换机，不做流量中转
- **语言分工（性能优先）**：Go 扛全部逻辑，Python 只做 embedding 推理，TS 只做前端（后续的独立前端服务）
- **智能体循环 = 跳转式调度**：每轮推理决定是访问工具服务、重新访问自己，还是发起审批

## 本地运行

```powershell
# 构建并启动第一批两个服务（settings-center :9000 + agentloop :9101）
.\scripts\run-local.ps1
```

- 自定义地址：`.\scripts\run-local.ps1 -CenterAddr 127.0.0.1:9000 -AgentAddr 127.0.0.1:9101`
- 接入真 LLM：`$env:DEEPSEEK_API_KEY='sk-...'; .\scripts\run-local.ps1`（或显式 `-LlmKey/-LlmModel/-LlmBase`）
- 真 LLM 冒烟测试：`$env:SUMP_LIVE_LLM='1'; $env:DEEPSEEK_API_KEY='sk-...'; cd agentloop; go test ./tests/ -run TestLiveDeepSeek -v`（平时自动跳过）
- `Ctrl+C` 停止（脚本会清理两个子进程）
- 跨服务端到端测试：`cd tests; go test ./... -count=1`

## 进度

- [x] 重构设计（[DESIGN.md](./DESIGN.md)）
- [x] 第一批骨架：agentloop + 设置中心（注册 / 名册 / 跨服务跳转 / 自我跳转）
- [x] 单步推理链（M2）：LLM 决策 / 工具跳转 / 自跳 step / deliver 直达 boss——含假 LLM 端到端与真 DeepSeek 冒烟
- [ ] 下一步：首个真实入口（QQ 服务接入）

## 文档

| 文档 | 内容 |
| ---- | ---- |
| [DESIGN.md](./DESIGN.md) | 重构设计：背景 / 架构 / 目录约定 / 实施路线 / 待决问题 |
