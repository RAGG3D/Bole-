# /setup — 采访式建档

面向用户的输出遵守 `profile/config.json` 的 `config.ui_language`；首次建档默认中文。

目标是建立经用户逐条确认的事实台账，而不是“润色”或猜测。严格分五节采访，**每节
一轮对话**，不要一次抛出十个问题。允许用户粘贴已有简历或求职信作为线索，但抽取
出的每条事实和每个数字都必须回读确认，未确认内容不得写入台账。

## 第一节：基本信息

询问姓名、邮箱、电话、地址、LinkedIn/GitHub/作品链接、工作权利原文、是否需避开
公民/PR/安全许可职位、通知期、意向城市，以及 `config.region`（例如
`AU-Melbourne`）。出生日期是敏感且可选的信息；只有用户主动愿意提供才记录，否则
写 `null`。说明资料只保存在本地且被 Git 忽略。

## 第二节：工作经历

逐段询问角色、组织、起止年月、地点、真实职责与成果、实际用过的技术。成果逐条
回读，尤其确认数量、百分比、时间节省等数字。粘贴简历时也按逐条确认执行。为每段
生成稳定 id（`exp1`、`exp2`……），暂不凭空补充技能。

## 第三节：技能与红线

让用户把技能分为 `expert`、`working`、`basic` 三档。明确问：
“哪些技能或领域你没有、绝不能写进材料？”将用户原话逐项写入 `red_lines`。再询问
措辞规则，例如技术排序或不能使用的表述，写入 `phrasing_rules`。

## 第四节：求职意向

询问目标职位、目标公司、目标技能、薪资期望（数字、币种、含/不含 super）、平台
偏好、LinkedIn 地点和关键词。SEEK 无免费公开接口，说明 SEEK 职位需用户手贴。
询问公开 Workday/Greenhouse/Lever/Ashby 职位板信息时，只记录公开 host/token，不要
索取登录 Cookie 或凭据。可收集用户想手动补录的职位 URL。

## 第五节：stretch 容忍度

解释 stretch 只调节“是否为较弱但合理的 junior/mid 匹配生成材料”，不允许捏造。
让用户选择 `allowed` 和 `max_level`：保守 / 适度 / 激进，并说明 `/scan` 会按打分
规则调节生成边界。

## 确认与落盘

采访完成后先给用户一份**尽可能短的总结清单**：基本信息、技能三档、红线、求职
目标和 stretch；每段经历列出已确认事实，并由你基于事实总结“适合投放的职位类型”。
把该映射准备写入 `suits_archetypes`。必须等用户明确确认或修正后再落盘。

确认后创建：

- `profile/facts.json`：严格遵守 SKILL.md 中 facts schema；`language_of_materials`
  默认为 `en`。
- `profile/config.json`：包含 days、ui_language、region、目标、薪资、公开来源和阈值；
  根据红线生成只供**标题**机械分诊使用的 `redline_stack_regex`；将
  `requires_no_citizenship_roles` 同步进 config 供 triage 使用。
- `profile/digest.md`：确认摘要，不添加新事实。

`auto_submit` 必须按以下安全默认值写入，不得在 `/setup` 中擅自开启：

```json
{
  "enabled": false,
  "allowed_ats": ["greenhouse", "ashby", "hibob", "oracle_cloud", "workday"],
  "max_per_run": 5,
  "final_confirm": "per_run",
  "submit_timeout_s": 600,
  "verify_timeout_s": 240,
  "max_continues_per_job": 6
}
```

同时补齐 `generate_threshold=70`、`junior_generate_floor=60`、`max_generate=10`、
`seniority_caps={"senior":45,"lead_plus":38}`、资格正则和地区薪资默认字段。最后告知：
“建档已完成。下一步运行 `/scan`；想自动投递时说一声，我带你走 `/apply` 开通流程。”
