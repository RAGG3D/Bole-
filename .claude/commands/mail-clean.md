# /mail-clean

按“只读扫描 → 展示完整计划 → 用户确认 → 按计划执行”的顺序清理邮件。插件根目录为
`plugins/assholassin/`。

## 不可覆盖的安全铁律

1. 永远先 dry-run；未展示完整计划并取得明确确认，不得运行 apply。
2. purge 必须在普通确认之外单独再次确认，并默认劝导改用 trash。
3. 只处理计划中的 UID，遵守 `max_actions_per_run`；不得扩大关键词或整箱处理。
4. 授权码和邮件正文不得出现在输出、报错、计划或日志中。
5. 断网或 IMAP 报错后先核对 `state/clean_log_*.json`，再续跑同一计划；绝不整轮
   重扫后盲目重放。

## 1. dry-run

默认扫描规则自己的时间窗口；用户说“只清最近 7 天”时添加 `--days 7`：

```bash
python3 plugins/assholassin/scripts/mail_agent.py scan [--days N] [--mailbox X]
```

读取输出中的 `plan_file`，完整展示日期、发件人、主题、命中规则和动作，并按
soft/trash/purge 分组统计。若 `truncated=true`，明确说明已达到单轮上限。

## 2. 确认与执行

先取得一次明确的整体执行确认。只要清单中存在 purge，再单独展示全部 purge 项并
询问“这些邮件将永久删除且不可恢复，是否仍要继续？”。

- 无 purge：

  ```bash
  python3 plugins/assholassin/scripts/mail_agent.py apply \
    --plan <plan_file> --confirm
  ```

- 用户单独确认 purge：

  ```bash
  python3 plugins/assholassin/scripts/mail_agent.py apply \
    --plan <plan_file> --confirm --confirm-purge
  ```

- 用户不确定或接受降级：

  ```bash
  python3 plugins/assholassin/scripts/mail_agent.py apply \
    --plan <plan_file> --confirm --level-limit trash
  ```

## 3. 完成与恢复

报告实际执行数、跳过的已完成数和审计日志路径。soft 的 INBOX 原件仍保留；
trash 可在服务商垃圾箱保留期内搬回；purge 不可恢复。任何中断都先对照审计日志，
同一计划再次执行时脚本会跳过已有成功记录。
