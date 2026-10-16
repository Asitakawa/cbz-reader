"""生成应用图标：assets/icon.ico（多尺寸）与 assets/icon_256.png。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"
OUT.mkdir(parents=True, exist_ok=True)

ACCENT = (59, 111, 224, 255)
WHITE = (255, 255, 255, 255)
LINE = (59, 111, 224, 255)


def draw_icon(size: int = 256) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = max(2, int(s * 0.14))

    # 蓝色圆角底板（书本）
    d.rounded_rectangle([s * 0.09, s * 0.13, s * 0.91, s * 0.87], radius=r, fill=ACCENT)
    # 白色书页
    d.rounded_rectangle([s * 0.22, s * 0.09, s * 0.63, s * 0.91],
                        radius=max(2, int(s * 0.07)), fill=WHITE)
    # 书页上的两条文字线
    lw = max(1, int(s * 0.05))
    d.line([s * 0.31, s * 0.28, s * 0.54, s * 0.28], fill=LINE, width=lw)
    d.line([s * 0.31, s * 0.44, s * 0.54, s * 0.44], fill=LINE, width=lw)
    # 右侧书脊高光
    d.rounded_rectangle([s * 0.68, s * 0.20, s * 0.80, s * 0.80],
                        radius=max(1, int(s * 0.03)), fill=(255, 255, 255, 90))
    return img


def main() -> None:
    img = draw_icon(256)
    img.save(OUT / "icon_256.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(OUT / "icon.ico", format="ICO", sizes=sizes)
    print("图标已生成:", OUT / "icon.ico", OUT / "icon_256.png")


if __name__ == "__main__":
    main()
