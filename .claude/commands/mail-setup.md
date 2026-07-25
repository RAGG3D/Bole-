# /mail-setup

为 assHOLassin 接入一个或多个邮箱。插件根目录固定为
`plugins/assholassin/`；开始前读取该目录的 `README.md` 与 `providers.json`。

## 安全边界

- 只接受服务商生成的授权码或应用专用密码，绝不索要邮箱登录密码。
- 不让用户把授权码发进对话，不把授权码放进 shell 命令参数、输出、错误或日志。
- 绝不代用户登录网页、开启 IMAP、生成授权码或点击账户安全按钮。
- 授权码只写入本地且 gitignored 的 `plugins/assholassin/profile/mailbox.json`。

## 流程

1. 询问邮箱地址，据域名匹配 `providers.json`。支持 Gmail、Outlook/Hotmail、
   163、126、Yeah、QQ 与 Foxmail；不支持时停止，不猜 IMAP 参数。
2. 原样展示该服务商的 `setup_guide_zh` 和 `quirks`，让用户自己完成网页设置。
3. 让用户在自己的终端运行下列命令。不要替用户传入授权码：

   ```bash
   python3 plugins/assholassin/scripts/mail_agent.py configure \
     --provider <邮箱域名> --email <邮箱地址>
   ```

   脚本会隐藏读取授权码，以 `0600` 权限落盘，并立即执行 LOGIN +
   `SELECT INBOX readonly`。
4. 用户返回执行结果后：
   - 成功：报告“接入成功，共 N 封”，并询问是否继续增加邮箱；
   - 失败：只依据对应 provider 的 `quirks` 排查，建议吊销并重新生成授权码；
     不要求用户展示授权码，也不回显服务端原始错误。
5. 全部邮箱可随时再次只读验证：

   ```bash
   python3 plugins/assholassin/scripts/mail_agent.py probe
   ```
