"""
logo_tp.py — Simbolul site-ului („Primăria din grafice”, oct. 2026).

Acoperișul primăriei peste coloane care sunt bare de grafic în creștere, pe un pătrat
rotunjit. Desenul e definit O SINGURĂ DATĂ, pe o grilă de 48×48 (FORME), și de aici
ies toate formele lui:
  - simbol_svg()        SVG-ul din meniu (site_shell.header_html); culorile vin din CSS
                        (.tp-logo în assets/tp.css), deci se schimbă cu tema întunecată;
  - logo_svg()          SVG cu culori fixe (assets/logo.svg);
  - deseneaza_simbol()  aceeași formă desenată cu Pillow, pentru imaginile de distribuire
                        (og-image.png, og/…) și pentru iconițe.

Iconițele (favicon.ico, icon-192.png, icon-512.png, icon-maskable-512.png,
apple-touch-icon.png) și assets/logo.svg se refac rulând:  python logo_tp.py
"""
import os

GRILA = 48
RAZA_FUNDAL = 11

# (tip, culoare, geometrie) — culoare: "fg" (clădirea) sau "hi" (bara cea mai înaltă)
FORME = [
    ("poli", "fg", ((8, 18.5), (24, 8), (40, 18.5))),         # acoperișul (fronton)
    ("drept", "fg", (11, 30, 5, 7, 0)),                       # bare = coloane, în creștere
    ("drept", "fg", (18, 26.5, 5, 10.5, 0)),
    ("drept", "fg", (25, 23, 5, 14, 0)),
    ("drept", "hi", (32, 20, 5, 17, 0)),
    ("drept", "fg", (8, 38.5, 32, 3, 0.8)),                   # treapta / soclul
]

# Culorile fixe (paleta temei „Registru” din assets/tp.css)
CULORI_LUMINOS = {"bg": "#1D3F63", "fg": "#FFFFFF", "hi": "#9CC0E6"}
# pe fundalul bleumarin al imaginilor de distribuire (#14263D)
CULORI_OG = {"bg": "#4D86C2", "fg": "#14263D", "hi": "#FFFFFF"}


def _corp_svg(bg: str, fg: str, hi: str) -> str:
    culori = {"fg": fg, "hi": hi}
    parti = [f'<rect width="{GRILA}" height="{GRILA}" rx="{RAZA_FUNDAL}" fill="{bg}"/>']
    for tip, c, g in FORME:
        if tip == "poli":
            puncte = " ".join(f"{x:g} {y:g}" for x, y in g)
            parti.append(f'<path d="M{puncte}z" fill="{culori[c]}"/>')
        else:
            x, y, w, h, rx = g
            r = f' rx="{rx:g}"' if rx else ""
            parti.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}"{r} fill="{culori[c]}"/>')
    return "".join(parti)


def simbol_svg(px: int = 44, clasa: str = "tp-logo") -> str:
    """SVG pentru pagină, decorativ (numele site-ului e text alături). Lățimea și înălțimea
    sunt fixe, ca meniul să nu se mute când se încarcă pagina (CLS)."""
    corp = _corp_svg("var(--tp-logo-bg,#1D3F63)", "var(--tp-logo-fg,#fff)", "var(--tp-logo-hi,#9CC0E6)")
    return (f'<svg class="{clasa}" width="{px}" height="{px}" viewBox="0 0 {GRILA} {GRILA}" '
            f'aria-hidden="true" focusable="false">{corp}</svg>')


def logo_svg(culori: dict = CULORI_LUMINOS) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{GRILA}" height="{GRILA}" '
            f'viewBox="0 0 {GRILA} {GRILA}"><title>Transparența Pantelimon</title>'
            f'{_corp_svg(culori["bg"], culori["fg"], culori["hi"])}</svg>\n')


def deseneaza_simbol(marime: int, culori: dict = CULORI_LUMINOS, plin: bool = False,
                     umplere: float = 1.0):
    """Simbolul ca imagine RGBA marime×marime (Pillow), desenat de 4× mai mare și micșorat,
    ca marginile să fie netede.

    plin=True: fundal pătrat, fără colțuri rotunjite (iOS și Android le rotunjesc singure).
    umplere: cât din imagine ocupă grila de 48 (sub 1 lasă margine pentru iconițe „maskable”).
    """
    from PIL import Image, ImageDraw

    ss = 4
    lat = marime * ss
    img = Image.new("RGBA", (lat, lat), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if plin:
        d.rectangle([0, 0, lat, lat], fill=culori["bg"])
    else:
        d.rounded_rectangle([0, 0, lat - 1, lat - 1], radius=RAZA_FUNDAL * lat / GRILA, fill=culori["bg"])
    k = lat * umplere / GRILA
    dx = (lat - GRILA * k) / 2
    for tip, c, g in FORME:
        if tip == "poli":
            d.polygon([(dx + x * k, dx + y * k) for x, y in g], fill=culori[c])
        else:
            x, y, w, h, rx = g
            box = [dx + x * k, dx + y * k, dx + (x + w) * k - 1, dx + (y + h) * k - 1]
            if rx:
                d.rounded_rectangle(box, radius=rx * k, fill=culori[c])
            else:
                d.rectangle(box, fill=culori[c])
    return img.resize((marime, marime), Image.LANCZOS)


def lipeste_simbol(img, x: int, y: int, marime: int, culori: dict = CULORI_OG) -> None:
    """Pune simbolul pe o imagine RGB existentă (colțul stânga-sus în x, y)."""
    s = deseneaza_simbol(marime, culori)
    img.paste(s, (x, y), s)


def genereaza_iconite(radacina: str = ".") -> list:
    """Scrie iconițele site-ului și assets/logo.svg. Întoarce lista fișierelor scrise."""
    p = lambda *a: os.path.join(radacina, *a)  # noqa: E731
    scrise = []

    def salveaza(img, nume):
        img.save(p(nume), "PNG", optimize=True)
        scrise.append(nume)

    # favicon.ico: fiecare mărime desenată separat (la 16 px se vede mai clar decât micșorat)
    mari = [deseneaza_simbol(m) for m in (48, 32, 16)]
    mari[0].save(p("favicon.ico"), format="ICO", sizes=[(48, 48), (32, 32), (16, 16)],
                 append_images=mari[1:])
    scrise.append("favicon.ico")
    salveaza(deseneaza_simbol(192), "icon-192.png")
    salveaza(deseneaza_simbol(512), "icon-512.png")
    # „maskable”: Android taie forma (cerc, picătură…); desenul stă în zona sigură de 80%
    salveaza(deseneaza_simbol(512, plin=True, umplere=0.78), "icon-maskable-512.png")
    # iOS nu acceptă transparență (colțurile ar ieși negre) și rotunjește singur
    salveaza(deseneaza_simbol(180, plin=True, umplere=0.92).convert("RGB"), "apple-touch-icon.png")
    with open(p("assets", "logo.svg"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(logo_svg())
    scrise.append("assets/logo.svg")
    return scrise


if __name__ == "__main__":
    for f in genereaza_iconite(os.path.dirname(os.path.abspath(__file__))):
        print(f"  [OK] {f}")
