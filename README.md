# SUMP v2

> 状态：M4 完成（QQ 私聊接通：第一个真实入口 + 图片服务；全链真进程 e2e） · 设计文档：[DESIGN.md](./DESIGN.md)

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
- **记忆激活（完全启动）**：LLM 调 API 前先把任务上下文托管给记忆服务；只有收到 `from=memory` 的 `resume` 才“完全启动”——注入什么记忆由记忆服务决定
- **图片链路**：QQ 图片存入 images 服务（独立进程/独立库）；llm 推理前自动取“最近一条消息”的图转 base64 内联给模型（更早的消息转文本占位）

## 本地运行

```powershell
# 构建并启动五个服务（settings-center :9000 + memory :9201 + images :9401 + qq :9301 + agentloop :9101）
.\scripts\run-local.ps1
```

- 自定义地址：`.\scripts\run-local.ps1 -CenterAddr 127.0.0.1:9000 -MemoryAddr 127.0.0.1:9201 -ImageAddr 127.0.0.1:9401 -QQAddr 127.0.0.1:9301 -AgentAddr 127.0.0.1:9101`
- 接 QQ（NapCat 正向 WS，仅私聊）：`.\scripts\run-local.ps1 -Owner 2271917353 -NapCatURL ws://192.168.11.196:3001 -NapCatToken <token>`——连不上会自动重试，不影响其余服务
- 记忆/图片数据落在 `data/`（`memory.db` / `images.db` / `images/`，不入库）
- 接入真 LLM：`$env:DEEPSEEK_API_KEY='sk-...'; .\scripts\run-local.ps1`（或显式 `-LlmKey/-LlmModel/-LlmBase`）
- 真 LLM 冒烟测试：`$env:SUMP_LIVE_LLM='1'; $env:DEEPSEEK_API_KEY='sk-...'; cd agentloop; go test ./tests/ -run TestLiveDeepSeek -v`（平时自动跳过）
- `Ctrl+C` 停止（脚本会清理全部子进程）
- 跨服务端到端测试：`cd tests; go test ./... -count=1`

## 进度

- [x] 重构设计（[DESIGN.md](./DESIGN.md)）
- [x] 第一批骨架：agentloop + 设置中心（注册 / 名册 / 跨服务跳转 / 自我跳转）
- [x] 单步推理链（M2）：LLM 决策 / 工具跳转 / 自跳 step / deliver 直达 boss——含假 LLM 端到端与真 DeepSeek 冒烟
- [x] 记忆服务（M3）：会话历史 + 上下文组装；llm 经记忆激活的“完全启动”链（recall → resume）——含全链测试与真进程端到端
- [x] QQ 私聊接入 + 图片服务（M4）：NapCat/OneBot 11 → 任务链 → deliver 回发；图片存入 images、推理前取图内联（含全链真进程 e2e）
- [ ] 下一步：群聊（@ 必回 / 自主插话）、审批链路

## 文档

| 文档 | 内容 |
| ---- | ---- |
| [DESIGN.md](./DESIGN.md) | 重构设计：背景 / 架构 / 目录约定 / 实施路线 / 待决问题 |
