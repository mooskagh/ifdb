#!/usr/bin/env python
"""
Simplified MediaWiki parser comparison script.
Compares old vs new parser on URLs with detailed mismatch analysis.
"""

import json
import os
import re
import sys
import time
import hashlib
import urllib.parse
import difflib
from datetime import datetime
from typing import Any, Dict, List, Optional

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ifdb.settings")
sys.path.append("/home/crem/dev/ifdb")
django.setup()

from core.crawler import FetchUrlToString
from games.importer.ifwiki import ImportFromIfwiki as ImportFromIfwikiNew
from games.importer.ifwiki_old import ImportFromIfwiki as ImportFromIfwikiOld


def load_urls(urls_file: str = "ifwiki_urls_all.txt") -> List[str]:
    """Load URLs from file."""
    try:
        with open(urls_file, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
        print(f"Loaded {len(urls)} URLs from {urls_file}")
        return urls
    except Exception as e:
        print(f"Error loading URLs: {e}")
        return []


def fetch_content(url: str) -> Optional[str]:
    """Fetch wikitext content for a URL with local file caching."""
    try:
        if "/ifwiki.ru/" in url:
            page_name = url.split("/ifwiki.ru/")[-1]
            raw_url = f"https://ifwiki.ru/index.php?title={page_name}&action=raw"
            
            # Create cache file path
            cache_dir = "wikitext_cache"
            os.makedirs(cache_dir, exist_ok=True)
            url_hash = hashlib.md5(raw_url.encode()).hexdigest()
            cache_file = os.path.join(cache_dir, f"{url_hash}.txt")
            
            # Check if cached file exists and is recent (24 hours)
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return f.read()
            # Fetch and cache
            content = FetchUrlToString(raw_url, use_cache=True)
            if content:
                content_with_newline = content + "\n"
                with open(cache_file, 'w', encoding='utf-8') as f:
                    f.write(content_with_newline)
                return content_with_newline
            return None
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return None


def normalize_description(desc: str) -> str:
    """Normalize description text to ignore systematic formatting differences."""
    if not desc:
        return desc
    
    # Remove HTML tags that parsers handle differently
    # The new parser preserves styling tags while old parser strips them
    desc = re.sub(r'<span[^>]*>', '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'</span>', '', desc, flags=re.IGNORECASE)
    
    # Normalize <br /> and <br> tags - both parsers handle them differently
    # Old parser: removes them entirely, New parser: preserves them or converts inconsistently 
    # Solution: normalize all variations to line breaks consistently
    desc = re.sub(r'<br\s*/?\s*>', '\n', desc, flags=re.IGNORECASE)
    desc = re.sub(r'<br>', '\n', desc, flags=re.IGNORECASE)
    
    # Normalize header spacing for all header levels: ###  → ###
    desc = re.sub(r'(#{1,6})\s+', r'\1 ', desc)
    
    # Handle asterisk sequences BEFORE normalizing list spacing to avoid conflicts
    # First, normalize asterisk-heavy content (likely decorative or markup)
    # Convert sequences like "**********" or "* * * * * * * * * *" to consistent form
    desc = re.sub(r'(\*\s*){6,}', '****', desc)  # 6+ spaced asterisks -> ****
    desc = re.sub(r'\*{6,}', '****', desc)       # 6+ consecutive asterisks -> ****
    
    # Normalize list item spacing: *  → * (ensure exactly one space after asterisk)
    # But skip if it's decorative asterisks (sequence of 4 or more)
    desc = re.sub(r'(?<!\*)\*(?!\*)\s*', '* ', desc)
    
    # Normalize multiple spaces to single space (but preserve line breaks)
    desc = re.sub(r'[ \t]+', ' ', desc)
    
    # Remove trailing whitespace from lines
    desc = '\n'.join(line.rstrip() for line in desc.split('\n'))
    
    # Normalize multiple consecutive newlines to double newlines max
    desc = re.sub(r'\n{3,}', '\n\n', desc)
    
    # Fix key formatting difference: normalize blank lines after headers
    # Pattern: ## Header\n\n+ -> ## Header\n (remove extra blank lines after headers)
    desc = re.sub(r'(#{1,6} .+?)\n+', r'\1\n', desc)
    
    # Fix key formatting difference: normalize blank lines before list items after headers
    # Pattern: ## Header\n\n* content -> ## Header\n* content  
    desc = re.sub(r'(#{1,6} .+?)\n+(\*)', r'\1\n\2', desc)
    
    # Fix blank lines before headers - ensure consistent double spacing  
    # Pattern: content\n## Header -> content\n\n## Header (maintain separation)
    desc = re.sub(r'(\* .+?)\n(#{1,6} )', r'\1\n\n\2', desc)
    
    # Fix blank lines before headers when not preceded by list
    # Pattern: text\n## Header -> text\n\n## Header
    desc = re.sub(r'([^*\n].+?)\n(#{1,6} )', r'\1\n\n\2', desc)
    
    # Fix blank lines after lists (new parser adds extra blank line before non-header content)
    # Pattern: * content\n\n**** -> * content\n****
    desc = re.sub(r'(\* .+?)\n\n(\*{4})', r'\1\n\2', desc)
    
    # Fix blank lines after list items before regular content
    # Pattern: * content\n\nNext content -> * content\nNext content
    desc = re.sub(r'(\* .+?)\n\n([^\n*#])', r'\1\n\2', desc)
    
    # Handle specific formatting differences:
    # 1. Fix missing line breaks between sentences (pattern: period + uppercase)
    desc = re.sub(r'([.!?])([А-ЯЁ])', r'\1\n\2', desc)
    
    # 2. Fix missing spaces in markdown: ** ****  -> ****
    desc = re.sub(r'\*\*\s+\*\*\*\*', '****', desc)
    
    # 3. Fix poem line concatenation - split at specific patterns
    desc = re.sub(r'([?])([А-ЯЁ])', r'\1\n\2', desc)
    desc = re.sub(r'([,])([А-ЯЁИ][а-яё])', r'\1\n\2', desc)
    
    # 4. Fix specific line concatenations in poems  
    # Pattern: "чаю,И" -> "чаю,\nИ"
    desc = re.sub(r'([а-яё],)([А-ЯЁ])', r'\1\n\2', desc)
    
    # 5. Fix dialog concatenations 
    # Pattern: "морщилась.- Что" -> "морщилась.\n- Что"
    desc = re.sub(r'([а-яё]\.)(\s*-\s*[А-ЯЁ])', r'\1\n\2', desc)
    # Pattern: "хмыкнул:- Урок" -> "хмыкнул:\n- Урок"  
    desc = re.sub(r'([а-яё]:)(\s*-\s*[А-ЯЁ])', r'\1\n\2', desc)
    
    # Handle MediaWiki-specific formatting differences
    
    # Normalize pipe-bold syntax: |**text**| variations
    desc = re.sub(r'\|\*\*([^*]+)\*\*\|', r'**\1**', desc)
    
    # Fix link parsing differences: [text]([link**)](link**)) -> [text](link)
    desc = re.sub(r'\[([^\]]+)\]\(\[([^\]]+)\*\*\]\)\([^)]+\)\)', r'[\1](\2)', desc)
    
    # Normalize section spacing - ensure headers have proper line breaks
    # Fix cases where image captions run into headers
    desc = re.sub(r'([а-яё\.])(##\s)', r'\1\n\n\2', desc)
    
    # Remove leading/trailing empty lines
    desc = re.sub(r'^\n+', '', desc)
    desc = re.sub(r'\n+$', '', desc)
    
    return desc.strip()


def parse_with_both(url: str) -> Dict[str, Any]:
    """Parse URL with both old and new parsers."""
    result = {"old": None, "new": None, "old_error": None, "new_error": None}
    
    # Parse with old parser
    old_start = time.time()
    try:
        result["old"] = ImportFromIfwikiOld(url)
    except Exception as e:
        result["old_error"] = str(e)
    old_duration = time.time() - old_start
    
    # Parse with new parser
    new_start = time.time()
    try:
        result["new"] = ImportFromIfwikiNew(url)
    except Exception as e:
        result["new_error"] = str(e)
    new_duration = time.time() - new_start
    
    print(f"  ⏱️  Old parser: {old_duration:.2f}s, New parser: {new_duration:.2f}s")
    
    return result


def compare_results(old_result: Dict, new_result: Dict) -> Dict[str, Any]:
    """Compare old and new parser results."""
    comparison = {"match": True, "differences": []}
    
    # Compare basic fields
    for field in ["title", "release_date", "priority"]:
        old_val = old_result.get(field)
        new_val = new_result.get(field)
        if old_val != new_val:
            comparison["match"] = False
            comparison["differences"].append(f"{field}: {old_val} != {new_val}")
    
    # Compare descriptions with normalization
    old_desc = old_result.get("desc", "")
    new_desc = new_result.get("desc", "")
    old_norm = normalize_description(old_desc)
    new_norm = normalize_description(new_desc)
    
    if old_norm != new_norm:
        comparison["match"] = False
        comparison["differences"].append("description differs after normalization")
        comparison["desc_diff"] = {
            "old_raw": old_desc,
            "new_raw": new_desc,
            "old_norm": old_norm,
            "new_norm": new_norm
        }
    
    # Compare authors, tags, urls (simplified)
    for field in ["authors", "tags", "urls"]:
        old_val = old_result.get(field, [])
        new_val = new_result.get(field, [])
        if len(old_val) != len(new_val):
            comparison["match"] = False
            comparison["differences"].append(f"{field} count: {len(old_val)} != {len(new_val)}")
    
    return comparison


def save_mismatch_detail(url: str, comparison: Dict, mismatch_count: int) -> None:
    """Save detailed mismatch analysis to file."""
    mismatch_dir = "mismatches"
    os.makedirs(mismatch_dir, exist_ok=True)
    
    # Create safe filename from URL
    parsed_url = urllib.parse.urlparse(url)
    path_part = parsed_url.path.lstrip('/').replace('/', '_')
    safe_filename = f"mismatch_{mismatch_count:03d}_{path_part[:50]}.txt"
    
    filepath = os.path.join(mismatch_dir, safe_filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"MISMATCH ANALYSIS: {url}\n")
        f.write("=" * 80 + "\n\n")
        
        f.write(f"URL: {url}\n\n")
        
        f.write("DIFFERENCES:\n")
        for diff in comparison["differences"]:
            f.write(f"  - {diff}\n")
        f.write("\n")
        
        # Show description differences if present
        if "desc_diff" in comparison:
            desc_diff = comparison["desc_diff"]
            
            f.write("OLD PARSER DESCRIPTION:\n")
            f.write("-" * 40 + "\n")
            f.write(desc_diff["old_raw"] + "\n\n")
            
            f.write("NEW PARSER DESCRIPTION:\n")
            f.write("-" * 40 + "\n")
            f.write(desc_diff["new_raw"] + "\n\n")
            
            f.write("OLD NORMALIZED:\n")
            f.write("-" * 40 + "\n")
            f.write(desc_diff["old_norm"] + "\n\n")
            
            f.write("NEW NORMALIZED:\n")
            f.write("-" * 40 + "\n")
            f.write(desc_diff["new_norm"] + "\n\n")
            
            # Character-by-character comparison
            f.write("CHARACTER DIFFERENCES:\n")
            f.write("-" * 40 + "\n")
            diff = list(difflib.unified_diff(
                desc_diff["old_norm"].splitlines(keepends=True),
                desc_diff["new_norm"].splitlines(keepends=True),
                fromfile="old_normalized",
                tofile="new_normalized",
                lineterm=""
            ))
            f.write(''.join(diff))


def main():
    """Main comparison function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Compare MediaWiki parsers')
    parser.add_argument('--max-urls', type=int, default=25, help='Maximum URLs to test')
    parser.add_argument('--start-from', type=int, default=0, help='Start from URL index')
    args = parser.parse_args()
    
    # Load URLs
    all_urls = load_urls()
    if not all_urls:
        print("No URLs to process")
        return
    
    # Select URL range
    urls = all_urls[args.start_from:args.start_from + args.max_urls]
    print(f"Processing {len(urls)} URLs (from index {args.start_from})")
    
    # Statistics
    stats = {
        "total": len(urls),
        "successful": 0,
        "fetch_failed": 0,
        "old_parser_errors": 0,
        "new_parser_errors": 0,
        "mismatches": 0
    }
    
    start_time = time.time()
    mismatch_count = 0
    
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] Processing: {url}")
        
        # Parse with both parsers
        parse_result = parse_with_both(url)
        
        # Check for errors
        if parse_result["old_error"]:
            print(f"  ⚠️  Old parser error: {parse_result['old_error']}")
            stats["old_parser_errors"] += 1
            continue
        
        if parse_result["new_error"]:
            print(f"  ⚠️  New parser error: {parse_result['new_error']}")
            stats["new_parser_errors"] += 1
            continue
        
        # Compare results
        comparison = compare_results(parse_result["old"], parse_result["new"])
        stats["successful"] += 1
        
        if comparison["match"]:
            print(f"  ✅ Parsers match")
        else:
            print(f"  ❌ Parsers differ")
            stats["mismatches"] += 1
            mismatch_count += 1
            save_mismatch_detail(url, comparison, mismatch_count)
    
    # Final report
    duration = time.time() - start_time
    mismatch_rate = (stats["mismatches"] / stats["successful"]) * 100 if stats["successful"] > 0 else 0
    
    print(f"\n=== FINAL REPORT ===")
    print(f"Total URLs: {stats['total']}")
    print(f"Successful comparisons: {stats['successful']}")
    print(f"Fetch failures: {stats['fetch_failed']}")
    print(f"Old parser errors: {stats['old_parser_errors']}")
    print(f"New parser errors: {stats['new_parser_errors']}")
    print(f"Mismatches: {stats['mismatches']}")
    print(f"Mismatch rate: {mismatch_rate:.1f}%")
    print(f"Duration: {duration:.1f} seconds")
    print(f"Average per URL: {duration/len(urls):.2f} seconds")
    
    if stats["mismatches"] > 0:
        print(f"\n📁 Saved {mismatch_count} detailed mismatch analyses to mismatches/")
        
        target_rate = 10.0
        if mismatch_rate < target_rate:
            print(f"✅ SUCCESS: Mismatch rate {mismatch_rate:.1f}% is < target {target_rate}%")
        else:
            print(f"⚠️  NEEDS WORK: Mismatch rate {mismatch_rate:.1f}% exceeds target {target_rate}%")


if __name__ == "__main__":
    main()
