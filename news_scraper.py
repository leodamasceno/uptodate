import argparse
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

import requests
import yaml
from bs4 import BeautifulSoup

try:
    import cloudscraper
except ImportError:
    cloudscraper = None

DEFAULT_CONFIG = "config.yaml"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
             "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict) or "sites" not in config:
        raise ValueError("Configuration file must contain a top-level 'sites' list")

    return config


def fetch_html(url: str, timeout: int = 15) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-User": "?1",
    }

    response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    if response.status_code == 403 and cloudscraper is not None:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url, headers=headers, timeout=timeout, allow_redirects=True)

    response.raise_for_status()
    return response.text


def extract_headlines(html: str, selector, feed_type: str = "html") -> list[str]:
    """Extract headlines based on feed type (html or xml)."""
    if feed_type == "xml":
        return extract_headlines_xml(html, selector)
    else:
        return extract_headlines_html(html, selector)


def extract_headlines_html(html: str, selector) -> list[str]:
    """Extract headlines from HTML using CSS selectors."""
    soup = BeautifulSoup(html, "html.parser")
    if isinstance(selector, list):
        elements = []
        for s in selector:
            elements.extend(soup.select(s))
    else:
        elements = soup.select(selector)

    headlines = []
    for element in elements:
        text = element.get_text(separator=" ", strip=True)
        if text:
            headlines.append(text)
    return headlines


def extract_headlines_xml(xml_content: str, selector: str) -> list[str]:
    """Extract headlines from XML/RSS feed using tag name."""
    headlines = []
    try:
        root = ET.fromstring(xml_content)
        
        # Handle namespaces in RSS/Atom feeds
        namespaces = {
            '': 'http://www.rss-spec.org/specification.html',
            'atom': 'http://www.w3.org/2005/Atom',
            'content': 'http://purl.org/rss/1.0/modules/content/'
        }
        
        # Try to find elements with the given tag name
        # First try with namespace, then without
        for ns_prefix, ns_url in namespaces.items():
            if ns_prefix:
                tag = f'{{{ns_url}}}{selector}'
            else:
                tag = selector
            
            elements = root.findall(f'.//{tag}')
            if elements:
                for element in elements:
                    text = element.text
                    if text and text.strip():
                        # Skip if this is the channel/feed title (usually first)
                        if selector == 'title' and len(headlines) == 0 and text.startswith(('AWS', 'Amazon', 'News')):
                            # This is likely the feed title itself, skip it for RSS
                            continue
                        headlines.append(text.strip())
                return headlines
        
        # Fallback: search without namespace
        for element in root.iter(selector):
            text = element.text
            if text and text.strip():
                headlines.append(text.strip())
    
    except ET.ParseError as e:
        raise ValueError(f"Failed to parse XML: {e}")
    
    return headlines


def print_site_news(site: dict, default_max: int) -> None:
    name = site.get("name", site.get("url", "Unknown site"))
    url = site.get("url")
    selector = site.get("selector")
    feed_type = site.get("type", "html")  # Default to html if not specified
    max_items = site.get("max_items", default_max)

    print(f"\n== {name} ==")
    if not url or not selector:
        print("  Skipping site because both 'url' and 'selector' are required in config.")
        return

    try:
        html = fetch_html(url)
        headlines = extract_headlines(html, selector, feed_type)
    except Exception as exc:
        print(f"  Error fetching news from {url}: {exc}")
        return

    if not headlines:
        print("  No headlines found with the configured selector.")
        return

    for rank, headline in enumerate(headlines[:max_items], start=1):
        print(f"  {rank}. {headline}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CLI news scraper that reads site configuration from YAML and prints headlines."
    )
    parser.add_argument(
        "-c", "--config",
        default=DEFAULT_CONFIG,
        help="Path to the YAML configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "-n", "--max",
        type=int,
        default=10,
        help="Maximum number of headlines to display per site",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)

    try:
        config = load_config(config_path)
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    sites = config.get("sites", [])
    if not isinstance(sites, list) or not sites:
        print("Error: 'sites' must be a non-empty list in the configuration file.")
        return 1

    for site in sites:
        print_site_news(site, args.max)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
