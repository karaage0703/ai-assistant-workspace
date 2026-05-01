#!/usr/bin/env python3
"""
Notion Manager - Search, read, create pages, upload files
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional
import requests

# Configuration
CONFIG_DIR = Path.home() / ".config" / "notion"
API_KEY_FILE = CONFIG_DIR / "api_key"
NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"


def get_api_key() -> str:
    """Get Notion API key from config file."""
    if not API_KEY_FILE.exists():
        raise FileNotFoundError(
            f"Notion API key not found. Please create {API_KEY_FILE} with your API key.\n"
            "Get your key at: https://notion.so/my-integrations"
        )
    return API_KEY_FILE.read_text().strip()


def get_headers() -> dict:
    """Get headers for Notion API requests."""
    return {
        "Authorization": f"Bearer {get_api_key()}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def search(query: str, filter_type: Optional[str] = None) -> dict:
    """Search for pages and databases in Notion."""
    payload = {"query": query}
    if filter_type:
        payload["filter"] = {"property": "object", "value": filter_type}
    
    response = requests.post(
        f"{BASE_URL}/search",
        headers=get_headers(),
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def get_page(page_id: str) -> dict:
    """Get page metadata."""
    response = requests.get(
        f"{BASE_URL}/pages/{page_id}",
        headers=get_headers(),
    )
    response.raise_for_status()
    return response.json()


def get_page_content(page_id: str) -> dict:
    """Get page content (blocks)."""
    response = requests.get(
        f"{BASE_URL}/blocks/{page_id}/children",
        headers=get_headers(),
    )
    response.raise_for_status()
    return response.json()


def blocks_to_text(blocks: list) -> str:
    """Convert blocks to readable text."""
    lines = []
    for block in blocks:
        block_type = block.get("type")
        if block_type in ["paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item"]:
            rich_text = block.get(block_type, {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            if block_type == "heading_1":
                lines.append(f"# {text}")
            elif block_type == "heading_2":
                lines.append(f"## {text}")
            elif block_type == "heading_3":
                lines.append(f"### {text}")
            elif block_type == "bulleted_list_item":
                lines.append(f"- {text}")
            elif block_type == "numbered_list_item":
                lines.append(f"1. {text}")
            else:
                lines.append(text)
        elif block_type == "image":
            image = block.get("image", {})
            if image.get("type") == "external":
                url = image.get("external", {}).get("url", "")
            else:
                url = image.get("file", {}).get("url", "")
            lines.append(f"![image]({url})")
        elif block_type == "code":
            code = block.get("code", {})
            lang = code.get("language", "")
            text = "".join([t.get("plain_text", "") for t in code.get("rich_text", [])])
            lines.append(f"```{lang}\n{text}\n```")
    return "\n".join(lines)


def get_existing_image_names(page_id: str) -> set:
    """Get existing image file names (UUID part) from a page."""
    try:
        content = get_page_content(page_id)
        names = set()
        for block in content.get("results", []):
            if block.get("type") == "image":
                image = block.get("image", {})
                url = ""
                if image.get("type") == "external":
                    url = image.get("external", {}).get("url", "")
                else:
                    url = image.get("file", {}).get("url", "")
                if url and "/" in url:
                    # Extract filename from URL (last part before query string)
                    # Example: .../6e8e7564-d7cc-.../f0bb11df-f258-...jpg?...
                    filename = url.split("/")[-1].split("?")[0]
                    names.add(filename)
        return names
    except Exception:
        return set()


def extract_image_uuid(file_path: str) -> Optional[str]:
    """Extract UUID from downloaded image filename if present."""
    # Check if filename contains UUID pattern (e.g., f0bb11df-f258-4737-8a46-7fb465d7bb03.jpg)
    import re
    name = Path(file_path).name
    # UUID pattern: 8-4-4-4-12 hex characters
    uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    match = re.search(uuid_pattern, name, re.IGNORECASE)
    if match:
        return match.group(0)
    return None


def is_duplicate_image(page_id: str, file_path: str) -> bool:
    """Check if the image already exists on the page."""
    existing_names = get_existing_image_names(page_id)
    if not existing_names:
        return False
    
    # Check by UUID in filename
    file_uuid = extract_image_uuid(file_path)
    if file_uuid:
        for name in existing_names:
            if file_uuid in name:
                return True
    
    # Check by exact filename match
    filename = Path(file_path).name
    for name in existing_names:
        if filename in name or name in filename:
            return True
    
    return False


def create_page(
    parent_id: str,
    title: str,
    content: str = "",
    is_database: bool = False,
    date: Optional[str] = None,  # YYYY-MM-DD形式
) -> dict:
    """Create a new page."""
    if is_database:
        parent = {"database_id": parent_id}
        properties = {
            "名前": {"title": [{"text": {"content": title}}]}
        }
        # 日付プロパティを追加（DBの場合のみ）
        if date:
            properties["日付"] = {"date": {"start": date}}
    else:
        parent = {"page_id": parent_id}
        properties = {
            "title": {"title": [{"text": {"content": title}}]}
        }
    
    payload = {
        "parent": parent,
        "properties": properties,
    }
    
    # Add content blocks if provided
    if content:
        payload["children"] = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"text": {"content": content}}]
                }
            }
        ]
    
    response = requests.post(
        f"{BASE_URL}/pages",
        headers=get_headers(),
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def upload_file(file_path: str) -> dict:
    """Upload a file to Notion and return the file_upload object."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    # Step 1: Create file upload object
    response = requests.post(
        f"{BASE_URL}/file_uploads",
        headers=get_headers(),
    )
    response.raise_for_status()
    upload_obj = response.json()
    file_upload_id = upload_obj["id"]
    
    # Step 2: Upload file content
    # Determine content type
    suffix = path.suffix.lower()
    content_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
    }
    content_type = content_types.get(suffix, "application/octet-stream")
    
    with open(path, "rb") as f:
        headers = {
            "Authorization": f"Bearer {get_api_key()}",
            "Notion-Version": NOTION_VERSION,
        }
        files = {"file": (path.name, f, content_type)}
        response = requests.post(
            f"{BASE_URL}/file_uploads/{file_upload_id}/send",
            headers=headers,
            files=files,
        )
    response.raise_for_status()
    return response.json()


def add_image_block(page_id: str, file_upload_id: str, caption: str = "") -> dict:
    """Add an image block to a page using uploaded file."""
    payload = {
        "children": [
            {
                "object": "block",
                "type": "image",
                "image": {
                    "type": "file_upload",
                    "file_upload": {"id": file_upload_id},
                    "caption": [{"text": {"content": caption}}] if caption else []
                }
            }
        ]
    }
    
    response = requests.patch(
        f"{BASE_URL}/blocks/{page_id}/children",
        headers=get_headers(),
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def add_video_block(page_id: str, file_upload_id: str, caption: str = "") -> dict:
    """Add a video block to a page using uploaded file."""
    payload = {
        "children": [
            {
                "object": "block",
                "type": "video",
                "video": {
                    "type": "file_upload",
                    "file_upload": {"id": file_upload_id},
                    "caption": [{"text": {"content": caption}}] if caption else []
                }
            }
        ]
    }
    
    response = requests.patch(
        f"{BASE_URL}/blocks/{page_id}/children",
        headers=get_headers(),
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def add_file_block(page_id: str, file_upload_id: str, caption: str = "") -> dict:
    """Add a file block to a page using uploaded file."""
    payload = {
        "children": [
            {
                "object": "block",
                "type": "file",
                "file": {
                    "type": "file_upload",
                    "file_upload": {"id": file_upload_id},
                    "caption": [{"text": {"content": caption}}] if caption else []
                }
            }
        ]
    }
    
    response = requests.patch(
        f"{BASE_URL}/blocks/{page_id}/children",
        headers=get_headers(),
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def add_text_block(page_id: str, text: str) -> dict:
    """Add a text block to a page."""
    payload = {
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"text": {"content": text}}]
                }
            }
        ]
    }
    
    response = requests.patch(
        f"{BASE_URL}/blocks/{page_id}/children",
        headers=get_headers(),
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def add_heading_block(page_id: str, text: str, level: int = 2) -> dict:
    """Add a heading block to a page."""
    heading_type = f"heading_{level}"
    payload = {
        "children": [
            {
                "object": "block",
                "type": heading_type,
                heading_type: {
                    "rich_text": [{"text": {"content": text}}]
                }
            }
        ]
    }
    
    response = requests.patch(
        f"{BASE_URL}/blocks/{page_id}/children",
        headers=get_headers(),
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def add_bullet_block(page_id: str, text: str, link: Optional[str] = None) -> dict:
    """Add a bulleted list item to a page. Optionally make it a clickable link."""
    if link:
        rich_text = [{"text": {"content": text, "link": {"url": link}}}]
    else:
        rich_text = [{"text": {"content": text}}]
    
    payload = {
        "children": [
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": rich_text
                }
            }
        ]
    }
    
    response = requests.patch(
        f"{BASE_URL}/blocks/{page_id}/children",
        headers=get_headers(),
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def append_blocks(page_id: str, blocks: list) -> dict:
    """Append multiple blocks to a page."""
    payload = {"children": blocks}

    response = requests.patch(
        f"{BASE_URL}/blocks/{page_id}/children",
        headers=get_headers(),
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def get_block(block_id: str) -> dict:
    """Get a single block."""
    response = requests.get(
        f"{BASE_URL}/blocks/{block_id}",
        headers=get_headers(),
    )
    response.raise_for_status()
    return response.json()


def update_block(
    block_id: str,
    text: Optional[str] = None,
    link: Optional[str] = None,
    checked: Optional[bool] = None,
) -> dict:
    """Update an existing block (same-type only).

    Notion API only allows updating fields within the existing block type.
    Changing block type (e.g. paragraph -> heading_2) is not supported by the API.
    """
    current = get_block(block_id)
    block_type = current.get("type")

    supported = {
        "paragraph", "heading_1", "heading_2", "heading_3",
        "bulleted_list_item", "numbered_list_item", "to_do", "quote", "code",
    }
    if block_type not in supported:
        raise ValueError(
            f"Unsupported block type for update: {block_type}. "
            f"Supported: {sorted(supported)}"
        )

    if text is None and checked is None:
        raise ValueError("Specify at least one of: text, checked")

    body: dict = {block_type: {}}

    if text is not None:
        if link:
            rich_text = [{"text": {"content": text, "link": {"url": link}}}]
        else:
            rich_text = [{"text": {"content": text}}]
        body[block_type]["rich_text"] = rich_text

    if checked is not None and block_type == "to_do":
        body[block_type]["checked"] = checked

    response = requests.patch(
        f"{BASE_URL}/blocks/{block_id}",
        headers=get_headers(),
        json=body,
    )
    response.raise_for_status()
    return response.json()


def delete_block(block_id: str) -> dict:
    """Delete (archive) a block."""
    response = requests.delete(
        f"{BASE_URL}/blocks/{block_id}",
        headers=get_headers(),
    )
    response.raise_for_status()
    return response.json()


def convert_block_type(
    block_id: str,
    new_type: str,
    text: Optional[str] = None,
    link: Optional[str] = None,
) -> dict:
    """Replace a block with a new one of a different type at the same position.

    Notion API does not allow PATCH to change block type, so this:
      1. Reads the existing block (for parent ID and current text if needed)
      2. Inserts a new block of `new_type` immediately after the existing one
         using `position: { type: "after_block", after_block: { id } }`
      3. Deletes (archives) the original block

    The new block ends up where the old one was. Returns the new block.
    """
    supported = {
        "paragraph", "heading_1", "heading_2", "heading_3",
        "bulleted_list_item", "numbered_list_item", "to_do", "quote",
    }
    if new_type not in supported:
        raise ValueError(
            f"Unsupported new block type: {new_type}. "
            f"Supported: {sorted(supported)}"
        )

    current = get_block(block_id)
    parent = current.get("parent", {})
    parent_type = parent.get("type")
    parent_id = parent.get(parent_type) if parent_type else None
    if not parent_id:
        raise ValueError(f"Could not determine parent of block {block_id}")

    if text is None:
        old_type = current.get("type")
        rich_text = current.get(old_type, {}).get("rich_text", [])
        text = "".join([t.get("plain_text", "") for t in rich_text])

    if link:
        new_rich = [{"text": {"content": text, "link": {"url": link}}}]
    else:
        new_rich = [{"text": {"content": text}}]

    new_block = {
        "object": "block",
        "type": new_type,
        new_type: {"rich_text": new_rich},
    }

    payload = {
        "children": [new_block],
        "after": block_id,
    }

    response = requests.patch(
        f"{BASE_URL}/blocks/{parent_id}/children",
        headers=get_headers(),
        json=payload,
    )
    if response.status_code >= 400:
        payload = {
            "children": [new_block],
            "position": {"type": "after_block", "after_block": {"id": block_id}},
        }
        response = requests.patch(
            f"{BASE_URL}/blocks/{parent_id}/children",
            headers=get_headers(),
            json=payload,
        )
    response.raise_for_status()
    inserted = response.json()

    delete_block(block_id)

    return inserted


def blocks_to_text_with_ids(blocks: list) -> str:
    """Convert blocks to readable text with their block IDs (for editing)."""
    lines = []
    for block in blocks:
        block_type = block.get("type")
        block_id = block.get("id", "")
        short_id = block_id.replace("-", "")[:8] if block_id else ""

        text = ""
        prefix = ""
        if block_type in ["paragraph", "heading_1", "heading_2", "heading_3",
                          "bulleted_list_item", "numbered_list_item", "to_do", "quote"]:
            rich_text = block.get(block_type, {}).get("rich_text", [])
            text = "".join([t.get("plain_text", "") for t in rich_text])
            if block_type == "heading_1":
                prefix = "# "
            elif block_type == "heading_2":
                prefix = "## "
            elif block_type == "heading_3":
                prefix = "### "
            elif block_type == "bulleted_list_item":
                prefix = "- "
            elif block_type == "numbered_list_item":
                prefix = "1. "
            elif block_type == "to_do":
                checked = block.get("to_do", {}).get("checked", False)
                prefix = "- [x] " if checked else "- [ ] "
            elif block_type == "quote":
                prefix = "> "
        elif block_type == "image":
            image = block.get("image", {})
            if image.get("type") == "external":
                url = image.get("external", {}).get("url", "")
            else:
                url = image.get("file", {}).get("url", "")
            text = f"![image]({url})"
        elif block_type == "code":
            code = block.get("code", {})
            lang = code.get("language", "")
            text = "".join([t.get("plain_text", "") for t in code.get("rich_text", [])])
            text = f"```{lang} {text[:60]}```"
        else:
            text = f"[{block_type}]"

        lines.append(f"[{short_id}] [{block_type}] {prefix}{text}")
        lines.append(f"   id: {block_id}")
    return "\n".join(lines) if lines else "(empty page)"


def create_diary_entry(
    parent_id: str,
    title: Optional[str] = None,
    content: str = "",
    images: list[str] = None,
    force: bool = False,
    is_database: bool = True,  # デフォルトでDB内に作成
    date: Optional[str] = None,  # 日付プロパティ用
) -> dict:
    """Create a diary entry with optional images.
    
    Title format: YYYYMMDD_タイトル
    Example: 20260206_東京出張
    """
    if title is None:
        title = datetime.now().strftime("%Y%m%d_日記")
    elif not (len(title) > 8 and title[:8].isdigit() and title[8] == "_"):
        # タイトルが指定されたがYYYYMMDD_パターンでない場合、プレフィックスを追加
        date_prefix = (date or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
        title = f"{date_prefix}_{title}"
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    # Create the page
    page = create_page(parent_id, title, content, is_database=is_database, date=date)
    page_id = page["id"]
    
    # Upload and attach images
    if images:
        for img_path in images:
            try:
                # Check for duplicate (skip if already exists)
                if not force and is_duplicate_image(page_id, img_path):
                    print(f"  ⏭️ Skipped (duplicate): {img_path}")
                    continue
                
                upload_result = upload_file(img_path)
                file_upload_id = upload_result["id"]
                add_image_block(page_id, file_upload_id, caption=Path(img_path).name)
                print(f"  ✅ Added image: {img_path}")
            except Exception as e:
                print(f"  ❌ Failed to add image {img_path}: {e}")
    
    return page


def format_search_results(results: dict) -> str:
    """Format search results for display."""
    lines = []
    for item in results.get("results", []):
        obj_type = item.get("object")
        item_id = item.get("id")
        
        if obj_type == "page":
            props = item.get("properties", {})
            # Try different title property names
            title = ""
            for key in ["title", "Name", "名前"]:
                if key in props:
                    title_arr = props[key].get("title", [])
                    if title_arr:
                        title = title_arr[0].get("plain_text", "")
                    break
            lines.append(f"📄 {title or '(Untitled)'}")
            lines.append(f"   ID: {item_id}")
        elif obj_type == "database":
            title_arr = item.get("title", [])
            title = title_arr[0].get("plain_text", "") if title_arr else "(Untitled DB)"
            lines.append(f"🗃️ {title}")
            lines.append(f"   ID: {item_id}")
    
    return "\n".join(lines) if lines else "No results found."


def main():
    parser = argparse.ArgumentParser(description="Notion Manager")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # search command
    search_parser = subparsers.add_parser("search", help="Search Notion")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-t", "--type", choices=["page", "database"], help="Filter by type")
    search_parser.add_argument("--json", action="store_true", help="Output raw JSON")
    
    # read command
    read_parser = subparsers.add_parser("read", help="Read a page")
    read_parser.add_argument("page_id", help="Page ID")
    read_parser.add_argument("--json", action="store_true", help="Output raw JSON")
    read_parser.add_argument("--with-ids", action="store_true", help="Show block IDs (for editing individual blocks)")
    
    # create command
    create_parser = subparsers.add_parser("create", help="Create a page")
    create_parser.add_argument("parent_id", help="Parent page/database ID")
    create_parser.add_argument("title", help="Page title")
    create_parser.add_argument("-c", "--content", default="", help="Page content")
    create_parser.add_argument("--database", action="store_true", help="Parent is a database")
    
    # upload command
    upload_parser = subparsers.add_parser("upload", help="Upload a file to a page")
    upload_parser.add_argument("file", help="File path")
    upload_parser.add_argument("page_id", help="Page ID to attach to")
    upload_parser.add_argument("-c", "--caption", default="", help="Caption")
    upload_parser.add_argument("--as-file", action="store_true", help="Add as file block (not image)")
    upload_parser.add_argument("-f", "--force", action="store_true", help="Force upload even if duplicate")
    
    # diary command
    diary_parser = subparsers.add_parser("diary", help="Create a diary entry")
    diary_parser.add_argument("parent_id", help="Database ID for diary (use --page for page)")
    diary_parser.add_argument("-t", "--title", help="Diary title (default: YYYY-MM-DD 日記)")
    diary_parser.add_argument("-c", "--content", default="", help="Diary content")
    diary_parser.add_argument("-i", "--images", nargs="+", help="Image files to attach")
    diary_parser.add_argument("-f", "--force", action="store_true", help="Force upload even if duplicate")
    diary_parser.add_argument("-d", "--date", help="Date for diary (YYYY-MM-DD, default: today)")
    diary_parser.add_argument("--page", action="store_true", help="Create under page instead of database")
    
    # append command
    append_parser = subparsers.add_parser("append", help="Append content to a page")
    append_parser.add_argument("page_id", help="Page ID")
    append_parser.add_argument("-t", "--text", help="Text to append (paragraph)")
    append_parser.add_argument("-H", "--heading", help="Heading text")
    append_parser.add_argument("-l", "--level", type=int, default=2, choices=[1, 2, 3], help="Heading level (1-3)")
    append_parser.add_argument("-b", "--bullet", help="Bullet item text")
    append_parser.add_argument("--link", help="URL to make bullet text clickable")
    append_parser.add_argument("--bullets", nargs="+", help="Multiple bullet items")

    # get-block command
    get_block_parser = subparsers.add_parser("get-block", help="Get a single block")
    get_block_parser.add_argument("block_id", help="Block ID")
    get_block_parser.add_argument("--json", action="store_true", help="Output raw JSON")

    # update command
    # Same-type edits go through PATCH /blocks/{id}.
    # Type changes are simulated via insert-after + delete (Notion API does not allow type change via PATCH).
    update_parser = subparsers.add_parser("update", help="Update a block (text, or change type via replace)")
    update_parser.add_argument("block_id", help="Block ID to update")
    update_parser.add_argument("-t", "--text", help="New text content")
    update_parser.add_argument("--link", help="URL to make text clickable")
    update_parser.add_argument("--checked", dest="checked", action="store_true", help="Mark to_do as checked")
    update_parser.add_argument("--unchecked", dest="unchecked", action="store_true", help="Mark to_do as unchecked")
    update_parser.add_argument(
        "--type",
        dest="new_type",
        choices=[
            "paragraph", "heading_1", "heading_2", "heading_3",
            "bulleted_list_item", "numbered_list_item", "to_do", "quote",
        ],
        help="Change block type (replaces the block at the same position)",
    )
    update_parser.add_argument("-l", "--level", type=int, choices=[1, 2, 3], help="Heading level shortcut for --type")

    # delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a block")
    delete_parser.add_argument("block_id", help="Block ID to delete")
    delete_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    args = parser.parse_args()
    
    try:
        if args.command == "search":
            results = search(args.query, args.type)
            if args.json:
                print(json.dumps(results, indent=2, ensure_ascii=False))
            else:
                print(format_search_results(results))
        
        elif args.command == "read":
            content = get_page_content(args.page_id)
            if args.json:
                print(json.dumps(content, indent=2, ensure_ascii=False))
            elif getattr(args, "with_ids", False):
                text = blocks_to_text_with_ids(content.get("results", []))
                print(text)
            else:
                text = blocks_to_text(content.get("results", []))
                print(text)
        
        elif args.command == "create":
            page = create_page(args.parent_id, args.title, args.content, args.database)
            print(f"✅ Created page: {page['id']}")
            print(f"   URL: {page.get('url', 'N/A')}")
        
        elif args.command == "upload":
            # Check for duplicate (images only)
            suffix = Path(args.file).suffix.lower()
            is_image = suffix in [".jpg", ".jpeg", ".png", ".gif", ".webp"]
            
            if is_image and not args.force and is_duplicate_image(args.page_id, args.file):
                print(f"⏭️ Skipped (duplicate): {args.file}")
                print("   Use --force to upload anyway")
                sys.exit(0)
            
            # Upload file
            print(f"📤 Uploading {args.file}...")
            upload_result = upload_file(args.file)
            file_upload_id = upload_result["id"]
            print(f"   File upload ID: {file_upload_id}")
            
            # Attach to page
            print(f"📎 Attaching to page {args.page_id}...")
            if args.as_file:
                add_file_block(args.page_id, file_upload_id, args.caption)
            else:
                # Check file type
                if is_image:
                    add_image_block(args.page_id, file_upload_id, args.caption)
                elif suffix in [".mp4", ".mov", ".webm", ".avi", ".mkv"]:
                    add_video_block(args.page_id, file_upload_id, args.caption)
                else:
                    add_file_block(args.page_id, file_upload_id, args.caption)
            print("✅ Done!")
        
        elif args.command == "diary":
            is_database = not getattr(args, 'page', False)
            print(f"📝 Creating diary entry in {'database' if is_database else 'page'}...")
            page = create_diary_entry(
                args.parent_id,
                args.title,
                args.content,
                args.images,
                getattr(args, 'force', False),
                is_database=is_database,
                date=getattr(args, 'date', None),
            )
            print(f"✅ Created diary: {page['id']}")
            print(f"   URL: {page.get('url', 'N/A')}")
        
        elif args.command == "append":
            added = []
            
            # Add heading if specified
            if args.heading:
                add_heading_block(args.page_id, args.heading, args.level)
                added.append(f"Heading {args.level}: {args.heading}")
            
            # Add text paragraph if specified
            if args.text:
                add_text_block(args.page_id, args.text)
                added.append(f"Text: {args.text[:50]}...")
            
            # Add single bullet if specified
            if args.bullet:
                link = getattr(args, 'link', None)
                add_bullet_block(args.page_id, args.bullet, link=link)
                if link:
                    added.append(f"Bullet (link): {args.bullet}")
                else:
                    added.append(f"Bullet: {args.bullet}")
            
            # Add multiple bullets if specified
            if args.bullets:
                blocks = [
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [{"text": {"content": b}}]
                        }
                    }
                    for b in args.bullets
                ]
                append_blocks(args.page_id, blocks)
                added.append(f"Bullets: {len(args.bullets)} items")
            
            if added:
                print(f"✅ Appended to page {args.page_id}:")
                for item in added:
                    print(f"   - {item}")
            else:
                print("❌ No content specified. Use -t, -H, -b, or --bullets")

        elif args.command == "get-block":
            block = get_block(args.block_id)
            if args.json:
                print(json.dumps(block, indent=2, ensure_ascii=False))
            else:
                print(blocks_to_text_with_ids([block]))

        elif args.command == "update":
            checked = None
            if args.checked:
                checked = True
            elif args.unchecked:
                checked = False

            new_type = args.new_type
            if args.level is not None:
                new_type = f"heading_{args.level}"

            if new_type is not None:
                result = convert_block_type(
                    args.block_id,
                    new_type=new_type,
                    text=args.text,
                    link=args.link,
                )
                inserted = result.get("results", [{}])[0]
                print(f"✅ Replaced block {args.block_id} with {new_type}")
                print(f"   new id: {inserted.get('id')}")
            else:
                if args.text is None and checked is None:
                    print("❌ Specify -t/--text, --checked/--unchecked, or --type/-l")
                    sys.exit(1)
                result = update_block(
                    args.block_id,
                    text=args.text,
                    link=args.link,
                    checked=checked,
                )
                print(f"✅ Updated block {args.block_id}")
                print(f"   type: {result.get('type')}")

        elif args.command == "delete":
            if not args.yes:
                print(f"⚠️  About to delete block {args.block_id}")
                print("    Use -y/--yes to confirm")
                sys.exit(1)
            result = delete_block(args.block_id)
            print(f"✅ Deleted block {args.block_id} (archived: {result.get('archived')})")

        else:
            parser.print_help()
    
    except requests.exceptions.HTTPError as e:
        print(f"❌ API Error: {e}")
        if e.response is not None:
            print(f"   {e.response.text}")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
