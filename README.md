# SUMP

> **状态：开发中 | 版本 v0.1.4**

> ⚠️ **警告：目前终端工具未加任何安全审核逻辑，请勿在生产环境使用。**

SUMP 是一个面向 Agent 的轻量级运行时框架，核心围绕记忆分层、技能热插拔、工具沙箱与内置安全。

## 架构设计

- [架构总览](docs/SUMP_architecture.md)
- [工作流图](docs/SUMP_flow.drawio.html)
- [函数调用关系](docs/architecture/call_graph.md)

## 当前进展

- ✅ 架构设计完成
- ✅ Python 3.12 + conda 开发环境
- ✅ DeepSeek V4 API 接入（支持 thinking mode）
- ✅ CLI 交互式对话（流式输出 + 上下文记忆）
- ✅ FastAPI REST + SSE 流式 API 服务
- ✅ Vite + TypeScript 前端（AI-Native UI / 浅色主题 / Inter 字体）
- ✅ 前端会话管理 / 模型切换 / 思考强度调节 / 深度思考指示条
- ✅ Markdown 渲染 + highlight.js 语法高亮 / 流式 SSE 输出
- ✅ 工具调用可视化（tool_call / tool_result 终端风格展示）
- ✅ API 记忆管理端点（前端 SDK 已就绪）
- ✅ Shell 工具：终端命令执行（LLM 可自主调用，CLI + 前端均支持）
- ✅ SQLite 会话持久化 + 历史回档（重启即恢复）
- ✅ 统一 Agent 核心循环 `run_stream()`（CLI 和 API 纯消费层）
- ✅ 会话管理 API（创建/切换/删除/列出）
- ✅ uv 依赖管理 + uv.lock 锁版本
- ✅ mypy 静态类型检查（59 文件 0 错误）
- ⏳ 技能系统实现
- ⏳ 安全审查

### 快速开始

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

## 许可证

MIT
