"""Exemplo mínimo: analisar as imagens de exemplo e salvar o mapa de hotspots.

    pip install -e .
    export HF_TOKEN=...   # o DINOv3 é 'gated': aceite a licença em huggingface.co/facebook/dinov3-vitb16-pretrain-lvd1689m
    python exemplos/usar_modelo.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from solar_hotspots import Modelo

RAIZ = Path(__file__).resolve().parents[1]
modelo = Modelo()
for arq in sorted((RAIZ / "modelo" / "exemplos").glob("*.jpg")):
    r = modelo.analisar(arq)
    print(f"{arq.name:12s} nível {r['nivel']} | cabeça {r['cabeca']} | {len(r['hotspots'])} hotspots | "
          f"{'FORA DE SUPORTE' if r['alerta'] else 'dentro do suporte'} (dist. {r['dist_suporte']:.1f})")
    img = np.asarray(Image.open(arq).convert("RGB"))
    acima = np.kron(r["mapa"] >= r["limiar"], np.ones((8, 8)))[: img.shape[0], : img.shape[1]]
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    ax[0].imshow(img); ax[0].set_title(arq.name)
    ax[1].imshow(img); ax[1].imshow(np.ma.masked_where(acima == 0, acima), cmap="autumn", alpha=0.6)
    ax[1].set_title(f"hotspots ({r['cabeca']})")
    for a in ax:
        a.axis("off")
    fig.savefig(RAIZ / "exemplos" / f"saida_{arq.stem}.png", dpi=110, bbox_inches="tight"); plt.close(fig)
