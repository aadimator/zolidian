import os
import re
from datetime import datetime
from os import environ
from pathlib import Path
from typing import Callable, List
import urllib.parse as urparse

ENV_VARS = [
    "SITE_URL",
    "SITE_TITLE",
    "TIMEZONE",
    "REPO_URL",
    "LANDING_PAGE",
    "LANDING_TITLE",
    "LANDING_DESCRIPTION",
    "LANDING_BUTTON",
]

ZOLA_DIR = Path(__file__).resolve().parent
NOTES_DIR = ZOLA_DIR / "content"


def print_step(msg: str):
    print(msg.center(100, "-"))


def process_lines(path: Path, fn: Callable[[str], str]):
    content = "\n".join([fn(line.rstrip())
                        for line in open(path, "r", encoding="utf-8").readlines()])
    open(path, "w", encoding="utf-8").write(content)
    print_step(str(path))
    print(content)


def step1():
    """
    Check environment variables
    """
    print_step("CHECKING ENVIRONMENT VARIABLES")
    for item in ENV_VARS:
        if item not in environ:
            print(f"WARNING: build.environment.{item} not set!")
            environ[item] = f"build.environment.{item}"
        else:
            print(f"{item}: {environ[item]}")


def step2():
    """
    Substitute netlify.toml settings into config.toml and landing page
    """

    print_step("SUBSTITUTING CONFIG FILE AND LANDING PAGE")

    def sub(line: str) -> str:
        for env_var in ENV_VARS:
            line = line.replace(f"___{env_var}___", environ[env_var])
        return line

    process_lines(ZOLA_DIR / "config.toml", sub)
    # process_lines(ZOLA_DIR / "content" / "index.md", sub)


def step3():
    """
    Generate _index.md for each section
    """

    print_step("GENERATING _index.md")
    sections = list(NOTES_DIR.glob("**/**"))
    content = None
    for section in sections:
        # Set section title as relative path to section
        title = re.sub(r"^.*?content/*", "", str(section))

        # Skip the root _index.md file
        if title == "":
            continue

        sort_by = (
            "date"
            if "SORT_BY" in environ and environ["SORT_BY"].lower() == "date"
            else "title"
        )

        original_content = []
        md_file = Path(section / "_index.md")
        # Read file, if exists
        if md_file.exists():
            original_content = [line.rstrip() for line in open(
            md_file, "r", encoding="utf-8").readlines()]
            original_content = remove_obsidian_comments(original_content)

        # Print frontmatter to file
        content = [
            "---",
            f"title: {title}",
            "template: section.html",
            f"sort_by: {sort_by}",
            "---",
            *original_content
        ]
        open(md_file, "w",
             encoding="utf-8").write("\n".join(content))
    if content:
        print("\n".join(content))


def remove_frontmatters(content: List[str]) -> List[str]:
    """
    Remove obsidian-specific frontmatters
    """

    # Skip if no frontmatters
    if len(content) == 0 or not content[0].startswith("---"):
        return content

    # Search for line number where frontmatters ends
    frontmatter_end = -1
    for i, line in enumerate(content[1:]):
        if line.startswith("---"):
            frontmatter_end = i
            break

    # Return content without frontmatters
    if frontmatter_end > 0:
        return content[frontmatter_end + 2:]

    # No frontmatters ending tag
    return content


def fix_links(file: Path, content: List[str]) -> List[str]:
    """
    1. Replace obsidian relative links to valid absolute links
    2. Preserve #section
    3. Remove file name from section links within same page
    4. Create <span> of around blockembeds
    5. Remove first part of link [first part > heading](link)
    """
    # Replace relative links
    parent_dir = f"{file.parents[0]}".replace(str(ZOLA_DIR / "content"), "").replace(
        " ", "%20"
    )

    # Markdown links: [xxx](yyy)
    # (\[.+?\]): Capture [xxx] part
    # \((?!http)(.+?)(?:.md)?\): Capture (yyy) part, ensuring that link is not http and remove .md from markdown files
    replaced_links = [
        re.sub(
            r"(\[.+?\])\((?!http)(.+?)(?:.md)?\)", r"\1(" +
            re.escape(parent_dir) + r"/\2)", line
        )
        for line in content
    ]

    # remove .md from links like [test](test.md#testing) preserving the #testing
    replaced_links = [
        re.sub(
            r"(\[.+?\])\((?!http)(.+?).md(.+)\)", r"\1(\2\3)", line
        )
        for line in replaced_links
    ]

    file_match_str = re.escape(parent_dir) + r"/" + \
        re.escape(urparse.quote(file.stem.encode('utf-8')))

    replaced_links = re.sub(
        r'(\[.+?\])\((?!http)(' + file_match_str + r')(#.+)\)', r'\1(\3)', u'\n'.join(replaced_links)).split('\n')

    replaced_links = [re.sub(
        r'\s\^(.+)\s*', r' <span id="\1">^\1</span>', line) for line in replaced_links]

    replaced_links = [re.sub(
        r'(.*\[).*>\s*(.*?\])(.*)', r'\1\2\3', line) for line in replaced_links]

    return replaced_links


def fix_katex_issues(file: Path, content: List[str]) -> List[str]:
    """
    1. Remove \displaylines command
    2. Replace double forward slashes
    """
    joined_content = '\n'.join(content)
    replaced_displaylines = re.sub(
        r"(\s*\$\$)\s*\\displaylines\s*{((.|\n)*?)}(\s*\$\$)", r"\1\2\4", joined_content)
    replaced_displaylines = replaced_displaylines.split('\n')

    # Fix `obsidian-export` issues where first \ is escaped
    replaced_displaylines = [re.sub(r"^\s*\\\\([A-z])", r"\\\1", line) for line in replaced_displaylines]

    # Replace double forward slashes (in LaTEX) to fix issues
    replaced_slashes = [
        re.sub(r"\\\\", r"\\\\\\\\", line) for line in replaced_displaylines
    ]

    return replaced_slashes


def remove_obsidian_comments(content: List[str]) -> List[str]:
    """
    Remove the obsidian comments from the content. %% comment %%
    """

    return re.sub(r'\s*\%\%(.|\n)*?\s*\%\%', '', '\n'.join(content)).split('\n')


def write_frontmatters(file: Path, content: List[str]) -> List[str]:
    """
    Write Zola-specific frontmatters
    """

    # Use Titlecase file name (preserving uppercase words) as title
    title = " ".join(
        [item if item[0].isupper() else item.title()
         for item in file.stem.split(" ")]
    )

    # Use last modified time as creation and updated time
    modified = datetime.fromtimestamp(os.path.getmtime(file))

    return [
        "---",
        f"title: {title}",
        f"date: {modified}",
        f"updated: {modified}",
        "template: page.html",
        "---",
        *content,
    ]


def step4():
    """
    Parse markdown files contents
    """

    print_step("PARSING MARKDOWN FILES")
    md_files = list(NOTES_DIR.glob("**/*.md"))
    for md_file in md_files:
        if str(md_file).endswith("_index.md"):
            continue

        content = [line.rstrip() for line in open(
            md_file, "r", encoding="utf-8").readlines()]
        content = remove_frontmatters(content)
        content = fix_links(md_file, content)
        content = remove_obsidian_comments(content)
        content = fix_katex_issues(md_file, content)
        content = write_frontmatters(md_file, content)

        if str(md_file).endswith("📇 Index.md"):
            p = Path(md_file)
            renamed_file = Path(p.parent, f"_index{p.suffix}")
            p.rename(renamed_file)
            md_file = renamed_file
            content.remove("template: page.html")

        open(md_file, "w", encoding="utf-8").write("\n".join(content))


if __name__ == "__main__":
    step1()
    step2()
    step3()
    step4()
