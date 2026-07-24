# /apply — 可选的 OpenClaw 自动投递

面向用户的输出遵守 `profile/config.json` 的 `config.ui_language`。

`/apply` 是高影响、可选流程。全程顺序执行，同一时刻只允许一个浏览器投递会话；
每单之间等待至少 30 秒；一轮不超过 `auto_submit.max_per_run`。Bole 只向用户本人已登录
的 OpenClaw 浏览器 profile 发任务，绝不读取或接触凭据。

## 三道启动闸门

1. 只读取 `profile/config.json`。若 `config.auto_submit.enabled` 不是 `true`，立即停止；
   不调用网络、OpenClaw 或任何投递脚本。按 ui_language 说明：
   - 自动投递默认关闭，`/scan` 的投递包仍可完整手动使用；
   - 启用前要运行 `/doctor`，安装可选 OpenClaw、由用户本人登录招聘站；
   - 解释 `final_confirm` 的 `per_job` / `per_run` / `off`，警告 `off` 会移除最终人为
     确认；询问用户是否希望在理解风险后修改配置。此轮只给引导，不擅自开关。
2. 开关已启用时，执行 `/doctor` 的 OpenClaw 扩展检查。Node ≥18、OpenClaw、网关或
   用户登录态未就绪则给修复指引并退出，不发投递任务。
3. 从 `Applications/` 读取投递包 verdict，不从文件夹名反解析。先按路由和投前防线
   得出本轮清单，再按 `final_confirm`：
   - `per_job`：每岗提交前展示公司、职位、URL、薪资和材料并明确确认；
   - `per_run`：在本轮开始展示完整清单并取得一次明确确认；
   - `off`：再次警告无人值守风险后按配置继续，但仍不得放宽任何安全红线。

没有取得配置要求的确认时，不提交。

## 路由与逐岗投前防线

投递 URL 优先 `verdict.apply_url`，空则 `verdict.url`。按 hostname 小写去端口匹配
`data/ats_map.json`：`hostname == d` 或 `hostname.endswith("." + d)`，多条取最长
domain，path/query 不参与。只有条目 `auto_submit=true` 且平台名在
`config.auto_submit.allowed_ats` 才自动投，其余记 `manual`。绝不把 linkedin.com
岗位页交给浏览器；LinkedIn easy apply 始终手动。

每岗在发任务前依次执行：

0. LinkedIn offsite 且 apply_url 为空：按 verdict 中 source_id 重访
   `sources.py jd --source linkedin` 提取直链；仍为空则记 manual，提示用户手动提供
   直链并可由 `sources.py jd --source url` 重新入列。
1. `jd_completeness=stub`：用 apply_url 经 `sources.py jd --source url` 抓 ATS 完整
   JD，按 `/scan` §7.2 重跑资格闸门与红线核对，更新岗位 `verdict.json`。资格不符或
   核心红线则 skip/manual。stub 会高估匹配，绝不按 stub 直接投。
2. 确认 CV PDF、Cover PDF（若 ATS 收）、README、verdict.json 齐备，并重新执行
   `redline_scan.py`；未通过不得提交。
3. 查 `state/submissions.json`；submitted/unknown 均不得再 run。只有用户已经人工
   核实并明确承担双投风险时才可使用 `--force`。

执行新投递：

```sh
python3 scripts/submit.py run --job "<folder>" --config profile/config.json --facts profile/facts.json
```

不要自行拼 OpenClaw 命令；所有通信只能经过 `submit.py` 的 adapter 单点。

## 任务消息与回复协议（原文规则）

发给 OpenClaw 的每条投递任务消息必含,依序:
1. **目标**:投递直链 URL(verdict.apply_url,为空时用 url——但绝不允许是 linkedin.com 岗位页)、公司、职位名;
2. **材料**:要上传的 CV / Cover PDF 的**绝对路径**;明确"必须上传这两个指定文件,**绝不使用平台已存储的旧简历**,简历解析回填的字段要逐一核对并改回定制内容";
3. **表单速查答案**(全部来自 facts/config/verdict,不许代理自己发挥):工作权利原文、通知期、期望薪资 = verdict 的 `recommended_salary_form.amount`(连同币种与含/不含 super 说明;amount 为 null 时回退 `config.salary_expectation.amount`;两者皆缺则该项不写入速查答案,表单强制必填时由代理报 `NEED | what=salary`)、如何得知职位=LinkedIn、出生日期(仅当 facts 里有且该 ATS 的 quirks 说明必填);
4. **该 ATS 的 quirks[]** 原样列出;
5. **行为红线**:遇验证码/在线测评/视频面试/性格测试 → 立即停止报 BLOCKED(对应 reason);站点只提供 Google/LinkedIn OAuth 一键登录/注册 → BLOCKED oauth_register;机器人墙 → BLOCKED bot_wall;表单要求登录、会话失效、或出现任何"设置密码/输入密码"字段 → 报 `NEED | what=login`,**绝不填写注册表单、绝不创建或输入密码**;绝不在浏览器打开 linkedin.com 岗位页(必触 bot 墙);表单出现速查答案之外的问题 → 不许编造,报 NEED;核实任何状态时走权威页面(application 列表/确认页),**不要依赖详情页懒加载渲染的文本**;
6. **回复协议**:最后必须输出**恰好一行**:
```
RESULT: SUBMITTED | evidence=<确认编号或确认页原文摘录>
RESULT: NEED | what=<otp|dob|login|salary|file|answer> | question=<表单原文>
RESULT: BLOCKED | reason=<captcha|assessment|video|oauth_register|bot_wall> | detail=<...>
RESULT: FAILED | detail=<...>
```

## 升级回路（原文规则）

收到 `NEED` 时按类型处理后续跑:
1. facts/config/verdict 里已有答案(通知期、工作权利、薪资等)→ 直接 `continue --answer` 补料;
2. `what=otp`(OTP/邮箱验证码/激活链接确认)→ 暂停问用户,拿到后经 `continue --answer` 转达——**这是唯一允许经补料转达的验证信息**(Oracle 验证码 10 分钟有效,拿到立即续跑);
3. `what=login`(登录/会话失效/注册,含设密码)→ 提示用户**本人**在 OpenClaw 浏览器 profile 中完成登录或注册(含设置密码、点激活链接),完成后用**无 --answer** 的 continue 发送标准续跑指令。**`--answer` 永不用于传递密码/凭据——绝不接收、转发或代输用户密码**;
4. 台账外的事实问题(如"是否持有 X 认证")→ **绝不编造**:问用户,答案经确认后先写回 `facts.json`,再补料续跑——下次同类问题就有据可查。**密码/凭据永远不属于可写回 facts.json 的台账问题,一律按第 3 条处理**。
收到 `BLOCKED` → 记账 `status=blocked`,转手动队列,继续下一单,**不重试**。
收到 `FAILED` → 记账;允许 Claude 判断值得时用无 --answer 的 continue 试**一次**(如纯页面加载失败);连续两次 FAILED → 转手动 `status=manual`。

续跑必须使用：

```sh
python3 scripts/submit.py continue --job "<folder>" [--answer "<经确认的补料>"]
```

脚本从台账复用原 thread。NEED login 后必须省略 `--answer`。不得让用户把密码发给你。

## verify-after-timeout（原文规则）

**超时 ≠ 失败**。实测:填全部表单的首个 turn 常在 470-500s 被杀,超时属**常态**而非异常——代理往往已增量提交了部分表单甚至已完成投递,只是回复丢失;且详情页懒加载会让"读回来的状态"不可靠。不要因频繁 UNKNOWN 而调低超时或改为直接重投。规则:
- 超时(RESULT: UNKNOWN)后**禁止立即重投**;先 `submit.py verify`:发只读任务,用权威通道核实——ATS 账号的 application 列表、确认页 URL 重访、提示用户查收确认邮件。verify 回复协议(末行恰好一行):
```
VERIFY: SUBMITTED | evidence=<...>
VERIFY: NOT_SUBMITTED | progress=<step_advanced|fields_saved|none> | detail=<当前所在步骤>
VERIFY: UNKNOWN
```
- `VERIFY: SUBMITTED` → 记账完成;
- `VERIFY: NOT_SUBMITTED` 且 progress ≠ none → 用无 --answer 的 continue 续跑**原 thread**(多步 ATS 如 Workday/Oracle 预期要 3-6 轮 verify→continue 循环,见 ats_map quirks);同一岗因超时触发的 continue 总数上限 `config.auto_submit.max_continues_per_job`(默认 6,NEED 补料触发的 continue 不计入);连续两次 progress=none → 转手动 `status=manual`;
- `VERIFY: UNKNOWN` → `status=unknown`,列入人工核实清单,**永不自动重投**;
- 网关中途崩溃(adapter 报连接错误)同样按 UNKNOWN 处理,并提示用户 `openclaw gateway run` 恢复后再 verify。

核实命令：

```sh
python3 scripts/submit.py verify --job "<folder>"
```

verify 必须新开只读会话，不复用投递 thread。多轮 Workday/Oracle 严格跟踪因超时而触发
的 continue 数和连续 progress=none 次数；到上限立即转 manual。UNKNOWN 永不自动重投。

## 每轮报告与社区反哺

每单完成后才等待至少 30 秒进入下一单。本轮结束运行
`python3 scripts/submit.py status --all`，输出：

- ✅ 已提交（附 evidence）
- ⏸ 需要用户补料（具体缺什么）
- 🧱 被墙转手动
- ❓ 未知待人工核实（附 application 列表/确认邮件等步骤）
- ⏭ 防线拦下（附原因）

提醒用户核对确认邮件，并列出每个手动队列 README 路径。

若遇 `ats_map` 未收录域名，或实际行为与地图不符，生成一段匿名化的 ats_map 增补/修正
JSON（绝不含姓名、邮箱、电话、地址、简历路径等 PII；公司名可选）和一份预填 issue
文本，询问用户是否愿意自行提交到 GitHub。**只生成文本给用户，绝不代发 issue/PR。**
