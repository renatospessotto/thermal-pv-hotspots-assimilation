"""Inferência do detector de hotspots: DINOv3 congelado + cabeça logística com termos de assimilação de dados.

Fluxo de uma imagem (o mesmo do notebook, seção 11):
1. leitura e nível A/B/C (`leitura.ler_qualquer`);
2. features da pseudo-cor da câmera (R0) → máscara de painel → ΔT_z (temperatura relativa ao fundo de painel);
3. features da pseudo-cor canônica do ΔT_z na escala de 3 cm/px (R2);
4. cabeça escolhida pelo nível (A/B → R4, C → R0) → escore por célula de 8×8 px;
5. alerta de fora de suporte (Mahalanobis do embedding R2 contra o treino).
"""
import io
import json
import os
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as Fnn
from scipy import ndimage
from safetensors.torch import load_file

from . import _transformacoes as T
from .leitura import CEL, GSD_REF, grade, gsd_centro, ler_qualquer, luminancia

PASTA_MODELO = Path(__file__).resolve().parents[2] / "modelo"
MEDIA = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
DESVIO = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


class Modelo:
    """Carrega os pesos de `modelo/` (ou de outra pasta) e o backbone do Hugging Face."""

    def __init__(self, pasta=PASTA_MODELO, device=None, backbone=None, token=None):
        self.pasta = Path(pasta)
        self.cfg = json.loads((self.pasta / "config.json").read_text())
        T.CFG.update(z_faixa=self.cfg["z_faixa"], janela_fundo=self.cfg["janela_fundo"])
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.painel = load_file(str(self.pasta / "painel.safetensors"))
        self.pca = load_file(str(self.pasta / "pca.safetensors"))
        self.alerta = load_file(str(self.pasta / "alerta.safetensors"))
        self.cabecas = {c: load_file(str(self.pasta / f"cabeca_{c}.safetensors"))
                        for c in self.cfg["cabecas"] if (self.pasta / f"cabeca_{c}.safetensors").exists()}
        self._nome_backbone = backbone or self.cfg["backbone"]
        self._token = token or os.environ.get("HF_TOKEN")
        self._bb = None

    # ------------------------------------------------------------------ backbone
    def _backbone(self):
        if self._bb is None:
            from transformers import AutoModel
            try:
                self._bb = AutoModel.from_pretrained(self._nome_backbone, token=self._token).to(self.device).eval()
            except OSError as e:
                raise RuntimeError(
                    f"Não foi possível baixar {self._nome_backbone}. O DINOv3 é 'gated' no Hugging Face: aceite a licença na "
                    "página do modelo e defina HF_TOKEN (token de leitura).") from e
            self._patch = self._bb.config.patch_size
        return self._bb

    @torch.no_grad()
    def features(self, img, escala, gh, gw):
        """img uint8 (h×w×3) → features por célula da grade gh×gw (gh·gw × D)."""
        bb = self._backbone(); p = self._patch
        x = torch.from_numpy(np.array(img, dtype=np.uint8, copy=True)).permute(2, 0, 1)[None].float().div(255).to(self.device)
        H2, W2 = max(p, round(img.shape[0] * escala / p) * p), max(p, round(img.shape[1] * escala / p) * p)
        x = Fnn.interpolate(x, size=(H2, W2), mode="bilinear", align_corners=False)
        x = (x - MEDIA.to(self.device)) / DESVIO.to(self.device)
        nh, nw = H2 // p, W2 // p
        with torch.autocast(device_type=self.device.type, dtype=torch.float16, enabled=self.device.type == "cuda"):
            tok = bb(pixel_values=x).last_hidden_state[:, -nh * nw:, :]          # descarta CLS e register tokens
        mapa = tok.float().reshape(1, nh, nw, -1).permute(0, 3, 1, 2)
        cel = Fnn.interpolate(mapa, size=(gh, gw), mode="bilinear", align_corners=False)
        return cel[0].permute(1, 2, 0).reshape(gh * gw, -1).cpu()

    # ------------------------------------------------------------------ partes do modelo
    def prob_painel(self, f0):
        p = self.painel
        return torch.sigmoid(((f0 - p["mu"]) / p["sd"]) @ p["lin_w"] + p["lin_b"]).numpy()

    def projetar(self, f, variante):
        return (f - self.pca[f"{variante}_mu"]) @ self.pca[f"{variante}_V"]

    def escore(self, cabeca, fp, P, dz, temC):
        """Logit por célula. Mesma fórmula da cabeça treinada, sem o viés por fonte (α = γ = 0 na inferência)."""
        t = self.cabecas[cabeca]; termos = self.cfg["cabecas"][cabeca]["termos"]
        P = torch.as_tensor(P, dtype=torch.float32)
        logit = ((fp - t["mu"]) / t["sd"]) @ t["lin_w"] + t["lin_b"]
        if "vies" in termos:
            logit = logit + P @ t["beta"]
        if "ganho" in termos:
            K = self.cfg["K_max"] * torch.sigmoid(-(t["a_obs"] + P @ t["b_obs"]))
            logit = logit + K * torch.as_tensor(np.clip(dz, -5, 20), dtype=torch.float32) * temC
        return logit.numpy()

    def dist_suporte(self, fp_r2):
        e = fp_r2.mean(0) - self.alerta["mu"]
        return float(torch.sqrt(e @ self.alerta["cov_inv"] @ e))

    # ------------------------------------------------------------------ análise completa
    def analisar(self, imagem, cabeca="auto"):
        """imagem: caminho, bytes ou arquivo aberto de um JPEG térmico de drone.

        Devolve um dict com: mapa (logit por célula de 8×8 px), hotspots (caixas em px da imagem), nivel, cabeca,
        limiar, alerta (fora do que o modelo viu no treino), dist_suporte, camera, gsd_cm e termos usados.
        """
        dados = imagem if isinstance(imagem, (bytes, bytearray)) else (
            imagem.read() if hasattr(imagem, "read") else Path(imagem).read_bytes())
        d = ler_qualquer(bytes(dados))
        meta = d["meta"]
        gsd = gsd_centro(meta, d["hfov"], d["w"]) if d["T"] is not None else None
        nivel = "C" if d["T"] is None else ("A" if gsd and 0.3 <= gsd <= 15 else "B")
        if cabeca == "auto":
            cabeca = self.cfg["cabeca_por_nivel"][nivel]
        r = dict(nivel=nivel, gsd=gsd if nivel == "A" else None, pitch=meta["pitch"], hora=meta["hora"])
        gh, gw = grade(d["h"], d["w"])

        f0 = self.features(d["rgb"], self.cfg["escala"], gh, gw)                   # R0: pseudo-cor da câmera
        painel = self.prob_painel(f0).reshape(gh, gw)
        base = d["T"] if nivel != "C" else luminancia(d["rgb"])
        z, mad = T.mapa_z(base, painel, self.cfg["painel_limiar"], nivel)
        dz = T.dz_celulas(z, gh, gw)
        escala = self.cfg["escala"]
        if nivel == "A" and gsd:
            escala = float(np.clip(self.cfg["escala"] * gsd / GSD_REF, *self.cfg["escala_lim"]))
        f2 = self.features(T.pintar(z), escala, gh, gw)                              # R2: ΔT_z canônico a 3 cm/px
        fp = {"R0": self.projetar(f0, "R0"), "R2": self.projetar(f2, "R2")}
        if self.cfg["cabecas"][cabeca]["variante"] == "R1":
            fp["R1"] = self.projetar(self.features(T.pintar(z), self.cfg["escala"], gh, gw), "R1")

        P = T.preditores(r, mad, self.cfg["mad_ref"].get(nivel, 1.0))
        s = self.escore(cabeca, fp[self.cfg["cabecas"][cabeca]["variante"]], P, dz, float(nivel != "C"))
        mapa = s.reshape(gh, gw)
        limiar = self.cfg["cabecas"][cabeca]["limiar_logit"]
        lab, n = ndimage.label(mapa >= limiar)
        caixas = []
        for sl in ndimage.find_objects(lab):
            y0, x0 = sl[0].start * CEL, sl[1].start * CEL
            y1, x1 = min(sl[0].stop * CEL, d["h"]) - 1, min(sl[1].stop * CEL, d["w"]) - 1
            caixas.append(dict(x1=x0, y1=y0, x2=x1, y2=y1, escore=float(mapa[sl].max())))
        dist = self.dist_suporte(fp["R2"])
        termos = [t for t in self.cfg["cabecas"][cabeca]["termos"] if not (t == "ganho" and nivel == "C")]
        return dict(mapa=mapa, hotspots=caixas, nivel=nivel, cabeca=cabeca, limiar=limiar,
                    alerta=dist > self.cfg["alerta_limiar"], dist_suporte=dist, camera=d["camera"],
                    gsd_cm=gsd, termos=termos, painel=painel)
