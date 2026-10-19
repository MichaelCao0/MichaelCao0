"""Refresh public authored PRs/issues; leave README intact on API failure."""

import html
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
START, END = "<!-- ACTIVITY:START -->", "<!-- ACTIVITY:END -->"


def search(username, kind, limit=5):
    query = urlencode({
        "q": f"is:public author:{username} type:{kind}",
        "sort": "updated", "order": "desc", "per_page": limit,
    })
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-readme"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"https://api.github.com/search/issues?{query}", headers=headers)
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                data = json.load(response)
            if data.get("incomplete_results"):
                raise RuntimeError("GitHub returned incomplete search results")
            return data
        except HTTPError as error:
            if error.code not in (403, 429, 500, 502, 503, 504) or attempt == 2:
                raise
        except URLError:
            if attempt == 2:
                raise
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError("GitHub search failed")


def escape_title(value):
    value = html.escape(" ".join(value.split()), quote=False)
    # Prevent titles from changing the Markdown table or creating image/link markup.
    return re.sub(r"([\\`*_{}\[\]()|~!])", r"\\\1", value)


def table(items):
    if not items:
        return "No public activity yet."
    rows = ["| Status | Repository · Title | Updated |", "| :--- | :--- | :--- |"]
    for item in items:
        url = item["html_url"]
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "github.com":
            raise ValueError("Unexpected activity URL")
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 4 or parts[2] not in ("pull", "issues") or not parts[3].isdigit():
            raise ValueError("Unexpected activity path")
        repo = escape_title("/".join(parts[:2]))
        title = escape_title(item["title"])
        merged = (item.get("pull_request") or {}).get("merged_at")
        state = "🟣 Merged" if merged else ("🟢 Open" if item["state"] == "open" else "⚪ Closed")
        updated = item["updated_at"][:10]
        rows.append(f"| {state} | **{repo}** · [{title} #{parts[3]}]({url}) | {updated} |")
    return "\n".join(rows)


def main():
    username = os.environ.get("PROFILE_USER", "MichaelCao0")
    readme = ROOT / "README.md"
    original = readme.read_text(encoding="utf-8")
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError("Expected exactly one activity marker pair")
    if original.index(START) >= original.index(END):
        raise ValueError("Activity markers are out of order")
    # Fetch both before writing so an error cannot erase an existing activity block.
    prs = search(username, "pr")
    issues = search(username, "issue")
    block = (
        f"**Pull requests** · {prs['total_count']} public PRs authored\n\n"
        f"{table(prs['items'])}\n\n"
        f"**Issues** · {issues['total_count']} public issues authored\n\n"
        f"{table(issues['items'])}"
    )
    before, remainder = original.split(START)
    _, after = remainder.split(END)
    updated = before + START + "\n" + block + "\n" + END + after
    if updated != original:
        temporary = readme.with_suffix(".tmp")
        temporary.write_text(updated, encoding="utf-8")
        temporary.replace(readme)
    print(f"Refreshed {len(prs['items'])} PRs and {len(issues['items'])} issues for {username}.")


if __name__ == "__main__":
    main()
