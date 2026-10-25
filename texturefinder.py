#!/usr/bin/env python3
"""Find free PBR textures and bundle them into zip packs.

Sources:
  ambientcg   https://ambientcg.com  (CC0, public JSON API)
  texturecan  https://www.texturecan.com  (scraped from its pages; experimental)

Every pack is written to packs/<Pack_Name>.zip and looks like:

  Pack Name/
    CREDITS.txt
    Bricks059/
      Bricks059_1K-JPG_Color.jpg
      Bricks059_1K-JPG_NormalGL.jpg
      ...
    Wood049/
      ...

Only the Python standard library is used, so no install step is needed.
"""

import argparse
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / ".cache"
PACKS_DIR = ROOT / "packs"

AMBIENTCG_API = "https://ambientcg.com/api/v2/full_json"
AMBIENTCG_GET = "https://ambientcg.com/get?file={asset}_{attr}.zip"
AMBIENTCG_ASSET = "https://ambientcg.com/view?id={asset}"
AMBIENTCG_TYPES = ["Material", "Decal", "Atlas", "HDRI", "3DModel", "Terrain",
                   "PlainTexture", "Substance", "Brush"]
AMBIENTCG_SORTS = ["Popular", "Latest", "Downloads", "Alphabet"]

TEXTURECAN_BASE = "https://www.texturecan.com"
TEXTURECAN_HOST = "texturecan.com"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".exr", ".tif", ".tiff", ".tga", ".hdr"}
USER_AGENT = "ClaudeTextureFinder/1.0 (+https://github.com/alexbezi2123-cpu/ClaudeTExtureFinder)"


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def http_get(url, retries=3):
    """GET a URL and return (bytes, final_url). Retries transient failures."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read(), resp.geturl()
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries - 1:
                raise
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError("unreachable")


def http_json(url):
    data, _ = http_get(url)
    return json.loads(data)


def cached_download(url, name):
    """Download url into .cache/<name>, reusing an existing copy."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / name
    if path.exists() and path.stat().st_size > 0:
        return path
    data, _ = http_get(url)
    path.write_bytes(data)
    return path


# --------------------------------------------------------------------------- #
# ambientCG
# --------------------------------------------------------------------------- #

def ambientcg_search(query=None, types=("Material",), category=None,
                     sort="Popular", limit=20, ids=None):
    """Return a list of asset dicts from the ambientCG API."""
    assets = []
    offset = 0
    page = min(limit, 100)
    while len(assets) < limit:
        params = {
            "type": ",".join(types),
            "sort": sort,
            "limit": page,
            "offset": offset,
            "include": "downloadData,tagData,displayData",
        }
        if query:
            params["q"] = query
        if category:
            params["category"] = category
        if ids:
            params["id"] = ",".join(ids)
        data = http_json(AMBIENTCG_API + "?" + urllib.parse.urlencode(params))
        found = data.get("foundAssets", [])
        assets.extend(found)
        if len(found) < page or ids:
            break
        offset += page
    return assets[:limit]


def ambientcg_downloads(asset):
    """Yield every download entry (dict with attribute/downloadLink) of an asset."""
    def walk(node):
        if isinstance(node, dict):
            if "downloadLink" in node or "rawLink" in node:
                yield node
            else:
                for v in node.values():
                    yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)
    yield from walk(asset.get("downloadFolders", {}))


def ambientcg_pick_download(asset, res, fmt):
    """Pick the zip download matching e.g. res='1K', fmt='JPG'.

    Falls back to the closest available resolution, then to a guessed URL.
    """
    asset_id = asset["assetId"]
    wanted = f"{res}-{fmt}".upper()
    zips = [d for d in ambientcg_downloads(asset)
            if str(d.get("fileName", d.get("downloadLink", ""))).lower().endswith(".zip")
            or "zip" in str(d.get("filetype", "")).lower()]
    by_attr = {str(d.get("attribute", "")).upper(): d for d in zips}
    if wanted in by_attr:
        d = by_attr[wanted]
    else:
        same_fmt = [a for a in by_attr if a.endswith("-" + fmt.upper())]
        if same_fmt:
            # Closest resolution by number, e.g. asked 1K but only 2K/4K exist.
            def res_num(a):
                m = re.match(r"(\d+)K", a)
                return int(m.group(1)) if m else 99
            target = res_num(wanted)
            d = by_attr[min(same_fmt, key=lambda a: abs(res_num(a) - target))]
        elif by_attr:
            d = next(iter(by_attr.values()))
        else:
            return AMBIENTCG_GET.format(asset=asset_id, attr=wanted), f"{asset_id}_{wanted}.zip"
    url = d.get("downloadLink") or d.get("rawLink")
    name = d.get("fileName") or f"{asset_id}_{d.get('attribute', wanted)}.zip"
    return url, name


def ambientcg_collect(args):
    """Return list of (folder_name, zip_path, credit_line) for an ambientCG pack."""
    ids = [i.strip() for i in args.ids.split(",") if i.strip()] if args.ids else None
    limit = max(args.limit, len(ids)) if ids else args.limit
    assets = ambientcg_search(query=args.query, types=args.type, category=args.category,
                              sort=args.sort, limit=limit, ids=ids)
    if not assets:
        sys.exit("No ambientCG assets matched.")
    items = []
    for n, asset in enumerate(assets, 1):
        asset_id = asset["assetId"]
        url, name = ambientcg_pick_download(asset, args.res, args.format)
        print(f"[{n}/{len(assets)}] {asset_id}: {name}")
        try:
            path = cached_download(url, "ambientcg_" + name)
        except urllib.error.HTTPError as e:
            print(f"    skipped ({e.code} {e.reason})")
            continue
        credit = f"{asset_id} - {AMBIENTCG_ASSET.format(asset=asset_id)} - CC0 1.0 (ambientCG.com)"
        items.append((asset_id, path, credit))
    return items


def cmd_search(args):
    if args.source == "texturecan":
        for url in texturecan_detail_links(texturecan_listing_url(args), args.limit):
            print(url)
        return
    assets = ambientcg_search(query=args.query, types=args.type, category=args.category,
                              sort=args.sort, limit=args.limit)
    for a in assets:
        name = a.get("displayName", "")
        cat = a.get("displayCategory", a.get("category", ""))
        tags = ", ".join(a.get("tags", [])[:6])
        print(f"{a['assetId']:<22} {name:<26} {cat:<16} {tags}")
    print(f"\n{len(assets)} result(s)")


# --------------------------------------------------------------------------- #
# TextureCan (no public API, so links are pulled out of the HTML)
# --------------------------------------------------------------------------- #

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ("href", "data-href", "data-url") and value:
                self.links.append(value)


def page_links(url):
    html, final_url = http_get(url)
    parser = LinkParser()
    parser.feed(html.decode("utf-8", "replace"))
    return [urllib.parse.urljoin(final_url, link) for link in parser.links]


def texturecan_listing_url(args):
    if args.url:
        return args.url
    if args.query:
        return f"{TEXTURECAN_BASE}/?s={urllib.parse.quote_plus(args.query)}"
    if args.category:
        return f"{TEXTURECAN_BASE}/category/{urllib.parse.quote(args.category)}/"
    return TEXTURECAN_BASE + "/"


def texturecan_detail_links(listing_url, limit):
    if "/details/" in listing_url:
        return [listing_url]
    seen = []
    for link in page_links(listing_url):
        if "/details/" in link and TEXTURECAN_HOST in link:
            link = link.split("#")[0]
            if link not in seen:
                seen.append(link)
    return seen[:limit]


def texturecan_fetch_zip(detail_url, res):
    """Follow download links from a detail page until a zip file comes back."""
    links = page_links(detail_url)
    candidates = [l for l in links
                  if TEXTURECAN_HOST in l and ("download" in l.lower() or l.lower().endswith(".zip"))]
    res_l = res.lower()
    candidates.sort(key=lambda l: 0 if res_l in l.lower() else 1)
    for link in candidates:
        data, final_url = http_get(link)
        if data[:2] == b"PK":
            return data, final_url
        # A download landing page: look one level deeper for the real zip.
        parser = LinkParser()
        parser.feed(data.decode("utf-8", "replace"))
        for inner in parser.links:
            inner = urllib.parse.urljoin(final_url, inner)
            if inner.lower().split("?")[0].endswith(".zip") or "download" in inner.lower():
                inner_data, inner_url = http_get(inner)
                if inner_data[:2] == b"PK":
                    return inner_data, inner_url
    return None, None


def texturecan_collect(args):
    details = texturecan_detail_links(texturecan_listing_url(args), args.limit)
    if not details:
        sys.exit("No TextureCan textures found on that page.")
    items = []
    CACHE_DIR.mkdir(exist_ok=True)
    for n, detail in enumerate(details, 1):
        slug = detail.rstrip("/").split("/")[-1] or f"texture{n}"
        folder = f"TextureCan_{slug}"
        cache = CACHE_DIR / f"texturecan_{slug}_{args.res}.zip"
        print(f"[{n}/{len(details)}] {detail}")
        if not cache.exists():
            data, _ = texturecan_fetch_zip(detail, args.res)
            if not data:
                print("    skipped (no zip download found)")
                continue
            cache.write_bytes(data)
        items.append((folder, cache, f"{folder} - {detail} - see TextureCan.com for license"))
    return items


# --------------------------------------------------------------------------- #
# Packing
# --------------------------------------------------------------------------- #

def slugify(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "pack"


def build_pack(pack_name, items, images_only=False, out_dir=PACKS_DIR):
    """Write out_dir/<slug>.zip with one folder per texture inside a root folder."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slugify(pack_name)}.zip"
    root = pack_name.strip()
    credits = [f"{root}", "=" * len(root), "",
               "Textures collected with ClaudeTextureFinder.", ""]
    count = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as pack:
        for folder, zip_path, credit in items:
            try:
                src = zipfile.ZipFile(zip_path)
            except zipfile.BadZipFile:
                print(f"    {folder}: not a valid zip, skipped")
                continue
            with src:
                for info in src.infolist():
                    if info.is_dir():
                        continue
                    name = Path(info.filename).name  # flatten, and blocks ../ paths
                    if not name or (images_only and Path(name).suffix.lower() not in IMAGE_EXTS):
                        continue
                    pack.writestr(f"{root}/{folder}/{name}", src.read(info))
            credits.append(credit)
            count += 1
        pack.writestr(f"{root}/CREDITS.txt", "\n".join(credits) + "\n")
    size_mb = out_path.stat().st_size / 1e6
    print(f"\nWrote {out_path} ({count} textures, {size_mb:.1f} MB)")
    return out_path


def cmd_pack(args):
    collect = texturecan_collect if args.source == "texturecan" else ambientcg_collect
    items = collect(args)
    if not items:
        sys.exit("Nothing downloaded, no pack written.")
    build_pack(args.name, items, images_only=args.images_only)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--source", choices=["ambientcg", "texturecan"], default="ambientcg")
        sp.add_argument("-q", "--query", help="search words, e.g. 'mossy rock'")
        sp.add_argument("-c", "--category", help="site category, e.g. Bricks, Wood, Metal")
        sp.add_argument("-t", "--type", nargs="+", default=["Material"], choices=AMBIENTCG_TYPES,
                        help="ambientCG asset types (default: Material)")
        sp.add_argument("-s", "--sort", default="Popular", choices=AMBIENTCG_SORTS)
        sp.add_argument("-n", "--limit", type=int, default=20, help="max textures (default 20)")
        sp.add_argument("--url", help="texturecan: listing/category/detail page to pull from")

    sp = sub.add_parser("search", help="list matching textures without downloading")
    common(sp)
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("pack", help="download textures and build a zip pack")
    sp.add_argument("name", help="pack name, e.g. 'Medieval Stone'")
    common(sp)
    sp.add_argument("--ids", help="ambientCG asset ids, comma separated (overrides search)")
    sp.add_argument("-r", "--res", default="1K", help="resolution: 1K, 2K, 4K, 8K (default 1K)")
    sp.add_argument("-f", "--format", default="JPG", choices=["JPG", "PNG"], help="image format")
    sp.add_argument("--images-only", action="store_true",
                    help="keep only texture images (drop .mtlx/.usdc/.blend extras)")
    sp.set_defaults(func=cmd_pack)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
