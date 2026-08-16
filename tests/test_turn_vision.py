from io import BytesIO

from PIL import Image, ImageDraw

from src.vision.layout import Region, TableLayout
from src.vision.turn import is_hero_turn


def test_detects_blue_action_badge() -> None:
    image = Image.new("RGB", (100, 100), "black")
    ImageDraw.Draw(image).rectangle((50, 80, 59, 89), fill=(0, 159, 217))
    output = BytesIO()
    image.save(output, format="PNG")
    layout = TableLayout(hero=(), board=(), action_badge=Region(0.5, 0.8, 0.1, 0.1))
    assert is_hero_turn(output.getvalue(), layout)
