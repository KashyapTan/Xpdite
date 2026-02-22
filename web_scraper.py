import requests
from bs4 import BeautifulSoup
import json
from urllib.parse import urljoin, urlparse


class WebScraper:
    def __init__(self, base_url=None, headers=None):
        self.base_url = base_url
        self.session = requests.Session()
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        self.session.headers.update(headers or default_headers)

    def fetch_page(self, url):
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None

    def parse_html(self, html):
        return BeautifulSoup(html, "html.parser")

    def get_text(self, soup, selector=None):
        if selector:
            elements = soup.select(selector)
            return [el.get_text(strip=True) for el in elements]
        return soup.get_text(strip=True)

    def get_links(self, soup, base_url=None):
        links = []
        base = base_url or self.base_url or ""
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full_url = urljoin(base, href)
            links.append({"text": a.get_text(strip=True), "url": full_url})
        return links

    def get_images(self, soup, base_url=None):
        images = []
        base = base_url or self.base_url or ""
        for img in soup.find_all("img", src=True):
            src = img["src"]
            full_url = urljoin(base, src)
            images.append({"alt": img.get("alt", ""), "url": full_url})
        return images

    def extract_data(self, url, selectors):
        html = self.fetch_page(url)
        if not html:
            return None

        soup = self.parse_html(html)
        data = {}

        for key, selector in selectors.items():
            elements = soup.select(selector)
            if len(elements) == 1:
                data[key] = elements[0].get_text(strip=True)
            elif len(elements) > 1:
                data[key] = [el.get_text(strip=True) for el in elements]
            else:
                data[key] = None

        return data

    def scrape_multiple(self, urls, selectors):
        results = []
        for url in urls:
            data = self.extract_data(url, selectors)
            if data:
                data["_url"] = url
                results.append(data)
        return results

    def save_to_json(self, data, filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Saved to {filename}")


def main():
    scraper = WebScraper()

    target_url = "https://example.com"

    print(f"Scraping: {target_url}\n")

    html = scraper.fetch_page(target_url)
    if html:
        soup = scraper.parse_html(html)

        title = soup.find("title")
        print(f"Title: {title.get_text() if title else 'N/A'}\n")

        links = scraper.get_links(soup, target_url)
        print(f"Found {len(links)} links:")
        for link in links[:5]:
            print(f"  - {link['text']}: {link['url']}")
        if len(links) > 5:
            print(f"  ... and {len(links) - 5} more")

        print(f"\nPage text preview:")
        text = scraper.get_text(soup)
        text_str = str(text) if text else ""
        print(text_str[:500] + "..." if len(text_str) > 500 else text_str)


if __name__ == "__main__":
    main()
