# 为 Bole 贡献 / Contributing to Bole

感谢你帮助 Bole 变得更可靠。安全规则、事实唯一来源和本地隐私边界不是可选偏好，任何
贡献都不能放宽它们。

Thank you for making Bole more reliable. Its safety rules, facts-only content,
and local privacy boundary are non-negotiable.

## 中文

### 开始前

1. Fork 仓库并从 `main` 创建小而聚焦的分支。
2. 使用 Python ≥3.10；不要增加付费 API、遥测、数据库或浏览器自动化依赖。
3. 运行：

   ```sh
   python3 scripts/ats_lint.py
   python3 -m unittest discover tests
   ```

CI 完全离线，不安装依赖、不访问网络。网络相关代码必须用 mock/fixture 测试。

### ATS 地图报告

更新 `data/ats_map.json` 时请提供平台名、小写裸域名、是否能自动投、已知坑、复现环境
和实测日期。`friendly`/`tricky` 只用于文档组织，路由只看 `auto_submit`。`quirks` 会
原样进入代理任务，因此要短、具体、可执行。验证码、评测、视频、OAuth 注册、密码
字段永远不能标为可自动越过。

先用 issue 模板报告也可以。必须匿名化：删除姓名、邮箱、电话、地址、简历、出生日期、
申请编号、截图中的账号信息和本机绝对路径。公司名可选保留。

### 薪资数据

`data/salary_regions.json` 只提供粗略起点。请注明币种、是否含养老金/福利等口径和
junior/mid/senior 区间；最好在 PR 中说明公开数据来源与校准日期。不要把区间描述成
保证，也不要提交个人薪资记录。

### 代码与文档

- 仅用 Python 标准库（OpenClaw 仍是唯一可选外部依赖）。
- 使用 `pathlib`，保证 Linux/macOS/Windows/WSL2。
- 用户数据只能写入 `profile/`、`Applications/`、`state/` 或用户明确指定的构建输出。
- 所有公开请求无 Cookie、间隔 ≥2 秒、429 首次 8 秒退避、遇墙转手动。
- 修改中文 README 章节时同步修改英文镜像；命令文件本身保持中文。
- 新行为添加离线 `unittest`，特别覆盖失败恢复和不触网路径。

### Pull Request

填写 PR 模板，说明变更、风险和验证命令。维护者会重点审查是否可能捏造事实、泄露 PII、
重复投递、代输凭据或绕过招聘平台安全机制。

## English

### Before You Start

1. Fork the repository and create a small, focused branch from `main`.
2. Use Python ≥3.10. Do not add paid APIs, telemetry, databases, or browser
   automation dependencies.
3. Run:

   ```sh
   python3 scripts/ats_lint.py
   python3 -m unittest discover tests
   ```

CI is fully offline: it installs no dependencies and makes no network calls.
Test network code with mocks or fixtures.

### ATS Map Reports

For `data/ats_map.json`, provide the platform, lowercase bare domains,
auto-submit outcome, quirks, reproduction environment, and test date.
`friendly`/`tricky` are documentation groups only; routing uses `auto_submit`.
`quirks` enter agent tasks verbatim, so keep them short, concrete, and
actionable. CAPTCHA, assessment, video, OAuth registration, and password steps
can never be marked as automatically bypassable.

An issue report is welcome before code. Anonymize it: remove names, email,
phone, address, resume, date of birth, application IDs, account details in
screenshots, and absolute local paths. Company name is optional.

### Salary Data

`data/salary_regions.json` provides rough starting points only. Include currency,
the basis (such as pension/benefits inclusion), and junior/mid/senior bands.
Prefer citing public methodology and calibration date in the PR. Do not present
ranges as guarantees or submit personal salary records.

### Code and Documentation

- Use only the Python standard library (OpenClaw remains the sole optional
  external dependency).
- Use `pathlib` and preserve Linux/macOS/Windows/WSL2 behavior.
- User data may only go to `profile/`, `Applications/`, `state/`, or an
  explicitly requested document output.
- Public requests carry no cookies, wait ≥2 seconds, back off eight seconds on
  the first 429, and move bot walls to manual.
- Keep the English README mirror aligned when changing Chinese sections;
  command files remain written in Chinese.
- Add offline `unittest` coverage, especially for recovery and no-network
  paths.

### Pull Requests

Complete the PR template with the change, risk, and validation commands.
Reviewers will focus on possible fact invention, PII leakage, duplicate
submission, credential entry, or bypass of recruitment-platform safeguards.
