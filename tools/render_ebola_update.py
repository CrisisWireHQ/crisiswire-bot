"""CrisisWire — daily Ebola Outbreak Update card renderer.

Run from the repo root or anywhere with this Python on PATH:

    py tools/render_ebola_update.py \\
        --date "MAY 22, 2026" \\
        --congo-cases 827 --congo-cases-delta "+146" \\
        --congo-deaths 175 --congo-deaths-delta "+37" \\
        --uganda-cases 2  --uganda-cases-delta "—" \\
        --uganda-deaths 1 --uganda-deaths-delta "—" \\
        --total-cases 829 --total-cases-delta "+146" \\
        --total-deaths 176 --total-deaths-delta "+37"

Output PNG is written to the Desktop by default
(ebola_outbreak_update_<ISO-date>.png). Pass --out PATH to override.

Requirements: Pillow + an internet connection on first run (the country
GeoJSON is fetched once; pass --geojson PATH to use a local cached copy).
"""
from __future__ import annotations
import argparse, json, math, os, sys, urllib.request
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ----- Palette ----------------------------------------------------------
BG       = (10, 10, 14)
PANEL    = (22, 23, 28)
PANEL_HI = (32, 33, 39)
LINE     = (52, 54, 62)
WHITE    = (245, 246, 248)
MUTE     = (150, 155, 165)
SUB      = (180, 184, 192)
RED      = (215, 38, 44)
RED_DK   = (152, 24, 28)
YELLOW   = (252, 209, 22)
SKYBLUE  = (117, 180, 226)

AFRICA_ISO = {"DZA","AGO","BEN","BWA","BFA","BDI","CMR","CPV","CAF","TCD","COM",
 "COG","COD","DJI","EGY","GNQ","ERI","ETH","GAB","GMB","GHA","GIN","GNB","CIV",
 "KEN","LSO","LBR","LBY","MDG","MWI","MLI","MRT","MUS","MAR","MOZ","NAM","NER",
 "NGA","RWA","STP","SEN","SLE","SOM","ZAF","SSD","SDN","SWZ","TZA","TGO","TUN",
 "UGA","ZMB","ZWE","ESH"}
GEOJSON_URL = ("https://raw.githubusercontent.com/johan/"
               "world.geo.json/master/countries.geo.json")


def load_geojson(local_path: str | None) -> dict:
    if local_path and Path(local_path).is_file():
        return json.loads(Path(local_path).read_text(encoding="utf-8"))
    with urllib.request.urlopen(GEOJSON_URL, timeout=30) as r:
        return json.load(r)


def render(args) -> str:
    S = 2
    W, H = 1600, 900

    img = Image.new("RGBA", (W*S, H*S), (*BG, 255))
    d = ImageDraw.Draw(img)

    def F(sz, bold=True):
        return ImageFont.truetype(args.font_bold if bold else args.font_reg, sz*S)
    def text(xy, s, font, fill, anchor="la"):
        d.text((xy[0]*S, xy[1]*S), s, font=font, fill=fill, anchor=anchor)
    def rrect(xyxy, r, fill=None, outline=None, width=0):
        x0,y0,x1,y1 = xyxy
        d.rounded_rectangle([x0*S,y0*S,x1*S,y1*S], radius=r*S, fill=fill,
                             outline=outline, width=width*S)

    # soft red glow upper-right
    glow = Image.new("RGBA", (W*S, H*S), (0,0,0,0))
    gd = ImageDraw.Draw(glow)
    for i, a in enumerate((26, 18, 12, 6)):
        rr = (260 + i*80) * S
        cx, cy = (W-160)*S, 80*S
        gd.ellipse([cx-rr, cy-rr, cx+rr, cy+rr], fill=(220, 40, 44, a))
    glow = glow.filter(ImageFilter.GaussianBlur(40))
    img.alpha_composite(glow); d = ImageDraw.Draw(img)

    gj = load_geojson(args.geojson)

    def feat_rings(feat):
        g=feat["geometry"]; t=g["type"]; cs=g["coordinates"]
        if t=="Polygon": return [cs[0]]
        if t=="MultiPolygon": return [p[0] for p in cs]
        return []

    def draw_africa(rect, hot_iso, base=(70,75,84), hot=RED):
        x0,y0,x1,y1 = rect
        lon0,lon1,lat0,lat1 = -19.0,52.0,-36.0,38.0
        sc = min((x1-x0)/(lon1-lon0), (y1-y0)/(lat1-lat0))
        ox = x0 + ((x1-x0) - sc*(lon1-lon0))/2
        oy = y0 + ((y1-y0) - sc*(lat1-lat0))/2
        def p(lon,lat): return ((ox+(lon-lon0)*sc)*S, (oy+(lat1-lat)*sc)*S)
        for feat in gj["features"]:
            iso = feat.get("id")
            if iso not in AFRICA_ISO: continue
            fill = hot if iso == hot_iso else base
            for ring in feat_rings(feat):
                pts=[p(lo,la) for lo,la in ring]
                if len(pts)>=3:
                    d.polygon(pts, fill=fill, outline=fill)

    def circle_mask(diameter):
        m=Image.new("L",(diameter,diameter),0)
        ImageDraw.Draw(m).ellipse([0,0,diameter-1,diameter-1], fill=255)
        return m

    def paste_flag(cx, cy, radius, flag):
        diam = radius*2*S
        flag = flag.resize((diam, diam), Image.LANCZOS)
        img.paste(flag, ((cx-radius)*S, (cy-radius)*S), circle_mask(diam))
        d.ellipse([(cx-radius)*S,(cy-radius)*S,(cx+radius)*S,(cy+radius)*S],
                  outline=(70,75,84), width=2*S)

    def make_drc_flag(size=240):
        f = Image.new("RGB", (size, size), SKYBLUE)
        strip_h = int(size*0.22)
        band  = Image.new("RGBA",(int(size*1.6), strip_h), (215,38,44,255))
        yband = Image.new("RGBA",(int(size*1.6), strip_h+int(size*0.06)),
                          (252,209,22,255))
        f.paste(yband.rotate(28, expand=True, resample=Image.BICUBIC),
                ((size - yband.rotate(28, expand=True).width)//2,
                 (size - yband.rotate(28, expand=True).height)//2),
                yband.rotate(28, expand=True, resample=Image.BICUBIC))
        f.paste(band.rotate(28, expand=True, resample=Image.BICUBIC),
                ((size - band.rotate(28, expand=True).width)//2,
                 (size - band.rotate(28, expand=True).height)//2),
                band.rotate(28, expand=True, resample=Image.BICUBIC))
        cx,cy = int(size*0.27), int(size*0.27)
        rout,rin = size*0.13, size*0.055
        pts=[(cx + (rout if i%2==0 else rin)*math.cos(-math.pi/2+i*math.pi/5),
              cy + (rout if i%2==0 else rin)*math.sin(-math.pi/2+i*math.pi/5))
             for i in range(10)]
        ImageDraw.Draw(f).polygon(pts, fill=(252,209,22))
        return f

    def make_uganda_flag(size=240):
        bands=[(0,0,0),(252,209,22),(215,38,44),(0,0,0),(252,209,22),(215,38,44)]
        f = Image.new("RGB",(size,size), bands[0])
        fd = ImageDraw.Draw(f)
        h = size/6
        for i,c in enumerate(bands):
            fd.rectangle([0,int(i*h),size,int((i+1)*h)], fill=c)
        r = int(size*0.18)
        fd.ellipse([size//2-r,size//2-r,size//2+r,size//2+r], fill=(245,245,245))
        return f

    def draw_virion(cx, cy, r):
        d.ellipse([(cx-r)*S,(cy-r)*S,(cx+r)*S,(cy+r)*S],
                  fill=RED, outline=RED_DK, width=2*S)
        for i in range(14):
            a = i*(2*math.pi/14)
            x0=cx+r*math.cos(a); y0=cy+r*math.sin(a)
            x1=cx+(r+r*0.45)*math.cos(a); y1=cy+(r+r*0.45)*math.sin(a)
            d.line([x0*S,y0*S,x1*S,y1*S], fill=RED, width=3*S)
            d.ellipse([(x1-r*0.10)*S,(y1-r*0.10)*S,
                       (x1+r*0.10)*S,(y1+r*0.10)*S], fill=RED)

    # ---- Header ---------------------------------------------------------
    LOGO_X0, LOGO_Y0, LOGO_SIZE = 60, 48, 140
    if args.logo and Path(args.logo).is_file():
        logo = Image.open(args.logo).convert("RGBA")
        logo = logo.resize((LOGO_SIZE*S, LOGO_SIZE*S), Image.LANCZOS)
        mask = Image.new("L", (LOGO_SIZE*S, LOGO_SIZE*S), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0,0,LOGO_SIZE*S-1,LOGO_SIZE*S-1], radius=16*S, fill=255)
        img.paste(logo, (LOGO_X0*S, LOGO_Y0*S), mask)
    text((W//2, 78), "EBOLA", F(96), WHITE, anchor="ma")
    text((W//2, 180), "OUTBREAK UPDATE", F(34), WHITE, anchor="ma")
    # date pill
    DX0,DY0,DX1,DY1 = 1240,70,1540,160
    rrect((DX0,DY0,DX1,DY1), r=12, fill=RED)
    cgx, cgy = DX0+38, (DY0+DY1)//2
    d.rounded_rectangle([(cgx-22)*S,(cgy-18)*S,(cgx+22)*S,(cgy+22)*S],
                        radius=4*S, outline=WHITE, width=3*S)
    d.line([(cgx-22)*S,(cgy-8)*S,(cgx+22)*S,(cgy-8)*S], fill=WHITE, width=3*S)
    d.line([(cgx-12)*S,(cgy-22)*S,(cgx-12)*S,(cgy-14)*S], fill=WHITE, width=3*S)
    d.line([(cgx+12)*S,(cgy-22)*S,(cgx+12)*S,(cgy-14)*S], fill=WHITE, width=3*S)
    text((cgx+34, (DY0+DY1)//2), args.date.upper(), F(30), WHITE, anchor="lm")

    # ---- Country cards --------------------------------------------------
    def stat_block(cx, cy, label, value, delta):
        text((cx, cy-58), label, F(22), SUB, anchor="ma")
        text((cx, cy+2),  str(value), F(72), RED, anchor="mm")
        if delta:
            text((cx, cy+50), str(delta), F(24), MUTE, anchor="ma")

    def country_card(top, name, flag, hot_iso, s1, s2):
        rrect((60, top, 1540, top+190), r=14, fill=PANEL, outline=LINE, width=2)
        d.rounded_rectangle([60*S, top*S, 70*S, (top+190)*S], radius=4*S, fill=RED)
        paste_flag(140, top+95, 56, flag)
        text((220, top+95), name, F(48), WHITE, anchor="lm")
        d.line([(540)*S,(top+30)*S,(540)*S,(top+160)*S], fill=LINE, width=2*S)
        stat_block(700, top+95, *s1)
        d.line([(900)*S,(top+30)*S,(900)*S,(top+160)*S], fill=LINE, width=2*S)
        stat_block(1060, top+95, *s2)
        d.line([(1230)*S,(top+30)*S,(1230)*S,(top+160)*S], fill=LINE, width=2*S)
        draw_africa((1255, top+15, 1525, top+175), hot_iso)

    country_card(225, "DR CONGO", make_drc_flag(), "COD",
                 ("CASES",  args.congo_cases,  args.congo_cases_delta),
                 ("DEATHS", args.congo_deaths, args.congo_deaths_delta))
    country_card(435, "UGANDA",   make_uganda_flag(), "UGA",
                 (args.uganda_cases_label, args.uganda_cases,  args.uganda_cases_delta),
                 ("DEATHS", args.uganda_deaths, args.uganda_deaths_delta))

    # ---- Total bar ------------------------------------------------------
    TY0, TY1 = 640, 790
    rrect((60, TY0, 1540, TY1), r=14, fill=PANEL_HI, outline=LINE, width=2)
    d.rounded_rectangle([60*S, TY0*S, 70*S, TY1*S], radius=4*S, fill=RED)
    draw_virion(150, (TY0+TY1)//2, 42)
    text((230, (TY0+TY1)//2), "TOTAL", F(52), WHITE, anchor="lm")
    def total_stat(cx, label, value, delta):
        text((cx, TY0+24),  label, F(22), SUB, anchor="ma")
        text((cx, TY0+76),  str(value), F(64), RED, anchor="mm")
        text((cx, TY0+118), str(delta), F(22), MUTE, anchor="ma")
    total_stat(820,  "CASES",  args.total_cases,  args.total_cases_delta)
    d.line([(990)*S,(TY0+22)*S,(990)*S,(TY1-22)*S], fill=LINE, width=2*S)
    total_stat(1230, "DEATHS", args.total_deaths, args.total_deaths_delta)

    # ---- Footer ---------------------------------------------------------
    text((W//2, 845), args.sources, F(18), MUTE, anchor="ma")

    out = args.out or str(Path.home() / "OneDrive" / "Desktop"
                           / f"ebola_outbreak_update_{datetime.now():%Y-%m-%d}.png")
    img.convert("RGB").resize((W, H), Image.LANCZOS).save(out, "PNG")
    return out


def main():
    desktop = Path.home() / "OneDrive" / "Desktop"
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", required=True, help='e.g. "MAY 22, 2026"')
    # Country: Congo
    p.add_argument("--congo-cases", required=True)
    p.add_argument("--congo-cases-delta", default="")
    p.add_argument("--congo-deaths", required=True)
    p.add_argument("--congo-deaths-delta", default="")
    # Country: Uganda
    p.add_argument("--uganda-cases", required=True)
    p.add_argument("--uganda-cases-delta", default="")
    p.add_argument("--uganda-cases-label", default="CONFIRMED CASES")
    p.add_argument("--uganda-deaths", required=True)
    p.add_argument("--uganda-deaths-delta", default="")
    # Total
    p.add_argument("--total-cases", required=True)
    p.add_argument("--total-cases-delta", default="")
    p.add_argument("--total-deaths", required=True)
    p.add_argument("--total-deaths-delta", default="")
    # Branding / sources
    p.add_argument("--logo", default=str(desktop / "cw_logo.png"),
                   help="Path to CW logo PNG (default: Desktop/cw_logo.png)")
    p.add_argument("--sources", default=(
        "SOURCES:  MINISTRY OF HEALTH (DR CONGO)   •   "
        "MINISTRY OF HEALTH (UGANDA)   •   WORLD HEALTH ORGANIZATION"))
    p.add_argument("--font-bold", default="C:/Windows/Fonts/arialbd.ttf")
    p.add_argument("--font-reg",  default="C:/Windows/Fonts/arial.ttf")
    p.add_argument("--geojson", default="",
                   help="Local path to a cached countries.geo.json (else fetched)")
    p.add_argument("--out", default="", help="Output PNG path")
    args = p.parse_args()
    print("rendered:", render(args))


if __name__ == "__main__":
    main()
