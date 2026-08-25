# SUMP — 数字神经系统

> **状态：开发中 | 版本 v0.2.0**

集水器 · 汇聚万家之长 / The Sump — where diverse agentic paradigms converge.

SUMP 不是又一个"Agent 框架"。它是一个**以人体生理机制为蓝本的智能体运行时**。

## 核心哲学

工业隐喻（流水线、管道、插件板）在描述智能体系统时总有局限——它们要么过于僵硬，要么过于散乱。人体则不同：它用**层级化的、并行化的、异步的**机制同时处理呼吸、走路、聊天和回忆，而且资源利用率极高。



### 九个生理结构的工程映射

> 💡 标注说明：✅ 已实现 | 🚧 部分实现 | 📋 规划中

| 生理结构 | SUMP 模块 | 职责 | 状态 |
|----------|----------|------|------|
| **丘脑** | 意图路由器 | 消息到达后先分类再路由，决定"该送到大脑哪个区域" | 📋 |
| **前额叶皮层** | 主代理 / 执行循环 | 制定计划、多步推理、监控子代理、判断任务完成 | ✅ |
| **海马体** | 会话记忆 | 快速编码当前对话上下文，容量有限，超出后压缩迁移 | ✅ |
| **皮层** | 长期记忆 | 离线"睡眠"时巩固记忆——去重、冲突解决、过期剪枝 | ✅ |
| **杏仁核** | 重要性评分 / 信号门控 | 自动标记高价值交互，决定"这个值得长期记住吗" | 🚧 |
| **小脑** | 技能自动化 | 高频操作固化为可复用 skills，无需每次推理 | � |
| **胼胝体** | 子代理通信协议 | 闲聊皮层和代码皮层（OpenCode）共享用户偏好 | 📋 |
| **网状激活系统** | 注意力过滤 | 群聊海量消息中只关注相关的；决定上下文窗口内容 | � |
| **自主神经系统** | 后台常驻服务 | 消息队列保活、安全过滤、日志、记忆巩固定时触发 | 🚧 |

### 运行节奏：清醒-睡眠周期

```
清醒状态（用户在线）
├── 丘脑高频运转（消息路由）
├── 前额叶随时待命（执行控制）
├── 海马体快速编码（会话记忆）
├── 小脑自动响应（常见问题秒回）
└── 杏仁核实时打分（重要性标记）

睡眠状态（用户离线）
├── 海马体 → 皮层：记忆巩固
├── 技能整理、去重、更新
├── 过期信息修剪
├── 新旧知识冲突检测
└── 自主系统维护（日志归档、索引重建）
```

> 关键设计原则：**平时低功耗待命，需要时全功率运转。记忆"近似最新"而非"强制实时"。**

---

## 目标场景

SUMP 的最终形态是接入 QQ、微信的**全能个人助手**：

- 💬 **日常聊天**：丘脑识别闲聊意图 → 低延迟直接回复
- 🛠️ **代码任务**：丘脑识别编程意图 → 唤醒 OpenCode 子代理 → 自动纠错循环
- 🧠 **知识问答**：海马体 + 皮层联合检索，RAG 增强
- 🔒 **安全边界**：自主神经系统全程值守，危险操作自动拦截

---

## 当前进展

### 已实现

- ✅ DeepSeek V4 API 接入（支持 thinking mode / reasoning_effort 调节）
- ✅ 统一 Agent 核心循环 `run_stream()`（CLI 和 API 纯消费层）
- ✅ Plan-Execute 分离架构（Planner 任务拆解 → Executor 工具调度）
- ✅ FastAPI REST + SSE 流式 API 服务
- ✅ Vite + TypeScript 前端（DeepSeek 风格居中布局 / 悬浮输入框）
- ✅ 前端会话管理 / 模型切换 / 思考强度调节 / 深度思考指示条
- ✅ Markdown 渲染 + highlight.js 语法高亮 / 流式 SSE 输出
- ✅ 工具调用可视化（tool_call / tool_result 终端风格展示）
- ✅ Shell 工具：终端命令执行（GBK 编码适配 / 30s 超时）
- ✅ SQLite 会话持久化 + 历史回档（重启即恢复）
- ✅ 会话管理 API（创建/切换/删除/列出/重命名）
- ✅ 安全审查系统（Judge 规则匹配 + LLM Flash 分析 + Interceptor 裁决 → 前端审批）
- ✅ 前端审批弹窗（safe/risky 自适应样式，拒绝/同意按钮）
- ✅ 多轮工具调用链式审批 + LLM 多 tool_calls 裁剪
- ✅ 记忆四层（按重要性分层）：L0 会话 → L1 浅层（按需唤醒）→ L2 场景 → L3 深层核心
- ✅ 深层核心信息（身份/核心偏好/长期约束/关键决策，容量 50 条，每次对话强制注入 top 20 确保一致性）
- ✅ 本地 embedding（fastembed + bge-small-zh-v1.5，离线零 API 依赖 + 启动预下载）
- ✅ priority 打分剪枝 + 遗忘曲线（访问频次加权，越用越牢、越不用越忘）
- ✅ 记忆冲突检测（store/update/merge/skip）+ 矛盾检测 + 过期回收（80% 安全阈值）
- ✅ 混合检索（FTS5 BM25 + 向量余弦 + RRF）+ 召回三重上限（条数/字符/超时）
- ✅ 纯增量睡眠巩固（游标推进只处理新增，超限才 LLM 压缩丢低价值）
- ✅ 归档通道（历史会话 FTS5 全文检索，不再是黑洞）
- ✅ 工作记忆（跨会话任务进度：flash 摘要 goal + 工具结果 note）
- ✅ 灵魂注入（SOUL.md / AGENTS.md → system prompt + 睡眠精简备份）
- ✅ MCP 客户端（Model Context Protocol 工具接入 + 工具自动注册进 ToolRegistry）
- ✅ MCP 工具沙箱（Sandbox 超时 + 异常隔离执行）
- ✅ NapCat QQ 适配（正向 WebSocket / 零信任主人 / 数字审批 1同意2拒绝 / 群聊记录+自主插话 @必回·星宝加权 / QQ 图片下载识别）
- ✅ 多模态图像理解工具（deepseek-v4-flash-vision-exp，支持本地文件与 URL）
- ✅ 评价器接入执行循环（InternalEvaluator flash 评估 + Arbiter 裁决 finish/continue/retry，8s 超时降级）
- ✅ 技能自动创建（SkillCreator LLM 提炼 → 持久化 skills/permanent/ → 启动加载）
- ✅ Agent 生命周期事件总线（消息/回复/工具/审批事件，供插件订阅）
- ✅ 审批超时自动拒绝（默认 30s，可配置）
- ✅ 记忆召回优化（深层相关召回走 search + 核心/相关字符预算独立 + 内存向量缓存索引）
- ✅ 记忆主人过滤（owner_marker 只提炼主人消息，非主人不进长期记忆）
- ✅ QQ 图片缓存自动清理（睡眠巩固时清理超期文件）
- ✅ 归档查询接口（/api/archive/sessions 等，供前端查看历史）
- ✅ Shell 平台配置化（windows / linux / auto / 自定义提示词）
- ✅ DeepSeek V4 XML 工具调用解析兜底
- ✅ uv 依赖管理 + uv.lock 锁版本 + mypy 静态类型检查
- ✅ SearXNG 搜索接入（MCP 元搜索引擎，自托管免费，聚合 Google/Bing/百度等）
- ✅ 智能家居控制抽象层（SmartHomeBackend 可插拔后端，预留 HA / MQTT / 米家 / 涂鸦）
- ✅ Docker 部署支持（多阶段构建单容器，前后端一体 + docker-compose + 数据卷持久化）

### 规划中

- 📋 丘脑（意图路由 / 消息分类）
- 📋 杏仁核（重要性评分 / 信号门控）
- 📋 小脑技能熟练度管理（自动创建已实现，熟练度升级待接）
- 📋 胼胝体（子代理通信协议 / OpenCode 集成）
- 📋 网状激活系统（注意力过滤 / 上下文窗口管理）
- 📋 自主神经系统完善（消息队列保活 / 记忆巩固定时触发）
- 📋 内置工具完善（FileTool / SearchTool / WebTool / DateTimeTool）

---

## 架构参考

SUMP 的设计充分研究了现有最佳实践：

- **Codex (OpenAI)**：两阶段记忆流水线的信号门控和渐进式披露 → SUMP 的"杏仁核 + 皮层睡眠"
- **Claude Code (Anthropic)**：钩子系统的生命周期注入 → SUMP 的"自主神经系统"
- **OpenCode (SST)**：LSP 深度集成和自动纠错循环 → SUMP 的"代码任务皮层"
- **Hermes Agent (Nous Research)**：技能即过程记忆、跨会话持久记忆（MEMORY.md / USER.md）与记忆提供者插件 → SUMP 的"小脑技能系统 + 灵魂注入"
- **TencentDB-Agent-Memory (腾讯)**：场景-团队记忆分层与记忆流固化调度 → SUMP 的"重要性分层记忆 + 睡眠巩固"

详见 [架构总览](docs/SUMP_architecture.md) | [工作流图](docs/SUMP_flow.drawio.html)

---

## 快速开始

```powershell
# 环境准备
conda create -n sump python=3.12 -y
conda activate sump
pip install uv
uv sync --extra dev

# 设置 API Key
$env:DEEPSEEK_API_KEY = "你的key"

# 启动 CLI 对话
python examples/basic_chat.py

# 启动 Web API
uv run uvicorn api.server:app --host 0.0.0.0 --port 8765

# 启动前端
cd src/frontend && npm install && npm run dev  # → http://localhost:5173
```

### Docker 部署（生产推荐）

```powershell
# 设置 API Key
$env:DEEPSEEK_API_KEY = "你的key"

# 构建并启动（单容器，前端 + API 同端口）
docker compose up -d --build

# 访问 http://localhost:8765
```

数据持久化：`./data`（记忆/日志/模型）与 `./skills`（技能）自动挂载，重建容器不丢失。

## 许可证

MIT
