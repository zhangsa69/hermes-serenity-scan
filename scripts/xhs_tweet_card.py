#!/usr/bin/env python3
"""
Serenity推文 → 小红书retro卡片生成器
标题、原文、翻译全部放图片内。内容过多时自动分页。

用法:
  python3 xhs_tweet_card.py \
    --tweet "原文" --time "UTC时间" \
    --translation "中文直译" \
    --out /tmp/cards/

输出: /tmp/cards/card_1.png, card_2.png, ...（至少1张）
"""

import argparse, json, os, sys
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

# ── Retro 配色 ──
WIDTH, HEIGHT = 1080, 1440
BG = (253, 246, 227)          # #FDF6E3 复古米黄
TITLE_C = (211, 84, 0)        # #D35400 复古橙
TEXT_C = (92, 64, 51)         # #5C4033 棕褐
SECTION_C = (139, 69, 19)     # #8B4513 马鞍棕
SEP_C = (211, 84, 0)
DOT_C = (211, 84, 0)

FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

# ── 布局 ──
ML, MR = 72, 72
MT, MB = 56, 56
CW = WIDTH - ML - MR

TITLE_FS = 44
SECTION_FS = 40
BODY_FS = 42                   # 起始字号
MIN_FS = 28                    # 最小字号，低于此分页
SECTION_GAP = 20
BLOCK_GAP = 36
SEP_H = 3
DOT_R = 7

# 标题区域固定高度
TITLE_AREA_H = 100              # 标题+分隔线占的约高度


def beijing_time(utc_str, name="白毛股神"):
    try:
        utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        bj = utc_dt + timedelta(hours=8)
        ds = f"{str(bj.year)[2:]}年{bj.month}月{bj.day}日"
        ts = f"{bj.hour:02d}:{bj.minute:02d}"
        title = f"{ds} {ts} {name}"
        return ds, ts, title
    except:
        return "", "", name


def wrap_text(text, font, draw):
    """文字换行"""
    lines = []
    for para in text.replace("\r\n", "\n").split("\n"):
        para = para.strip()
        if not para:
            lines.append("")
            continue
        cur = ""
        for ch in para:
            test = cur + ch
            if (draw.textbbox((0, 0), test, font=font)[2]) > CW and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = test
        if cur:
            lines.append(cur)
    return lines


def build_flat_items(tweet_text, translation_text, font, draw):
    """构建所有内容行的扁平列表，每项 (text, color, font, gap)"""
    items = []
    section_font = ImageFont.truetype(FONT_PATH, SECTION_FS)

    items.append(("原文", SECTION_C, section_font, SECTION_GAP))
    for line in wrap_text(tweet_text, font, draw):
        items.append((line if line else " ", TEXT_C, font, 4))
    items.append(("", None, None, BLOCK_GAP))
    items.append(("中文翻译", SECTION_C, section_font, SECTION_GAP))
    for line in wrap_text(translation_text, font, draw):
        items.append((line if line else " ", TEXT_C, font, 4))

    return items


def item_height(item, draw):
    """计算单项高度（含gap）"""
    text, color, fnt, gap = item
    if text is None:
        return gap
    return (draw.textbbox((0, 0), text, font=fnt)[3] -
            draw.textbbox((0, 0), text, font=fnt)[1]) + gap


def measure_items(items, draw):
    return sum(item_height(it, draw) for it in items)


def draw_title(draw, title):
    """绘制标题区域，返回标题底部y坐标"""
    title_font = ImageFont.truetype(FONT_PATH, TITLE_FS)
    ty = MT
    tx = ML + DOT_R * 2 + 14
    dot_cx, dot_cy = ML + DOT_R, ty + TITLE_FS // 2
    draw.ellipse([dot_cx - DOT_R, dot_cy - DOT_R,
                  dot_cx + DOT_R, dot_cy + DOT_R], fill=DOT_C)
    draw.text((tx, ty), title, fill=TITLE_C, font=title_font)
    th = draw.textbbox((0, 0), title, font=title_font)[3]
    sy1 = ty + th + 16
    sy2 = sy1 + 5
    draw.rectangle([ML, sy1, WIDTH - MR, sy1 + SEP_H], fill=SEP_C)
    draw.rectangle([ML, sy2, WIDTH - MR, sy2 + SEP_H], fill=SEP_C)
    return sy2 + SEP_H + 24  # body top


def render_page(items_slice, draw, has_title, title_str):
    """渲染一张卡片，返回 PIL Image"""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)

    if has_title:
        body_top = draw_title(d, title_str)
    else:
        body_top = MT  # 续页无标题，顶部留白少

    avail_h = HEIGHT - MB - body_top
    total_h = measure_items(items_slice, d)

    y = body_top + max(0, (avail_h - total_h) // 2)
    x = ML

    for text, color, fnt, gap in items_slice:
        if text is None:
            y += gap
            continue
        d.text((x, y), text, fill=color, font=fnt)
        y += item_height((text, color, fnt, gap), d)

    return img


def generate(tweet_text, tweet_time_utc, translation, out_dir, name="白毛股神"):
    os.makedirs(out_dir, exist_ok=True)

    date_str, time_str, title = beijing_time(tweet_time_utc, name)

    # 用临时 ImageDraw 做测量
    tmp_img = Image.new("RGB", (1, 1), BG)
    tmp_draw = ImageDraw.Draw(tmp_img)

    # 尝试不同字号，看是否一页能放下
    fs = BODY_FS
    font = ImageFont.truetype(FONT_PATH, fs)
    items = build_flat_items(tweet_text, translation, font, tmp_draw)

    page1_avail = HEIGHT - MB - (MT + TITLE_AREA_H)
    total_h = measure_items(items, tmp_draw)

    # 先尝试缩字号
    while total_h > page1_avail and fs > MIN_FS:
        fs -= 2
        font = ImageFont.truetype(FONT_PATH, fs)
        items = build_flat_items(tweet_text, translation, font, tmp_draw)
        total_h = measure_items(items, tmp_draw)

    pages = []

    if total_h <= page1_avail:
        # 一页能放下
        img = render_page(items, tmp_draw, has_title=True, title_str=title)
        path = os.path.join(out_dir, "card_1.png")
        img.save(path, "PNG")
        pages.append(path)
    else:
        # 需要分页，用舒适字号
        fs = 34  # 分页模式下固定 34px，阅读舒服
        font = ImageFont.truetype(FONT_PATH, fs)
        items = build_flat_items(tweet_text, translation, font, tmp_draw)
        page1_avail = HEIGHT - MB - (MT + TITLE_AREA_H)
        cont_avail = HEIGHT - MB - MT  # 续页可用高度

        # 每页能放多少高度
        remaining = list(items)
        page_num = 0

        while remaining:
            page_num += 1
            avail = page1_avail if page_num == 1 else cont_avail
            has_title = (page_num == 1)

            # 贪心取尽可能多的行
            taken = []
            taken_h = 0
            while remaining:
                h = item_height(remaining[0], tmp_draw)
                if taken_h + h <= avail:
                    taken.append(remaining.pop(0))
                    taken_h += h
                else:
                    break

            if not taken:
                break

            img = render_page(taken, tmp_draw, has_title=has_title, title_str=title)
            path = os.path.join(out_dir, f"card_{page_num}.png")
            img.save(path, "PNG")
            pages.append(path)

    return {"title": title, "cards": pages, "count": len(pages)}


def main():
    p = argparse.ArgumentParser(description="推文→retro卡片（自动分页）")
    p.add_argument("--tweet", required=True)
    p.add_argument("--time", required=True)
    p.add_argument("--translation", required=True)
    p.add_argument("--out", required=True, help="Output directory for card_*.png")
    p.add_argument("--name", default="白毛股神", help="Author name for title")
    args = p.parse_args()
    result = generate(args.tweet, args.time, args.translation, args.out, name=args.name)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
