#!/usr/bin/env python3
"""観測地と時刻から天体の方位と高度を計算する（Skyfield を使用）。

方位は北を 0°、東を 90° とする。高度は既定で大気差を含む。
"""
import argparse
import re
import unicodedata
from pathlib import Path

from skyfield.api import Loader, Star, wgs84

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# 恒星は J2000 の位置と固有運動（Hipparcos）。カタログ全体は持たない
STARS = {
    "polaris": Star(ra_hours=(2, 31, 49.09), dec_degrees=(89, 15, 50.8),
                    ra_mas_per_year=44.48, dec_mas_per_year=-11.85),
    "vega": Star(ra_hours=(18, 36, 56.34), dec_degrees=(38, 47, 1.3),
                 ra_mas_per_year=200.94, dec_mas_per_year=286.23),
    "capella": Star(ra_hours=(5, 16, 41.36), dec_degrees=(45, 59, 52.8),
                    ra_mas_per_year=75.25, dec_mas_per_year=-426.89),
    "altair": Star(ra_hours=(19, 50, 46.99), dec_degrees=(8, 52, 6.0),
                   ra_mas_per_year=536.23, dec_mas_per_year=385.29),
}
# 一覧にない恒星や星雲・星団（J2000、固有運動は省略。導入の精度 0.05° に比べて小さい）
for _key, _ra, _dec in [
    ("alcyone", (3, 47, 29.08), (24, 6, 18.5)), ("m1", (5, 34, 31.94), (22, 0, 52.2)),
    ("m42", (5, 35, 17.3), (-5, -23, -28.0)), ("m31", (0, 42, 44.3), (41, 16, 9.0)),
    ("m13", (16, 41, 41.2), (36, 27, 35.0)), ("m57", (18, 53, 35.1), (33, 1, 45.0)),
    ("mirach", (1, 9, 43.92), (35, 37, 14.0)), ("aldebaran", (4, 35, 55.24), (16, 30, 33.5)),
    ("betelgeuse", (5, 55, 10.31), (7, 24, 25.4)), ("rigel", (5, 14, 32.27), (-8, -12, -5.9)),
    ("sirius", (6, 45, 8.92), (-16, -42, -58.0)), ("deneb", (20, 41, 25.9), (45, 16, 49.0)),
    ("albireo", (19, 30, 43.28), (27, 57, 34.8)),
]:
    STARS[_key] = Star(ra_hours=_ra, dec_degrees=_dec)
BODIES = {"moon": "moon", "sun": "sun", "mercury": "mercury", "mars": "mars", "venus": "venus",
          "jupiter": "jupiter barycenter", "saturn": "saturn barycenter",
          "uranus": "uranus barycenter", "neptune": "neptune barycenter"}
# 画面に出す名前と、検索で受け付ける別名
LABELS = {"polaris": "北極星", "vega": "ベガ", "capella": "カペラ", "altair": "アルタイル",
          "alcyone": "アルキオネ（プレアデス）", "m1": "M1 かに星雲", "m42": "M42 オリオン大星雲",
          "m31": "M31 アンドロメダ銀河", "m13": "M13 ヘルクレス座球状星団", "m57": "M57 環状星雲",
          "mirach": "ミラク", "aldebaran": "アルデバラン", "betelgeuse": "ベテルギウス", "rigel": "リゲル",
          "sirius": "シリウス", "deneb": "デネブ", "albireo": "アルビレオ",
          "moon": "月", "sun": "太陽", "mercury": "水星", "venus": "金星", "mars": "火星",
          "jupiter": "木星", "saturn": "土星", "uranus": "天王星", "neptune": "海王星"}
ALIASES = {"m45": "alcyone", "pleiades": "alcyone", "プレアデス": "alcyone", "すばる": "alcyone",
           "昴": "alcyone", "crab": "m1", "かに星雲": "m1", "orion nebula": "m42", "andromeda": "m31",
           "ring nebula": "m57"}
for _key, _label in LABELS.items():
    ALIASES.setdefault(_label.split("（")[0].split(" ")[-1].lower(), _key)


class TargetError(ValueError):
    pass


def _sexagesimal(text):
    """「3h47m29.08s」「3:47:29.08」「24°06'18.5"」「24 06 18.5」「56.87」を数にする。"""
    text = text.strip()
    sign = -1.0 if text.startswith("-") else 1.0
    body = text.lstrip("+-").strip()
    parts = [p for p in re.split(r"[hmsd°'\":\s]+", body, flags=re.I) if p]
    if not 1 <= len(parts) <= 3:
        raise TargetError(f"読めない値です: {text}")
    try:
        values = [float(p) for p in parts]
    except ValueError:
        raise TargetError(f"読めない値です: {text}") from None
    if values[0] < 0 or any(not 0 <= v < 60 for v in values[1:]):
        raise TargetError(f"分・秒は 0〜60 未満です: {text}")
    return sign * (values[0] + sum(v / 60 ** (i + 1) for i, v in enumerate(values[1:])))


def parse_radec(text):
    """赤経・赤緯（J2000）の文字列を (赤経 時, 赤緯 度) にする。
    赤経は h、m、s か : を含むか、3 つの数に分かれていれば時。小数 1 つだけなら度とみなす。
    例: 「3h47m29.08s +24°06'18.5"」「03:47:29.08 +24:06:18.5」「3 47 29.08 24 06 18.5」「56.87 24.105」"""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("′", "'").replace("″", '"').replace("−", "-").replace("’", "'").replace("”", '"')
    text = re.sub(r"(?i)\b(ra|dec)\b\s*[:=]?", " ", text).strip()
    sign_at = re.search(r"(?<=\S)\s*[+-]", text)
    if "," in text:
        ra_text, dec_text = text.split(",", 1)
    elif sign_at:
        ra_text, dec_text = text[:sign_at.start()], text[sign_at.start():]
    else:
        tokens = text.split()
        if len(tokens) == 2:
            ra_text, dec_text = tokens
        elif len(tokens) == 6:
            ra_text, dec_text = " ".join(tokens[:3]), " ".join(tokens[3:])
        elif len(tokens) == 4:
            ra_text, dec_text = " ".join(tokens[:2]), " ".join(tokens[2:])
        else:
            raise TargetError("赤経と赤緯を空白かカンマで区切って入力してください（例: 5h34m31.9s +22°00'52\"）")
    ra_text, dec_text = ra_text.strip(), dec_text.strip()
    if not ra_text or not dec_text:
        raise TargetError("赤経と赤緯の両方を入力してください")
    if ra_text.startswith("-"):
        raise TargetError("赤経は 0 以上です")
    hours = bool(re.search(r"[hms:]", ra_text, re.I)) or len(ra_text.split()) > 1
    ra = _sexagesimal(ra_text)
    ra_hours = ra if hours else ra / 15.0
    dec = _sexagesimal(dec_text)
    if not 0 <= ra_hours < 24:
        raise TargetError("赤経は 0〜24 時（0〜360°）の範囲です")
    if not -90 <= dec <= 90:
        raise TargetError("赤緯は −90〜+90° の範囲です")
    return ra_hours, dec


def format_radec(ra_hours, dec_degrees):
    """3h47m29.08s +24°06'18.5" の形にする。繰り上がりで 60 秒と書かないよう、整数で丸める。"""
    centi = round(ra_hours * 360000) % (24 * 360000)
    h, rest = divmod(centi, 360000)
    m, cs = divmod(rest, 6000)
    tenths = round(abs(dec_degrees) * 36000)
    d, rest = divmod(tenths, 36000)
    dm, ds = divmod(rest, 600)
    sign = "-" if dec_degrees < 0 else "+"
    return f"{h}h{m:02d}m{cs / 100:05.2f}s {sign}{d:02d}°{dm:02d}'{ds / 10:04.1f}\""


def resolve(query):
    """名前か赤経・赤緯から、追尾と導入に使う対象を返す。
    {"key", "label", "kind"（"catalog" / "coords"）, "object"（Skyfield の天体）}"""
    text = unicodedata.normalize("NFKC", str(query or "")).strip()
    if not text:
        raise TargetError("天体の名前か赤経・赤緯を入力してください")
    key = text.lower()
    key = ALIASES.get(key, key)
    key = key.replace(" ", "") if key.replace(" ", "") in LABELS else key
    if key in STARS or key in BODIES:
        target = STARS.get(key)
        return {"key": key, "label": LABELS.get(key, key), "kind": "catalog",
                "body": None if target else BODIES[key], "object": target}
    if not re.search(r"\d", text):
        raise TargetError(f"一覧にない名前です: {text}。赤経・赤緯で入力してください")
    ra_hours, dec = parse_radec(text)
    return {"key": f"radec:{ra_hours:.6f},{dec:.6f}", "label": format_radec(ra_hours, dec), "kind": "coords",
            "body": None, "object": Star(ra_hours=ra_hours, dec_degrees=dec), "ra_hours": ra_hours, "dec": dec}


class Sky:
    def __init__(self, latitude, longitude, elevation_m=0.0, data_dir=DATA_DIR):
        load = Loader(str(data_dir))
        self.timescale = load.timescale(builtin=True)
        self.ephemeris = load("de421.bsp")
        self.set_site(latitude, longitude, elevation_m)

    def set_site(self, latitude, longitude, elevation_m=0.0):
        """観測地を変える。標高は WGS84 の楕円体からの高さ。"""
        self.site = self.ephemeris["earth"] + wgs84.latlon(latitude, longitude, elevation_m)

    def now(self):
        return self.timescale.now()

    def _object(self, target):
        """名前（一覧のキー）、resolve() の結果、Skyfield の天体のどれでも受け付ける。"""
        if isinstance(target, str):
            target = resolve(target)
        if isinstance(target, dict):
            return target["object"] if target["object"] is not None else self.ephemeris[target["body"]]
        return target

    def altaz(self, name, time=None, refraction=True):
        target = self._object(name)
        apparent = self.site.at(self.now() if time is None else time).observe(target).apparent()
        if refraction:
            alt, az, _ = apparent.altaz(temperature_C=10.0, pressure_mbar=1013.25)
        else:
            alt, az, _ = apparent.altaz()
        return az.degrees, alt.degrees

    def radec_j2000(self, name, time=None):
        """観測地から見た J2000（ICRS）の赤経（時）と赤緯（度）。SynScan の `r` に渡す値。
        月は視差があるので、地球の中心ではなく観測地から見た位置を使う。"""
        time = self.now() if time is None else time
        ra, dec, _ = self.site.at(time).observe(self._object(name)).radec()
        return ra.hours, dec.degrees

    def rates(self, name, time=None, step=30.0):
        """方位と高度の変化の速さを秒角/秒で返す。"""
        time = self.now() if time is None else time
        before = self.altaz(name, self.timescale.tt_jd(time.tt - step / 86400))
        after = self.altaz(name, self.timescale.tt_jd(time.tt + step / 86400))
        d_az = (after[0] - before[0] + 180.0) % 360.0 - 180.0
        return d_az * 3600.0 / (2 * step), (after[1] - before[1]) * 3600.0 / (2 * step)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("names", nargs="*", default=["polaris", "vega", "capella", "altair", "moon", "sun"])
    args = parser.parse_args()
    sky = Sky(args.lat, args.lon)
    time = sky.now()
    print(time.utc_iso())
    for name in args.names:
        az, alt = sky.altaz(name, time)
        print(f"{name:10} az={az:8.3f} alt={alt:8.3f}")


if __name__ == "__main__":
    main()
