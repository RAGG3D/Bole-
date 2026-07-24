#!/usr/bin/env python3
"""Bole 的免费公开职位发现与 JD 抓取通道。"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


UA = "Bole/0.3 (+https://github.com/RAGG3D/Bole-; polite public-job fetcher)"
BOT_WALL = re.compile(
    r"datadome|captcha-delivery|__cf_chl|px-captcha|just a moment",
    re.IGNORECASE,
)
MIN_REQUEST_INTERVAL = 2.0
_last_request_at = 0.0


class SourceError(RuntimeError):
    pass


class TooManyRequests(SourceError):
    pass


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in {"script", "style", "noscript"}:
            self.ignored += 1
        elif not self.ignored and tag in {"p", "br", "li", "div", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.ignored:
            self.ignored -= 1
        elif not self.ignored and tag in {"p", "li", "div", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts)).replace("\xa0", " ")
        lines = [" ".join(line.split()) for line in value.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def html_text(markup: str) -> str:
    parser = TextExtractor()
    parser.feed(markup)
    return parser.text()


def polite_wait() -> None:
    global _last_request_at
    remaining = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
    if remaining > 0:
        time.sleep(remaining)


def request_bytes(
    url: str,
    *,
    data: bytes | None = None,
    content_type: str | None = None,
    retry_429: bool = True,
    timeout: float = 20,
) -> tuple[bytes, str]:
    global _last_request_at
    headers = {"User-Agent": UA, "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers)
    polite_wait()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        _last_request_at = time.monotonic()
        if exc.code == 429 and retry_429:
            print("收到 429；等待 8 秒后只重试一次。", file=sys.stderr)
            time.sleep(8)
            return request_bytes(
                url,
                data=data,
                content_type=content_type,
                retry_429=False,
                timeout=timeout,
            )
        if exc.code == 429:
            raise TooManyRequests(f"429：{url}") from exc
        raise SourceError(f"HTTP {exc.code}：{url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _last_request_at = time.monotonic()
        raise SourceError(f"网络请求失败：{url}（{exc}）") from exc
    _last_request_at = time.monotonic()
    return raw, final_url


def request_text(url: str, **kwargs: Any) -> tuple[str, str]:
    raw, final_url = request_bytes(url, **kwargs)
    return raw.decode("utf-8", errors="replace"), final_url


def iso_date_days(value: object) -> int | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return max(0, (date.today() - parsed).days)
    except ValueError:
        return None


def relative_days(value: object) -> int | None:
    text = str(value or "").casefold()
    if "today" in text or "hour" in text or "minute" in text:
        return 0
    match = re.search(r"(\d+)\s*(day|week|month)", text)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    return amount * {"day": 1, "week": 7, "month": 30}[unit]


def clean_fragment(value: str) -> str:
    return " ".join(html_text(value).split())


def attr(markup: str, name: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1",
        markup,
        re.IGNORECASE | re.DOTALL,
    )
    return html.unescape(match.group(2)).strip() if match else None


def first_tag_text(markup: str, tag: str, class_part: str = "") -> str | None:
    class_clause = (
        rf"(?=[^>]*class=[\"'][^\"']*{re.escape(class_part)}[^\"']*[\"'])"
        if class_part
        else ""
    )
    match = re.search(
        rf"<{tag}\b{class_clause}[^>]*>(.*?)</{tag}>",
        markup,
        re.IGNORECASE | re.DOTALL,
    )
    return clean_fragment(match.group(1)) if match else None


def linkedin_cards(markup: str, keyword: str, days: int) -> list[dict[str, Any]]:
    chunks = re.findall(r"<li\b.*?</li>", markup, re.IGNORECASE | re.DOTALL)
    if not chunks:
        chunks = re.split(r"(?=<div\b[^>]*base-card)", markup, flags=re.IGNORECASE)
    records: list[dict[str, Any]] = []
    for chunk in chunks:
        id_match = re.search(
            r"(?:jobs/view/|jobPosting:|currentJobId[=:])(?:%3A)?(\d{5,})",
            chunk,
            re.IGNORECASE,
        )
        if not id_match:
            continue
        job_id = id_match.group(1)
        title = first_tag_text(chunk, "h3", "base-search-card__title")
        company = (
            first_tag_text(chunk, "h4", "base-search-card__subtitle")
            or first_tag_text(chunk, "a", "hidden-nested-link")
        )
        location = first_tag_text(chunk, "span", "job-search-card__location")
        time_match = re.search(r"<time\b([^>]*)>(.*?)</time>", chunk, re.I | re.S)
        posted = attr(time_match.group(1), "datetime") if time_match else None
        if not posted and time_match:
            posted = clean_fragment(time_match.group(2))
        days_ago = iso_date_days(posted)
        if days_ago is None:
            days_ago = relative_days(posted)
        link_match = re.search(
            r"<a\b[^>]*href=([\"'])(.*?)\1[^>]*(?:base-card__full-link)?",
            chunk,
            re.I | re.S,
        )
        url = (
            html.unescape(link_match.group(2)).strip()
            if link_match
            else f"https://www.linkedin.com/jobs/view/{job_id}"
        )
        records.append(
            {
                "source": "linkedin",
                "channel": "linkedin",
                "title": title,
                "company": company,
                "location": location,
                "date": posted,
                "days_ago": days_ago,
                "in_window": days_ago is None or days_ago <= days,
                "id": job_id,
                "url": url,
                "keyword": keyword,
            }
        )
    return records


def discover_linkedin(config: dict[str, Any], days: int) -> list[dict[str, Any]]:
    keywords = config.get("linkedin_keywords") or config.get("target_titles") or []
    location = str(config.get("linkedin_location") or "")
    pages = max(1, int(config.get("linkedin_pages_per_keyword", 2)))
    junior_pages = max(pages, int(config.get("linkedin_junior_keywords_pages", 4)))
    junior_enabled = bool(config.get("linkedin_junior_pass", True))
    results: dict[str, dict[str, Any]] = {}
    for raw_keyword in keywords:
        keyword = str(raw_keyword).strip()
        if not keyword:
            continue
        is_junior = bool(
            re.search(r"\b(?:junior|graduate|associate|entry)\b", keyword, re.I)
        )
        page_count = junior_pages if junior_enabled and is_junior else pages
        for page in range(page_count):
            query: dict[str, str | int] = {
                "keywords": keyword,
                "location": location,
                "f_TPR": f"r{days * 86400}",
                "start": page * 10,
            }
            if junior_enabled and is_junior:
                query["f_E"] = "2,3"
            url = (
                "https://www.linkedin.com/jobs-guest/jobs/api/"
                "seeMoreJobPostings/search?"
                + urllib.parse.urlencode(query)
            )
            try:
                markup, _ = request_text(url)
            except TooManyRequests as exc:
                print(f"LinkedIn 关键词「{keyword}」触发限流，跳过：{exc}", file=sys.stderr)
                break
            except SourceError as exc:
                print(f"LinkedIn 关键词「{keyword}」失败，继续其他通道：{exc}", file=sys.stderr)
                break
            for record in linkedin_cards(markup, keyword, days):
                results.setdefault(record["id"], record)
    return list(results.values())


def discover_workday(source: dict[str, Any], days: int) -> list[dict[str, Any]]:
    host = str(source.get("host") or "").strip().rstrip("/")
    tenant = str(source.get("tenant") or "").strip("/")
    site = str(source.get("site") or "").strip("/")
    name = str(source.get("name") or tenant or host)
    if not (host and tenant and site):
        return []
    if not host.startswith(("http://", "https://")):
        host = "https://" + host
    endpoint = f"{host}/wday/cxs/{tenant}/{site}/jobs"
    results: list[dict[str, Any]] = []
    for offset in range(0, 100, 20):
        body = json.dumps(
            {"limit": 20, "offset": offset, "searchText": "", "appliedFacets": {}}
        ).encode()
        raw, _ = request_bytes(
            endpoint, data=body, content_type="application/json; charset=utf-8"
        )
        payload = json.loads(raw)
        postings = payload.get("jobPostings", [])
        if not isinstance(postings, list) or not postings:
            break
        for item in postings:
            if not isinstance(item, dict):
                continue
            path = item.get("externalPath")
            posted = item.get("postedOn")
            days_ago = relative_days(posted)
            results.append(
                {
                    "source": "workday",
                    "channel": "company_boards",
                    "title": item.get("title"),
                    "company": name,
                    "location": item.get("locationsText"),
                    "date": posted,
                    "days_ago": days_ago,
                    "in_window": days_ago is None or days_ago <= days,
                    "id": path,
                    "url": f"{host}/en-US/{site}{path}" if path else host,
                    "keyword": "",
                    "host": urllib.parse.urlparse(host).netloc,
                    "tenant": tenant,
                    "site": site,
                    "path": path,
                }
            )
        if len(postings) < 20:
            break
    return results


def board_endpoint(ats: str, token: str) -> str:
    if ats == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    if ats == "lever":
        return f"https://api.lever.co/v0/postings/{token}?mode=json"
    if ats == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    raise SourceError(f"不支持的 ATS：{ats}")


def board_items(ats: str, payload: Any) -> list[dict[str, Any]]:
    if ats == "lever" and isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        key = "jobs"
        values = payload.get(key, [])
        return [item for item in values if isinstance(item, dict)]
    return []


def discover_board(source: dict[str, Any], days: int) -> list[dict[str, Any]]:
    ats = str(source.get("ats") or "").strip().lower()
    token = str(source.get("token") or "").strip()
    if not ats or not token:
        return []
    raw, _ = request_bytes(board_endpoint(ats, token))
    items = board_items(ats, json.loads(raw))
    results: list[dict[str, Any]] = []
    for item in items:
        if ats == "greenhouse":
            job_id = item.get("id")
            title = item.get("title")
            location = (item.get("location") or {}).get("name")
            url = item.get("absolute_url")
            posted = item.get("updated_at")
        elif ats == "lever":
            job_id = item.get("id")
            title = item.get("text")
            location = (item.get("categories") or {}).get("location")
            url = item.get("hostedUrl") or item.get("applyUrl")
            posted = item.get("createdAt")
            if isinstance(posted, (int, float)):
                posted = datetime.fromtimestamp(
                    posted / 1000, tz=timezone.utc
                ).isoformat()
        else:
            job_id = item.get("id") or item.get("jobUrl")
            title = item.get("title")
            location = item.get("location")
            url = item.get("jobUrl") or item.get("applyUrl")
            posted = item.get("publishedAt")
        days_ago = iso_date_days(posted)
        results.append(
            {
                "source": "board",
                "channel": "company_boards",
                "ats": ats,
                "token": token,
                "title": title,
                "company": token,
                "location": location,
                "date": posted,
                "days_ago": days_ago,
                "in_window": days_ago is None or days_ago <= days,
                "id": str(job_id or ""),
                "url": url,
                "keyword": "",
            }
        )
    return results


def meta_content(markup: str, key: str) -> str | None:
    patterns = (
        rf"<meta\b[^>]*(?:property|name)=[\"']{re.escape(key)}[\"'][^>]*content=([\"'])(.*?)\1",
        rf"<meta\b[^>]*content=([\"'])(.*?)\1[^>]*(?:property|name)=[\"']{re.escape(key)}[\"']",
    )
    for pattern in patterns:
        match = re.search(pattern, markup, re.I | re.S)
        if match:
            return clean_fragment(match.group(2))
    return None


def jd_url(url: str) -> dict[str, Any]:
    # 直链既用于人工补录也用于投前补全；断网时应尽快进入人工队列。
    markup, final_url = request_text(url, timeout=8)
    if BOT_WALL.search(markup):
        return {"status": "bot_walled", "source": "url", "url": final_url}
    title = meta_content(markup, "og:title") or first_tag_text(markup, "title")
    company = meta_content(markup, "og:site_name")
    location = meta_content(markup, "job:location")
    text = html_text(markup)
    return jd_result(
        source="url",
        url=final_url,
        text=text,
        title=title,
        company=company,
        location=location,
        apply_type="direct",
        apply_url=final_url,
    )


def unwrap_linkedin_redirect(url: str) -> str:
    value = html.unescape(url).replace("\\u0026", "&").replace("\\/", "/")
    parsed = urllib.parse.urlparse(value)
    if parsed.netloc.casefold().endswith("linkedin.com") and parsed.path.startswith(
        "/safety/go"
    ):
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("url"):
            return urllib.parse.unquote(query["url"][0])
    return value


def linkedin_apply_url(markup: str) -> str | None:
    candidates: list[str] = []
    for pattern in (
        r'"applyUrl"\s*:\s*"([^"]+)"',
        r"<a\b(?=[^>]*apply-link-offsite)[^>]*href=([\"'])(.*?)\1",
        r"<a\b[^>]*href=([\"'])(.*?)\1[^>]*apply-link-offsite",
    ):
        for match in re.finditer(pattern, markup, re.I | re.S):
            candidates.append(match.group(match.lastindex or 1))
    for candidate in candidates:
        candidate = unwrap_linkedin_redirect(candidate)
        if candidate.startswith(("http://", "https://")):
            return candidate
    return None


def jd_linkedin(job_id: str) -> dict[str, Any]:
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    markup, _ = request_text(url)
    if BOT_WALL.search(markup):
        return {"status": "bot_walled", "source": "linkedin", "url": url}
    detail_match = re.search(
        r'<div\b[^>]*class=[\"\'][^\"\']*show-more-less-html__markup[^\"\']*[\"\'][^>]*>(.*?)</div>\s*</div>',
        markup,
        re.I | re.S,
    )
    detail_markup = detail_match.group(1) if detail_match else markup
    title = first_tag_text(markup, "h2", "top-card-layout__title")
    company = first_tag_text(markup, "a", "topcard__org-name-link")
    location = first_tag_text(markup, "span", "topcard__flavor--bullet")
    onsite = bool(re.search(r"public_jobs_apply-link-onsite", markup, re.I))
    offsite = bool(re.search(r"public_jobs_apply-link-offsite|applyUrl", markup, re.I))
    apply_url = linkedin_apply_url(markup) if offsite else None
    return jd_result(
        source="linkedin",
        url=f"https://www.linkedin.com/jobs/view/{job_id}",
        text=html_text(detail_markup),
        title=title,
        company=company,
        location=location,
        apply_type="easy_apply" if onsite else ("external" if offsite else "unknown"),
        apply_url=apply_url,
    )


def jd_workday(host: str, tenant: str, site: str, path: str) -> dict[str, Any]:
    host = host.rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "https://" + host
    path = "/" + path.lstrip("/")
    endpoint = f"{host}/wday/cxs/{tenant.strip('/')}/{site.strip('/')}{path}"
    raw, final_url = request_bytes(endpoint)
    payload = json.loads(raw)
    info = payload.get("jobPostingInfo", payload)
    text = html_text(str(info.get("jobDescription") or info.get("description") or ""))
    external_url = (
        info.get("externalUrl")
        or info.get("jobPostingUrl")
        or f"{host}/en-US/{site.strip('/')}{path}"
    )
    return jd_result(
        source="workday",
        url=final_url,
        text=text,
        title=info.get("title"),
        company=info.get("company"),
        location=info.get("location"),
        apply_type="direct",
        apply_url=external_url,
    )


def jd_board(ats: str, token: str, job_id: str) -> dict[str, Any]:
    raw, _ = request_bytes(board_endpoint(ats, token))
    items = board_items(ats, json.loads(raw))
    job = next(
        (
            item
            for item in items
            if str(item.get("id") or item.get("jobUrl") or "") == str(job_id)
        ),
        None,
    )
    if job is None:
        raise SourceError(f"{ats} board 中找不到 job id：{job_id}")
    if ats == "greenhouse":
        title = job.get("title")
        company = token
        location = (job.get("location") or {}).get("name")
        url = job.get("absolute_url")
        text = html_text(str(job.get("content") or ""))
    elif ats == "lever":
        title = job.get("text")
        company = token
        location = (job.get("categories") or {}).get("location")
        url = job.get("hostedUrl") or job.get("applyUrl")
        text = html_text(
            " ".join(
                str(value or "")
                for value in (
                    job.get("description"),
                    job.get("descriptionPlain"),
                    job.get("additional"),
                )
            )
        )
    else:
        title = job.get("title")
        company = token
        location = job.get("location")
        url = job.get("jobUrl") or job.get("applyUrl")
        text = html_text(str(job.get("descriptionHtml") or job.get("description") or ""))
    return jd_result(
        source="board",
        url=str(url or ""),
        text=text,
        title=title,
        company=company,
        location=location,
        apply_type="direct",
        apply_url=url,
    )


def jd_paste(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceError(f"无法读取手贴 JD：{path}（{exc}）") from exc
    if not text.strip():
        raise SourceError(f"手贴 JD 为空：{path}")
    return jd_result(source="paste", url="", text=text)


def jd_result(
    *,
    source: str,
    url: str,
    text: str,
    title: object = None,
    company: object = None,
    location: object = None,
    apply_type: str = "unknown",
    apply_url: object = None,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "source": source,
        "url": url,
        "title": title,
        "company": company,
        "location": location,
        "text": text,
        "apply_type": apply_type,
        "apply_url": apply_url,
        "fetched": date.today().isoformat(),
    }


def discover(config_path: Path, days_override: int | None, output: Path) -> int:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    days = int(days_override if days_override is not None else config.get("days", 7))
    candidates: list[dict[str, Any]] = []
    manual_queue: list[dict[str, Any]] = []

    try:
        candidates.extend(discover_linkedin(config, days))
    except (SourceError, ValueError, json.JSONDecodeError) as exc:
        print(f"LinkedIn 通道失败，继续：{exc}", file=sys.stderr)

    for source in config.get("workday_sources", []):
        if not isinstance(source, dict):
            continue
        try:
            candidates.extend(discover_workday(source, days))
        except (SourceError, ValueError, json.JSONDecodeError) as exc:
            print(f"Workday 通道失败，继续：{exc}", file=sys.stderr)

    for source in config.get("board_sources", []):
        if not isinstance(source, dict):
            continue
        try:
            candidates.extend(discover_board(source, days))
        except (SourceError, ValueError, json.JSONDecodeError) as exc:
            print(f"公开 ATS 通道失败，继续：{exc}", file=sys.stderr)

    for manual_url in config.get("manual_candidates", []):
        url = str(manual_url).strip()
        if not url:
            continue
        try:
            detail = jd_url(url)
            if detail.get("status") == "bot_walled":
                manual_queue.append(
                    {"url": url, "status": "bot_walled", "reason": "机器人墙，转手动"}
                )
                continue
            candidates.append(
                {
                    "source": "manual",
                    "channel": "url",
                    "title": detail.get("title"),
                    "company": detail.get("company"),
                    "location": detail.get("location"),
                    "date": date.today().isoformat(),
                    "days_ago": 0,
                    "in_window": True,
                    "id": "",
                    "url": url,
                    "keyword": "",
                }
            )
        except SourceError as exc:
            manual_queue.append(
                {"url": url, "status": "error", "reason": str(exc)}
            )
            print(f"手动 URL 无法抓取，已保留在人工队列：{exc}", file=sys.stderr)

    candidates = [item for item in candidates if item.get("in_window", True)]
    result = {
        "generated": date.today().isoformat(),
        "days": days,
        "count": len(candidates),
        "candidates": candidates,
        "manual_queue": manual_queue,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"发现 {len(candidates)} 个窗口内候选；人工队列 {len(manual_queue)} 个。"
    )
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bole 免费职位发现与 JD 抓取")
    sub = parser.add_subparsers(dest="command", required=True)
    discover_parser = sub.add_parser("discover", help="从配置的公开通道发现职位")
    discover_parser.add_argument("--config", required=True, type=Path)
    discover_parser.add_argument("--days", type=int)
    discover_parser.add_argument("--out", required=True, type=Path)

    jd_parser = sub.add_parser("jd", help="抓取单个职位的完整 JD")
    jd_parser.add_argument(
        "--source",
        required=True,
        choices=("linkedin", "workday", "board", "url", "paste"),
    )
    jd_parser.add_argument("--id")
    jd_parser.add_argument("--host")
    jd_parser.add_argument("--tenant")
    jd_parser.add_argument("--site")
    jd_parser.add_argument("--path")
    jd_parser.add_argument("--ats", choices=("greenhouse", "lever", "ashby"))
    jd_parser.add_argument("--token")
    jd_parser.add_argument("--job-id")
    jd_parser.add_argument("--url")
    jd_parser.add_argument("--file", type=Path)
    return parser


def require(args: argparse.Namespace, *names: str) -> None:
    missing = [f"--{name.replace('_', '-')}" for name in names if not getattr(args, name)]
    if missing:
        raise SourceError("缺少参数：" + " ".join(missing))


def main() -> int:
    args = make_parser().parse_args()
    try:
        if args.command == "discover":
            return discover(args.config, args.days, args.out)
        if args.source == "paste":
            require(args, "file")
            result = jd_paste(args.file)
        elif args.source == "url":
            require(args, "url")
            result = jd_url(args.url)
        elif args.source == "linkedin":
            require(args, "id")
            result = jd_linkedin(args.id)
        elif args.source == "workday":
            require(args, "host", "tenant", "site", "path")
            result = jd_workday(args.host, args.tenant, args.site, args.path)
        else:
            require(args, "ats", "token", "job_id")
            result = jd_board(args.ats, args.token, args.job_id)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, json.JSONDecodeError, SourceError, ValueError) as exc:
        print(f"抓取失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
