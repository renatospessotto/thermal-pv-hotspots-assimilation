"""Leitura de qualquer imagem térmica de drone: radiometria (FLIR FFF e DJI APP3), metadados de voo e escala (GSD).

Mesmas funções usadas no notebook (`solar_hotspots.ipynb`). O nível de entrada sai daqui:
A = radiométrica com escala conhecida; B = radiométrica sem escala confiável; C = só pseudo-cor.
"""
import io
import math
import re
import struct

import numpy as np
from PIL import Image


CEL = 8


GSD_REF = 3.0


HFOV_TABELA = {"M3T": 49.4, "M30T": 50.6, "H20T": 40.6, "H20N": 40.6, "M2EA": 46.4}


def _segmentos(b, marcador, prefixo=None, pular=0):
    i, saida = 2, b""
    while i < len(b) - 4 and b[i] == 0xFF and b[i + 1] != 0xDA:
        tam = struct.unpack(">H", b[i + 2:i + 4])[0]
        dados = b[i + 4:i + 2 + tam]
        if b[i + 1] == marcador and (prefixo is None or dados[:len(prefixo)] == prefixo):
            saida += dados[pular:]
        i += 2 + tam
    return saida


def _fff(b):
    fff = _segmentos(b, 0xE1, b"FLIR", 8)
    if not fff.startswith(b"FFF\0"):
        return None
    hb = ">" if struct.unpack(">I", fff[20:24])[0] < 1000 else "<"   # versão do FFF = 100 nas duas ordens
    _, dir_off, n_reg = struct.unpack(hb + "III", fff[20:32])
    regs = {}
    for k in range(n_reg):
        tipo, _, _, _, off, tam = struct.unpack(hb + "HHIIII", fff[dir_off + 32 * k: dir_off + 32 * k + 20])
        if tipo:
            regs[tipo] = fff[off:off + tam]
    return regs if 0x01 in regs and 0x20 in regs else None


def temperatura_flir(b):
    regs = _fff(b)
    if regs is None:
        return None
    raw = regs[0x01]
    bo = "<" if struct.unpack("<H", raw[:2])[0] == 2 else ">"
    w, h = struct.unpack(bo + "HH", raw[2:6])
    if raw[32:36] == b"\x89PNG":
        cru = np.array(Image.open(io.BytesIO(raw[32:]))).astype(np.uint16)
        cru = (cru.byteswap() if bo == "<" else cru).astype(np.float64)   # PNG da FLIR guarda os 16 bits trocados
    else:
        cru = np.frombuffer(raw[32:32 + w * h * 2], dtype=bo + "u2").reshape(h, w).astype(np.float64)
    ci = regs[0x20]
    f = lambda o: struct.unpack(bo + "f", ci[o:o + 4])[0]
    E = f(0x20) if f(0x20) > 0 else 1.0
    IRT = f(0x34) if f(0x34) > 0 else 1.0
    OD, RTemp, ATemp, IRWTemp, RH = f(0x24), f(0x28) - 273.15, f(0x2C) - 273.15, f(0x30) - 273.15, f(0x3C)
    R1, B, F_, R2 = f(0x58), f(0x5C), f(0x60), f(0x30C)
    ATA1, ATA2, ATB1, ATB2, ATX = f(0x70), f(0x74), f(0x78), f(0x7C), f(0x80)
    O = struct.unpack(bo + "i", ci[0x308:0x30C])[0]
    planck = lambda t: R1 / (R2 * (math.exp(B / (t + 273.15)) - F_)) - O
    h2o = RH * math.exp(1.5587 + 0.06939 * ATemp - 0.00027816 * ATemp ** 2 + 0.00000068455 * ATemp ** 3)
    d = math.sqrt(max(OD, 0) / 2)
    tau = ATX * math.exp(-d * (ATA1 + ATB1 * math.sqrt(h2o))) + (1 - ATX) * math.exp(-d * (ATA2 + ATB2 * math.sqrt(h2o)))
    raw_obj = (cru / E / tau / IRT / tau - (1 - E) / E * planck(RTemp) - (1 - tau) / E / tau * planck(ATemp)
               - (1 - IRT) / E / tau / IRT * planck(IRWTemp) - (1 - tau) / E / tau / IRT / tau * planck(ATemp))
    with np.errstate(invalid="ignore", divide="ignore"):
        T = (B / np.log(R1 / (R2 * (raw_obj + O)) + F_) - 273.15).astype(np.float32)
    return T if np.isfinite(T).mean() > 0.99 else None


def fov_flir(b):
    regs = _fff(b)
    if regs is None:
        return None
    ci = regs[0x20]
    raw = regs[0x01]
    bo = "<" if struct.unpack("<H", raw[:2])[0] == 2 else ">"
    v = struct.unpack(bo + "f", ci[0x1B4:0x1B8])[0]
    return float(v) if 5 < v < 120 else None


def temperatura_dji(b, h, w):
    raw = _segmentos(b, 0xE3)
    if len(raw) < h * w * 2:
        return None                       # sem radiometria completa: a imagem vira nível C (sem fallback)
    cru = np.frombuffer(raw[:h * w * 2], dtype="<u2").reshape(h, w).astype(np.float32)
    T = cru / 64.0 - 273.15
    return T if -40 < float(np.median(T)) < 120 else None


def _xmp(b, tag):
    m = re.search(rb"drone-dji:" + tag.encode() + rb'(?:="|>)\s*([+\-\d.]+)', b)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def ler_meta(b, img):
    ex = img.getexif()
    modelo = (ex.get(272) or "").strip().strip("\x00").strip()
    data = ex.get(306) or ""
    m = re.match(r"(\d{4}):(\d\d):(\d\d) (\d\d):(\d\d)", data)
    lrf_ok = re.search(rb'LRFStatus="Normal"', b) is not None
    return dict(modelo=modelo, data=f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None,
                hora=int(m.group(4)) + int(m.group(5)) / 60 if m else None,
                altitude=_xmp(b, "RelativeAltitude"), pitch=_xmp(b, "GimbalPitchDegree"),
                lrf=_xmp(b, "LRFTargetDistance") if lrf_ok else None)


def ler_qualquer(b):
    """Lê uma imagem térmica de qualquer fonte. Devolve dict com rgb, T (ou None), camera, hfov e meta."""
    img = Image.open(io.BytesIO(b))
    rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]
    meta = ler_meta(b, img)
    T, hfov, leitor = None, None, None
    if b"FLIR" in b[:200000]:
        T = temperatura_flir(b); hfov = fov_flir(b); leitor = "flir"
    elif meta["modelo"] in HFOV_TABELA or b"\xff\xe3" in b[:4096]:
        T = temperatura_dji(b, h, w); leitor = "dji"
    if hfov is None:
        hfov = HFOV_TABELA.get(meta["modelo"])
    if T is not None and T.shape != (h, w):
        # FLIR com imagem embutida em outra resolução: a temperatura manda; a pseudo-cor é reamostrada
        rgb = np.asarray(Image.fromarray(rgb).resize((T.shape[1], T.shape[0]), Image.BILINEAR))
        h, w = T.shape
    return dict(rgb=rgb, T=T, h=h, w=w, camera=meta["modelo"] or "desconhecida", hfov=hfov, leitor=leitor, meta=meta)


def luminancia(rgb):
    return np.asarray(Image.fromarray(rgb).convert("L"), dtype=np.float32)


def distancia(meta):
    if meta.get("lrf") and 1 < meta["lrf"] < 500:
        return float(meta["lrf"])
    a, p = meta.get("altitude"), meta.get("pitch")
    if a is None or p is None or a <= 1 or abs(p) < 15:
        return None
    return a / math.sin(math.radians(abs(p)))


def gsd_centro(meta, hfov, w):
    d = distancia(meta)
    if d is None or not hfov:
        return None
    return 100 * 2 * d * math.tan(math.radians(hfov / 2)) / w


def grade(h, w):
    return math.ceil(h / CEL), math.ceil(w / CEL)
