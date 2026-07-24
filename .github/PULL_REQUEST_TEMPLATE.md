## 中文

### 变更

<!-- 简述改了什么、为什么。若更新 ATS，请说明平台、域名、能否自动投、实测坑。 -->

### 验证

- [ ] `python3 scripts/ats_lint.py`
- [ ] `python3 -m unittest discover tests`
- [ ] 不含姓名、邮箱、电话、地址、简历、投递确认编号等 PII
- [ ] ATS 域名为小写裸域名，实测平台与日期已记录
- [ ] 没有放宽验证码、评测、OAuth、密码或重复投递安全规则

## English

### Change

<!-- What changed and why? For ATS changes: platform, domain, auto-submit result, and quirks. -->

### Verification

- [ ] `python3 scripts/ats_lint.py`
- [ ] `python3 -m unittest discover tests`
- [ ] No PII (name, email, phone, address, resume, confirmation IDs)
- [ ] ATS domains are lowercase bare domains; platform and test date documented
- [ ] CAPTCHA, assessment, OAuth, credential, and duplicate-submit safeguards remain intact
