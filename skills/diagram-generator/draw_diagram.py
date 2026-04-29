#!/usr/bin/env python3
"""
ローカル図表生成スクリプト (Pillow)
API不要、ローカルで PNG 画像を生成

使用例:
  python draw_diagram.py architecture --output /tmp/arch.png --data '{"title": "システム構成", "boxes": [...]}'
  python draw_diagram.py flowchart --output /tmp/flow.png --data '{"steps": [...]}'
"""

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow")
    sys.exit(1)


# ─── フォント設定 ─────────────────────────────────────────────────────

def get_font(size: int) -> ImageFont.FreeTypeFont:
    """日本語対応フォントを取得"""
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ─── 色定義 ────────────────────────────────────────────────────────────

COLORS = {
    "blue": {"fill": "#e1f5fe", "stroke": "#01579b", "text": "#01579b"},
    "orange": {"fill": "#fff3e0", "stroke": "#e65100", "text": "#e65100"},
    "purple": {"fill": "#f3e5f5", "stroke": "#7b1fa2", "text": "#7b1fa2"},
    "green": {"fill": "#e8f5e9", "stroke": "#2e7d32", "text": "#2e7d32"},
    "red": {"fill": "#ffebee", "stroke": "#c62828", "text": "#c62828"},
    "gray": {"fill": "#f5f5f5", "stroke": "#616161", "text": "#616161"},
    "teal": {"fill": "#e0f2f1", "stroke": "#00695c", "text": "#00695c"},
}


# ─── 描画ヘルパー ──────────────────────────────────────────────────────

def draw_box(draw: ImageDraw, x: int, y: int, w: int, h: int, 
             color: str, text: str, font_large, font_small, subtext: str = None):
    """角丸ボックスを描画"""
    c = COLORS.get(color, COLORS["gray"])
    
    # 角丸の半径
    r = 8
    
    # 角丸四角形（Pillow 9.2.0+ では rounded_rectangle が使える）
    try:
        draw.rounded_rectangle([x, y, x+w, y+h], radius=r, fill=c["fill"], outline=c["stroke"], width=2)
    except AttributeError:
        # 古いバージョンのPillow用フォールバック
        draw.rectangle([x, y, x+w, y+h], fill=c["fill"], outline=c["stroke"], width=2)
    
    # テキスト
    text_y = y + h//3 if subtext else y + h//2
    draw.text((x + w//2, text_y), text, fill=c["text"], font=font_large, anchor="mm")
    
    if subtext:
        draw.text((x + w//2, y + h*2//3), subtext, fill="#666666", font=font_small, anchor="mm")


def draw_arrow(draw: ImageDraw, start: tuple, end: tuple, color: str = "#666666", 
               label: str = None, font = None):
    """矢印を描画"""
    x1, y1 = start
    x2, y2 = end
    
    # 線
    draw.line([start, end], fill=color, width=2)
    
    # 矢印の頭
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    arrow_len = 12
    arrow_angle = math.pi / 6
    
    p1 = (x2 - arrow_len * math.cos(angle - arrow_angle),
          y2 - arrow_len * math.sin(angle - arrow_angle))
    p2 = (x2 - arrow_len * math.cos(angle + arrow_angle),
          y2 - arrow_len * math.sin(angle + arrow_angle))
    
    draw.polygon([(x2, y2), p1, p2], fill=color)
    
    # ラベル
    if label and font:
        mid_x = (x1 + x2) // 2
        mid_y = (y1 + y2) // 2
        draw.text((mid_x, mid_y - 15), label, fill=color, font=font, anchor="mm")


# ─── アーキテクチャ図 ──────────────────────────────────────────────────

def draw_architecture(data: dict, output: str):
    """
    アーキテクチャ図を生成
    
    data format:
    {
        "title": "図のタイトル",
        "subtitle": "サブタイトル（オプション）",
        "boxes": [
            {"id": "box1", "label": "ラベル", "sublabel": "サブ", "color": "blue", "row": 0, "col": 0},
            ...
        ],
        "arrows": [
            {"from": "box1", "to": "box2", "label": "ラベル"},
            ...
        ]
    }
    """
    # キャンバスサイズ計算
    boxes = data.get("boxes", [])
    max_row = max((b.get("row", 0) for b in boxes), default=0)
    max_col = max((b.get("col", 0) for b in boxes), default=0)
    
    box_w, box_h = 200, 100
    margin_x, margin_y = 100, 80
    padding = 50
    
    width = (max_col + 1) * (box_w + margin_x) + padding * 2
    height = (max_row + 1) * (box_h + margin_y) + padding * 2 + 100  # タイトル用
    
    width = max(width, 800)
    height = max(height, 500)
    
    img = Image.new('RGB', (width, height), '#ffffff')
    draw = ImageDraw.Draw(img)
    
    font_large = get_font(20)
    font_med = get_font(16)
    font_small = get_font(14)
    font_title = get_font(24)
    
    # ボックス位置を計算
    box_positions = {}
    for box in boxes:
        col = box.get("col", 0)
        row = box.get("row", 0)
        x = padding + col * (box_w + margin_x)
        y = padding + row * (box_h + margin_y)
        box_positions[box["id"]] = {"x": x, "y": y, "w": box_w, "h": box_h}
        
        draw_box(draw, x, y, box_w, box_h,
                 box.get("color", "gray"),
                 box.get("label", ""),
                 font_med, font_small,
                 box.get("sublabel"))
    
    # 矢印描画
    for arrow in data.get("arrows", []):
        from_box = box_positions.get(arrow["from"])
        to_box = box_positions.get(arrow["to"])
        if from_box and to_box:
            # 中心点を計算
            start = (from_box["x"] + from_box["w"]//2, from_box["y"] + from_box["h"])
            end = (to_box["x"] + to_box["w"]//2, to_box["y"])
            
            # 方向によって調整
            if from_box["y"] > to_box["y"]:
                start = (from_box["x"] + from_box["w"]//2, from_box["y"])
                end = (to_box["x"] + to_box["w"]//2, to_box["y"] + to_box["h"])
            elif from_box["x"] < to_box["x"] and abs(from_box["y"] - to_box["y"]) < box_h:
                start = (from_box["x"] + from_box["w"], from_box["y"] + from_box["h"]//2)
                end = (to_box["x"], to_box["y"] + to_box["h"]//2)
            elif from_box["x"] > to_box["x"] and abs(from_box["y"] - to_box["y"]) < box_h:
                start = (from_box["x"], from_box["y"] + from_box["h"]//2)
                end = (to_box["x"] + to_box["w"], to_box["y"] + to_box["h"]//2)
            
            draw_arrow(draw, start, end, "#666666", arrow.get("label"), font_small)
    
    # タイトル
    if data.get("title"):
        draw.text((width//2, height - 60), data["title"], fill="#333333", font=font_title, anchor="mm")
    if data.get("subtitle"):
        draw.text((width//2, height - 30), data["subtitle"], fill="#666666", font=font_med, anchor="mm")
    
    img.save(output)
    print(f"Saved: {output}")


# ─── フローチャート ────────────────────────────────────────────────────

def draw_flowchart(data: dict, output: str):
    """
    フローチャートを生成
    
    data format:
    {
        "title": "タイトル",
        "steps": [
            {"id": "s1", "label": "開始", "type": "start"},
            {"id": "s2", "label": "処理1", "type": "process"},
            {"id": "s3", "label": "条件?", "type": "decision"},
            {"id": "s4", "label": "終了", "type": "end"},
        ],
        "connections": [
            {"from": "s1", "to": "s2"},
            {"from": "s2", "to": "s3"},
            {"from": "s3", "to": "s4", "label": "Yes"},
        ]
    }
    """
    steps = data.get("steps", [])
    
    box_w, box_h = 180, 60
    margin_y = 40
    padding = 50
    
    width = 600
    height = len(steps) * (box_h + margin_y) + padding * 2 + 80
    
    img = Image.new('RGB', (width, height), '#ffffff')
    draw = ImageDraw.Draw(img)
    
    font_med = get_font(16)
    font_small = get_font(14)
    font_title = get_font(22)
    
    # ステップ位置
    step_positions = {}
    center_x = width // 2
    
    for i, step in enumerate(steps):
        x = center_x - box_w // 2
        y = padding + i * (box_h + margin_y)
        step_positions[step["id"]] = {"x": x, "y": y, "w": box_w, "h": box_h}
        
        step_type = step.get("type", "process")
        color = {
            "start": "green",
            "end": "red",
            "decision": "orange",
            "process": "blue",
        }.get(step_type, "gray")
        
        draw_box(draw, x, y, box_w, box_h, color, step.get("label", ""), font_med, font_small)
    
    # 接続線
    for conn in data.get("connections", []):
        from_step = step_positions.get(conn["from"])
        to_step = step_positions.get(conn["to"])
        if from_step and to_step:
            start = (from_step["x"] + from_step["w"]//2, from_step["y"] + from_step["h"])
            end = (to_step["x"] + to_step["w"]//2, to_step["y"])
            draw_arrow(draw, start, end, "#666666", conn.get("label"), font_small)
    
    # タイトル
    if data.get("title"):
        draw.text((width//2, height - 40), data["title"], fill="#333333", font=font_title, anchor="mm")
    
    img.save(output)
    print(f"Saved: {output}")


# ─── 階層図 ────────────────────────────────────────────────────────────

def draw_hierarchy(data: dict, output: str):
    """
    階層図（組織図など）を生成
    
    data format:
    {
        "title": "タイトル",
        "root": {
            "label": "トップ",
            "color": "purple",
            "children": [
                {"label": "子1", "color": "blue", "children": [...]},
                {"label": "子2", "color": "green"},
            ]
        }
    }
    """
    def count_leaves(node):
        children = node.get("children", [])
        if not children:
            return 1
        return sum(count_leaves(c) for c in children)
    
    def get_depth(node, d=0):
        children = node.get("children", [])
        if not children:
            return d
        return max(get_depth(c, d+1) for c in children)
    
    root = data.get("root", {})
    leaves = count_leaves(root)
    depth = get_depth(root) + 1
    
    box_w, box_h = 150, 50
    margin_x, margin_y = 30, 60
    padding = 50
    
    width = leaves * (box_w + margin_x) + padding * 2
    height = depth * (box_h + margin_y) + padding * 2 + 60
    
    width = max(width, 600)
    
    img = Image.new('RGB', (width, height), '#ffffff')
    draw = ImageDraw.Draw(img)
    
    font_med = get_font(16)
    font_small = get_font(12)
    font_title = get_font(22)
    
    def draw_node(node, x, y, available_width):
        # ボックスを描画
        bx = x + (available_width - box_w) // 2
        draw_box(draw, bx, y, box_w, box_h, 
                 node.get("color", "gray"), node.get("label", ""), font_med, font_small)
        
        children = node.get("children", [])
        if not children:
            return
        
        # 子ノードの幅を計算
        child_widths = [count_leaves(c) * (box_w + margin_x) for c in children]
        total_child_width = sum(child_widths)
        
        # 子ノードを描画
        child_x = x + (available_width - total_child_width) // 2
        for i, child in enumerate(children):
            child_center = child_x + child_widths[i] // 2
            
            # 接続線
            parent_center = bx + box_w // 2
            draw.line([(parent_center, y + box_h), (parent_center, y + box_h + margin_y//2)], fill="#666666", width=2)
            draw.line([(parent_center, y + box_h + margin_y//2), (child_center, y + box_h + margin_y//2)], fill="#666666", width=2)
            draw.line([(child_center, y + box_h + margin_y//2), (child_center, y + box_h + margin_y)], fill="#666666", width=2)
            
            draw_node(child, child_x, y + box_h + margin_y, child_widths[i])
            child_x += child_widths[i]
    
    draw_node(root, padding, padding, width - padding * 2)
    
    # タイトル
    if data.get("title"):
        draw.text((width//2, height - 30), data["title"], fill="#333333", font=font_title, anchor="mm")
    
    img.save(output)
    print(f"Saved: {output}")


# ─── メイン ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ローカル図表生成")
    parser.add_argument("type", choices=["architecture", "flowchart", "hierarchy"],
                        help="図の種類")
    parser.add_argument("--output", "-o", required=True, help="出力ファイルパス")
    parser.add_argument("--data", "-d", help="JSON データ（文字列）")
    parser.add_argument("--file", "-f", help="JSON データファイル")
    
    args = parser.parse_args()
    
    # データ読み込み
    if args.file:
        with open(args.file) as f:
            data = json.load(f)
    elif args.data:
        data = json.loads(args.data)
    else:
        # 標準入力から
        data = json.load(sys.stdin)
    
    # 描画
    if args.type == "architecture":
        draw_architecture(data, args.output)
    elif args.type == "flowchart":
        draw_flowchart(data, args.output)
    elif args.type == "hierarchy":
        draw_hierarchy(data, args.output)


if __name__ == "__main__":
    main()
