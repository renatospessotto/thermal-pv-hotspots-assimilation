"""Inversão do operador de observação: ΔT_z, pseudo-cor canônica, preditores de aquisição (iguais ao notebook)."""
import math
import warnings

import matplotlib
import numpy as np
from PIL import Image

from .leitura import CEL, GSD_REF, grade

CFG = {}   # preenchido pelo Modelo com o config.json (z_faixa, janela_fundo)


_LUT = (matplotlib.colormaps["inferno"](np.linspace(0, 1, 256))[:, :3] * 255).astype(np.uint8)


def pintar(z, lut=_LUT):
    lo, hi = CFG["z_faixa"]
    k = np.clip((z - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    return lut[k]


def mapa_z(T, painel_prob, limiar_painel, nivel):
    """ΔT_z: (T − fundo local de painel) / MAD do resíduo nos painéis (definição única, igual à do v2)."""
    h, w = T.shape
    gh, gw = grade(h, w)
    k = 4
    Hp, Wp = gh * CEL, gw * CEL
    Tq = np.pad(T, ((0, Hp - h), (0, Wp - w)), mode="edge")
    pg = np.asarray(painel_prob, dtype=np.float32)
    if pg.shape != (gh, gw):            # máscara calculada noutra grade (imagem perturbada): reamostra
        pg = np.asarray(Image.fromarray(pg).resize((gw, gh), Image.NEAREST))
    pcel = pg >= limiar_painel
    pm = np.kron(pcel, np.ones((CEL, CEL), dtype=bool))
    Tp = Tq.reshape(Hp // k, k, Wp // k, k).mean(axis=(1, 3))
    pk = pm.reshape(Hp // k, k, Wp // k, k).mean(axis=(1, 3)) >= 0.5
    Tm = np.where(pk, Tp, np.nan)
    j = CFG["janela_fundo"]; r = j // 2
    jan = np.lib.stride_tricks.sliding_window_view(np.pad(Tm, r, constant_values=np.nan), (j, j))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        fundo = np.nanmedian(jan.reshape(jan.shape[0], jan.shape[1], -1), axis=-1)
        ref = np.nanmedian(Tm) if pk.any() else np.median(Tp)
    fundo = np.repeat(np.repeat(np.where(np.isfinite(fundo), fundo, ref), k, axis=0), k, axis=1)[:h, :w]
    res = T - fundo
    vals = res[pm[:h, :w]] if pm[:h, :w].sum() > 500 else res.ravel()
    mad = 1.4826 * float(np.median(np.abs(vals - np.median(vals)))) + (0.5 if nivel == "C" else 0.02)
    return (res / mad).astype(np.float32), mad


NOMES_P = ["1-cos(visada)", "log(GSD/3)", "log(MAD/MAD_ref)", "sen(hora)", "cos(hora)", "falta_geometria", "falta_hora", "nivel_C"]


def preditores(r, mad, mad_ref=1.0):
    vis = 90 - abs(r["pitch"]) if r.get("pitch") is not None else None
    geo_ok = r["nivel"] == "A" and r.get("gsd") and vis is not None
    h = r.get("hora")
    return np.array([
        1 - math.cos(math.radians(vis)) if geo_ok else 0.0,
        math.log(r["gsd"] / GSD_REF) if geo_ok else 0.0,
        math.log(max(mad, 1e-3) / mad_ref) if r["nivel"] != "C" else 0.0,
        math.sin(2 * math.pi * h / 24) - math.sin(2 * math.pi * 12 / 24) if h is not None else 0.0,
        math.cos(2 * math.pi * h / 24) - math.cos(2 * math.pi * 12 / 24) if h is not None else 0.0,
        0.0 if geo_ok else 1.0,
        0.0 if h is not None else 1.0,
        1.0 if r["nivel"] == "C" else 0.0,
    ], dtype=np.float32)


def dz_celulas(z, gh, gw):
    """ΔT_z (em qualquer resolução) → máximo por célula da grade original gh×gw."""
    if z.shape != (gh * CEL, gw * CEL):
        z = np.asarray(Image.fromarray(z).resize((gw * CEL, gh * CEL), Image.BILINEAR), dtype=np.float32)
    return z.reshape(gh, CEL, gw, CEL).max(axis=(1, 3)).ravel()
