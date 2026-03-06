import requests
from bs4 import BeautifulSoup


def main():
    url = "https://example.com"

    response = requests.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    title = (soup.title.string or "").strip() if soup.title else "No title found"
    print(f"Title: {title}\n")

    links = soup.find_all("a")
    print(f"Found {len(links)} links:")
    for link in links:
        href = link.get("href")
        text = link.get_text(strip=True)
        print(f"  - {text}: {href}")


if __name__ == "__main__":
    main()
