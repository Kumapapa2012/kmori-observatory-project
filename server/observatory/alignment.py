"""架台の読み取り（軸の角度）と本当の方位・高度の対応（向きのモデル）。

モデルは方位と高度のずれ（az_offset、alt_offset）と、架台の傾き（tilt_x、tilt_y）の 4 つ。
傾きは、軸の角度で求めた向きを、北（x）と東（y）の水平軸まわりに回す小さな回転（度）で表す。
1 つの基準星や北・水平の電源投入ではずれだけ、プレートソルブで 2 点以上解くと傾きも求まる
（fit）。古い記録に傾きがなければ 0 とみなす。
"""
import math
import time

# 架台の時計は電源投入からの経過で進むので、実時間との差が変われば電源が入り直されたと分かる
CLOCK_TOLERANCE = 300.0


def wrap360(angle):
    return angle % 360.0


def wrap180(angle):
    return (angle + 180.0) % 360.0 - 180.0


def register(star, sky_position, raw, clock_time, now=None):
    now = time.time() if now is None else now
    return {
        "star": star,
        "time": now,
        "az_offset": wrap180(sky_position[0] - raw["az"]),
        "alt_offset": sky_position[1] - raw["alt"],
        "clock_offset": clock_time - now,
    }


def _vector(az, alt):
    a, h = math.radians(az), math.radians(alt)
    return (math.cos(h) * math.cos(a), math.cos(h) * math.sin(a), math.sin(h))


def _angles(v):
    x, y, z = v
    return wrap360(math.degrees(math.atan2(y, x))), math.degrees(math.atan2(z, math.hypot(x, y)))


def _tilt_matrix(tilt_x, tilt_y):
    """北（x）と東（y）の軸まわりの回転ベクトル (tilt_x, tilt_y, 0)（度）の回転行列（ロドリゲスの式）。"""
    wx, wy = math.radians(tilt_x), math.radians(tilt_y)
    angle = math.hypot(wx, wy)
    if angle < 1e-12:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    kx, ky = wx / angle, wy / angle
    c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return ((c + kx * kx * t, kx * ky * t, ky * s),
            (kx * ky * t, c + ky * ky * t, -kx * s),
            (-ky * s, kx * s, c))


def _apply(m, v, transpose=False):
    if transpose:
        return tuple(sum(m[j][i] * v[j] for j in range(3)) for i in range(3))
    return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def params_of(alignment):
    return {"az_offset": alignment.get("az_offset", 0.0), "alt_offset": alignment.get("alt_offset", 0.0),
            "tilt_x": alignment.get("tilt_x", 0.0), "tilt_y": alignment.get("tilt_y", 0.0)}


def sky_of(params, raw):
    """軸の角度から本当の方位・高度（度）。"""
    p = params_of(params)
    az, alt = raw["az"] + p["az_offset"], raw["alt"] + p["alt_offset"]
    if p["tilt_x"] or p["tilt_y"]:
        az, alt = _angles(_apply(_tilt_matrix(p["tilt_x"], p["tilt_y"]), _vector(az, alt)))
    return {"az": wrap360(az), "alt": wrap180(alt)}


def axis_of(params, az, alt, near_az=0.0):
    """本当の方位・高度から軸の角度。方位は near_az（軸の角度）に最も近い向きで返す。"""
    p = params_of(params)
    if p["tilt_x"] or p["tilt_y"]:
        az, alt = _angles(_apply(_tilt_matrix(p["tilt_x"], p["tilt_y"]), _vector(az, alt), transpose=True))
    axis_az = az - p["az_offset"]
    return {"az": near_az + wrap180(axis_az - near_az), "alt": alt - p["alt_offset"]}


def pointing(alignment, raw):
    """校正の結果から現在の向きを求める。"""
    return sky_of(alignment, raw)


def separation(az1, alt1, az2, alt2):
    a, b = _vector(az1, alt1), _vector(az2, alt2)
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))))


FIT_NAMES = ("az_offset", "alt_offset", "tilt_x", "tilt_y")


def fit(samples, start=None, tilt_sigma=3.0, iterations=30):
    """解いた点（軸の角度 raw と本当の方位・高度 sky の組）から向きのモデルを求める。

    1 点ならずれだけ、2 点以上なら傾きも求める。2 点では式と未知数が同じ数で残差が 0 になるので、
    傾きは tilt_sigma（度）程度に収まるよう弱く抑える。戻り値は (params, 各点の残差（度）)。"""
    params = {**{n: 0.0 for n in FIT_NAMES}, **(params_of(start) if start else {})}
    names = FIT_NAMES if len(samples) >= 2 else FIT_NAMES[:2]
    if len(samples) < 2:
        params["tilt_x"] = params["tilt_y"] = 0.0

    def residuals(p):
        out = []
        for raw, sky in samples:
            got = sky_of(p, raw)
            out.append(wrap180(got["az"] - sky["az"]) * math.cos(math.radians(sky["alt"])))
            out.append(got["alt"] - sky["alt"])
        if len(names) == 4:
            out += [p["tilt_x"] / tilt_sigma * 0.01, p["tilt_y"] / tilt_sigma * 0.01]
        return out

    for _ in range(iterations):
        r0 = residuals(params)
        jac = []
        for n in names:
            q = dict(params)
            q[n] += 1e-4
            jac.append([(b - a) / 1e-4 for a, b in zip(r0, residuals(q))])
        # 正規方程式 (J^T J + λI) dx = -J^T r
        m = len(names)
        a = [[sum(jac[i][k] * jac[j][k] for k in range(len(r0))) + (1e-9 if i == j else 0.0) for j in range(m)]
             for i in range(m)]
        b = [-sum(jac[i][k] * r0[k] for k in range(len(r0))) for i in range(m)]
        dx = _solve(a, b)
        for n, d in zip(names, dx):
            params[n] += d
        if max(abs(d) for d in dx) < 1e-7:
            break
    errors = [separation(sky_of(params, raw)["az"], sky_of(params, raw)["alt"], sky["az"], sky["alt"])
              for raw, sky in samples]
    params["az_offset"] = wrap180(params["az_offset"])
    return params, errors


def _solve(a, b):
    """小さな連立一次方程式（ガウスの消去法、部分ピボット）。"""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        if abs(m[col][col]) < 1e-15:
            continue
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] if abs(m[i][i]) > 1e-15 else 0.0 for i in range(n)]


def still_valid(alignment, clock_time, now=None):
    now = time.time() if now is None else now
    return abs(clock_time - now - alignment["clock_offset"]) <= CLOCK_TOLERANCE
