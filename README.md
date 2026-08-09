# SUMP

> **状态：开发中 | 版本 v0.1.2**

SUMP（Smart Unified Memory & Platform）是一个面向 Agent 的轻量级运行时框架，核心围绕记忆分层、技能热插拔、工具沙箱与内置安全。

## 架构设计

- [架构总览](docs/SUMP_architecture.md)
- [工作流图](docs/SUMP_flow.drawio.html)
- [函数调用关系](docs/architecture/call_graph.md)

## 当前进展

- ✅ 架构设计完成
- ✅ Python 3.12 + conda 开发环境
- ✅ DeepSeek V4 API 接入（支持 thinking mode）
- ✅ 最小自循环对话（流式输出 + 上下文记忆）
- ⏳ 记忆系统接入
- ⏳ 工具 / 技能系统实现
- ⏳ 安全审查

### 快速开始

```powershell
# 环境准备
conda create -n sump python=3.12 -y
conda activate sump
pip install -e ".[dev]"

# 设置 API Key（二选一）
$env:DEEPSEEK_API_KEY = "你的key"
# 或在 configs/default.yaml 中配置 deepseek.api_key

# 启动对话
python examples/basic_chat.py
```

## 许可证

MIT