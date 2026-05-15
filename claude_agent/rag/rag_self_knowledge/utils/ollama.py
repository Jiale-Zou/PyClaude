import subprocess
import sys
import time
import os
import platform
import requests


def is_ollama_running():
    """
    检查 Ollama 服务是否在运行
    """
    try:
        # 尝试访问 Ollama 的 API 端点
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            return True
        else:
            return False
    except requests.exceptions.ConnectionError:
        # 连接失败，说明服务未运行
        return False
    except ImportError:
        # 如果没有安装 requests，使用 subprocess 尝试检测进程
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ['tasklist', '/FI', 'IMAGENAME eq ollama.exe'],
                    capture_output=True, text=True, timeout=5
                )
                return 'ollama.exe' in result.stdout
            else:
                result = subprocess.run(
                    ['pgrep', '-f', 'ollama serve'],
                    capture_output=True, text=True, timeout=5
                )
                return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False


def start_ollama():
    """
    启动 Ollama 服务（后台运行）
    """
    system = platform.system()

    try:
        if system == "Windows":
            # Windows：通过 subprocess 启动 ollama serve（后台运行）
            subprocess.Popen(
                ['ollama', 'serve'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW  # 不显示窗口
            )
            print("正在启动 Ollama 服务 (Windows)...")

        elif system == "Darwin":  # macOS
            # macOS：尝试使用 launchctl 启动服务
            result = subprocess.run(
                ['launchctl', 'list', 'com.ollama.ollama'],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                subprocess.run(['open', '-a', 'Ollama'], check=False)
                print("正在启动 Ollama 应用 (macOS)...")
            else:
                # 如果服务存在但未运行，尝试启动
                subprocess.Popen(
                    ['ollama', 'serve'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                print("正在启动 Ollama 服务 (macOS)...")

        else:  # Linux
            # Linux：尝试使用 systemctl，如果失败则使用 nohup
            try:
                result = subprocess.run(
                    ['systemctl', 'is-active', 'ollama'],
                    capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip() != 'active':
                    subprocess.run(['sudo', 'systemctl', 'start', 'ollama'], check=True)
                    print("通过 systemctl 启动 Ollama 服务...")
                else:
                    print("Ollama 服务已经在运行")
                    return True
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
                # systemctl 不可用或失败，使用 nohup 手动启动
                subprocess.Popen(
                    ['nohup', 'ollama', 'serve', '>', '/dev/null', '2>&1', '&'],
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                print("使用 nohup 启动 Ollama 服务 (后台运行)...")

        # 等待服务启动
        time.sleep(3)
        return True

    except Exception as e:
        print(f"启动 Ollama 时出错: {e}")
        return False


def ensure_ollama_running(max_retries=3):
    """
    确保 Ollama 服务正在运行，如果未运行则启动
    返回 True 表示服务已就绪，False 表示启动失败
    """
    # 首先检查是否已运行
    if is_ollama_running():
        print("✓ Ollama 服务已在运行")
        return True

    print("⚠ Ollama 服务未运行，正在尝试启动...")

    for attempt in range(max_retries):
        if start_ollama():
            # 等待服务完全启动
            for i in range(10):  # 最多等待 10 秒
                if is_ollama_running():
                    print("✓ Ollama 服务已成功启动")
                    return True
                time.sleep(1)

        if attempt < max_retries - 1:
            print(f"第 {attempt + 1} 次尝试失败，正在重试...")
            time.sleep(2)

    print("✗ 无法启动 Ollama 服务，请手动检查")
    return False
