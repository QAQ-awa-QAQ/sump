"""审判官（命令安全分析）"""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Verdict:
    verdict: str  # "safe" | "risky" | "unknown"
    summary: str
    danger: str  # "low" | "medium" | "high" | "critical"
    concerns: list[str] = field(default_factory=list)


class Judge:
    """分析 shell 命令的意图和危险程度。

    产出 Verdict 而非最终决定——由前端/用户裁决。
    """

    # 高危模式：(正则为匹配命令开头部分, 危险等级, 摘要, 关切)
    _DANGEROUS: list[tuple[str, str, str, list[str]]] = [
        (r"^(rm|del)\s", "high", "删除文件或目录", ["不可逆", "可能删库"]),
        (r"^(format|mkfs)", "critical", "格式化磁盘", ["不可逆", "全盘数据丢失"]),
        (r"^shutdown", "high", "关机/重启系统", ["影响系统可用性"]),
        (r"^(curl|wget)\s.*\|\s*(bash|sh|cmd)", "critical", "下载并执行远程脚本", ["远程代码执行", "无签名验证"]),
        (r"^(chmod\s.*777|chmod\s.*\+x)", "high", "修改文件权限", ["可能暴露敏感文件"]),
        (r"^sudo\s", "high", "以管理员权限执行", ["提权操作"]),
        (r"^taskkill\s", "high", "强制终止进程", ["可能终止关键服务"]),
        (r"^reg\s(delete|add)", "high", "修改注册表", ["可能影响系统配置"]),
        (r"^net\s(user|localgroup)", "high", "修改用户/组", ["影响系统安全策略"]),
        (r"^(sc\s|net\sstop)", "medium", "管理系统服务", ["可能停用安全服务"]),
    ]

    # 安全模式
    _SAFE: list[tuple[str, str, str]] = [
        (r"^dir\b", "列出目录内容", "low"),
        (r"^ls\b", "列出目录内容", "low"),
        (r"^echo\b", "输出文本", "low"),
        (r"^cd\b", "切换目录", "low"),
        (r"^type\b", "查看文件内容", "low"),
        (r"^cat\b", "查看文件内容", "low"),
        (r"^pwd\b", "查看当前路径", "low"),
        (r"^whoami\b", "查看当前用户", "low"),
        (r"^set\b", "查看环境变量", "low"),
        (r"^touch\b", "创建空文件", "low"),
        (r"^mkdir\b", "创建目录", "low"),
        (r"^(copy|xcopy|robocopy)\b", "复制文件", "low"),
        (r"^(move|ren|rename)\b", "移动/重命名文件", "low"),
        (r"^(python|node)\s", "运行脚本", "medium"),
        (r"^(pip|npm)\s", "包管理操作", "medium"),
    ]

    def analyze(self, command: str) -> Verdict:
        """分析命令，返回安全裁决。"""
        cmd = command.strip()

        # 拆分复合命令（&& | || ;），逐个检查
        import re as _re
        parts = _re.split(r"\s*(&&|\|\||;)\s*", cmd)

        # 先查黑名单（检查每个子命令）
        for part in parts:
            part_lower = part.lower().strip()
            for pattern, danger, summary, concerns in self._DANGEROUS:
                if _re.match(pattern, part_lower, _re.IGNORECASE):
                    return Verdict(
                        verdict="risky",
                        summary=summary,
                        danger=danger,
                        concerns=concerns,
                    )

        # 再查已知安全（只检查主命令）
        first = parts[0].lower().strip()
        for pattern, summary, danger in self._SAFE:
            if _re.match(pattern, first, _re.IGNORECASE):
                return Verdict(
                    verdict="safe",
                    summary=summary,
                    danger=danger,
                )

        # 不匹配 → 交给 LLM
        return Verdict(
            verdict="unknown",
            summary="待 LLM 分析",
            danger="medium",
        )

    async def analyze_llm(self, command: str, llm: Any) -> Verdict:
        """用 LLM（Flash 无思考）分析未知命令的意图和危险程度。"""
        prompt = (
            "分析以下 Shell 命令，只输出 JSON（不要 markdown）：\n"
            f"命令: {command}\n"
            '{{"summary":"一句话描述命令意图(中文)","danger":"low|medium|high|critical","verdict":"safe|risky","concerns":["关切1"]}}'
        )
        try:
            result = await llm.chat_flash(prompt)
            import json
            data = json.loads(result.strip().removeprefix("```json").removesuffix("```").strip())
            return Verdict(
                verdict=data.get("verdict", "risky"),
                summary=data.get("summary", "无法分析"),
                danger=data.get("danger", "medium"),
                concerns=data.get("concerns", []),
            )
        except Exception:
            return Verdict(
                verdict="risky",
                summary=f"无法分析的命令: {command[:50]}",
                danger="medium",
                concerns=["LLM 分析失败"],
            )
