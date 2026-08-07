from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)


FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"


def _register_fonts() -> None:
    global FONT_REGULAR, FONT_BOLD, FONT_ITALIC
    candidates = [
        (
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
        ),
        (
            Path("/Library/Fonts/Arial.ttf"),
            Path("/Library/Fonts/Arial Bold.ttf"),
            Path("/Library/Fonts/Arial Italic.ttf"),
        ),
    ]

    for regular, bold, italic in candidates:
        if regular.exists() and bold.exists() and italic.exists():
            pdfmetrics.registerFont(TTFont("AppRegular", str(regular)))
            pdfmetrics.registerFont(TTFont("AppBold", str(bold)))
            pdfmetrics.registerFont(TTFont("AppItalic", str(italic)))
            FONT_REGULAR = "AppRegular"
            FONT_BOLD = "AppBold"
            FONT_ITALIC = "AppItalic"
            return


def heading(text: str, style):
    return Paragraph(text, style)


def bullet(items, style):
    return [Paragraph(f"• {item}", style) for item in items]


def section(title, items, h_style, b_style):
    blocks = [heading(title, h_style), Spacer(1, 2 * mm)]
    blocks.extend(bullet(items, b_style))
    blocks.append(Spacer(1, 4 * mm))
    return KeepTogether(blocks)


def make_pdf(out_path: Path) -> None:
    _register_fonts()

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="PokerDom Practice - Strategy Guide",
        author="PokerDom Practice App",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontName=FONT_BOLD,
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0F5132"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleStyle",
        parent=styles["Normal"],
        fontName=FONT_REGULAR,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceAfter=10,
    )
    h_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontName=FONT_BOLD,
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#14532D"),
        spaceBefore=6,
        spaceAfter=4,
    )
    b_style = ParagraphStyle(
        "BulletStyle",
        parent=styles["BodyText"],
        fontName=FONT_REGULAR,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#111827"),
        spaceAfter=2,
    )
    note_style = ParagraphStyle(
        "NoteStyle",
        parent=styles["BodyText"],
        fontName=FONT_ITALIC,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#334155"),
        spaceAfter=8,
    )

    story = []
    story.append(Paragraph("PokerDom Practice: Полный гайд по игре и выводам", title_style))
    story.append(
        Paragraph(
            f"Версия документа: {date.today().isoformat()} · Основано на реальной логике текущего приложения (EV, solver, dossier, боты)",
            subtitle_style,
        )
    )

    summary_table = Table(
        [
            ["Что сейчас сильнее всего", "Где выше риск ошибки"],
            [
                "Heads-up постфлоп, дисциплина по -EV коллам, value против пассивных профилей",
                "Мультивей большие банки, низкая уверенность модели, переагрессия против нитов",
            ],
        ],
        colWidths=[86 * mm, 86 * mm],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCFCE7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#14532D")),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#86EFAC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 4 * mm))

    story.append(
        section(
            "1) Что мы проверяли и что узнали",
            [
                "Стабильность движка раздач: правила, all-in, сайд-поты, очередность действий и blind-rotation закрыты тестами.",
                "Слой рекомендаций: EV + solver-проекция + range CFR для HU постфлоп (флоп/тёрн/ривер).",
                "Слой поведения ботов: стохастический выбор действий из CatBoost-моделей + стилевой bias по archetype.",
                "Слой оппонент-модели: dossier с VPIP/PFR/3bet/AFq и контекстом по позиции/улицам.",
                "Контроль больших банков: проверены несколько механизмов damping/suppression, частичный эффект подтверждён логами.",
            ],
            h_style,
            b_style,
        )
    )

    story.append(
        section(
            "2) Простая стратегия (рабочая и безопасная)",
            [
                "Если EV call < 0: по умолчанию фолд, особенно в мультивей.",
                "Если confidence низкий: играй low-variance (чек/колл чаще, реже тонкие рейзы).",
                "Против Nit/TAG: чаще выбивай диапазон ставками на хороших runout.",
                "Против Station/Loose-passive: меньше блефа, больше прямого value.",
                "В мультивей без сильной руки не раздувай банк сериями рейзов.",
            ],
            h_style,
            b_style,
        )
    )

    story.append(
        section(
            "3) Сложная стратегия (максимум EV на дистанции)",
            [
                "Работай в двух режимах чтения: Auto и принудительный archetype; совпали идеи -> сильный сигнал.",
                "При близких EV top-2 действий выбирай линию с меньшей дисперсией, а не ""красивый"" high-variance розыгрыш.",
                "В HU постфлоп доверяй solver-линии сильнее, чем префлоп/мультивей проекции.",
                "Используй dossier-динамику: рост AFq -> шире bluff-catch; низкий VPIP/PFR -> больше hero-fold против больших линий.",
                "Отслеживай повторяемые ошибки в hand history и убирай сначала самые дорогие (blunder/mistake).",
            ],
            h_style,
            b_style,
        )
    )

    story.append(
        section(
            "4) Какие действия чаще дают большой выигрыш",
            [
                "Жёсткая фильтрация -EV коллов (главный источник сохранения bb/100).",
                "Value-беттинг против пассивных и коллирующих профилей на поздних улицах.",
                "Bluff-catch против гиперагрессии (LAG/Maniac), когда цена колла приемлема.",
                "Контроль размера банка в uncertain spot (низкая уверенность, мультивей, плохие runout).",
                "Серийная эксплуатация одного паттерна оппонента, а не единичные hero-line решения.",
            ],
            h_style,
            b_style,
        )
    )

    story.append(
        section(
            "5) Частые ошибки игроков в этой системе",
            [
                "Переоценка точности рекомендаций в мультивей-поте.",
                "Игнор confidence-note и принятие совета как абсолютной истины.",
                "Переагрессия против узких профилей, особенно в deep-stacked банках.",
                "Попытка выигрывать каждую раздачу вместо контроля дорогих ошибок.",
                "Ориентация только на один результат руки, а не на EV-потери по серии рук.",
            ],
            h_style,
            b_style,
        )
    )

    story.append(
        section(
            "6) Что работает не идеально и при каких условиях",
            [
                "Префлоп и мультивей: логика более приближённая, чем HU постфлоп CFR.",
                "Dossier в начале сессии опирается на популяцию сильнее, чем на персональные наблюдения.",
                "Тренерский вердикт оценивает решение относительно внутренней модели, а не внешнего идеального solver.",
                "Большие банки частично ограничены, но не полностью устранены (структурный мультивей-эффект остаётся).",
            ],
            h_style,
            b_style,
        )
    )

    story.append(
        section(
            "7) Практический чеклист на каждое решение",
            [
                "(1) Определи формат: HU или мультивей.",
                "(2) Посмотри confidence и note.",
                "(3) Сравни EV call и break-even equity.",
                "(4) Быстро сверяй Auto vs archetype-гипотезу.",
                "(5) При высокой уверенности -> бери топ-линию; при низкой -> снижай дисперсию.",
                "(6) После руки зафиксируй EV-loss и тип ошибки в истории.",
            ],
            h_style,
            b_style,
        )
    )

    story.append(
        Paragraph(
            "Итог: лучшая стратегия в текущей версии — дисциплина по -EV решениям + адаптация к confidence + exploit по archetype, с повышенным доверием к HU постфлоп и осторожностью в мультивее.",
            note_style,
        )
    )

    doc.build(story)


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "PokerDom_Practice_Strategy_Guide.pdf"
    make_pdf(out)
    print(out)
