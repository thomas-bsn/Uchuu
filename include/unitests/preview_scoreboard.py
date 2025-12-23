from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import os

W, H = 980, 560

def load_font(size: int):
    # Fallback: essaye DejaVu (souvent dispo Linux), sinon police par défaut
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except Exception:
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()

def draw_champion_icon(draw: ImageDraw.ImageDraw, x: int, y: int, champ: str, size: int, accent):
    # Placeholder : carré + initiale
    draw.rounded_rectangle((x, y, x + size, y + size), radius=10, outline=accent, width=2, fill=(24, 24, 30, 255))
    initial = (champ[:1] or "?").upper()
    f = load_font(18)
    tw = draw.textlength(initial, font=f)
    draw.text((x + (size - tw) / 2, y + 8), initial, font=f, fill=(235, 235, 235, 255))

def fmt_player(p):
    name = p["name"]
    champ = p["champion"]
    kda = p["kda"]
    cs = p.get("cs")
    lvl = p.get("lvl")
    extra = []
    if lvl is not None:
        extra.append(f"lvl {lvl}")
    if cs is not None:
        extra.append(f"{cs} cs")
    return name, champ, kda, (" · ".join(extra) if extra else "")

def render(match: dict, out_path: str = "scoreboard.png"):
    img = Image.new("RGBA", (W, H), (16, 16, 20, 255))
    draw = ImageDraw.Draw(img)

    title_f = load_font(30)
    sub_f = load_font(18)
    row_f = load_font(18)
    small_f = load_font(15)

    # Header
    title = f"{match['result']}  •  Custom 5v5  •  {match['duration']}"
    draw.text((26, 18), title, font=title_f, fill=(240, 240, 240, 255))

    score = f"{match['team1_kills']} - {match['team2_kills']}"
    draw.text((W - 160, 20), score, font=title_f, fill=(240, 240, 240, 255))

    meta = f"ID partie: {match.get('game_id','?')}  •  Généré: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    draw.text((26, 58), meta, font=small_f, fill=(170, 170, 180, 255))

    # Panels
    left_x, right_x = 26, 502
    top_y = 95
    panel_w, panel_h = 452, 430

    # Panel backgrounds
    draw.rounded_rectangle((left_x, top_y, left_x + panel_w, top_y + panel_h), radius=18, fill=(22, 22, 28, 255))
    draw.rounded_rectangle((right_x, top_y, right_x + panel_w, top_y + panel_h), radius=18, fill=(22, 22, 28, 255))

    # Titles
    blue = (80, 160, 255, 255)
    red = (255, 110, 130, 255)
    draw.text((left_x + 18, top_y + 14), "Équipe 1", font=sub_f, fill=blue)
    draw.text((right_x + 18, top_y + 14), "Équipe 2", font=sub_f, fill=red)

    # Rows
    row_h = 72
    start_y = top_y + 55

    def draw_team(team, x, accent):
        for i, p in enumerate(team):
            y = start_y + i * row_h
            bg = (28, 28, 36, 255) if i % 2 == 0 else (24, 24, 32, 255)
            draw.rounded_rectangle((x + 12, y, x + panel_w - 12, y + row_h - 10), radius=16, fill=bg)

            # icon
            draw_champion_icon(draw, x + 22, y + 12, p["champion"], 46, accent)

            name, champ, kda, extra = fmt_player(p)
            draw.text((x + 80, y + 14), name, font=row_f, fill=(240, 240, 240, 255))
            draw.text((x + 80, y + 40), champ, font=small_f, fill=(170, 170, 180, 255))

            # KDA right aligned-ish
            draw.text((x + 310, y + 18), kda, font=row_f, fill=(240, 240, 240, 255))
            if extra:
                draw.text((x + 310, y + 42), extra, font=small_f, fill=(170, 170, 180, 255))

    draw_team(match["team1"], left_x, blue)
    draw_team(match["team2"], right_x, red)

    img.convert("RGB").save(out_path, "PNG")
    return out_path

if __name__ == "__main__":
    sample = {
        "result": "VICTOIRE",
        "duration": "33:54",
        "team1_kills": 40,
        "team2_kills": 17,
        "game_id": "custom_1868_1777",
        "team1": [
            {"name": "ACOUSTICWHØRE", "champion": "Vayne", "kda": "10 / 4 / 12", "lvl": 15, "cs": 183},
            {"name": "LE93 C EST BIEN", "champion": "Zac", "kda": "4 / 4 / 23", "lvl": 16, "cs": 0},
            {"name": "WakandaForeverHZ", "champion": "Renekton", "kda": "11 / 3 / 13", "lvl": 17, "cs": 0},
            {"name": "Haerin", "champion": "Milio", "kda": "2 / 5 / 24", "lvl": 14, "cs": 0},
            {"name": "SANGUINIUS", "champion": "Anivia", "kda": "13 / 1 / 9", "lvl": 17, "cs": 0},
        ],
        "team2": [
            {"name": "Charli", "champion": "Zeri", "kda": "6 / 7 / 6", "lvl": 14, "cs": 0},
            {"name": "Hanni", "champion": "Ziggs", "kda": "1 / 8 / 7", "lvl": 14, "cs": 0},
            {"name": "WHITE KNIGHT", "champion": "Thresh", "kda": "0 / 8 / 12", "lvl": 13, "cs": 0},
            {"name": "Goultard", "champion": "DrMundo", "kda": "6 / 6 / 4", "lvl": 16, "cs": 0},
            {"name": "UnrealFrog", "champion": "Ambessa", "kda": "3 / 11 / 8", "lvl": 14, "cs": 0},
        ],
    }

    out = render(sample, "scoreboard.png")
    print("Generated:", os.path.abspath(out))
