# Bole（伯乐）

[English](README.en.md)

> **千里马常有，而伯乐不常有——现在有了。**

Bole 取名自“伯乐相马”。它是一个新手友好的中文 Claude Code 技能包：先和你建立
经确认的事实台账，再发现职位、阅读完整 JD、诚实匹配、为每个合适岗位生成独立
投递包。目标不是海投，而是让每份材料都真实、具体、量体裁衣。

## 1. 这是什么

Bole 运行在你本机的 Claude Code 中，不是网站、云服务或独立后端。Claude 负责采访、
理解、打分和写作；仓库中的标准库 Python 脚本负责可重复的抓取、去重、机械分诊、
红线扫描、PDF 构建、ATS 路由和投递记账。

完整能力一次交付：

- v0.1：`/doctor`、`/setup`、`/scan`，建档、发现、打分并生成手动投递包；
- v0.2：可选 `/apply`，只向能力地图允许的 ATS 交给 OpenClaw 顺序投递；
- v0.3：社区维护的 ATS 地图、多地区薪资起点、英文文档和离线 CI。

Bole 不做网页 UI、不上传用户资料、不接付费 API、不代做测评，也不保证获得面试。

## 2. 安全与诚实原则

`profile/facts.json` 是材料和表单答案的唯一事实来源。用户未确认的技能、年限、数字
或成果绝不写入；`red_lines` 命中会阻止 PDF。机器人墙、验证码、在线测评、视频面试、
性格测试和仅 OAuth 注册都会停止并转手动。Bole 永不保管、存储或代输密码；OTP 可由
用户一次性转达，用后即弃、不落盘。

自动投递默认关闭，并受 `final_confirm` 策略约束。超时不等于失败：必须先只读核实，
不能盲目重投。同一职位已 `submitted` 或 `unknown` 时脚本会拒绝再次投递。

## 3. 要求与安装

必需：

- Python 3.10 或更高；
- 已安装并登录的 Claude Code CLI（不限制模型）；
- Git。

推荐安装 Chrome、Chromium 或 Edge 以自动打印 PDF；没有浏览器仍会生成 HTML。
OpenClaw 是**唯一可选外部依赖**，只用于 `/apply`，没有它不影响建档、扫描和材料生成。

Linux / macOS / WSL：

```sh
git clone https://github.com/RAGG3D/Bole-.git bole
cd bole
bash install.sh
claude
```

`install.sh` 只检查并给指引，绝不擅自安装。Windows 原生用户可在 PowerShell 手动确认
`python --version`、`claude --version` 和 Chrome/Edge，然后在仓库目录运行 `claude`；
也可使用 WSL2。所有路径处理使用 `pathlib`。

## 4. 快速上手

在仓库目录进入 Claude Code 后依次输入：

```text
/doctor
/setup
/scan
```

`/doctor` 检查环境；`/setup` 用五轮短采访建立本地事实台账；`/scan` 先省额度地机械
分诊，再每批五个职位阅读完整 JD、打分、生成材料。想使用可选自动投递时，再运行：

```text
/apply
```

首次 `/apply` 会在开关关闭时只解释开通条件，不调用 OpenClaw 或网络。请先读
[自动投递](#9-可选自动投递)。

## 5. 事实台账与配置

`/setup` 经你确认后生成：

- `profile/facts.json`：基本信息、经历事实、技术、教育、作品、红线和措辞规则；
- `profile/config.json`：目标、地区、薪资期望、公开来源、阈值和默认关闭的自动投递；
- `profile/digest.md`：简短可读摘要及每段经历适合的职位类型。

这三个文件都被 `.gitignore` 排除。不要把真实用户数据复制到 `examples/`、issue 或 PR。
`config.ui_language` 控制对话、报告和每岗 README；材料语言独立由
`facts.language_of_materials` 控制。

## 6. 职位来源

Bole 只用免费、免登录公开通道：

- LinkedIn 访客职位列表和详情接口；
- Workday cxs JSON；
- Greenhouse、Lever、Ashby 公开职位板；
- 用户提供的公司直连 URL；
- 用户手贴 JD。

请求使用自定义 UA，间隔至少 2 秒；429 首次等待 8 秒后只重试一次；不带 Cookie，
不绕验证码或机器人墙。SEEK 没有适合本项目的免费公开接口，因此恒走手贴/手动投递。
断网或遇墙的手动 URL 会保留在人工队列，不会静默丢失。

公司改名或双名时，`id + 规范化公司/标题` 双键仍可能漏掉重复职位；投递前请人工自查。
`platforms_preference` 只改变报告展示顺序，不会让不可用通道变得可用。

## 7. 打分与投递包

`/scan` 的顺序是 discover → ledger.filter → triage → 全文 JD → 每批五岗打分 → 分层
归档 → 红线扫描 → HTML/PDF → 每岗 README → 本轮索引。资格不符直接跳过，资深/带队
岗位封顶且不生成；生成边界由匹配分、核心红线、stretch 和 `max_generate` 一起决定。
少于 800 字符的 JD 视为 stub，绝不能直接自动投递。

每个 generate 岗位位于：

```text
Applications/
├── Tier 1 (80+)/
├── Tier 2 (70-79)/
└── Tier 3 (under 70)/
```

每个岗位文件夹包含 `JD.txt`、`verdict.json`、定制 CV、定制 Cover Letter、README 和
`_content/` JSON。README 给出分数理由、真实弱项、推荐填写薪资、ATS 已知坑、材料清单
和手动步骤。薪资只是地区/职位信息的起点；没有依据时明确写“无参考区间”，不会编数字。

## 8. PDF 与降级

材料先由确定性红线扫描器检查，再用仓库模板渲染 HTML。脚本依次探测 Chrome、
Chromium、Edge，并用 A4 `@page` 打印；CV 尽量压到两页，求职信一页。没有浏览器或
打印失败时退出码仍为 0、保留同名 HTML，并提示用浏览器打开后 Ctrl+P 另存为 PDF。

可单独演示：

```sh
python3 scripts/sources.py jd --source paste --file examples/demo_jds/jd1.txt
python3 scripts/redline_scan.py --facts examples/demo_facts.json --content path/to/content
python3 scripts/build_docs.py path/to/cv.json output.pdf --fit-pages 2
```

## 9. 可选自动投递

OpenClaw 免费开源，使用用户自己的本地网关和浏览器 profile。用户必须本人登录各 ATS；
Workday 每家公司租户是独立账号，首投/复投可能需要本人注册或登录，这是设计而非
故障。缺少 OpenClaw 时核心流程完整可用。

如决定启用：

1. 自行安装 Node ≥18 和 `npm install -g openclaw`；
2. 运行 `/doctor`，按指引启动 `openclaw gateway run`，并由本人登录目标站；
3. 理解确认策略后，把 `config.auto_submit.enabled` 改为 `true`；
4. 运行 `/apply`，按 `per_run`（默认）或 `per_job` 确认本轮清单。

只有 `data/ats_map.json` 中 `auto_submit=true` 且在 `allowed_ats` 的平台会进入自动投递；
其余始终保留为手动包。全程严格顺序，每单间隔至少 30 秒，每轮最多五单。遇 NEED 时
按事实台账补料；登录/设密码必须由用户本人操作；验证码、评测、OAuth、bot wall 直接
阻断。若代理超时，`submit.py verify` 会新开只读核实会话，UNKNOWN 永不自动重投。

`--force` 能越过去重保护，可能造成双投；只有在人工核实后才应使用。

## 10. 隐私与本地文件

不发遥测。`profile/`、`Applications/`、`state/` 全部本地且被 Git 忽略。脚本不会向
其他目录写用户数据；只有用户明确指定的构建输出路径例外。公开抓取不携带登录 Cookie。
OpenClaw 的登录态留在其浏览器 profile，Bole 不读取密码。请定期自行备份本地资料，
并在共享终端输出前检查是否含个人信息。

## 11. 社区贡献

先运行完全离线的检查：

```sh
python3 scripts/ats_lint.py
python3 -m unittest discover tests
```

欢迎通过匿名化实测更新 ATS 域名、`auto_submit` 和 `quirks`，或改进薪资地区条目。
域名必须是小写裸域名；不要提交姓名、邮箱、电话、地址、简历内容、确认编号等 PII。
详见 [CONTRIBUTING.md](CONTRIBUTING.md) 和双语 issue/PR 模板。

## 12. FAQ

**一定要安装 OpenClaw 吗？**

不需要。只有可选 `/apply` 用它，最重要的投递包流程不依赖 OpenClaw。

**为什么不直接抓 SEEK？**

SEEK 没有适合零付费免登录方案的公开接口，常返回 403。请把 JD 保存为文本后走 paste。

**没装浏览器会失败吗？**

不会。Bole 会留下完整 HTML，手动 Ctrl+P 即可。

**为什么弱匹配求职信也写一句缺口？**

为了准确设定期望；随后立即说明可迁移能力，不道歉、不自贬，也不捏造。

**超时后能再点一次吗？**

不能。代理可能已经提交但丢了回复，必须先 verify 和查确认邮件，避免双投。

**能用现有简历吗？**

可以作为 `/setup` 的采访线索，但 Claude 会逐条回读事实与数字，只有确认后才写台账。

## 13. 免责声明、路线与许可证

Bole 生成的职位判断、材料和薪资建议必须由用户自行核实；使用者有责任遵守招聘平台
条款、当地隐私和就业法规。自动投递默认关闭；即使开启仍受确认策略和安全闸门约束。
软件按“原样”提供，不保证职位数据完整、材料无误、投递成功或获得录用。

仓库把 v0.1、v0.2、v0.3 作为功能层一次交付，并使用相应 Git tag 标记。未来改进应
继续坚持本地优先、零付费依赖、事实约束和人工可接管。

本项目采用 [MIT License](LICENSE)。
