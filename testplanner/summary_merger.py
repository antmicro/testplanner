import argparse
import os
from pathlib import Path
from typing import List, Optional

from bs4 import BeautifulSoup


def merge2(file1: Path, file2: Path) -> str:
    with open(file2, "r") as f:
        source_soup = BeautifulSoup(f, "html.parser")

    # attempt to take out the main table from file2
    content_div = source_soup.find("center", class_="results")

    with open(file1, "r", encoding="utf-8") as f:
        target_soup = BeautifulSoup(f, "html.parser")

    # attempt to take out the title from file2
    title = source_soup.find("span", class_="container-title")

    # embed the title into file1
    if title:
        target_soup.body.append(title)

    # embed the table into file1
    if content_div:
        target_soup.body.append(content_div)

    return str(target_soup)


def replace_links(
    files: List[Path],
    new_path: Path,
    base_path1: Optional[Path] = None,
    base_path2: Optional[Path] = None,
):
    for file in files:
        with open(file, "r") as f:
            soup = BeautifulSoup(f, "html.parser")

        foo = soup.find("div", class_="nav-urls")

        if foo:
            links = foo.find_all("a")
            for link in links:
                href = link.get("href")
                if href:
                    current_path = Path(href)
                    if base_path1 and (base_path1 / current_path).exists():
                        base_path = base_path1
                    elif base_path2 and (base_path2 / current_path).exists():
                        base_path = base_path2
                    else:
                        raise RuntimeError(
                            f"Warning: {href} does not exist in either base path."
                        )

                    relative_path = new_path.relative_to(
                        base_path / current_path.parent
                    )
                    link["href"] = str(relative_path)

        with open(file, "w") as f:
            f.write(str(soup))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "summaries",
        metavar="<summary-file>",
        nargs=3,
        help="testplan summary files - input 1, input 2, output",
    )
    parser.add_argument(
        "-r",
        "--replace-links",
        # action="store_true",
        help="Attempt to remap links from other sources in the destination directory tree",  # noqa: E501
    )
    args = parser.parse_args()

    testplans = [Path(os.path.abspath(s)) for s in args.summaries]
    assert len(testplans) == 3
    content_str = merge2(*testplans[:2])

    if args.replace_links:
        import glob

        files = list(
            map(
                lambda x: Path(args.replace_links) / x,
                glob.glob("*.html", root_dir=args.replace_links),
            )
        )
        replace_links(files, testplans[2], testplans[0].parent, testplans[1].parent)

    with open(testplans[2], "w", encoding="utf-8") as modified_file:
        modified_file.write(content_str)


if __name__ == "__main__":
    main()
