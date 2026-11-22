# 本地部署记录 / Local Setup Notes

本仓库是 [illria/deepseek-web-api-bridge](https://github.com/illria/deepseek-web-api-bridge) 的个人副本，
额外加了 macOS 安装脚本、登录态抓取工具和自检脚本。上游代码保持原样，改动集中在 `scripts/` 和 `run.sh`。

## 环境

| 项 | 值 |
|---|---|
| 主机 | MacBook Air M4 / 24G（192.168.1.6），macOS 27.0.1 |
| Python | 3.12.16（由 uv 安装，系统自带 3.9 不兼容本项目） |
| 浏览器 | Playwright Chromium 143（headless shell + 完整版） |
| 端口 | 8000 |

## 安装（已在本机完成，重装时照做）

```bash
cd ~/deepseek-web-api-bridge

# 1. Python 3.12 + 虚拟环境
uv python install 3.12
uv venv --python 3.12 .venv

# 2. 依赖（清华源）
export UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
uv pip install --python .venv/bin/python -r requirements.txt

# 3. Playwright Chromium（npmmirror 镜像，国内直连 CDN 会失败）
export PLAYWRIGHT_DOWNLOAD_HOST="https://cdn.npmmirror.com/binaries/playwright"
.venv/bin/python -m playwright install chromium

# 4. 配置
cp .env.example .env
# 填 STATE_ENCRYPTION_KEY / BRIDGE_API_KEYS（见下）
```

生成密钥：

```bash
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
.venv/bin/python -c "import secrets; print('sk-bridge-' + secrets.token_hex(24))"
```

## 启动 / 停止

```bash
./run.sh        # 前台
./run.sh bg     # 后台，日志 logs/bridge.log
./run.sh stop   # 停止
```

控制台：<http://127.0.0.1:8000/>

## 抓取登录态

```bash
.venv/bin/python scripts/capture_login.py --account-id ds-main --display-name "主账号"
```

弹出 Chromium → 手机号+验证码（或扫码）登录 → 脚本自动抓 cookies/localStorage，
加密导入 Bridge，并删除明文副本。浏览器 profile 持久化在 `data/browser-profile`，下次免登录。

## 自检

```bash
.venv/bin/python scripts/selftest.py        # 全部用例
.venv/bin/python scripts/selftest.py basic  # 只跑基础
```

## 客户端接入

```
Base URL : http://<本机IP>:8000/v1      # OpenAI 兼容
           http://<本机IP>:8000/anthropic/v1   # Anthropic 兼容
API Key  : .env 里的 BRIDGE_API_KEYS
Model    : deepseek-web
```

## 与上游的差异

新增文件：

- `run.sh` —— macOS 启动/停止脚本，自动带上 `PLAYWRIGHT_BROWSERS_PATH`
- `scripts/capture_login.py` —— 扫码登录 → 自动抓取并导入登录态
- `scripts/selftest.py` —— 端到端自检（多 session、复用、流式）
- `LOCAL_NOTES.md` —— 本文件

修改：`.gitignore` 增加 `.venv/`、`logs/`。

## 已知问题

见下节「调试记录」。
