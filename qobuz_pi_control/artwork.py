"""Stream Deck artwork, transport glyphs and tile rendering.

Pure image rendering: no network, ALSA or USB device lifecycle.
"""
from __future__ import annotations

from io import BytesIO

from .display import GAP as ART_GAP_PX, canvas_size, slice_tiles

# Keep physical-key layout consistent with the controller.
KEY_ACTIONS = {0: "previous", 1: "toggle", 2: "next"}

def _label_image(deck, label: str):
    from PIL import ImageDraw, ImageFont
    from StreamDeck.ImageHelpers import PILHelper

    image = PILHelper.create_image(deck)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=16)
    bounds = draw.textbbox((0, 0), label, font=font)
    x = (image.width - (bounds[2] - bounds[0])) // 2
    y = (image.height - (bounds[3] - bounds[1])) // 2
    draw.text((x, y), label, font=font, fill="white")
    return PILHelper.to_native_format(deck, image)


def _transport_image(deck, playing: bool):
    """Draw a proper play/pause symbol rather than a text label."""
    from PIL import ImageDraw
    from StreamDeck.ImageHelpers import PILHelper

    image = PILHelper.create_image(deck)
    draw = ImageDraw.Draw(image)
    w, h = image.size
    if playing:
        draw.rounded_rectangle((w * .30, h * .24, w * .43, h * .76),
                               radius=3, fill="white")
        draw.rounded_rectangle((w * .57, h * .24, w * .70, h * .76),
                               radius=3, fill="white")
    else:
        draw.polygon([(w * .34, h * .22), (w * .34, h * .78),
                      (w * .77, h * .50)], fill="white")
    return PILHelper.to_native_format(deck, image)


def _artwork_tiles(deck, artwork: bytes, playing: bool = False,
                   metadata=("", "", ""), remaining=None, progress=None, quality="", show_overlays=True, title_offset=0, track_word_count=0):
    """Compose one continuous 5x3 canvas, then omit the physical button gaps."""
    from PIL import Image, ImageOps, ImageDraw, ImageFont
    from StreamDeck.ImageHelpers import PILHelper

    key_w, key_h = deck.key_image_format()["size"]
    canvas_w, canvas_h = canvas_size((key_w, key_h))
    with Image.open(BytesIO(artwork)) as source:
        source.load()
        cover = ImageOps.fit(source.convert("RGB"), (canvas_w, canvas_h)).convert("RGBA")
    if False:  # Artwork-only fast path disabled: marquee remains visible.
        return [
            PILHelper.to_native_format(
                deck,
                cover.crop((
                    col * (key_w + ART_GAP_PX),
                    row * (key_h + ART_GAP_PX),
                    col * (key_w + ART_GAP_PX) + key_w,
                    row * (key_h + ART_GAP_PX) + key_h,
                )).convert("RGB"),
            )
            for row in range(3) for col in range(5)
        ]
    overlay = Image.new("RGBA", cover.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def font_at(size):
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except OSError:
            return ImageFont.load_default(size=size)

    def centered(text, box, size, max_lines=2, color=(255, 255, 255, 255)):
        """Fit text inside a canvas rectangle, shrinking or wrapping as needed."""
        text = str(text or "").strip()
        if not text:
            return
        x0, y0, x1, y1 = box
        width = x1 - x0 - 10
        height = y1 - y0 - 8
        for point_size in range(size, 9, -1):
            font = font_at(point_size)
            words = text.split()
            lines = []
            current = ""
            for word in words:
                candidate = (current + " " + word).strip()
                if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            line_h = point_size + 4
            if len(lines) <= max_lines and len(lines) * line_h <= height and all(
                draw.textbbox((0, 0), line, font=font)[2] <= width for line in lines
            ):
                break
        else:
            font = font_at(10)
            lines = [text]
            while lines[0] and draw.textbbox((0, 0), lines[0] + "…", font=font)[2] > width:
                lines[0] = lines[0][:-1]
            lines[0] += "…"
            line_h = 14
        top = (y0 + y1 - len(lines) * line_h) // 2
        for i, line in enumerate(lines):
            bounds = draw.textbbox((0, 0), line, font=font)
            draw.text(((x0 + x1 - (bounds[2] - bounds[0])) // 2,
                       top + i * line_h - bounds[1]), line, font=font,
                      fill=color)

    # Minimal, antialiased media controls: conventional skip-back,
    # play/pause and skip-forward glyphs on subtle circular scrims.
    if show_overlays:
        from PIL import Image as PILImage
        scale = 4
        icon_size = 48
        for index in KEY_ACTIONS:
            cx = index * (key_w + ART_GAP_PX) + key_w // 2
            cy = key_h // 2
            glyph = PILImage.new("RGBA", (icon_size * scale, icon_size * scale))
            gd = ImageDraw.Draw(glyph)
            def rect(x0, y0, x1, y1, radius=0):
                bounds = tuple(round(v * scale) for v in (x0, y0, x1, y1))
                if radius:
                    gd.rounded_rectangle(bounds, radius=radius * scale, fill="white")
                else:
                    gd.rectangle(bounds, fill="white")
            def triangle(points):
                gd.polygon([(round(x * scale), round(y * scale)) for x, y in points],
                           fill="white")
            if index == 0:  # Previous: point LEFT, with a stop bar.
                rect(12, 13, 15, 35, radius=1)
                triangle([(34, 12), (34, 36), (16, 24)])
            elif index == 2:  # Next: point RIGHT, with a stop bar.
                triangle([(14, 12), (14, 36), (32, 24)])
                rect(33, 13, 36, 35, radius=1)
            elif playing:
                rect(15, 13, 21, 35, radius=1)
                rect(27, 13, 33, 35, radius=1)
            else:
                triangle([(17, 12), (17, 36), (35, 24)])
            glyph = glyph.resize((icon_size, icon_size), PILImage.Resampling.LANCZOS)
            scrim_radius = 25
            draw.ellipse((cx - scrim_radius, cy - scrim_radius,
                          cx + scrim_radius, cy + scrim_radius),
                         fill=(0, 0, 0, 115))
            overlay.alpha_composite(glyph, (cx - icon_size // 2, cy - icon_size // 2))

    # Five independent word slots on one continuous translucent title band.
    middle_top = key_h + ART_GAP_PX
    draw.rounded_rectangle((0, middle_top + 12, canvas_w, middle_top + key_h - 8),
                           radius=10, fill=(0, 0, 0, 155))
    words = str(metadata[2] or "").split()
    visible = words[title_offset:title_offset + 5]
    # Short titles sit centred as a group; long titles occupy all five slots.
    start_col = (5 - len(visible)) // 2 if len(words) <= 5 else 0
    for slot, word in enumerate(visible):
        col = start_col + slot
        x = col * (key_w + ART_GAP_PX)
        word_index = title_offset + slot
        color = ((160, 220, 255, 255) if word_index > track_word_count
                 else (255, 255, 255, 255))
        # Anchor every word to the same typographic centre, rather than
        # centring its individual glyph bounding box (which shifts words
        # containing ascenders, descenders or punctuation vertically).
        # Scale the word to fit its own tile, even for unusually long words.
        # Do not stop at 10pt: a word wider than that was clipped by the LCD.
        available_width = key_w - 12
        word_font = font_at(19)
        for point_size in range(19, 5, -1):
            candidate_font = font_at(point_size)
            bounds = draw.textbbox((0, 0), word, font=candidate_font)
            if bounds[2] - bounds[0] <= available_width:
                word_font = candidate_font
                break
        else:
            word_font = font_at(6)
        bounds = draw.textbbox((0, 0), word, font=word_font)
        word_width = bounds[2] - bounds[0]
        if word_width > available_width:
            # For exceptionally long words, scale the rendered glyphs to
            # fit without truncation, keeping the same vertical baseline.
            from PIL import Image as PILImage
            glyph = PILImage.new("RGBA", (word_width + 4, max(1, bounds[3] - bounds[1] + 4)))
            glyph_draw = ImageDraw.Draw(glyph)
            glyph_draw.text((2 - bounds[0], 2 - bounds[1]), word, font=word_font, fill=color)
            fitted_width = max(1, available_width)
            glyph = glyph.resize((fitted_width, glyph.height), PILImage.Resampling.LANCZOS)
            overlay.alpha_composite(glyph, (x + (key_w - fitted_width) // 2,
                                            middle_top + (key_h - glyph.height) // 2))
        else:
            draw.text((x + key_w // 2, middle_top + key_h // 2),
                      word, font=word_font, anchor="mm", fill=color)

    # Bottom row: legible, bold, single-line labels rendered at 4x resolution.
    # Text is deliberately truncated rather than reduced to tiny point sizes.
    bottom_top = 2 * (key_h + ART_GAP_PX)
    for index, value in (((13, quality), (14, remaining)) if show_overlays else ()):
        if not value:
            continue
        x = (index - 10) * (key_w + ART_GAP_PX)
        draw.rounded_rectangle((x + 2, bottom_top + 7, x + key_w - 2,
                                bottom_top + key_h - 7), radius=8,
                               fill=(0, 0, 0, 110))
        scale = 4
        from PIL import Image as PILImage
        text_layer = PILImage.new("RGBA", (key_w * scale, key_h * scale),
                                  (0, 0, 0, 0))
        td = ImageDraw.Draw(text_layer)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 12 * scale)
        except OSError:
            font = ImageFont.load_default(size=12 * scale)
        value = str(value).strip()
        available = (key_w - 10) * scale
        def text_width(candidate):
            bb = td.textbbox((0, 0), candidate, font=font)
            return bb[2] - bb[0]
        if text_width(value) > available:
            while value and text_width(value + "…") > available:
                value = value[:-1]
            value += "…"
        bounds = td.textbbox((0, 0), value, font=font)
        td.text(((key_w * scale - (bounds[2] - bounds[0])) // 2,
                 (key_h * scale - (bounds[3] - bounds[1])) // 2 - bounds[1]),
                value, font=font, fill=(255, 255, 255, 255))
        text_layer = text_layer.resize((key_w, key_h), PILImage.Resampling.LANCZOS)
        overlay.alpha_composite(text_layer, (x, bottom_top))

    composite = Image.alpha_composite(cover, overlay).convert("RGB")
    return [PILHelper.to_native_format(deck, tile) for tile in slice_tiles(composite, (key_w, key_h))]
