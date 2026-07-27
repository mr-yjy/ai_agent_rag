from pathlib import Path

from PIL import Image, ImageDraw


OUTPUT = Path(__file__).parent / "assets" / "icon.ico"
CANVAS = 256
SCALE = CANVAS / 64


def scaled_point(x: float, y: float) -> tuple[int, int]:
    return round(x * SCALE), round(y * SCALE)


image = Image.new("RGBA", (CANVAS, CANVAS), "#10242D")
draw = ImageDraw.Draw(image)
draw.rounded_rectangle(
    (0, 0, CANVAS - 1, CANVAS - 1),
    radius=32,
    fill="#10242D",
)

route = [
    scaled_point(13, 45),
    scaled_point(30, 14),
    scaled_point(52, 43),
    scaled_point(39, 48),
    scaled_point(13, 45),
]
draw.line(
    route,
    fill="#D5E2E1",
    width=10,
    joint="curve",
)

for x, y, radius in ((30, 14, 5), (13, 45, 5), (52, 43, 5)):
    center_x, center_y = scaled_point(x, y)
    radius_px = round(radius * SCALE)
    draw.ellipse(
        (
            center_x - radius_px,
            center_y - radius_px,
            center_x + radius_px,
            center_y + radius_px,
        ),
        fill="#10242D",
        outline="#42C7C7",
        width=12,
    )

center_x, center_y = scaled_point(39, 48)
radius_px = round(3.5 * SCALE)
draw.ellipse(
    (
        center_x - radius_px,
        center_y - radius_px,
        center_x + radius_px,
        center_y + radius_px,
    ),
    fill="#3157C8",
)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
image.save(
    OUTPUT,
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)],
)
print(f"Created {OUTPUT}")
