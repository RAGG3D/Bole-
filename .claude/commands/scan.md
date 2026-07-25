# /scan — 扫描、打分与生成投递包

面向用户的输出遵守 `profile/config.json` 的 `config.ui_language`。

开始前读取 `SKILL.md`、`profile/facts.json`、`profile/config.json`、
`data/ats_map.json` 和 `data/salary_regions.json`。事实台账缺失时停止并引导 `/setup`。
不要触碰 OpenClaw；`/scan` 必须在 OpenClaw 未安装时完整可用。

## 1. 发现、去重、分诊

1. 创建 `state/` 和 `Applications/`（都已 gitignored）。
2. 运行：

   ```sh
   python3 scripts/sources.py discover --config profile/config.json --out state/discover.json
   python3 scripts/ledger.py filter --candidates state/discover.json --out state/filtered.json
   python3 scripts/triage.py --candidates state/filtered.json --config profile/config.json --out state/buckets.json
   ```

   搜索时间窗口默认取 `config.days`（建档时设定，单位天）；用户本轮想临时改窗口
   （如"只看最近 3 天"/"扩到 14 天"）时，给 discover 加 `--days N` 即可，不必改
   config。想永久修改就更新 `config.days`。

3. 用户手贴 JD：先运行 `sources.py jd --source paste --file <txt>`，从文本抽取
   title/company，构造一条与 `state/discover.json` 中候选**同构**的记录：

   ```json
   {"source": "manual", "channel": "paste",
    "title": "<抽取>", "company": "<抽取>", "location": null,
    "date": null, "days_ago": null, "in_window": true,
    "id": null, "url": "<有链接则填，手贴无链接时空串>", "keyword": null}
   ```

   手动 URL 岗把 `channel` 改为 `"url"` 并保留 url（后续裁决与 README 投递指引都
   依赖它）。人工队列的可读 JD 同理。`source` 必须为 `"manual"`——triage 只对
   source=manual 直送 SCORE。把这些记录追加进 `state/filtered.json` 的 candidates
   数组后再跑 triage；打分阶段的资格与红线闸门仍按全文 JD 生效。
4. 展示各桶清单，让用户可以即时调整明显误分。triage 只允许读取 title(+company)，
   绝不能把全文 JD 提前塞给它。
5. **固定补录环节（每轮都问，不能省略）**：在展示初始桶清单之后、开始全文打分
   之前，明确询问用户：“有没有想补投的职位链接？任何网站都行，包括中国大陆招聘站，
   直接贴给我；没有链接就贴 JD 文本。”如果用户：
   - 贴 URL：运行
     `python3 scripts/sources.py jd --source url --url "<用户链接>"`。`status=ok` 时从
     返回的 title/company/location/text 构造上述 `source="manual"`、
     `channel="url"` candidate，将 JD 全文保存在本轮 `state/`，追加到
     `state/discover.json.candidates`，再重跑 ledger.filter 与 triage，并展示更新后的
     桶；title/company 为 null 时请用户补齐，绝不猜测。
   - URL 返回 `status=bot_walled`：把原 URL 与原因写入本轮 manual_queue 并在汇总
     保留，明确提示“该站触发访问验证，Bole 不绕过；请改贴 JD 全文”。
   - 贴 JD 文本：保存到 `state/` 后走 `sources.py jd --source paste --file <txt>`，
     构造 `source="manual"`、`channel="paste"` candidate，按上一条同样重新去重与
     triage。
   - 回答没有：直接继续。`config.manual_candidates` 仍只在 discover 阶段消费，
     这个固定提问是本轮临时补录入口，两者不可互相替代。
6. 脚本超时或网络失败时，先检查 `state/` 中已产出的中间文件再决定从哪一步重试；
   不要盲目重跑全程。机器人墙和断网的手动 URL 必须保留在人工队列。

## 2. Claude 打分规则（必须原样执行）

> 对 SCORE 桶每个职位,先取全文 JD(sources.py jd),然后严格按序:
> **(1) 资格闸门**:JD 要求公民/PR/安全许可而用户不符 → eligible=false,decision=skip,不打分。
> **(2) 资历分档**:title 优先,JD 年限/带队要求可上调。SENIOR → fit 封顶 `seniority_caps.senior`;LEAD+ → 封顶 `seniority_caps.lead_plus`;封顶岗**永不 generate**。junior/mid 且在用户轮辐内应得高分。
> **(3) 0-100 打分**:真实重合(技能/领域/年限)加分;红线技术是**必备项**记 1 个 core red-line;用户没有且学不快的硬门槛降分。警惕 LinkedIn 残缺 stub 高估匹配——JD 太短时记 `jd_completeness=stub` 并在 rationale 注明"需投前核对完整 PD"。
> **(4) 裁决**:generate 仅当 eligible 且 core red-line ≤1 且 (fit ≥ generate_threshold 或 (junior/mid 且 fit ≥ junior_generate_floor));其余 list-only / skip。`stretch` 调节生成边界:保守(或 allowed=false)→ 停用 junior_generate_floor,仅 fit ≥ generate_threshold 才 generate;适度 → 默认规则;激进 → junior_generate_floor 下调 5 分(下限 55)。若本轮 generate 岗数超过 `config.max_generate`,按 fit 降序保留前 max_generate 个,其余降为 list-only 并在 rationale 注明"超出本轮生成上限,可下轮补生成或手动指定"。
> **(5) 推荐薪资**:JD 有区间→取区间内贴近用户期望值;无区间→按地区参考区间与档位给出(优先用户填写的 `config.region_salary_defaults`,否则读 `data/salary_regions.json` 中 `config.region` 对应条目),并注明含/不含 super 及币种。除 README 用的散文 `recommended_salary_note` 外,**必须同时输出结构化的 `recommended_salary_form`**(单一整数 amount、币种、是否含 super;给不出单一数字则 amount=null)。若 `config.region_salary_defaults` 为空且 `data/salary_regions.json` 无 `config.region` 对应条目:amount=null,`recommended_salary_note` 与 README 薪资一节写"无参考区间,请自行调研",**禁止凭模型常识臆造区间或数字**。
> 每个职位输出一条裁决 JSON(字段见下)。为省额度,**每批 5 个职位一次性打分**,禁用长篇思考。

每条裁决必须包含：`jd_key`（`Company :: Title`）、company、title、url、apply_url、
apply_type、source、source_id（若有）、fit、seniority_band、eligible、
redline_core_count、redline_flags、decision、rationale、jd_completeness、
recommended_salary_note、recommended_salary_form。JD 全文少于 800 字符，或 LinkedIn
跳外部 ATS 却没抓到 ATS 全文，记为 stub。全部裁决写
`state/scan_<date>_verdicts.json`。

中国地区薪资条目是**月薪区间**，但 `recommended_salary_form.amount` 继续保持单一
**年薪整数**，避免破坏既有数据契约：从选定月薪按 12 薪基准换算为年薪，并在
`recommended_salary_note` 明写“月薪口径、按 12 薪换算；13–16 薪及奖金需用户按
实际校准”。不得臆测具体奖金或薪数。

## 3. 分层归档

按 fit 创建：

- `Applications/Tier 1 (80+)/`
- `Applications/Tier 2 (70-79)/`
- `Applications/Tier 3 (under 70)/`

每个 generate 岗创建安全文件名 `<Company> - <Title>/`，写入 `JD.txt` 和
`verdict.json`。verdict 必须是该岗裁决原样落盘，是 `/apply` 唯一数据接口；不得靠
文件夹名恢复字段。全部 generate/list-only/skip 都写入
`Applications/_SCAN-<date>_INDEX.md`，每条含一行理由。

## 4. 生成材料

对每个 generate 岗，只依据 `profile/facts.json` 与该岗完整 JD 生成
`_content/cv.json`、`_content/cover.json`，遵守材料 schema 和 phrasing_rules：

- CV 与求职信用 `facts.language_of_materials` 指定的语言（支持 `"en"` / `"zh"`）；
  subtitle/profile 围绕 JD 真实重合点，不能把 JD 要求当成用户技能。
- 求职信 4–6 段，并包含**恰好一句**平静、不卑不亢的真实差距说明，紧接一句可迁移
  能力；不道歉、不自贬。即使强匹配也只用一句具体而轻微的真实缺口。
- 台账没有的技能、工具、年限或成果必须绕开，绝不写入。

先强制执行：

```sh
python3 scripts/redline_scan.py --facts profile/facts.json --content "<folder>/_content/"
```

退出码非 0 时停止该岗 PDF，按报错修正 JSON 后重扫。WARNING 逐项和事实台账核对，
不能无视。通过后运行：

```sh
python3 scripts/build_docs.py "<folder>/_content/cv.json" "<folder>/<Name> - CV - <Company>.pdf" --fit-pages 2
python3 scripts/build_docs.py "<folder>/_content/cover.json" "<folder>/<Name> - Cover Letter - <Company>.pdf" --fit-pages 1
```

没有浏览器时保留 HTML，汇总中明确告诉用户如何 Ctrl+P 生成 PDF。

## 5. 每岗 README 与汇总

按 `templates/readme_template.md` 生成每岗 README，语言遵守 ui_language。必须包含：
职位/公司概述；分数、理由和真实弱项；推荐薪资数字+币种+含/不含 super+散文理由
（无参考来源时按打分规则 (5) 兜底写"无参考区间，请自行调研"）；材料清单；常见表单
答案速查（只取 facts/config，与 apply.md 的表单速查同一口径，必含三项：**工作权利
原文、通知期、如何得知职位**）。LinkedIn 来源填 LinkedIn；其他来源如实填对应
公司职位板或平台名。用户手动补录的中国站链接绝不能写成 LinkedIn；提醒核对完整
JD。

投递指引使用 `apply_url`（空则 url）的 hostname 匹配 `data/ats_map.json`：
hostname 小写去端口，命中 `hostname == d` 或 `hostname.endswith("." + d)`，多条取
最长 domain，path/query 不参与。说明手动投是否顺畅和 quirks；只有 auto_submit=true
且用户开关开启才写“可交 `/apply`”。offsite 缺 apply_url 写“ATS 未知，转手动”。
目标 hostname 命中 zhipin/zhaopin/51job/liepin/lagou 时，README 还必须注明：
这些平台不自动投递；表单通常按**月薪**填写。把年薪结构值
`recommended_salary_form.amount` 除以 12 后取合理整数展示，并明确“这是 12 薪基准
月薪；13–16 薪、奖金和税前/税后口径请用户自行核对”。BOSS直聘另给一段只基于事实
台账和 JD 的简短沟通开场白，供用户本人发送，不能承诺台账外能力。

最后输出：新岗数 / generate / list / skip / 人工队列数；generate 清单表格；哪些可
由 `/apply`、哪些需手动。完成索引后才运行：

```sh
python3 scripts/ledger.py commit --candidates state/discover.json
```

提交台账前确认本轮中间文件和索引已经落盘，避免失败后永久漏岗。
