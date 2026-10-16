"""WeatherPicture — генерує 800x480 картинку з погодою для e-ink дисплея.

Використання:
    python weather_picture.py -o weather.png   # зберегти картинку у файл (необов'язково)

Для передачі в display_picture.py використовується create_picture() — картинка
повертається як PIL.Image, без запису на диск.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import lru_cache
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

WIDTH = 800
HEIGHT = 480

LATITUDE = 50.4547
LONGITUDE = 30.5238

BASE_DIR = Path(__file__).resolve().parent
ICONS_DIR = BASE_DIR / "eink"          # папка з PNG-іконками (01d.png, 53d.png ...)

FONT_NAME = "LiberationSans-Regular.ttf"
SS = 4  # supersampling для згладжених кривих

BLACK = (0, 0, 0)
GRAY = (128, 128, 128)
GREEN = (0, 128, 0)
BLUE = (0, 0, 255)
ORANGE = (255, 165, 0)
DARK_ORANGE = (255, 140, 0)
ORANGE_RED = (255, 69, 0)


# ─────────────────────────── AskData ────────────────────────────
def get_data() -> dict:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "daily": "temperature_2m_min,temperature_2m_max,sunrise,sunset,weather_code",
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "current": ",".join([
            "temperature_2m", "apparent_temperature", "precipitation", "rain",
            "showers", "snowfall", "weather_code", "cloud_cover", "wind_speed_10m",
            "is_day", "wind_direction_10m", "pressure_msl", "surface_pressure",
        ]),
        "timezone": "auto",
        "wind_speed_unit": "kmh",
        "forecast_days": 8,  # сьогодні + 7 днів прогнозу
    }
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


# ─────────────────────────── Parsed data ────────────────────────
@dataclass
class Day:
    date: datetime
    min_t: float | None
    max_t: float | None
    code: int | None
    sunrise: datetime | None
    sunset: datetime | None


@dataclass
class Hour:
    time: datetime
    temp: float | None
    code: int | None
    precip: float | None


@dataclass
class Parsed:
    now: datetime
    current: dict
    days: list[Day]
    hourly: list[Hour]

    @property
    def today(self) -> Day:
        return next(d for d in self.days if d.date.date() == self.now.date())

    @staticmethod
    def parse(data: dict) -> "Parsed":
        cur = data["current"]
        now = datetime.fromisoformat(cur["time"])

        d = data["daily"]
        days = [
            Day(
                date=datetime.fromisoformat(d["time"][i]),
                min_t=d["temperature_2m_min"][i],
                max_t=d["temperature_2m_max"][i],
                code=d.get("weather_code", [None] * len(d["time"]))[i],
                sunrise=datetime.fromisoformat(d["sunrise"][i]) if d["sunrise"][i] else None,
                sunset=datetime.fromisoformat(d["sunset"][i]) if d["sunset"][i] else None,
            )
            for i in range(len(d["time"]))
        ]

        h = data["hourly"]
        hourly = [
            Hour(
                time=datetime.fromisoformat(h["time"][i]),
                temp=h["temperature_2m"][i],
                code=h["weather_code"][i],
                precip=h["precipitation_probability"][i],
            )
            for i in range(len(h["time"]))
        ]
        return Parsed(now=now, current=cur, days=days, hourly=hourly)


# ─────────────────────────── Helpers ────────────────────────────
def round_away(value: float) -> int:
    return int(math.floor(abs(value) + 0.5)) * (1 if value >= 0 else -1)


def to_degree(value: float | None) -> str:
    return "n/a" if value is None else f"{round_away(value)}°"


WEEKDAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
WEEKDAYS_LOWER = ["понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя"]
MONTHS_GEN = ["січня", "лютого", "березня", "квітня", "травня", "червня",
              "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]


def format_date(dt: datetime) -> str:
    return f"{dt.day} {MONTHS_GEN[dt.month - 1]}, {WEEKDAYS_LOWER[dt.weekday()]}"


# ── WMO → опис (підмножина кодів, які повертає Open-Meteo) ──
WMO_DESCRIPTIONS = {
    0: "Ясно (хмари не розвиваються)",
    1: "Переважно ясно (хмари розсіюються)",
    2: "Мінлива хмарність (стан неба без змін)",
    3: "Хмарно (хмари розвиваються)",
    45: "Туман без змін, небо не видно",
    48: "Туман з утворенням паморозі, небо видно",
    51: "Суцільна слабка мряка",
    53: "Суцільна помірна мряка",
    55: "Суцільна сильна мряка",
    56: "Слабка замерзаюча мряка",
    57: "Помірна або сильна замерзаюча мряка",
    61: "Суцільний слабкий дощ",
    63: "Суцільний помірний дощ",
    65: "Суцільний сильний дощ",
    66: "Слабкий замерзаючий дощ",
    67: "Помірний або сильний замерзаючий дощ",
    71: "Суцільний слабкий сніг",
    73: "Суцільний помірний сніг",
    75: "Суцільний сильний сніг",
    77: "Сніжні зерна",
    80: "Слабка злива (зливовий дощ)",
    81: "Помірна або сильна злива",
    82: "Дуже сильна злива",
    85: "Слабкий зливовий сніг",
    86: "Помірний або сильний зливовий сніг",
    95: "Слабка або помірна гроза з дощем чи снігом",
    96: "Слабка або помірна гроза з градом",
    99: "Сильна гроза з градом",
}


def get_weather_description(code: int) -> str:
    if code < 0 or code > 99:
        return f"Некоректний код погоди ({code})"
    return WMO_DESCRIPTIONS.get(code, f"Невідомий код WMO ({code})")


# ── WMO → ім'я PNG-іконки ──
def map_weather_code_to_icon(code: int, is_day: bool) -> str:
    if code == 0:
        icon = "01d"
    elif code == 1:
        icon = "22d"
    elif code == 2:
        icon = "02d"
    elif code == 3:
        icon = "04d"
    elif code in (51, 61, 80):
        icon = "51d"
    elif code in (53, 63, 81):
        icon = "53d"
    elif code in (55, 65, 82):
        icon = "09d"
    elif code == 45:
        icon = "50d"
    elif code == 48:
        icon = "48d"
    elif code in (56, 66):
        icon = "56d"
    elif code in (57, 67):
        icon = "57d"
    elif code in (71, 85):
        icon = "71d"
    elif code == 73:
        icon = "73d"
    elif code in (75, 86):
        icon = "13d"
    elif code == 77:
        icon = "77d"
    elif code in (95, 96, 99):
        icon = "11d"
    else:
        icon = "01d"

    if not is_day:
        icon = {"01d": "01n", "22d": "22n", "02d": "02n", "10d": "10n"}.get(icon, icon)
    return icon


def get_png_path(code: int, is_day: bool) -> Path:
    return ICONS_DIR / f"{map_weather_code_to_icon(code, is_day)}.png"


# ─────────────────────────── Text drawing ───────────────────────
class TextFrom(Enum):
    LEFT = 0
    CENTER = 1
    RIGHT = 2


@lru_cache(maxsize=None)
def get_font(size_pt: int) -> ImageFont.FreeTypeFont:
    px = round(size_pt * 96 / 72)  # GDI+ використовує пункти при 96 dpi
    for name in (FONT_NAME, "LiberationSans.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def measure(text: str, size_pt: int) -> tuple[float, float]:
    """Наближення Graphics.MeasureString (GDI+ додає невеликі поля до ширини)."""
    font = get_font(size_pt)
    px = font.size
    ascent, descent = font.getmetrics()
    return font.getlength(text) + px / 6, float(ascent + descent)


def write_string(draw: ImageDraw.ImageDraw, text: str | None, size_pt: int, color,
                 offset_x: float, text_from: TextFrom, y: float,
                 right_x: float | None = None) -> int:
    if not text or not text.strip():
        return 0
    font = get_font(size_pt)
    w, h = measure(text, size_pt)

    if text_from == TextFrom.LEFT:
        x = offset_x
    elif text_from == TextFrom.CENTER:
        if right_x is not None:
            x = offset_x + (right_x - offset_x - w) / 2
        else:
            x = offset_x + (WIDTH - w) / 2
    else:
        x = WIDTH - w - offset_x

    draw.text((x, y), text, font=font, fill=color)
    return int(h)


def paste_icon(img: Image.Image, path: Path, x: float, y: float, size: int) -> bool:
    if not path.exists():
        return False
    icon = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    img.paste(icon, (int(x), int(y)), icon)
    return True


# ─────────────────────────── Smooth curve ───────────────────────
def cardinal_spline(points: list[tuple[float, float]], tension: float = 0.5,
                    samples: int = 12) -> list[tuple[float, float]]:
    """Аналог GraphicsPath.AddCurve / Graphics.DrawCurve (кардинальний сплайн)."""
    n = len(points)
    if n < 3:
        return list(points)
    tangents = []
    for i in range(n):
        p_prev = points[max(i - 1, 0)]
        p_next = points[min(i + 1, n - 1)]
        tangents.append((tension * (p_next[0] - p_prev[0]), tension * (p_next[1] - p_prev[1])))

    result = [points[0]]
    for i in range(n - 1):
        p0, p3 = points[i], points[i + 1]
        p1 = (p0[0] + tangents[i][0] / 3, p0[1] + tangents[i][1] / 3)
        p2 = (p3[0] - tangents[i + 1][0] / 3, p3[1] - tangents[i + 1][1] / 3)
        for s in range(1, samples + 1):
            t = s / samples
            mt = 1 - t
            x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
            y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
            result.append((x, y))
    return result


# ─────────────────────────── Forecast (7 днів) ──────────────────
def draw_forecast(img: Image.Image, draw: ImageDraw.ImageDraw, parsed: Parsed) -> None:
    size = WIDTH // 7
    days = [d for d in parsed.days if d.date.date() > parsed.now.date()][:7]

    for i, day in enumerate(days):
        x = 2 + i * size
        y = HEIGHT - size

        draw.rectangle([x, y, x + size - 5, y + size - 3], outline=GREEN)

        write_string(draw, WEEKDAYS[day.date.weekday()], 16, BLACK, x, TextFrom.CENTER,
                     y + 5, right_x=x + size - 2)

        icon_size = 64
        shift = (size - icon_size) // 2
        paste_icon(img, get_png_path(day.code if day.code is not None else 1, True),
                   x + shift, y + shift, icon_size)

        lo = "n/a" if day.min_t is None else round_away(day.min_t)
        hi = "n/a" if day.max_t is None else round_away(day.max_t)
        write_string(draw, f"{lo}° - {hi}°", 16, BLACK, x, TextFrom.CENTER,
                     y + size - 30, right_x=x + size - 2)


# ─────────────────────────── Diagram (24 год) ───────────────────
def draw_diagram(img: Image.Image, draw: ImageDraw.ImageDraw, parsed: Parsed) -> None:
    diagram_height = 80
    diagram_y = 90
    size = WIDTH // 24
    hours = [h for h in parsed.hourly if h.time.date() == parsed.now.date()]
    if not hours:
        return

    y = HEIGHT - diagram_height - diagram_y

    temps = [h.temp for h in hours if h.temp is not None]
    min_t = min(temps) if temps else 0
    max_t = max(temps) if temps else 0
    delta_t = max_t - min_t

    draw.line([(25, y), (25, y - diagram_height)], fill=GRAY)
    draw.line([(25, y), (24 * size, y)], fill=GRAY)

    koef = 1 if delta_t == 0 else diagram_height / delta_t

    def horizontal_marker(j: int) -> None:
        yy = y - j * koef
        draw.line([(25, yy), (24 * size, yy)], fill=GRAY)
        write_string(draw, to_degree(min_t + j), 8, BLACK, 2, TextFrom.LEFT, int(yy) - 10)

    for j in range(0, int(delta_t) + 1, 5):
        horizontal_marker(j)
    if delta_t < 5:
        horizontal_marker(5)

    # вертикальні лінії та підписи годин
    for j in range(4, 24, 4):
        draw.line([(j * size, y), (j * size, y - diagram_height)], fill=GRAY)
        write_string(draw, f"{j}:00", 8, BLACK, j * size - 15, TextFrom.LEFT, y + 2)

    # точки графіків
    rain_koef = diagram_height / 100.0
    temp_pts: list[tuple[float, float]] = []
    rain_pts: list[tuple[float, float]] = []
    for i, item in enumerate(hours):
        xx = 30 + i * size
        yy = y if item.temp is None else y - (item.temp - min_t) * koef
        temp_pts.append((xx, yy))
        rain_pts.append((xx, y - rain_koef * (item.precip or 0)))

    # Згладжені криві малюємо на збільшеному прозорому шарі
    layer = Image.new("RGBA", (WIDTH * SS, HEIGHT * SS), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    def scaled(pts):
        return [(px * SS, py * SS) for px, py in pts]

    temp_curve = cardinal_spline(temp_pts)
    fill_poly = [(temp_pts[0][0], y)] + temp_curve + [(temp_pts[-1][0], y)]
    ld.polygon(scaled(fill_poly), fill=ORANGE + (100,))
    ld.line(scaled(temp_curve), fill=DARK_ORANGE + (255,), width=3 * SS, joint="curve")
    ld.line(scaled(cardinal_spline(rain_pts)), fill=BLUE + (255,), width=3 * SS, joint="curve")

    layer = layer.resize((WIDTH, HEIGHT), Image.LANCZOS)
    img.paste(layer, (0, 0), layer)

    # іконки погоди по годинах
    today = parsed.today
    sunset = today.sunset.hour if today.sunset else 24
    sunrise = today.sunrise.hour if today.sunrise else 0

    x = 10
    icon_size = 30
    shift = (size - icon_size) + 10
    for j, item in enumerate(hours):
        is_day = sunrise <= j <= sunset
        path = get_png_path(item.code if item.code is not None else 1, is_day)
        if paste_icon(img, path, x + shift, y + shift, icon_size):
            x += icon_size + 2


# ─────────────────────────── PictureGenerator ───────────────────
def draw_current_icon(img: Image.Image, parsed: Parsed, current_y: int) -> int:
    cur = parsed.current
    path = get_png_path(cur.get("weather_code") if cur.get("weather_code") is not None else 1,
                        cur.get("is_day") == 1)
    paste_icon(img, path, 10, current_y + 10, 200)
    return 10 + 200


def draw_current_temp(draw: ImageDraw.ImageDraw, parsed: Parsed, current_y: int, shift_x: int) -> None:
    cur = parsed.current
    font_size = 85

    temp = "n/a"
    if cur.get("temperature_2m") is not None:
        temp = str(round_away(cur["temperature_2m"]))

    w, h = measure(temp, font_size)
    text_y = current_y + int(h / 2)
    write_string(draw, temp, font_size, BLUE, shift_x, TextFrom.LEFT, text_y)
    write_string(draw, "°", font_size, BLUE, shift_x + int(w) - 20, TextFrom.LEFT, text_y)

    current_y += int(h)

    apparent = cur.get("apparent_temperature")
    if apparent is not None:
        write_string(draw, f"feels like {to_degree(apparent)}", 18, ORANGE_RED,
                     shift_x + 15, TextFrom.LEFT, current_y + 35)

    today = parsed.today
    write_string(draw, f"{to_degree(today.min_t)} - {to_degree(today.max_t)}", 18, BLACK,
                 shift_x + 15, TextFrom.LEFT, current_y + 60)


HPA_TO_MMHG = 0.750062
# "surface_pressure" — тиск на рівні станції (як зазвичай показують в Україні),
# "pressure_msl" — приведений до рівня моря. Змініть за потреби.
PRESSURE_KEY = "surface_pressure"

COMPASS = ["Пн", "ПнСх", "Сх", "ПдСх", "Пд", "ПдЗх", "Зх", "ПнЗх"]


def compass_direction(degrees: float) -> str:
    return COMPASS[int((degrees % 360) / 45 + 0.5) % 8]


def draw_extra_info(draw: ImageDraw.ImageDraw, parsed: Parsed) -> None:
    """Тиск, вітер, схід/захід сонця — у вільному місці справа від температури."""
    cur = parsed.current
    today = parsed.today
    x = 450
    y = 95
    step = 40
    font_size = 18

    pressure = cur.get(PRESSURE_KEY)
    pressure_text = "n/a" if pressure is None else f"{round_away(pressure * HPA_TO_MMHG)} мм рт. ст."
    write_string(draw, f"тиск: {pressure_text}", font_size, BLACK, x, TextFrom.LEFT, y)

    wind = cur.get("wind_speed_10m")
    if wind is None:
        wind_text = "n/a"
    else:
        wind_text = f"{round_away(wind)} км/год"
        if cur.get("wind_direction_10m") is not None:
            wind_text += f", {compass_direction(cur['wind_direction_10m'])}"
    write_string(draw, f"вітер: {wind_text}", font_size, BLACK, x, TextFrom.LEFT, y + step)

    sunrise = f"{today.sunrise:%H:%M}" if today.sunrise else "n/a"
    sunset = f"{today.sunset:%H:%M}" if today.sunset else "n/a"
    write_string(draw, f"схід: {sunrise}   захід: {sunset}", font_size, BLACK,
                 x, TextFrom.LEFT, y + 2 * step)


def generate_picture(data: dict) -> Image.Image:
    parsed = Parsed.parse(data)

    img = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(img)

    write_string(draw, f"оновлено: {datetime.now():%d.%m.%Y %H:%M}", 8, BLACK, 5, TextFrom.RIGHT, 10)

    current_y = 10
    current_y += write_string(draw, format_date(parsed.now), 18, BLACK, 0, TextFrom.CENTER, current_y)

    code = parsed.current.get("weather_code")
    description = get_weather_description(code if code is not None else 1)
    write_string(draw, description.lower(), 15, GRAY, 0, TextFrom.CENTER, current_y)

    shift_x = draw_current_icon(img, parsed, current_y)
    current_y -= 40
    draw_current_temp(draw, parsed, current_y, shift_x)
    draw_extra_info(draw, parsed)

    draw_forecast(img, draw, parsed)
    draw_diagram(img, draw, parsed)

    return img


def create_picture() -> Image.Image:
    """Завантажує дані з Open-Meteo і повертає готову картинку (без запису у файл)."""
    return generate_picture(get_data())


# ─────────────────────────── Program ────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", default="", help="зберегти картинку у файл")
    args = parser.parse_args()

    img = create_picture()
    if args.output:
        img.save(args.output, "PNG")


if __name__ == "__main__":
    main()
