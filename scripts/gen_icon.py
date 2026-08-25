"""生成 PWA 图标：医疗十字 + 雷达波纹，输出 icon-192.png / icon-512.png"""
import os
from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pwa")


def make_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角背景（浅蓝渐变感：纯色即可）
    bg = (59, 130, 246, 255)  # #3B82F6
    radius = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=bg)

    s = size / 512.0  # 缩放系数（以 512 为基准设计）

    # 雷达波纹（左上角发射的圆弧）
    ring_color = (255, 255, 255, 70)
    cx, cy = int(150 * s), int(150 * s)
    for i, r in enumerate([70, 110, 150]):
        rr = int(r * s)
        d.arc([cx - rr, cy - rr, cx + rr, cy + rr],
              start=-30, end=160, fill=ring_color, width=int(14 * s))

    # 雷达扫描线
    d.line([cx, cy, int(cx + 175 * s), int(cy - 105 * s)],
           fill=(255, 255, 255, 160), width=int(12 * s))
    d.ellipse([cx - int(16 * s), cy - int(16 * s),
               cx + int(16 * s), cy + int(16 * s)],
              fill=(255, 255, 255, 220))

    # 医疗十字（中心，白色）
    cw = int(120 * s)   # 十字臂长
    cth = int(38 * s)   # 臂宽
    ccx, ccy = int(256 * s), int(300 * s)
    d.rounded_rectangle([ccx - cth // 2, ccy - cw // 2,
                         ccx + cth // 2, ccy + cw // 2],
                        radius=int(10 * s), fill=(255, 255, 255, 255))
    d.rounded_rectangle([ccx - cw // 2, ccy - cth // 2,
                         ccx + cw // 2, ccy + cth // 2],
                        radius=int(10 * s), fill=(255, 255, 255, 255))

    return img


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    for sz in (192, 512):
        p = os.path.join(OUT_DIR, f"icon-{sz}.png")
        make_icon(sz).save(p)
        print("saved", p)
