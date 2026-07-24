# Bole

[中文](README.md)

> **Fine horses are common; a good judge is rare—now there is one.**

Bole takes its name from the legendary Chinese judge of horses. It is a
beginner-friendly Claude Code skill pack that builds a confirmed facts ledger,
finds jobs, reads full job descriptions, scores honest fit, and creates a
separate application pack for every suitable role. The goal is not mass
application; it is truthful, specific tailoring for each job.

## 1. What It Is

Bole runs locally inside Claude Code. It is not a website, cloud service, or
standalone backend. Claude handles interviews, understanding, scoring, and
writing. Standard-library Python scripts provide repeatable discovery,
deduplication, mechanical triage, red-line scanning, PDF generation, ATS
routing, and submission records.

The repository ships all capability layers together:

- v0.1: `/doctor`, `/setup`, and `/scan` for profiling, discovery, scoring, and
  manual application packs;
- v0.2: optional `/apply`, sending eligible ATS applications sequentially via
  OpenClaw;
- v0.3: community ATS data, regional salary starting points, English docs, and
  offline CI.

Bole does not provide a web UI, upload user data, use paid APIs, take
assessments, or promise interviews.

## 2. Safety and Honesty

`profile/facts.json` is the only source for application content and form
answers. Unconfirmed skills, tenure, metrics, and achievements are forbidden.
A `red_lines` match blocks PDF output. Bot walls, CAPTCHAs, online assessments,
video interviews, personality tests, and OAuth-only registration stop and move
to the manual queue. Bole never stores or enters passwords. A user may relay an
OTP once; it is discarded and never written to disk.

Auto-submit is off by default and remains governed by `final_confirm`. A timeout
is not failure: Bole must verify read-only before any continuation and never
blindly resubmit. The script rejects a second run when the same role is already
`submitted` or `unknown`.

## 3. Requirements and Installation

Required:

- Python 3.10 or later;
- an installed and authenticated Claude Code CLI (any model);
- Git.

Chrome, Chromium, or Edge is recommended for automatic PDF printing. Without
one, Bole still generates HTML. OpenClaw is the **only optional external
dependency** and is used solely by `/apply`; profiling, scanning, and document
generation do not need it.

Linux, macOS, or WSL:

```sh
git clone https://github.com/RAGG3D/Bole-.git bole
cd bole
bash install.sh
claude
```

`install.sh` only reports checks and guidance; it installs nothing. Native
Windows users can check `python --version`, `claude --version`, and Chrome/Edge
manually in PowerShell, then run `claude` in the repository, or use WSL2. Python
paths use `pathlib`.

## 4. Quick Start

Inside Claude Code at the repository root, run:

```text
/doctor
/setup
/scan
```

`/doctor` checks the environment. `/setup` uses five short interview rounds to
build a local facts ledger. `/scan` performs token-saving mechanical triage,
then reads full JDs and scores five at a time before generating documents. To
use optional auto-submit later, run:

```text
/apply
```

When the switch is off, the first `/apply` only explains activation. It does not
call OpenClaw or the network. Read [Auto-submit](#9-optional-auto-submit) first.

## 5. Facts Ledger and Configuration

After your confirmation, `/setup` creates:

- `profile/facts.json`: basics, confirmed experience facts, skills, education,
  portfolio, red lines, and phrasing rules;
- `profile/config.json`: targets, region, salary expectations, public sources,
  thresholds, and disabled-by-default auto-submit;
- `profile/digest.md`: a concise summary and role archetypes for each
  experience.

All three are gitignored. Never copy real user data into `examples/`, issues, or
pull requests. `config.ui_language` controls conversation, reports, and each
job README. Document language is separately controlled by
`facts.language_of_materials`.

## 6. Job Sources

Bole uses only free, public, unauthenticated sources:

- LinkedIn guest job lists and details;
- Workday cxs JSON;
- public Greenhouse, Lever, and Ashby boards;
- user-supplied direct company URLs;
- pasted job descriptions.

Requests use a custom user agent, wait at least two seconds, retry a first 429
once after eight seconds, carry no cookies, and never bypass bot protection.
SEEK has no suitable free public interface for this project, so it always uses
pasted JDs and manual submission. Offline or bot-walled manual URLs stay in a
manual queue instead of disappearing.
Use of LinkedIn's guest interface may still be governed by platform terms.
Evaluate and follow the rules that apply to you; Bole never attempts to evade
access controls.

The `id + normalized company/title` keys can still miss duplicates after a
company rename or dual branding; check manually before submission.
`platforms_preference` only changes report ordering and cannot enable an
unavailable channel.

## 7. Scoring and Application Packs

`/scan` runs discover → ledger.filter → triage → full JD → five-job scoring
batches → tiered archive → red-line scan → HTML/PDF → per-job README → scan
index. Ineligible roles are skipped. Senior and leadership roles are capped and
never generated. Score, core red lines, stretch, and `max_generate` jointly set
the generation boundary. A JD under 800 characters is a stub and can never be
auto-submitted directly.

Generated jobs appear under:

```text
Applications/
├── Tier 1 (80+)/
├── Tier 2 (70-79)/
└── Tier 3 (under 70)/
```

Each folder contains `JD.txt`, `verdict.json`, a tailored CV, a tailored cover
letter, README, and `_content/` JSON. The README explains score, honest gaps,
recommended salary, ATS quirks, materials, and manual steps. Salary is only a
regional/job-specific starting point. With no evidence, Bole says there is no
reference range instead of inventing a number.

## 8. PDF and Graceful Fallback

Documents pass a deterministic red-line scan before repository templates render
HTML. The script detects Chrome, Chromium, and Edge and prints A4 using
`@page`; it attempts to fit a CV to two pages and a cover letter to one. If no
browser exists or printing fails, the command still succeeds, keeps matching
HTML, and tells the user to open it and save as PDF with Ctrl+P.

Try the offline pieces independently:

```sh
python3 scripts/sources.py jd --source paste --file examples/demo_jds/jd1.txt
python3 scripts/redline_scan.py --facts examples/demo_facts.json --content path/to/content
python3 scripts/build_docs.py path/to/cv.json output.pdf --fit-pages 2
```

## 9. Optional Auto-submit

OpenClaw is free and open source and uses the user's own local gateway and
browser profile. The user must personally log into every ATS. Each Workday
company tenant has a separate account, so a first or later application may
require personal registration or login; this is expected. Core Bole remains
complete without OpenClaw.

If you choose to enable it:

1. install Node ≥18 and run `npm install -g openclaw` yourself;
2. run `/doctor`, follow its `openclaw gateway run` guidance, and personally log
   into target sites;
3. after understanding confirmation modes, set
   `config.auto_submit.enabled` to `true`;
4. run `/apply` and confirm the list under `per_run` (default) or `per_job`.

Only platforms with `auto_submit=true` in `data/ats_map.json` and present in
`allowed_ats` are routed to automation. Everything else remains a manual pack.
Applications are strictly sequential, at least 30 seconds apart, and limited to
five per run. NEED answers come from the facts ledger; users handle login and
password steps personally; CAPTCHA, assessment, OAuth, and bot-wall events
block immediately. After a timeout, `submit.py verify` opens a new read-only
session. UNKNOWN is never automatically resubmitted.

`--force` bypasses duplicate protection and can double-submit. Use it only
after manual verification.

## 10. Privacy and Local Files

Bole sends no telemetry. `profile/`, `Applications/`, and `state/` stay local
and are gitignored. Scripts write no user data elsewhere, except an output path
the user explicitly provides to the document builder. Public fetches carry no
login cookies. OpenClaw login state remains in its browser profile; Bole does
not read passwords. Back up local files yourself and inspect terminal output
before sharing it.

## 11. Community Contributions

Run the fully offline checks first:

```sh
python3 scripts/ats_lint.py
python3 -m unittest discover tests
```

Anonymous field reports can update ATS domains, `auto_submit`, and `quirks`, or
improve regional salary entries. Domains must be lowercase and bare. Never
submit PII such as names, email, phone, address, resume content, or confirmation
IDs. See [CONTRIBUTING.md](CONTRIBUTING.md) and the bilingual issue/PR
templates.

## 12. FAQ

**Does Bole cost money?**

The repository uses no paid API or SaaS. You still use your own Claude Code
subscription. OpenClaw is free and open source and is only needed if you choose
auto-submit.

**Must I install OpenClaw?**

No. Only optional `/apply` uses it. The central application-pack workflow does
not depend on OpenClaw.

**Why not scrape SEEK directly?**

SEEK has no suitable zero-cost public unauthenticated interface and commonly
returns 403. Save the JD as text and use the paste channel.

**Does a missing browser break Bole?**

No. Bole keeps complete HTML that you can print manually with Ctrl+P.

**Why does a weaker-fit cover letter include one gap sentence?**

It sets expectations honestly, then immediately explains transferable
strengths—without apology, self-deprecation, or invention.

**Can I click submit again after a timeout?**

No. The agent may have submitted and lost its reply. Verify and check
confirmation email first to avoid duplicates.

**Can I use an existing resume?**

Yes, as interview evidence during `/setup`. Claude reads back each fact and
metric, and only confirmed items enter the ledger.

## 13. Disclaimer, Roadmap, and License

Users must verify Bole's job decisions, materials, and salary guidance and are
responsible for recruitment-platform terms and applicable privacy and
employment laws. Auto-submit is disabled by default and remains constrained by
confirmation and safety gates when enabled. The software is provided “as is”
without guarantees of complete job data, error-free materials, successful
submission, interview, or employment.

The repository ships v0.1, v0.2, and v0.3 as capability layers together and
marks them with matching Git tags. Future work should remain local-first,
zero-paid-dependency, fact-constrained, and human-recoverable.

Licensed under the [MIT License](LICENSE).
