from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def register_fonts() -> None:
    global FONT_REGULAR, FONT_BOLD
    candidates = [
        (
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ),
        (Path("/Library/Fonts/Arial.ttf"), Path("/Library/Fonts/Arial Bold.ttf")),
    ]
    for regular, bold in candidates:
        if regular.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont("CheatRegular", str(regular)))
            pdfmetrics.registerFont(TTFont("CheatBold", str(bold)))
            FONT_REGULAR = "CheatRegular"
            FONT_BOLD = "CheatBold"
            return


def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def card(title: str, lines: list[str], title_style: ParagraphStyle, body_style: ParagraphStyle) -> Table:
    title_para = paragraph(title, title_style)
    body_paras = [paragraph(f"• {line}", body_style) for line in lines]
    content = [[title_para], [Spacer(1, 1.5 * mm)]] + [[p] for p in body_paras]

    table = Table(content, colWidths=[80 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCFCE7")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#86EFAC")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def build_cheatsheet(out_path: Path) -> None:
    register_fonts()

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="PokerDom Practice - Памятка",
        author="PokerDom Practice",
    )

    title_style = ParagraphStyle(
        "title",
        fontName=FONT_BOLD,
        fontSize=21,
        leading=25,
        textColor=colors.HexColor("#14532D"),
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "subtitle",
        fontName=FONT_REGULAR,
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#334155"),
        spaceAfter=8,
    )
    card_title_style = ParagraphStyle(
        "card_title",
        fontName=FONT_BOLD,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#166534"),
    )
    card_body_style = ParagraphStyle(
        "card_body",
        fontName=FONT_REGULAR,
        fontSize=9.4,
        leading=13,
        textColor=colors.HexColor("#111827"),
    )
    footer_style = ParagraphStyle(
        "footer",
        fontName=FONT_REGULAR,
        fontSize=8.8,
        leading=12,
        textColor=colors.HexColor("#475569"),
        spaceBefore=6,
    )

    story = []
    story.append(paragraph("PokerDom Practice: Памятка по игре", title_style))
    story.append(
        paragraph(
            "Быстрый чеклист под текущую логику приложения: EV + solver + dossier."
            " Используй как guide во время каждой раздачи.",
            subtitle_style,
        )
    )

    left_cards = [
        card(
            "1) До нажатия кнопки",
            [
                "Определи формат: heads-up или мультивей.",
                "Проверь confidence: низкий confidence = меньше агрессии.",
                "Смотри EV call и break-even equity перед коллом.",
                "Сверь Auto и archetype-гипотезу: совпадение = сильный сигнал.",
            ],
            card_title_style,
            card_body_style,
        ),
        card(
            "2) Простая прибыльная стратегия",
            [
                "Если EV call < 0: чаще фолд.",
                "Против пассивных профилей: больше прямого value, меньше блефа.",
                "Против агрессивных профилей: чаще bluff-catch при нормальной цене.",
                "В мультивее без сильной руки не раздувай банк.",
            ],
            card_title_style,
            card_body_style,
        ),
        card(
            "3) Где чаще теряются деньги",
            [
                "-EV коллы из любопытства.",
                "Переоценка точности совета при низком confidence.",
                "Переагрессия против узких диапазонов Nit/TAG.",
                "Попытка выиграть каждую раздачу вместо контроля ошибок.",
            ],
            card_title_style,
            card_body_style,
        ),
    ]

    right_cards = [
        card(
            "4) Продвинутая стратегия",
            [
                "В HU постфлоп доверяй solver-линии сильнее.",
                "Если top-2 EV близко: выбирай менее дисперсионную линию.",
                "Повторяющиеся EV-loss важнее одиночного bad beat.",
                "Следи за сдвигом dossier: VPIP/PFR/AFq по мере сессии.",
            ],
            card_title_style,
            card_body_style,
        ),
        card(
            "5) Что даёт большой выигрыш",
            [
                "Дисциплина по фолдам в минусовых спотах.",
                "Системный value-bet против station/loose-passive.",
                "Контроль банка в uncertain spot.",
                "Серийный exploit одного паттерна соперника.",
            ],
            card_title_style,
            card_body_style,
        ),
        card(
            "6) Ограничения модели",
            [
                "Мультивей оценивается приближённо, не полным multiway solve.",
                "Префлоп точность ниже, чем в HU постфлоп.",
                "Тренерская оценка относительна внутренней модели.",
                "На старте сессии read ближе к популяции, чем к персональным данным.",
            ],
            card_title_style,
            card_body_style,
        ),
    ]

    grid_rows = []
    for idx in range(max(len(left_cards), len(right_cards))):
        left = left_cards[idx] if idx < len(left_cards) else Spacer(1, 1)
        right = right_cards[idx] if idx < len(right_cards) else Spacer(1, 1)
        grid_rows.append([left, right])

    grid = Table(grid_rows, colWidths=[82 * mm, 82 * mm], hAlign="CENTER")
    grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(grid)

    story.append(
        paragraph(
            "Ключевая мысль: долгосрочно выигрывает не “самая красивая линия”, а "
            "контроль дорогих ошибок + адаптация к confidence и типу оппонента.",
            footer_style,
        )
    )

    doc.build(story)


if __name__ == "__main__":
    output = Path(__file__).resolve().parents[1] / "PokerDom_Practice_Cheat_Sheet.pdf"
    build_cheatsheet(output)
    print(output)
