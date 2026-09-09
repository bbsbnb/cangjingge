#!/usr/bin/env python3
"""Small local browser for the daizhige Markdown archive."""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse


ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8000"))
PAGE_SIZE = 40
SKIP_DIRS = {".git", ".github", ".sources"}
CATEGORIES = [
    "佛藏", "儒藏", "医藏", "史藏", "子藏", "易藏", "现代作品", "艺藏", "诗藏", "道藏", "集藏"
]


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Read only the small YAML header; book bodies stay on disk until opened."""
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            text = os.read(fd, 4096).decode("utf-8", errors="replace")
        finally:
            os.close(fd)
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip().strip("'\"")
        values[key] = value
    return values


def build_index() -> list[dict[str, str]]:
    books: list[dict[str, str]] = []
    for path in ROOT.rglob("*.md"):
        relative = path.relative_to(ROOT)
        if relative.name in {"README.md", "FONTS.md"} or any(part in SKIP_DIRS for part in relative.parts):
            continue
        meta = parse_frontmatter(path)
        title = meta.get("title", "").strip()
        if not title:
            title = meta.get("zh-hans", relative.stem).strip()
        books.append({
            "path": relative.as_posix(),
            "title": title,
            "author": meta.get("author", ""),
            "category": meta.get("category", "/" + relative.parts[0]),
        })
    return sorted(books, key=lambda book: (book["title"].casefold(), book["path"]))


BOOKS = build_index()
BY_PATH = {book["path"]: book for book in BOOKS}


def safe_book_path(raw: str) -> Path | None:
    relative = Path(unquote(raw).replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".md":
        return None
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        return None
    return path if path.is_file() else None


def page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} - 殆知阁本地库</title>
<style>
:root {{ color-scheme: light; --ink:#20252b; --muted:#68727d; --line:#d9dee4; --accent:#9a3f2f; --paper:#fff; --wash:#f5f3ef; }}
* {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); background:var(--wash); font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif; }}
header {{ background:#20252b; color:#fff; border-bottom:4px solid var(--accent); }} .bar {{ max-width:1180px; margin:auto; padding:22px 24px; display:flex; gap:24px; align-items:center; flex-wrap:wrap; }}
.brand {{ color:#fff; text-decoration:none; font-size:24px; font-weight:700; }} nav {{ display:flex; gap:16px; }} nav a {{ color:#dfe5ea; text-decoration:none; }} nav a:hover, a:hover {{ color:var(--accent); }}
.search {{ margin-left:auto; display:flex; gap:8px; }} input {{ border:1px solid #aeb7c0; border-radius:4px; padding:9px 11px; min-width:240px; font:inherit; }} button {{ border:0; border-radius:4px; padding:9px 15px; color:#fff; background:var(--accent); font:inherit; cursor:pointer; }}
main {{ max-width:1180px; margin:0 auto; padding:34px 24px 60px; }} h1 {{ margin:0 0 10px; font-size:30px; }} h2 {{ margin-top:34px; }} a {{ color:var(--accent); }} .muted {{ color:var(--muted); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:12px; margin-top:22px; }} .tile, .result {{ background:var(--paper); border:1px solid var(--line); border-radius:5px; padding:16px; }} .tile strong {{ display:block; font-size:19px; }}
.result {{ margin:10px 0; }} .result-title {{ font-size:19px; font-weight:650; }} .meta {{ color:var(--muted); font-size:14px; margin-top:3px; }} .pager {{ display:flex; gap:14px; margin-top:22px; }}
.crumbs {{ color:var(--muted); margin-bottom:18px; }} article {{ background:var(--paper); border:1px solid var(--line); padding:30px clamp(18px,5vw,64px); border-radius:5px; }} article h1 {{ text-align:center; }} .book-meta {{ text-align:center; color:var(--muted); margin-bottom:30px; }} .markdown {{ white-space:pre-wrap; overflow-wrap:anywhere; font-family: "Noto Serif CJK SC", "Songti SC", "SimSun", serif; line-height:2; }}
@media(max-width:650px) {{ .bar {{ padding:16px; }} .search {{ width:100%; margin-left:0; }} input {{ min-width:0; width:100%; }} main {{ padding:24px 16px 44px; }} }}
</style></head><body><header><div class="bar"><a class="brand" href="/">殆知阁本地库</a><nav><a href="/">首页</a><a href="/browse">分类</a></nav><form class="search" action="/search"><input name="q" placeholder="搜索书名、作者或正文" value="{html.escape(current_query())}"><button type="submit">搜索</button></form></div></header><main>{body}</main></body></html>""".encode("utf-8")


_current_query = ""


def current_query() -> str:
    return _current_query


def link(path: str, label: str) -> str:
    return f'<a href="{html.escape(path, quote=True)}">{html.escape(label)}</a>'


def home() -> bytes:
    counts = {category: 0 for category in CATEGORIES}
    for book in BOOKS:
        top = book["path"].split("/", 1)[0]
        if top in counts:
            counts[top] += 1
    tiles = "".join(f'<a class="tile" href="/browse?category={quote(category)}"><strong>{html.escape(category)}</strong><span class="muted">{counts[category]:,} 部文献</span></a>' for category in CATEGORIES)
    body = f'<h1>中国古典文献</h1><p class="muted">本地数据浏览与全文检索，共 {len(BOOKS):,} 部 Markdown 文献。</p><section class="grid">{tiles}</section><h2>使用说明</h2><p>可按分类浏览，或搜索书名、作者和正文。打开文献后显示原始 Markdown 内容，原始数据不会被修改。</p>'
    return page("首页", body)


def browse(params: dict[str, list[str]]) -> bytes:
    category = params.get("category", [""])[0]
    books = [book for book in BOOKS if not category or book["path"].startswith(category + "/")]
    rows = []
    for book in books[:PAGE_SIZE]:
        rows.append(f'<div class="result"><div class="result-title">{link("/book?path=" + quote(book["path"]), book["title"])}</div><div class="meta">{html.escape(book["author"] or "作者未标注")} · {html.escape(book["category"])}</div></div>')
    label = category or "全部分类"
    body = f'<div class="crumbs">{link("/", "首页")} / 分类</div><h1>{html.escape(label)}</h1><p class="muted">共 {len(books):,} 部文献，显示前 {min(PAGE_SIZE, len(books)):,} 部。</p>{"".join(rows) or "<p>此分类暂无文献。</p>"}'
    return page(label, body)


def search(params: dict[str, list[str]]) -> bytes:
    global _current_query
    query = params.get("q", [""])[0].strip()
    _current_query = query
    if not query:
        return page("搜索", '<h1>搜索文献</h1><p class="muted">请输入书名、作者或正文关键词。</p>')
    lowered = query.casefold()
    results = [book for book in BOOKS if lowered in " ".join((book["title"], book["author"], book["category"])).casefold()]
    if len(results) < PAGE_SIZE:
        results.extend(content_search(query, {book["path"] for book in results}, PAGE_SIZE - len(results)))
    rows = "".join(f'<div class="result"><div class="result-title">{link("/book?path=" + quote(book["path"]), book["title"])}</div><div class="meta">{html.escape(book["author"] or "作者未标注")} · {html.escape(book["category"])}</div></div>' for book in results[:PAGE_SIZE])
    body = f'<div class="crumbs">{link("/", "首页")} / 搜索</div><h1>搜索结果</h1><p class="muted">“{html.escape(query)}” · 找到 {len(results):,} 部匹配文献</p>{rows or "<p>没有找到匹配内容。</p>"}'
    return page("搜索", body)


def content_search(query: str, known: set[str], limit: int) -> list[dict[str, str]]:
    rg = shutil.which("rg")
    if rg:
        command = [rg, "-l", "--fixed-strings", "--glob", "*.md", "--glob", "!README.md", "--glob", "!FONTS.md", query, str(ROOT)]
        try:
            output = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20, check=False).stdout.splitlines()
            found = []
            for raw in output:
                path = Path(raw).resolve()
                try:
                    relative = path.relative_to(ROOT).as_posix()
                except ValueError:
                    continue
                if relative in known or relative not in BY_PATH:
                    continue
                found.append(BY_PATH[relative])
                if len(found) >= limit:
                    break
            return found
        except (OSError, subprocess.TimeoutExpired):
            pass
    found = []
    for book in BOOKS:
        if book["path"] in known:
            continue
        try:
            with open(ROOT / book["path"], encoding="utf-8", errors="ignore") as handle:
                if query.casefold() in handle.read().casefold():
                    found.append(book)
                    if len(found) >= limit:
                        break
        except OSError:
            continue
    return found


def book_view(params: dict[str, list[str]]) -> bytes | None:
    raw_path = params.get("path", [""])[0]
    path = safe_book_path(raw_path)
    if not path:
        return None
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    book = BY_PATH.get(path.relative_to(ROOT).as_posix(), {"title": path.stem, "author": "", "category": ""})
    title = book["title"]
    body = f'<div class="crumbs">{link("/", "首页")} / {link("/browse?category=" + quote(path.relative_to(ROOT).parts[0]), path.relative_to(ROOT).parts[0])} / 阅读</div><article><h1>{html.escape(title)}</h1><div class="book-meta">{html.escape(book.get("author", "") or "作者未标注")} · {html.escape(book.get("category", ""))}</div><div class="markdown">{html.escape(content)}</div></article>'
    return page(title, body)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/":
            payload = home()
        elif parsed.path == "/browse":
            payload = browse(params)
        elif parsed.path == "/search":
            payload = search(params)
        elif parsed.path == "/book":
            payload = book_view(params)
            if payload is None:
                self.send_error(404, "文献不存在")
                return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


if __name__ == "__main__":
    print(f"Indexed {len(BOOKS):,} books from {ROOT}")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Serving at http://127.0.0.1:{PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
