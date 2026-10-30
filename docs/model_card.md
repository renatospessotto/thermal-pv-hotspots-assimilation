---
language:
- pt
- en
license: other
license_name: dinov3-derived
tags:
- thermal-imaging
- solar-energy
- photovoltaic
- anomaly-detection
- data-assimilation
- domain-generalization
- dinov3
base_model: facebook/dinov3-vitb16-pretrain-lvd1689m
pipeline_tag: image-segmentation
---

# Hotspots em usinas solares com qualquer câmera (DINOv3 + assimilação de dados)

Detector de **hotspots em módulos fotovoltaicos** em imagens térmicas de drone, feito para **não depender da câmera**.
O backbone (DINOv3-B/16) fica congelado; o que este repositório traz são as cabeças (regressões logísticas com termos de
assimilação de dados), a máscara de painel, a projeção PCA e o detector de "fora de suporte".

Código, notebook e documentação: [github.com/renatospessotto/thermal-pv-hotspots-assimilation](https://github.com/renatospessotto/thermal-pv-hotspots-assimilation)

## Como usar
```bash
git clone https://github.com/renatospessotto/thermal-pv-hotspots-assimilation && cd thermal-pv-hotspots-assimilation
pip install -e .
export HF_TOKEN=...   # o DINOv3 é "gated": aceite a licença em huggingface.co/facebook/dinov3-vitb16-pretrain-lvd1689m
```
```python
from solar_hotspots import analisar

r = analisar("imagem_termica.jpg")
r["hotspots"]   # [{"x1":..., "y1":..., "x2":..., "y2":..., "escore":...}, ...] em pixels da imagem
r["nivel"]      # "A" radiométrica com escala | "B" radiométrica sem escala | "C" só pseudo-cor
r["cabeca"]     # "R4" (níveis A/B) ou "R0" (nível C)
r["alerta"]     # True se a imagem está fora do que o modelo viu no treino
r["mapa"]       # logit por célula de 8×8 px
```

## O que o modelo faz
1. Lê a temperatura radiométrica (FLIR FFF e DJI R-JPEG, em Python puro) e os metadados de voo, e classifica a imagem em
   nível A, B ou C.
2. Calcula o **ΔT_z**: a temperatura relativa ao fundo de painel, dividida pela dispersão dos painéis. Isso remove a
   calibração e a escala da câmera.
3. Pinta o ΔT_z numa **paleta fixa**, reamostra para **3 cm/px** e extrai features com o DINOv3.
4. Aplica a cabeça com **correção de viés** (metadados de aquisição) e **ganho de Kalman** (peso da evidência física).
5. Devolve o mapa, as caixas e o alerta de fora de suporte.

| Nível da imagem | Cabeça usada | Por quê |
|---|---|---|
| A, B (radiométrica) | **R4** | invariante à câmera |
| C (só pseudo-cor) | **R0** | sem temperatura, a pseudo-cor da câmera é a melhor informação |

## Resultados
Avaliação deixando uma fonte inteira de fora (AUROC por célula, IC 95% por bootstrap sobre imagens):

| Teste | R0 (pseudo-cor) | **R4 (assimilação)** |
|---|---|---|
| **Câmera nova** (treino Índia/XT2 → teste China/Mavic 3T) | 0,836 (0,830–0,839), recall 0,05 | **0,927** (0,923–0,931), recall 0,57 |
| Troca de paleta da mesma imagem (recall, média de 4 fontes) | 0,51 → 0,25 | **0,47 → 0,40** |
| Mesma câmera de outra usina (Índia) | 0,91–0,95 | 0,90–0,91 |
| Sem radiometria (agregado da web, nível C) | **0,790** | 0,709 |

Detalhes: [resultados](https://github.com/renatospessotto/thermal-pv-hotspots-assimilation/blob/main/docs/resultados.md).

## Dados de treino
PV-HSD-2025 (China, DJI Mavic 3T, Apache-2.0) e três usinas de 50 MW na Índia (DJI Zenmuse XT2, Apache-2.0). Máscara de
painel treinada no dataset do Zenodo 16420123 (CC BY 4.0).

## Limitações
- **Uso indicado: triagem.** Boa ordenação (AUROC 0,86–0,98 na mesma usina), mas precisão baixa no limiar padrão
  (precisão por célula ~0,3–0,45; recall por caixa 0,38–0,74 entre usinas). Aponta onde olhar; não conta defeitos.
- Treinado com **duas câmeras radiométricas**. Outras câmeras são tratadas pelo mesmo contrato de entrada, mas não foram
  testadas com rótulo.
- O limiar foi calibrado nas fontes de treino: numa câmera nova o R4 gera mais falsos positivos (~34 células por imagem
  na China).
- Hotspots menores que um pixel (voo muito alto) não são recuperáveis.
- Em imagens sem radiometria a invariância à câmera não vale.
- Uma classe só ("hotspot"); diodo, bypass e string não são separados.

## Licença
As cabeças foram treinadas sobre features do DINOv3 (Meta), distribuído sob a licença própria da Meta; o uso do backbone
segue os termos da página do modelo. Dados de treino sob Apache-2.0 e CC BY 4.0 (atribuições acima).

## Referência
Lahoz, W. A. & Schneider, P. (2014). Data assimilation: making sense of Earth Observation. *Frontiers in Environmental
Science* 2:16.
