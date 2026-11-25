"""Refresh Scholar citation counts and render the curated publication list.

No API key or third-party dependency. A blocked/partial response never replaces
the last successful snapshot. Conference and code metadata stay curated.
"""

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
START, END = "<!-- RESEARCH:START -->", "<!-- RESEARCH:END -->"
VOID_TAGS = set("area base br col embed hr img input link meta param source track wbr".split())


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return "".join(child if isinstance(child, str) else child.text() for child in self.children)

    def find(self, *, tag=None, cls=None, ident=None):
        found = []
        for child in self.children:
            if isinstance(child, Node):
                if ((tag is None or child.tag == tag)
                    and (cls is None or cls in child.attrs.get("class", "").split())
                    and (ident is None or child.attrs.get("id") == ident)):
                    found.append(child)
                found.extend(child.find(tag=tag, cls=cls, ident=ident))
        return found


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def number(text):
    compact = text.strip().replace(",", "")
    if not re.fullmatch(r"\d+", compact):
        raise ValueError(f"Invalid citation count: {text!r}")
    return int(compact)


def parse_scholar(source, catalog):
    root = Document(source).root
    names = root.find(ident="gsc_prf_in")
    if len(names) != 1 or names[0].text().strip() != catalog["scholar_name"]:
        raise ValueError("Scholar profile identity missing or unexpected (possibly blocked)")
    tables = root.find(ident="gsc_rsb_st")
    if len(tables) != 1:
        raise ValueError("Scholar summary missing")
    totals = [number(n.text()) for n in tables[0].find(cls="gsc_rsb_std")]
    if len(totals) != 6:
        raise ValueError("Scholar summary is incomplete")
    papers = {}
    for row in root.find(tag="tr", cls="gsc_a_tr"):
        titles, counts = row.find(tag="a", cls="gsc_a_at"), row.find(tag="td", cls="gsc_a_c")
        if len(titles) != 1 or len(counts) != 1:
            raise ValueError("Scholar publication row is incomplete")
        identity = parse_qs(urlparse(titles[0].attrs["href"]).query)["citation_for_view"][0]
        user, paper_id = identity.split(":", 1)
        if user != catalog["scholar_user"] or paper_id in papers:
            raise ValueError("Unexpected or duplicate Scholar publication identity")
        anchors = counts[0].find(tag="a", cls="gsc_a_ac")
        if len(anchors) != 1:
            raise ValueError("Scholar citation field missing")
        raw_count = anchors[0].text().strip()
        count = number(raw_count) if raw_count else 0
        cited_by = urljoin("https://scholar.google.com", anchors[0].attrs.get("href", ""))
        if not raw_count:
            cited_by = "https://scholar.google.com" + titles[0].attrs["href"]
        if urlparse(cited_by).hostname != "scholar.google.com":
            raise ValueError("Unexpected Scholar citation URL")
        papers[paper_id] = {"title": titles[0].text().strip(), "citations": count, "cited_by_url": cited_by}
    required = {paper["id"] for paper in catalog["publications"]}
    if not required.issubset(papers):
        raise ValueError("Scholar returned a partial list; retaining the previous snapshot")
    return {
        "source": "Google Scholar",
        "scholar_user": catalog["scholar_user"],
        "updated_utc": datetime.now(timezone.utc).date().isoformat(),
        "citations": totals[0], "h_index": totals[2], "i10_index": totals[4],
        "papers": papers,
    }


def shield_escape(text):
    return quote(str(text).replace("_", "__").replace("-", "--"), safe="")


def badge(label, value, color="1d5c47"):
    return f"https://img.shields.io/badge/{shield_escape(label)}-{shield_escape(value)}-{color}?style=flat-square"


def single_pill(text, color="525856"):
    return f"https://img.shields.io/badge/{shield_escape(text)}-{color}?style=flat-square"


def venue_color(label):
    lower = label.lower()
    if "oral" in lower or "spotlight" in lower:
        return "b86b1d"
    if "neurips" in lower:
        return "573099"
    if "icml" in lower:
        return "135e6d"
    if "iclr" in lower:
        return "19643b"
    if "cvpr" in lower:
        return "1e5397"
    if "emnlp" in lower or "acl" in lower:
        return "992939"
    return "525856"


def format_paper_cell(paper):
    raw_title = paper["title"].replace("|", "\\|")
    if ":" in raw_title:
        short, rest = raw_title.split(":", 1)
        title_md = f"**{short.strip()}**: {rest.strip()}"
    else:
        title_md = f"**{raw_title}**"

    meta_parts = []
    if paper.get("featured"):
        meta_parts.append("★ Representative")
    if paper.get("role"):
        meta_parts.append(paper["role"])
    if paper.get("topic"):
        meta_parts.append(paper["topic"])
    for label, url in paper["links"].items():
        meta_parts.append(f'<a href="{url}">{label}</a>')

    return f"{title_md}<br/><sub>{' · '.join(meta_parts)}</sub>"


def format_venue_cell(venue):
    parts = [part.strip() for part in venue.split("·") if part.strip()]
    return "<br/>".join(f"![{part}]({single_pill(part, venue_color(part))})" for part in parts)


def render_group_table(papers, snapshot):
    rows = ["| Publication | Venue | Cited |", "| :--- | :--- | ---: |"]
    for paper in papers:
        count = snapshot["papers"][paper["id"]]
        cite_num = count["citations"]
        cite_color = "1d5c47" if cite_num > 0 else "6e7781"
        citation = f"[![{cite_num}]({badge('Cited by', cite_num, cite_color)})]({count['cited_by_url']})"
        rows.append(f"| {format_paper_cell(paper)} | {format_venue_cell(paper['venue'])} | {citation} |")
    return rows


def render(catalog, snapshot):
    if snapshot["scholar_user"] != catalog["scholar_user"]:
        raise ValueError("Cached Scholar profile does not match catalog")
    profile = "https://scholar.google.com/citations?" + urlencode({"user": catalog["scholar_user"], "hl": "en"})
    accepted = [p for p in catalog["publications"] if p.get("group") == "Conference papers"]
    preprints = [p for p in catalog["publications"] if p.get("group") != "Conference papers"]

    lines = [
        f"[![Google Scholar citations]({badge('Citations', snapshot['citations'], '1d5c47')})]({profile}) "
        f"[![h-index]({badge('h-index', snapshot['h_index'], '295c99')})]({profile}) "
        f"[![i10-index]({badge('i10-index', snapshot['i10_index'], '573099')})]({profile}) "
        f"<sub>· Google Scholar · Updated {snapshot['updated_utc']} UTC · Refreshed daily</sub>",
        "",
        f"#### Accepted Conference Papers ({len(accepted)})",
        "",
        *render_group_table(accepted, snapshot),
        "",
        f"#### Preprints & Surveys ({len(preprints)})",
        "",
        *render_group_table(preprints, snapshot),
    ]
    return "\n".join(lines)


def update_readme(text, block):
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) >= text.index(END):
        raise ValueError("Expected exactly one ordered Research marker pair")
    before, rest = text.split(START)
    _, after = rest.split(END)
    return before + START + "\n" + block + "\n" + END + after


def write_if_changed(path, content):
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=Path, help="Parse a saved Scholar response for validation")
    parser.add_argument("--cached", action="store_true", help="Render the last successful snapshot without network")
    args = parser.parse_args()
    catalog = json.loads((ROOT / "research/publications.json").read_text())
    cache = ROOT / "research/scholar.json"
    snapshot = None
    if not args.cached:
        try:
            if args.html:
                source = args.html.read_text(encoding="utf-8")
            else:
                url = "https://scholar.google.com/citations?" + urlencode({
                    "user": catalog["scholar_user"], "hl": "en", "cstart": 0, "pagesize": 100,
                })
                request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(request, timeout=30) as response:
                    source = response.read().decode("utf-8")
            snapshot = parse_scholar(source, catalog)
        except Exception as error:
            if args.html or not cache.exists():
                raise
            print(f"::warning::Scholar refresh unavailable ({type(error).__name__}); retaining the last successful snapshot.")
    if snapshot is None:
        snapshot = json.loads(cache.read_text())
    # Validate and render everything before writing either public file.
    block = render(catalog, snapshot)
    readme = ROOT / "README.md"
    updated = update_readme(readme.read_text(encoding="utf-8"), block)
    write_if_changed(cache, json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    write_if_changed(readme, updated)
    print(f"Rendered {len(catalog['publications'])} papers; {snapshot['citations']} citations as of {snapshot['updated_utc']}.")


if __name__ == "__main__":
    main()
