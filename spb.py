"""
Simple profile builder: fetch a few pages, collect class names, and emit
class-based and element-specific XPath selectors grouped by class.
"""
import argparse
import asyncio
import json
import os
from typing import List, Dict, Optional
from urllib.parse import urlparse, urljoin

import aiohttp
from bs4 import BeautifulSoup
from lxml import etree


######## Fetching SEKTOR ########

async def fetch_html(url: str, session: aiohttp.ClientSession, timeout: int = 15) -> Optional[str]:
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return await resp.text()
    except Exception:
        return None


async def fetch_sitemap_urls(sitemap_url: str, limit: int) -> List[str]:
    urls: List[str] = []
    headers = {"User-Agent": "ProfileBuilder/0.1"}

    async def fetch_text(url: str) -> Optional[str]:
        try: # a nice practice for all of my python codes is using try catch when dealing with async methods.
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=20) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.text()
        except Exception:
            return None

    candidates = [sitemap_url]
    if not sitemap_url.lower().endswith(".xml"):
        candidates.append(sitemap_url.rstrip("/") + ".xml")

    for candidate in candidates:
        text = await fetch_text(candidate)
        if not text:
            continue
        # XML location finder logic
        try:
            root = etree.fromstring(text.encode("utf-8"))
            for loc in root.findall(".//{*}loc"):
                if loc.text:
                    urls.append(loc.text.strip())
                    if len(urls) >= limit:
                        return urls
        except Exception:
            pass
        # HTML anchors and <pre> finder logic
        try:
            soup = BeautifulSoup(text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href:
                    urls.append(href)
                    if len(urls) >= limit:
                        return urls
            for pre in soup.find_all("pre"):
                for line in pre.get_text().splitlines():
                    s = line.strip()
                    if s.startswith("http"):
                        urls.append(s)
                        if len(urls) >= limit:
                            return urls
        except Exception:
            pass
        # Plain text lines 
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("http"):
                urls.append(s)
                if len(urls) >= limit:
                    return urls
    return urls[:limit]


async def crawl(domain: str, max_pages: int, sitemap_url: Optional[str]) -> List[str]:
    parsed = urlparse(domain)
    root = domain if parsed.scheme else f"https://{domain}"

    seeds = []
    if sitemap_url:
        seeds = await fetch_sitemap_urls(sitemap_url, max_pages)

    seen = set()
    queue = seeds[:] if seeds else [root]
    pages: List[str] = []

    async with aiohttp.ClientSession(headers={"User-Agent": "ProfileBuilder/0.1"}) as session:
        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            html = await fetch_html(url, session)
            if not html:
                continue
            pages.append(html)
            # simple same-domain links for discovery fallback
            soup = BeautifulSoup(html, "html.parser")
            base = urlparse(url).netloc
            for a in soup.find_all("a", href=True):
                target = urljoin(url, a["href"])
                parsed_t = urlparse(target)
                if parsed_t.netloc == base and parsed_t.scheme in ("http", "https"):
                    if target not in seen and len(queue) + len(pages) < max_pages:
                        queue.append(target)
    return pages


######## Profile Building SEKTOR########

def xpath_for_class(tag: str, cls: str) -> str:
    return f"//{tag}[contains(concat(' ', normalize-space(@class), ' '), ' {cls} ')]"


def absolute_xpath(tree: etree._ElementTree, element: etree._Element) -> str:
    try:
        return tree.getpath(element)
    except Exception:
        return ""


def build_profile(domain: str, pages: List[str]) -> Dict:
    selectors: Dict[str, List[Dict[str, str]]] = {}

    for html in pages:
        tree = etree.HTML(html)
        if tree is None:
            continue
        # Iterate elements with class
        for el in tree.xpath("//*[@class]"):
            class_list = el.attrib.get("class", "").split()
            tag = el.tag
            abs_path = absolute_xpath(tree, el)
            for cls in class_list:
                cls = cls.strip()
                if not cls:
                    continue
                field = cls
                selectors.setdefault(field, [])
                class_expr = xpath_for_class(tag, cls)
                for expr in (class_expr, abs_path):
                    if expr and not any(r.get("value") == expr for r in selectors[field]):
                        selectors[field].append({"type": "xpath", "value": expr})
        # Images for visuals (absolute paths and class-based if present)
        for img in tree.xpath("//img"):
            field = "Visuals"
            selectors.setdefault(field, [])
            abs_path = absolute_xpath(tree, img)
            if abs_path and not any(r.get("value") == abs_path for r in selectors[field]):
                selectors[field].append({"type": "xpath", "value": abs_path})
            class_list = img.attrib.get("class", "").split()
            for cls in class_list:
                cls = cls.strip()
                if cls:
                    expr = xpath_for_class("img", cls)
                    if not any(r.get("value") == expr for r in selectors[field]):
                        selectors[field].append({"type": "xpath", "value": expr})

    # Deduplicatation procedure happens here
    for field, rules in list(selectors.items()):
        seen = set()
        unique_rules = []
        for r in rules:
            sig = (r.get("type"), r.get("value"))
            if sig in seen:
                continue
            seen.add(sig)
            unique_rules.append(r)
        selectors[field] = unique_rules[:10] 

    return {
        "domain": domain,
        "selectors": selectors,
    }


######## Output SEKTOR ########

def write_profile(domain: str, profile: Dict, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    parsed = urlparse(domain)
    name = parsed.netloc or parsed.path or domain
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in name)
    path = os.path.join(output_dir, f"{safe_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    print(f"Wrote profile to {path}")


######## CLI SEKTOR ########

def main():
    parser = argparse.ArgumentParser(description="Simple profile builder (class-based XPaths, no LLM)")
    parser.add_argument("domain", help="Domain or URL to crawl (e.g., example.com or https://example.com)")
    parser.add_argument("--sitemap-url", default=None, help="Optional sitemap URL for seeding")
    parser.add_argument("--max-pages", type=int, default=5, help="Max pages to sample")
    parser.add_argument("--output-dir", default="SLM/profiles", help="Where to write profile JSON")
    args = parser.parse_args()

    asyncio.run(run(args))


async def run(args):
    pages = await crawl(args.domain, max_pages=args.max_pages, sitemap_url=args.sitemap_url)
    if not pages:
        raise RuntimeError("No pages fetched; cannot build profile.")
    profile = build_profile(args.domain, pages)
    write_profile(args.domain, profile, args.output_dir)


if __name__ == "__main__":
    main()
