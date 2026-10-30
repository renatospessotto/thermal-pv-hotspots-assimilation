"""Detector de hotspots em usinas solares para imagens térmicas de qualquer drone.

    from solar_hotspots import analisar
    r = analisar("imagem_termica.jpg")
    r["hotspots"], r["nivel"], r["alerta"]
"""
from .modelo import Modelo

_PADRAO = None


def analisar(imagem, cabeca="auto", **kwargs):
    """Atalho: carrega o modelo padrão (pasta `modelo/`) uma vez e analisa a imagem. Ver `Modelo.analisar`."""
    global _PADRAO
    if _PADRAO is None or kwargs:
        _PADRAO = Modelo(**kwargs)
    return _PADRAO.analisar(imagem, cabeca=cabeca)


__all__ = ["Modelo", "analisar"]
