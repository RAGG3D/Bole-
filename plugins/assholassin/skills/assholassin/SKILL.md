---
name: assholassin
description: 使用本地 IMAP 授权码连接 Gmail、Outlook、网易、QQ 等邮箱，建立订阅垃圾邮件规则，并严格按 dry-run、确认、执行的顺序清理邮件。适用于用户要求接入邮箱、编写邮件清理规则、扫描垃圾邮件、移入垃圾箱或恢复误处理邮件。
---

# assHOLassin

这是一个本地优先的邮件清理技能。插件根目录是本文件的 `../..`；所有脚本调用都应
从插件根目录解析，不要假设当前工作目录。

## 不可覆盖的安全规则

1. 只接受授权码或应用专用密码，绝不索要、接收或存储邮箱登录密码。
2. 授权码只能通过 `mail_agent.py configure` 的终端隐藏输入保存；不要让用户把它
   发到对话中，也不要把它放进命令行参数、输出、错误、计划或日志。
3. 不代用户登录网页、开启 IMAP、生成授权码或点击任何账户安全按钮。
4. 清理永远先运行 `scan`；未展示完整计划并取得明确确认，不得运行 `apply`。
5. `purge` 必须在普通执行确认之外再次单独确认，并优先建议降级到 `trash`。
6. 只读取邮件头，不读取或记录正文。dry-run 只允许只读 SELECT、SINCE SEARCH 和
   BODY.PEEK 头部 FETCH。
7. 网络中断后先核对 `state/clean_log_*.json`，只续跑未完成项，绝不盲目整轮重跑。

## 工作流

### 1. 接入邮箱

读取 `providers.json`，根据邮箱域名展示对应中文开通指引。让用户在自己的终端运行：

```bash
python3 <插件根>/scripts/mail_agent.py configure \
  --provider <域名> --email <邮箱地址>
```

授权码由终端隐藏输入。配置完成后脚本会以只读方式验证 INBOX。

### 2. 管理规则

规则保存在 `<插件根>/profile/rules.json`。逐条询问发件人关键词、主题关键词、
`any|all`、动作 `soft|trash|purge` 和最近天数；展示完整 JSON，得到确认后才写入。
白名单优先级永远最高。若文件不存在，按插件 README 的示例创建。

### 3. 清理

先运行：

```bash
python3 <插件根>/scripts/mail_agent.py scan [--days N] [--mailbox X]
```

按等级分组展示计划文件中的日期、发件人、主题、命中规则和动作。确认后才运行：

```bash
python3 <插件根>/scripts/mail_agent.py apply --plan <计划文件> --confirm
```

存在 purge 时还必须取得第二次明确确认并添加 `--confirm-purge`。如用户不确定，添加
`--level-limit trash` 将 purge 降级为 trash。

## 恢复与故障

- soft：原件仍在 INBOX，只需删除 `assHOLassin-标记` 中的副本或按需恢复未读。
- trash：在服务商垃圾箱保留期内搬回 INBOX。
- purge：不可恢复。
- 授权失败只展示 `providers.json` 中的排查提示，不回显服务端原始错误。
