"""Generate a single shareable PNG "verification certificate" summarizing a
run: the input face next to the matched image, the cosine score, the record
hash, and the on-chain tx (with a QR code to the public explorer when one
exists). Purely presentational -- built entirely from data already produced
by run.py's Steps 1-5, no new network calls or pipeline logic.
"""
from __future__ import annotations

import io
import pathlib
import textwrap
from typing import Any, Optional

import qrcode
from PIL import Image, ImageDraw, ImageFont

CANVAS_W, CANVAS_H = 1600, 1000
BG = (250, 250, 248)
CARD_BG = (255, 255, 255)
BORDER = (210, 210, 205)
INK = (30, 30, 30)
MUTED = (120, 120, 115)
GREEN = (34, 139, 58)
MONO_BG = (243, 243, 240)


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        ["arialbd.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]
    ) + [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _make_qr(data: str) -> Image.Image:
    qr = qrcode.QRCode(border=1, box_size=8)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def _fit_image(img: Image.Image, box: int) -> Image.Image:
    img = img.convert("RGB")
    img.thumbnail((box, box), Image.LANCZOS)
    canvas = Image.new("RGB", (box, box), CARD_BG)
    canvas.paste(img, ((box - img.width) // 2, (box - img.height) // 2))
    return canvas


def _draw_card(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int]) -> None:
    draw.rounded_rectangle(xy, radius=12, fill=CARD_BG, outline=BORDER, width=2)


def _center_text(draw: ImageDraw.ImageDraw, cx: int, y: int, text: str, font, fill) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text((cx - w / 2, y), text, font=font, fill=fill)


def _wrap_mono(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    # rough char-width-based wrap for a hex string with no natural break points
    bbox = draw.textbbox((0, 0), "0", font=font)
    char_w = max(bbox[2] - bbox[0], 1)
    per_line = max(int(max_width / char_w), 8)
    return textwrap.wrap(text, per_line, break_long_words=True) or [text]


def generate_certificate(
    *,
    query_crop_path: pathlib.Path,
    matched_image_bytes: bytes,
    match_record: dict[str, Any],
    record_hash_hex: str,
    receipt: dict[str, Any],
    chain_mode: str,
    dest_path: pathlib.Path,
) -> pathlib.Path:
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), BG)
    draw = ImageDraw.Draw(img)

    title_font = _load_font(42, bold=True)
    sub_font = _load_font(22)
    label_font = _load_font(18)
    mono_font = _load_font(20)
    big_font = _load_font(56, bold=True)
    badge_font = _load_font(24, bold=True)
    caption_font = _load_font(18)
    footer_font = _load_font(15)

    # -- header -----------------------------------------------------
    _center_text(draw, CANVAS_W // 2, 30, "FaceID Chain — Verification Certificate", title_font, INK)
    chain_label = "Polygon Amoy testnet" if chain_mode == "amoy" else "local in-process chain"
    subtitle = f"{match_record.get('timestamp_utc', '')}  ·  anchored on {chain_label}"
    _center_text(draw, CANVAS_W // 2, 82, subtitle, sub_font, MUTED)

    # -- left column: input face -------------------------------------
    left_box = 480
    left_x, left_y = 80, 160
    _draw_card(draw, (left_x, left_y, left_x + left_box, left_y + left_box))
    try:
        query_img = Image.open(query_crop_path)
        fitted = _fit_image(query_img, left_box - 24)
        img.paste(fitted, (left_x + 12, left_y + 12))
    except Exception:
        _center_text(draw, left_x + left_box // 2, left_y + left_box // 2, "(image unavailable)", label_font, MUTED)
    _center_text(draw, left_x + left_box // 2, left_y + left_box + 16, "Input face", label_font, MUTED)

    # -- right column: matched image ---------------------------------
    right_box = 480
    right_x, right_y = CANVAS_W - 80 - right_box, 160
    _draw_card(draw, (right_x, right_y, right_x + right_box, right_y + right_box))
    try:
        matched_img = Image.open(io.BytesIO(matched_image_bytes))
        fitted = _fit_image(matched_img, right_box - 24)
        img.paste(fitted, (right_x + 12, right_y + 12))
    except Exception:
        _center_text(draw, right_x + right_box // 2, right_y + right_box // 2, "(image unavailable)", label_font, MUTED)
    source = match_record.get("matched_post_source", "")
    title = match_record.get("matched_post_title", "") or ""
    caption = source or "matched post"
    if title:
        caption = f"{caption} — {title[:40]}{'...' if len(title) > 40 else ''}"
    _center_text(draw, right_x + right_box // 2, right_y + right_box + 16, caption, label_font, MUTED)

    # -- center column: badge, score, hashes, QR ----------------------
    center_x0, center_x1 = left_x + left_box + 40, right_x - 40
    center_cx = (center_x0 + center_x1) // 2
    center_w = center_x1 - center_x0
    y = 180

    status_ok = receipt.get("status") == 1
    badge_text = "  VERIFIED MATCH  " if status_ok else "  ANCHORED  "
    badge_font_metrics = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_w = badge_font_metrics[2] - badge_font_metrics[0] + 24
    badge_h = 44
    badge_xy = (center_cx - badge_w // 2, y, center_cx + badge_w // 2, y + badge_h)
    draw.rounded_rectangle(badge_xy, radius=badge_h // 2, fill=GREEN if status_ok else MUTED)
    _center_text(draw, center_cx, y + 9, badge_text.strip(), badge_font, (255, 255, 255))
    y += badge_h + 30

    cosine = match_record.get("cosine_similarity", 0.0)
    threshold = match_record.get("match_threshold", 0.0)
    _center_text(draw, center_cx, y, f"{cosine:.3f}", big_font, INK)
    y += 66
    _center_text(draw, center_cx, y, f"cosine similarity  (threshold {threshold})", caption_font, MUTED)
    y += 44

    def draw_mono_block(label: str, value: str, y: int) -> int:
        _center_text(draw, center_cx, y, label, caption_font, MUTED)
        y += 24
        lines = _wrap_mono(draw, value, mono_font, center_w - 20)
        for line in lines:
            _center_text(draw, center_cx, y, line, mono_font, INK)
            y += 26
        return y + 12

    y = draw_mono_block("record hash", record_hash_hex, y)
    y = draw_mono_block("tx hash", receipt.get("tx_hash", "n/a"), y)
    y = draw_mono_block("contract", receipt.get("contract_address", "n/a"), y)

    # -- QR / explorer or local-chain placeholder ----------------------
    qr_box = 200
    qr_x = center_cx - qr_box // 2
    explorer_url = receipt.get("explorer_tx_url")
    if explorer_url:
        qr_img = _make_qr(explorer_url).resize((qr_box, qr_box))
        img.paste(qr_img, (qr_x, y))
        _center_text(draw, center_cx, y + qr_box + 10, "Scan to view on PolygonScan", caption_font, MUTED)
    else:
        draw.rounded_rectangle((qr_x, y, qr_x + qr_box, y + qr_box), radius=8, fill=MONO_BG, outline=BORDER)
        _center_text(draw, center_cx, y + qr_box // 2 - 10, "local chain", label_font, MUTED)
        _center_text(draw, center_cx, y + qr_box // 2 + 14, "no public explorer", label_font, MUTED)

    # -- footer ---------------------------------------------------------
    footer = (
        "Generated by faceid.certificate — face detect (YuNet) + embed (SFace) "
        "-> Google Lens reverse-image search -> on-chain anchor"
    )
    _center_text(draw, CANVAS_W // 2, CANVAS_H - 70, footer, footer_font, MUTED)
    _center_text(draw, CANVAS_W // 2, CANVAS_H - 46, str(dest_path), footer_font, MUTED)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest_path, "PNG")
    return dest_path
