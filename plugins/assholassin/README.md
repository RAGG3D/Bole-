# assHOLassin

assHOLassin 是一个批量清理订阅垃圾邮件的本地刺客：它通过标准 IMAP 只读取邮件头，
先生成 dry-run 计划，再按用户确认执行。

它不包含任何账号或凭据，不使用 Gmail API，不进行 OAuth，也不会自动登录网页。
Gmail、Outlook/Hotmail、163、126、Yeah、QQ 和 Foxmail 用户都使用自己生成的
授权码或应用专用密码。授权码只保存在本机 `profile/mailbox.json`，可随时在邮箱
服务商的安全设置中吊销。

## 安装

本目录是一个完整 Codex 插件，安装标识为 `assholassin`。从仓库安装：

```bash
codex plugin marketplace add RAGG3D/Bole-
codex plugin add assholassin@personal
```

在 Claude Code 中使用本仓库时，也可以直接调用根目录提供的 `/mail-setup`、
`/mail-rules` 和 `/mail-clean`。

## 授权码不是登录密码

授权码或应用专用密码是为邮件客户端单独生成、可单独吊销的凭据；邮箱登录密码用于
登录账户本身。插件只接受前者，绝不索要后者，也不会替你打开网页、开启 IMAP 或
点击账户安全按钮。

为避免授权码进入聊天记录或 shell 历史，请在自己的终端运行隐藏输入向导：

```bash
python3 scripts/mail_agent.py configure --provider gmail.com --email you@example.com
```

配置文件会以 `0600` 权限写入 `profile/mailbox.json`。支持重复运行以增加多个邮箱。

## 三步上手

1. `/mail-setup`：选择服务商，按中文指引生成授权码并进行只读连接验证。
2. `/mail-rules`：配置发件人/主题关键词、时间窗口、白名单和处理等级。
3. `/mail-clean`：先 dry-run 展示清单，确认后才执行。

核心 CLI：

```bash
python3 scripts/mail_agent.py probe
python3 scripts/mail_agent.py scan --days 30
python3 scripts/mail_agent.py apply --plan state/scan_plan_<时间>.json --confirm
```

如果计划含永久删除，还必须再次确认并添加 `--confirm-purge`。使用
`--level-limit trash` 可以把本轮 purge 降级为 trash。

## 规则

`profile/rules.json` 示例：

```json
{
  "rules": [
    {
      "id": "r1",
      "enabled": true,
      "match": {
        "from_contains": ["noreply@", "marketing"],
        "subject_contains": ["unsubscribe", "促销"],
        "logic": "any"
      },
      "action": "trash",
      "window_days": 30
    }
  ],
  "whitelist": {
    "senders": [],
    "domains": [],
    "subject_contains": []
  },
  "default_window_days": 30,
  "max_actions_per_run": 200
}
```

中文主题不会交给服务器搜索。脚本只用 `SINCE` 初筛，再通过
`BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)]` 抓取邮件头，并在本地解码 RFC2047
后匹配。`any` 表示任一关键词命中，`all` 表示所有已填写关键词都命中；首条命中的
规则决定动作。白名单具有绝对优先级。

## 三档处理等级

| 动作 | 行为 | 风险与恢复 |
|---|---|---|
| `soft` | 标记已读，并复制到 `assHOLassin-标记`；INBOX 原件保留 | 完全可恢复 |
| `trash` | 复制到运行时识别的垃圾箱，再定向删除 INBOX 原件 | 垃圾箱保留期内可搬回 |
| `purge` | 标记删除并用 `UID EXPUNGE` 定向清除 | 不可恢复 |

建议从 `trash` 起步。服务商垃圾箱通常只保留有限时间，具体期限以服务商规则为准。
为避免普通 `EXPUNGE` 顺带删除计划外邮件，trash/purge 只在服务器声明支持 UIDPLUS
时执行；不支持则在任何删除写操作前停止并转人工。

## 审计、恢复与续跑

- dry-run 计划写入 `state/scan_plan_*.json`。
- 执行日志写入 `state/clean_log_<日期>.json`，只包含 UID、发件人、主题、动作、
  文件夹和时间，不包含授权码或正文。
- soft 的 INBOX 原件不会删除；trash 可在垃圾箱保留期内搬回 INBOX；purge 无法恢复。
- 断网或 IMAP 报错后，先查看审计日志。再次应用同一计划时，脚本会跳过已成功记录
  的项目，避免整轮重放。

## 免责声明

邮件规则可能误判，误删风险由使用者承担。永远先检查 dry-run 清单，优先使用
`trash`，谨慎使用 `purge`。首次使用前建议备份重要邮件并用少量规则测试。
