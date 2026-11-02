import argparse
import re
from pathlib import Path


URL_PATTERN = re.compile(r"https?://[^\"'\s,}\]]+")


def extract_urls(input_path: Path) -> list[str]:
    text = input_path.read_text(encoding="utf-8", errors="replace")
    seen: set[str] = set()
    urls: list[str] = []

    for match in URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(").;")
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract HTTP URLs from a text or JSON file."
    )
    parser.add_argument("input", nargs="?", default="urls_to_download.txt")
    parser.add_argument("--output", default="extracted_urls.txt")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    urls = extract_urls(input_path)

    output_path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    print(f"Extracted {len(urls)} URLs to {output_path}")


if __name__ == "__main__":
    main()
