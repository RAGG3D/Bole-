# /doctor — Bole 环境体检

面向用户的输出遵守 `profile/config.json` 的 `config.ui_language`；文件不存在时默认中文。

你的任务是只做检测和修复指引，不静默安装、登录或修改任何系统组件。依次检查并以
“通过 / 需修复 / 可选”逐项报告：

1. 执行 `claude --version`，确认 Claude Code CLI 可用；不要硬编码或要求特定模型。
2. 执行 `python3 --version`，确认 Python ≥ 3.10。
3. 探测 `google-chrome`、`chromium`、`chromium-browser`、Edge 及 macOS/Windows
   常见路径，说明浏览器用于 HTML→PDF。没有浏览器不阻断核心流程：说明会保留 HTML，
   用户可用浏览器 Ctrl+P 另存为 PDF。
4. 用不携带 Cookie 的 HEAD 请求探测 `https://www.linkedin.com` 的基本网络连通性。
   请求失败只说明公开职位发现会受影响，不要反复请求或尝试绕墙。
5. 检查 `profile/facts.json`、`profile/config.json`、`profile/digest.md`。未建档时
   引导下一步运行 `/setup`；不要把 demo 数据当作真实用户数据。
6. 执行 `bash install.sh` 可作为补充，但要理解它只检测、不安装。

先读取 `profile/config.json`（若存在）。只有当 `config.auto_submit.enabled=true`
时，才追加以下 OpenClaw 体检；开关关闭时不要调用 OpenClaw，也不要探测网关：

7. `node --version`，确认 Node ≥ 18。
8. `openclaw --version`。缺失时给出 `npm install -g openclaw` 并解释这是可选的
   自动投递依赖，由用户自己决定是否执行；绝不代为安装。
9. 以 OpenClaw 自身提供的状态命令探测本地网关，不通时建议用户前台执行
   `openclaw gateway run`。说明 WSL2 无 systemd 时网关崩溃不会自愈，可由用户自行
   使用 tmux/nohup 常驻；不要擅自创建系统服务。
10. 询问并仅探测 OpenClaw 浏览器 profile 是否已由**用户本人**登录本轮要投递的
    招聘站。绝不代登录、绝不读取凭据。提醒 Workday 每家公司租户是独立账号，首投
    可能需要本人注册，复投可能需要本人登录，这是设计而非故障。

最后给出一段短结论：是否可以运行 `/setup`、是否可以运行 `/scan`、`/apply` 是否
就绪。OpenClaw 未就绪绝不能阻断 `/setup` 或 `/scan`。
