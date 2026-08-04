"""生成贡献者列表"""

import subprocess


def main():
    try:
        result = subprocess.run(
            ["git", "log", "--format=%aN <%aE>", "--", "."],
            capture_output=True, text=True,
        )
        contributors = sorted(set(result.stdout.strip().split("
")))
        print("# 贡献者
")
        for c in contributors:
            if c:
                print(f"- {c}")
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    main()
