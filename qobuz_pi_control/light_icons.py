"""Antialiased sun and minus/plus glyphs, shared by artwork and spectrum."""
import math


def light_icon(increase, size=48):
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (192, 192))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 68, 88, 116), outline="white", width=8)
    for angle in range(0, 360, 45):
        a = math.radians(angle)
        draw.line((64 + 34 * math.cos(a), 92 + 34 * math.sin(a),
                   64 + 46 * math.cos(a), 92 + 46 * math.sin(a)),
                  fill="white", width=7)
    draw.rounded_rectangle((124, 88, 172, 96), radius=3, fill="white")
    if increase:
        draw.rounded_rectangle((144, 68, 152, 116), radius=3, fill="white")
    return image.resize((size, size), Image.Resampling.LANCZOS)
