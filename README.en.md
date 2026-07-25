# Bole

[中文](README.md)

> **Fine horses are common; a good judge of them is rare—now there is one.**

Bole is an open-source job-application assistant that lives inside [Claude Code](https://claude.com/claude-code): it discovers roles, scores honest fit, and tailors a CV, cover letter, and application guide to every JD—based strictly on **experience you have confirmed**. No mass applying. No fabrication.

---

## ⚡ Quick Start (Three Steps)

**Prerequisites**: Python ≥ 3.10; an installed and authenticated [Claude Code CLI](https://claude.com/claude-code) (your own subscription, any model); Git. Chrome/Chromium/Edge is recommended for automatic PDF printing—without one, Bole still generates HTML you can print with Ctrl+P.

```bash
git clone https://github.com/RAGG3D/Bole-.git bole
cd bole
bash install.sh   # checks the environment and gives guidance; never installs anything
claude
```

Inside Claude Code, run three commands in order:

| Step | Command | What it does |
|---|---|---|
| 1 | `/doctor` | Environment check: item by item, with fix guidance—**never silently installs anything** |
| 2 | `/setup` | Interview-style profiling: five short rounds covering experience/skills/red lines/targets, each fact confirmed before entering your local "facts ledger" |
| 3 | `/scan` | Discover jobs → score and tier → generate a tailored CV/cover-letter PDF plus a per-job application README for every match |

Then open the `Applications/` folder: one folder per matching job, containing the full JD, tailored CV PDF, tailored cover letter PDF, and a README that tells you **how to apply and what salary to enter**. Just follow it.

After showing the initial triage buckets, every `/scan` run asks whether you
want to add a role. Paste a detail-page URL from any site, or paste the full JD
when no usable link exists.

The fourth command, `/apply` (auto-submit), is **off by default**; running it with the switch off only explains activation and touches no network. See "Auto-submit" below.

---

## What It Is

**In one sentence: a Claude Code skill pack (skill repo)—not a website, cloud service, or standalone backend.** You clone the repository and run `claude` inside it: Claude handles interviews, understanding, scoring, and writing; the repository's standard-library Python scripts provide repeatable discovery, deduplication, mechanical triage, red-line scanning, PDF generation, ATS routing, and submission records. Your data stays on your own machine.

Four capability layers ship together:

- **v0.1**: `/doctor`, `/setup`, `/scan`—profiling, discovery, scoring, and manual application packs;
- **v0.2**: optional `/apply`—sequential auto-submission via OpenClaw, only to ATS platforms the capability map allows;
- **v0.3**: community-maintained ATS map, regional salary starting points, English docs, and offline CI.
- **v0.4**: complete repository PII cleanup plus Mainland China direct links,
  GB18030 pages, and Chinese-language documents.

### The Name

"Only when there is a Bole does a thousand-li horse get found. Thousand-li horses are common; a Bole is rare." The reality of the job market: capable candidates abound, but a resume gets six seconds of attention. Bole appraises each JD like the legendary judge of horses—reading what it truly asks for, then bringing your **genuinely held** matching strengths to the front.

### Three Founding Principles

1. **The facts ledger is the only source of truth**. Facts you confirm item by item during `/setup`—experience, skills, quantified results—form your local `profile/facts.json`. All generated materials and form answers may reference only ledger facts: **fabrication is structurally impossible**, and a deterministic scanner gate-keeps before any PDF is produced.
2. **Red lines**. Profiling explicitly asks "which skills do you NOT have and must never appear?" (e.g., never used Power BI, no wet-lab work). If a red-line term appears in generated material, the scanner refuses to produce the PDF.
3. **The honest gap sentence**. For weaker-fit roles, the cover letter contains **exactly one** calm, unapologetic statement of the real gap, immediately followed by your transferable strengths—no false perfection, no self-deprecation.

## What It Is Not

- ❌ Not a mass-application bot—each run only generates materials for high-fit roles, with a cap;
- ❌ No "embellishing" or inventing experience—see the ledger and red lines above;
- ❌ No CAPTCHA solving, no bot-wall evasion—walls always route to the manual queue, no exceptions;
- ❌ No taking online assessments/video interviews/personality tests on your behalf;
- ❌ Never touches your passwords—all login/registration is done by you in the browser;
- ❌ No promise of interviews or offers.

## How It Works

```
Discover jobs via free public channels (LinkedIn / Workday / public ATS / any detail URL / pasted JD)
        │
        ▼
Ledger dedup → mechanical triage: regex bucketing filters out senior/ineligible/red-line roles first
        │                                            — what it saves is your token budget
        ▼
Claude reads each full JD and scores (0-100): eligibility gate → seniority cap → red-line check → tiering
        │                         Tier 1 (80+) / Tier 2 (70-79) / Tier 3 (<70)
        ▼
Generate materials (ledger facts only) → red-line scan (no pass, no PDF) → local browser prints PDF (zero heavy deps)
        │
        ▼
Per-job README: score & rationale, recommended salary (number + currency + reasoning), known ATS quirks, form answers
```

Hard rules worth knowing: senior roles (Senior/Lead+) are score-capped and **never generated**—applying to the wrong roles wastes everyone's time; roles requiring citizenship/PR/clearance you lack are skipped outright; a JD under 800 characters is flagged as a stub and **can never be auto-submitted directly**; the generation boundary is set jointly by fit score, core red lines, stretch tolerance, and the `max_generate` cap.

Each generated job folder contains: `JD.txt`, `verdict.json` (the scoring verdict), the tailored CV, tailored cover letter, application README, and `_content/` source JSON. Recommended salary is only a regional/job-specific starting point; with no evidence Bole says "no reference range" instead of inventing a number.

## Auto-submit (v0.2, Off by Default)

`/apply` can hand roles on "clean ATS" platforms (field-tested: Greenhouse / Ashby / HiBob / Oracle / Workday) to the [OpenClaw](https://www.npmjs.com/package/openclaw) browser agent for automatic submission. OpenClaw is free, open source, uses your own Claude subscription, and is Bole's **only optional external dependency**—without it, profiling/scanning/document generation remain fully functional.

If you choose to enable it:

1. Install Node ≥ 18 and `npm install -g openclaw` yourself;
2. Run `/doctor`, follow its `openclaw gateway run` guidance, and personally log into the target job sites;
3. After understanding the confirmation modes, set `config.auto_submit.enabled` to `true`;
4. Run `/apply` and approve the list under `per_run` (default, once per round) or `per_job` (per submission).

Safety design:

- Only platforms with `auto_submit=true` in `data/ats_map.json` **and** present in your `allowed_ats` whitelist are automated; everything else stays a manual pack;
- Strictly sequential submission, at least 30 seconds apart, with a per-run cap;
- Login/registration/password steps are done by **you** in the browser—Bole never receives, stores, or types any password; the sole exception is an email one-time code (OTP) you relay, discarded after use (each Workday company tenant is a separate account, so first or repeat applications may need you to log in first—by design, not a fault);
- **Timeout ≠ failure**: the agent may have submitted and lost its reply. After a timeout Bole verifies read-only first; `UNKNOWN` status is **never auto-resubmitted**; a role already `submitted` or `unknown` is refused outright (`--force` overrides but can double-submit—use only after manual verification);
- CAPTCHA, online assessments, video interviews, OAuth-only registration → blocked immediately, routed to manual.

## Privacy & Security

- Your profile (`profile/`), generated materials (`Applications/`), and run state (`state/`) stay **local only**, gitignored, never committed;
- No telemetry;
- Unauthenticated fetching follows politeness rules: custom UA, ≥ 2s between requests, 429 backoff, never carries cookies; use of LinkedIn's guest interface may still be governed by platform terms—Bole rate-limits and prefers direct company ATS by default, evaluate for yourself (see Disclaimer);
- OpenClaw's login state lives in its own browser profile; Bole does not read it.

## Supported Job Sources

| Source | Method | Notes |
|---|---|---|
| LinkedIn | Guest API, no login | Junior-role recall boost; stub JDs flagged; external ATS apply links resolved |
| Workday | Public JSON | Configure target company sites in config |
| Greenhouse / Lever / Ashby | Public board JSON | Configure company tokens in config |
| Company career pages | URL fetch | Bot-wall detection; walled URLs go to the manual queue (never lost) |
| Mainland China job sites | User-pasted job detail URL | Polite direct fetch; login/access walls fall back to pasted JD |
| SEEK | Pasted JD | No free interface; paste it in, the rest of the flow is identical |

Note: after a company rename or dual branding, dual-key dedup can still miss duplicates—check manually before applying.

## Mainland China Job Sites

On-site search at BOSS Zhipin, Zhaopin, 51job, Liepin, and Lagou commonly
requires an account or uses strong anti-bot controls. Bole does not simulate
login, perform on-site search, or bypass GeeTest, sliders, or access checks.
Use either of these paths:

1. run `/scan` and paste a job **detail-page URL** at the fixed add-a-role
   prompt after initial triage. Bole tries a polite
   `sources.py jd --source url` fetch with UTF-8 and GBK/GB2312/GB18030 support;
2. if the result is `bot_walled` or incomplete, copy and paste the full JD in
   the same run. The original URL stays in the manual queue.

All of these platforms are manual-only in `ats_map`. BOSS Zhipin is
conversation-first: Bole can prepare a Chinese CV, cover letter, and opening
message strictly from the facts ledger and JD, but you must send the message
yourself. Set `facts.language_of_materials` to `"zh"` for Chinese documents.

Chinese job forms commonly request monthly salary. Each application README
converts the structured annual figure to a 12-month baseline and reminds you to
calibrate 13–16 salary months, bonuses, and gross/net conventions yourself.

## FAQ

**Does it cost money?** Zero paid dependencies. You only spend your own Claude subscription budget; scoring defaults to a token-saving mode (mechanical triage first, then batches of five).

**Must I install OpenClaw?** No. Only the optional `/apply` uses it; the core application-pack workflow doesn't depend on it.

**Will it fabricate my experience?** No—structurally: materials may only reference your confirmed facts ledger, and the red-line scan blocks any PDF otherwise.

**Can I use an existing resume?** Yes, as interview evidence for `/setup`. Claude extracts and reads back each fact and number; only confirmed items enter the ledger.

**Why does a weaker-fit cover letter include one gap sentence?** To set expectations honestly—immediately followed by transferable strengths; no apology, no self-deprecation, no invention.

**Can I click submit again after a timeout?** No. The agent may have already submitted and lost the reply. Verify and check the confirmation email first to avoid duplicates.

**Why not scrape SEEK?** SEEK has no free unauthenticated interface suitable for this project (commonly 403). Copy the JD text and paste it in.

**Does a missing browser break it?** No. Bole keeps the complete HTML; open it in a browser and Ctrl+P to save as PDF.

**Australia only?** No. Defaults use Melbourne as the example; region, keywords, and salary reference ranges (AU/US/UK/SG plus Beijing, Shanghai, Shenzhen, and Hangzhou) are configurable.

**Windows?** Linux / macOS / Windows supported (WSL2 recommended; native Windows works after manually confirming the environment per the README).

**English version?** You are reading it; UI language is controlled by `config.ui_language`. Generated CVs/cover letters default to English anyway (configurable).

## Roadmap

| Version | Scope | Status |
|---|---|---|
| v0.1 | /doctor checkup + /setup interview profiling + /scan scoring & "manual application packs" | ✅ Shipped (tag `v0.1`) |
| v0.2 | /apply via OpenClaw: clean-ATS auto-submit + escalation loop + verify-after-timeout | ✅ Shipped (tag `v0.2`) |
| v0.3 | Community: ats_map PR mechanism + regional salaries + English docs + offline CI | ✅ Shipped (tag `v0.3`) |
| v0.4 | PII history cleanup + China direct/paste routes + Chinese web/document support | ✅ Shipped |

Future work stays local-first, zero-paid-dependency, fact-constrained, and human-recoverable.

## Contributing

Run the fully offline checks first:

```sh
python3 scripts/ats_lint.py
python3 -m unittest discover tests
```

The most valuable contribution is **field-tested ATS experience**: which platforms submit cleanly, which have quirks—open an issue or PR against `data/ats_map.json` (domains must be lowercase and bare; lint and offline CI gate every change). Regional salary calibration is equally welcome. **Never submit PII** (names, email, phone, resume content, confirmation IDs) in issues or PRs. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Disclaimer

- Verify all job judgments, materials, and salary guidance yourself before applying; application actions and outcomes are the user's responsibility;
- Users must comply with each recruitment platform's terms and applicable privacy and employment laws;
- Salary reference ranges are community data—starting points only; local market reality prevails;
- Auto-submit is off by default; even when enabled it remains constrained by confirmation policy and safety gates, and always honors three iron rules: never take assessments, never touch credentials, walls go to manual;
- The software is provided "as is", with no guarantee of complete job data, error-free materials, successful submission, interviews, or employment.

## License

[MIT](LICENSE)
