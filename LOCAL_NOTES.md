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

## 调试记录（2026-11-23）

### 实测结论

| 场景 | 结果 |
|---|---|
| 单轮问答（5 连测） | 5/5 通过，每次约 4.8s |
| 多轮上下文（请求体带历史） | 通过，暗号能正确回忆 |
| 同 session 连续 3 次 | 3/3 通过，答案 A/B/C 未串 |
| 流式 SSE | 通过，6.0s 完整返回 |
| 同端口跑两个实例 | **必崩**：两个服务抢同一 DeepSeek 账号，出现 502 / 超时 / 答案错乱 |

### 发现的三个真实缺陷（已修）

1. **每个 sessionId 都新开一个浏览器 page**（上游 V12 设计）
   实测 DeepSeek 这个 SPA 在多标签页下第 2 个 page 常常只渲染空壳
   （`document.body.innerText` 只有 42 字符，正常 682），
   导致输入框点不动、回复永远提取不到。
   → 改为「一个账号一个页面」，会话隔离改用页面内切换 DeepSeek 会话。

2. **Playwright 调用没有超时保护**
   `page.evaluate` 本身不接受超时，一旦页面卡住，任务永久挂起，
   `_lock` 和 `_busy` 不释放，后续请求全部排队（表现为「任务仍在运行」）。
   → 给提取/生成检测加 `asyncio.wait_for`，并新增 `force_recover()` 看门狗：
   超过 `WORKER_HARD_TIMEOUT_MS + 30s` 仍 busy 就强制重建浏览器。

3. **客户端提前断开后 job 仍在后台跑**
   curl / 客户端超时断开时，服务端任务继续占用 worker，
   下一个请求要排队等它跑完（实测拖到 130s+、甚至 1000s+）。
   → 排查时务必让请求跑完；生产环境把客户端超时设置得比
   `WORKER_HARD_TIMEOUT_MS`(已调为 240s) 更大。

### 运行纪律

- **只允许一个实例**。`./run.sh bg` 已内置端口探测，重复启动会直接拒绝。
- 调参后要重启：`./run.sh stop && ./run.sh bg`。
- 查看状态：`./run.sh status`。
- 大量测试后清历史任务，避免残留 job 干扰：
  `rm -f data/jobs/*.json`（先停服务）。

### 长文本

2341 字符的 prompt 实测可用（速度会慢于短 prompt，属正常）。

## 技术备注：DeepSeek 网页接口

- 发消息走 `POST /api/v0/chat/completion`，前置 `POST /api/v0/chat/create_pow_challenge`。
- 响应是流式 SSE，且**带有 PoW 挑战**，无法直接用 HTTP 重放。
  本项目因此采用 Playwright 驱动真实页面 + DOM 提取，速度受网页渲染影响。
- 想读流式 body 用 Playwright 的 `response.text()` 会失败
  （`No data found for resource with given identifier`），
  这也是只能抓 DOM 的原因。

## 接入 Hermes（已完成）

Hermes 侧新增自定义 provider `dsweb`（配置在 `$HERMES_HOME/config.yaml` 的 `providers:` 下）：

```yaml
providers:
  dsweb:
    name: DeepSeek Web (local bridge)
    base_url: http://127.0.0.1:8000/v1
    api_mode: chat_completions
    transport: openai_chat
    model: deepseek-web
    api_key: "${BRIDGE_DSWEB_KEY}"   # 值放在 $HERMES_HOME/.env
    models:
      deepseek-web:
        supports_tools: true           # 实测可用：能返回标准 tool_calls
```

用法：

```bash
# CLI
hermes chat --provider dsweb -m deepseek-web
# 桌面端：Cmd+K / 模型选择里选 provider dsweb
```

实测：Hermes 走该 provider 提问，13s 返回「接入成功」，session 记录的模型为 `deepseek-web`，
Bridge trace 有 prepared/filled/sent/waiting_reply 完整链路。

注意：`hermes chat -m <alias>` **不会**解析用户自定义别名（会静默回落默认 provider），
必须用 `--provider dsweb`。

### 工具调用（实测可用）

| 测试 | 结果 |
|---|---|
| 直接打 `/v1/chat/completions` 带 `tools` | `finish_reason=tool_calls`，返回 `{"name":"get_weather","arguments":"{\"city\":\"北京\"}"}`，4.9s |
| Hermes 走 dsweb 派任务 | 真实执行 2 次 `ls`/`find` 命令，16s（`fast_final` 模式） |
| 同上，`agentToolResultMode=model` | 19s，最后自然回答「当前目录下共有 10 个文件。」 |

`agentToolResultMode` 两种行为：

- `fast_final`：直接把工具结果原文返回，省一次往返、最快，但回答是裸 JSON。
- `model`（**当前采用**）：把工具结果回灌给模型再总结一句，多一次往返（约 +3~10s），体验正常。

改法：`curl -X PUT /api/settings`（或改 `data/settings/runtime.json`）。

## 本次修复（2026-11-23）

| 问题 | 修复 |
|---|---|
| 每个 sessionId 新开一个 page，第 2 个标签页在 headless 下只渲染空壳（body≈42 字符），导致 composer 点不到、任务卡死 | 改为单账号单页面，会话隔离靠切换会话；加空壳检测自动 reload |
| `page.evaluate` 没有超时，页面挂起会永久占住 `_lock` | 所有 evaluate 包 `asyncio.wait_for` |
| worker 卡死后 `busy` 永久为 true | `worker_pool` 健康检查加看门狗，超硬超时强制重建浏览器（force_recover） |
| 上游按 DOM 顺序(order)判断“新回复”，复用会话时拿到上一条甚至用户提问 | 改为只取**最后一个 assistant 节点**，文本稳定 1.5s 且无“生成中”即收尾 |
| 回车没生效也干等 120s | 发送后校验提问气泡是否出现，未出现立即重发一次 |
| 卡在哪里看不出来 | `logs/worker-trace.log` 记录 prepared/filled/sent/waiting_reply |
| 单轮请求被套上「请自然继续下面的对话」，模型会回「好的，请继续。」 | 单轮（无 assistant 历史）直接送用户原话 |

实测（本机 MacBook Air，headless）：

- 连续 5 次请求：**5/5 通过，约 4.8s/次**
- 连续 10 次请求：**10/10 通过**（其中 1 次 191s，被 240s 硬超时兜住后正常返回）
- 多轮上下文（历史走请求体）：通过，约 4.8s
- 流式：通过，6.0s，`[DONE]` 正常收尾
- 修复前：经常 130s~1000s 超时、502、答案错乱
