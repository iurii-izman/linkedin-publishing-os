from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont
from PIL.ImageFont import ImageFont as PillowImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "assets" / "stage0" / "linkedin-publishing-workflow.png"
CANVAS_SIZE = (1200, 1200)

BACKGROUND = "#0B1422"
PANEL = "#152237"
PANEL_ACCENT = "#193151"
WHITE = "#F7FAFF"
MUTED = "#A9B8CC"
ACCENT = "#2F8FFF"
ACCENT_SOFT = "#77B7FF"


def _font_candidates(*names: str) -> list[Path]:
    candidates: list[Path] = []
    windows_root = Path(os.environ.get("WINDIR", "C:/Windows"))
    for name in names:
        candidates.append(windows_root / "Fonts" / name)
    candidates.extend(
        [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]
    )
    return candidates


def _load_font(size: int, *, bold: bool = False) -> FreeTypeFont | PillowImageFont:
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
    for candidate in _font_candidates(*names):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _rounded_card(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    *,
    fill: str = PANEL,
    outline: str = "#29415F",
    radius: int = 24,
) -> None:
    draw.rounded_rectangle(bounds, radius=radius, fill=fill, outline=outline, width=2)


def _centered_multiline(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    text: str,
    font: FreeTypeFont | PillowImageFont,
    *,
    fill: str = WHITE,
    spacing: int = 8,
) -> None:
    draw.multiline_text(
        center,
        text,
        font=font,
        fill=fill,
        anchor="mm",
        align="center",
        spacing=spacing,
    )


def _arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    color: str = ACCENT,
    width: int = 5,
) -> None:
    draw.line((start, end), fill=color, width=width)
    tip_x, tip_y = end
    draw.polygon(
        [(tip_x, tip_y), (tip_x - 14, tip_y - 10), (tip_x - 14, tip_y + 10)],
        fill=color,
    )


def generate(output: Path = DEFAULT_OUTPUT) -> Path:
    image = Image.new("RGB", CANVAS_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = _load_font(58, bold=True)
    card_font = _load_font(27, bold=True)
    branch_font = _load_font(25, bold=True)
    footer_font = _load_font(26)
    brand_font = _load_font(30, bold=True)

    draw.rounded_rectangle((72, 60, 1128, 72), radius=6, fill=ACCENT)
    draw.text(
        (600, 145),
        "LinkedIn Publishing Workflow",
        font=title_font,
        fill=WHITE,
        anchor="mm",
    )
    draw.text(
        (600, 205),
        "A human-approved state machine",
        font=footer_font,
        fill=MUTED,
        anchor="mm",
    )

    labels = ["Idea", "Draft", "Human\nApproval", "Schedule", "Publish"]
    card_width = 178
    card_height = 132
    gap = 34
    start_x = 87
    main_y = 290
    for index, label in enumerate(labels):
        left = start_x + index * (card_width + gap)
        bounds = (left, main_y, left + card_width, main_y + card_height)
        _rounded_card(
            draw,
            bounds,
            fill=PANEL_ACCENT if label == "Human\nApproval" else PANEL,
            outline=ACCENT if label == "Human\nApproval" else "#29415F",
        )
        _centered_multiline(
            draw,
            (left + card_width // 2, main_y + card_height // 2),
            label,
            card_font,
        )
        if index < len(labels) - 1:
            _arrow(
                draw,
                (left + card_width + 8, main_y + card_height // 2),
                (left + card_width + gap - 8, main_y + card_height // 2),
            )

    draw.text(
        (92, 525),
        "AMBIGUOUS RESULT PATH",
        font=_load_font(22, bold=True),
        fill=ACCENT_SOFT,
        anchor="lm",
    )
    draw.line((92, 552, 1108, 552), fill="#28405E", width=2)

    branch_labels = ["Ambiguous\nAPI Result", "PUBLISH_UNCERTAIN", "Manual\nVerification"]
    branch_width = 280
    branch_height = 142
    branch_gap = 70
    branch_start_x = 110
    branch_y = 615
    for index, label in enumerate(branch_labels):
        left = branch_start_x + index * (branch_width + branch_gap)
        bounds = (left, branch_y, left + branch_width, branch_y + branch_height)
        _rounded_card(
            draw,
            bounds,
            fill=PANEL_ACCENT if index == 1 else PANEL,
            outline=ACCENT if index == 1 else "#29415F",
        )
        _centered_multiline(
            draw,
            (left + branch_width // 2, branch_y + branch_height // 2),
            label,
            branch_font,
            fill=ACCENT_SOFT if index == 1 else WHITE,
        )
        if index < len(branch_labels) - 1:
            _arrow(
                draw,
                (left + branch_width + 12, branch_y + branch_height // 2),
                (left + branch_width + branch_gap - 12, branch_y + branch_height // 2),
            )

    draw.rounded_rectangle(
        (150, 890, 1050, 978),
        radius=30,
        fill="#111E31",
        outline="#29415F",
        width=2,
    )
    draw.text(
        (600, 934),
        "FastAPI  •  PostgreSQL  •  n8n  •  Official API",
        font=footer_font,
        fill=WHITE,
        anchor="mm",
    )

    draw.line((420, 1060, 780, 1060), fill=ACCENT, width=3)
    draw.text(
        (600, 1110),
        "Izman Systems Lab",
        font=brand_font,
        fill=WHITE,
        anchor="mm",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)
    with Image.open(output) as generated:
        if generated.size != CANVAS_SIZE or generated.mode != "RGB":
            raise RuntimeError("Generated image does not satisfy required dimensions and RGB mode")
        if generated.format != "PNG":
            raise RuntimeError("Generated image is not PNG")
    return output


if __name__ == "__main__":
    print(generate().relative_to(ROOT).as_posix())
