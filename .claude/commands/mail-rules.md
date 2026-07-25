# /mail-rules

逐条维护 assHOLassin 邮件清理规则。规则只写入本地且 gitignored 的
`plugins/assholassin/profile/rules.json`。

## 固定流程

1. 若文件存在，先读取并用表格展示现有规则和白名单；若不存在，从空规则开始。
2. 支持增、删、改、查。每次只处理一条变更，并询问：
   - 发件人关键词 `from_contains`；
   - 主题关键词 `subject_contains`；
   - 匹配逻辑 `any` 或 `all`；
   - 最近 N 天 `window_days`；
   - 处理等级 `soft`、`trash` 或 `purge`。
3. 解释风险：soft 保留 INBOX 原件；trash 在垃圾箱保留期内可恢复；purge
   不可恢复。新增规则默认推荐 trash，不主动推荐 purge。
4. 白名单可维护发件人、域名和主题关键词，白名单永远优先并绝对豁免。
5. 展示变更后的完整 JSON；只有用户逐条明确确认后才写入。

规则结构必须保持：

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

`rules[].id` 必须唯一；关键词数组至少有一个非空值；天数与动作上限必须是正整数。
不要在规则文件里写授权码、登录密码或邮件正文。
