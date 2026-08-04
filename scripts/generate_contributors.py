"""鐢熸垚璐＄尞鑰呭垪琛?""

import subprocess


def main():
    try:
        result = subprocess.run(
            ["git", "log", "--format=%aN <%aE>", "--", "."],
            capture_output=True, text=True,
        )
        contributors = sorted(set(result.stdout.strip().split("\n")))
        print("# Contributors\n")
        for c in contributors:
            if c:
                print(f"- {c}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()