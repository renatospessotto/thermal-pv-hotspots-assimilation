# Dados

O notebook baixa e prepara tudo sozinho na primeira execução (~4 min no Colab) e salva um pacote no Drive
(`MyDrive/SCC0287_Solar_v3/dados_v3.tar`) para as próximas sessões. Nenhum dado de imagem é redistribuído neste
repositório, exceto as 5 imagens de exemplo em `modelo/exemplos/` (licenças abaixo).

## Fontes
| Fonte | Origem | Câmera | Imagens usadas | Caixas de hotspot | Papel | Licença |
|---|---|---|---|---|---|---|
| **PV-HSD** | [PV-HSD-2025](https://huggingface.co/datasets/MisakaMikoto128/PV-HSD-2025), Kunming, China | DJI Mavic 3T (radiométrica, 640×512) | 4.023 | 25.177 | treino / teste (LOSO) | Apache-2.0 |
| **P16, P17, P18** | [Hlimaaa](https://huggingface.co/datasets/Hlimaaa/Solar-Panel-Thermal-Drone-UAV-Images), 3 usinas de 50 MW na Índia | DJI Zenmuse XT2 (FLIR, 640×512) | 494 / 659 / 200 | 2.088 / 2.031 / 785 | treino / teste (LOSO) | Apache-2.0 |
| **ZEN** | [Zenodo 16420123](https://zenodo.org/records/16420123), Tessalônica, Grécia | Mavic 3T (JPEG sem radiometria) | 353 | — (26.678 caixas de **painel**) | máscara de painel | CC BY 4.0 |
| **KAG** | [Kaggle pkdarabi/solarpanel](https://www.kaggle.com/datasets/pkdarabi/solarpanel), agregado do Roboflow | várias (sem metadados) | 349 | 468 | teste fixo, nunca no treino | CC BY-NC 4.0 |
| **ALF** | [Mendeley 82vzccxb6y](https://data.mendeley.com/datasets/82vzccxb6y/2), Colômbia | Zenmuse XT (336×256) | — | sem rótulo | robustez (**ficou de fora**: download recusado, HTTP 403) | CC BY 4.0 |

## Níveis de entrada por fonte
| Fonte | A | B | C |
|---|---|---|---|
| PV-HSD | 3.985 | 38 | 0 |
| P16 | 121 | 0 | 373 |
| P17 | 658 | 1 | 0 |
| P18 | 195 | 0 | 5 |
| KAG | 0 | 0 | 349 |
| ZEN | 0 | 0 | 353 |
| **Total** | **4.959** | **39** | **1.080** |

## Preparação (função `preparar` no notebook)
1. **Download só do necessário.** Os ZIPs da Índia (vários GB) são lidos por HTTP Range: só os pares JSON + JPG rotulados.
2. **Leitura de cada imagem** com os leitores radiométricos e o nível A/B/C (metodologia, seção 3).
3. **Rótulos num esquema único** `(x1, y1, x2, y2)` em pixels da imagem original:
   - Índia: LabelMe, rótulo `F1`;
   - PV-HSD: YOLO, `hot_spot`;
   - KAG: YOLO; `SingleHotSpot` e `MultiHotSpot` viram hotspot; diodo, bypass e string viram **"ignorar"** (são regiões
     quentes, mas não hotspots pontuais; não podem contar como negativas).
4. **Grupos para os splits:** sequência no PV-HSD (prefixo `N` de `N_k`), voo na Índia, imagem-base no KAG.
5. **Duplicatas entre fontes:** dHash de 256 bits (limiar ≤ 24) + correlação das miniaturas 48×48 (≥ 0,9). A dHash de
   64 bits dava falsos positivos em térmicas de fileiras de painéis. Resultado: 0 pares confirmados.
6. **Índice** `indice_v3.json` (id, fonte, câmera, nível, resolução, metadados, GSD, caixas, "ignorar", grupo, hash).

## Achados da preparação
- **Vazamento no split oficial do PV-HSD:** 746 das 809 sequências da validação oficial também estão no treino. Todos os
  splits deste trabalho são por sequência.
- **P16:** só 121 dos 494 JSONs têm o R-JPEG radiométrico na mesma pasta. Os outros 373 trazem a imagem embutida no
  próprio JSON (`imageData`, pseudo-cor) e entram como nível C do mesmo voo. São rótulos que o v2 descartava.
- **P18:** alguns JSONs embutem o próprio R-JPEG, com radiometria (por isso 195 de nível A).
- **PV-HSD:** 2 fotos da câmera visível (4000×3000) estavam misturadas às térmicas; foram descartadas.
- **KAG:** o treino do Roboflow tem 3 a 9 cópias aumentadas (rotação, cisalhamento) por imagem-base, e 53 bases aparecem
  em mais de um split. Só entram `valid` + `test`, sem as bases que também estão no treino.
- **Zenmuse XT (ALF):** o cabeçalho FFF está em *little-endian* (núcleo Tau), ao contrário da XT2. O leitor do v2 falhava
  em 100% dessas imagens; o atual detecta a ordem dos bytes.
- **Telêmetro a laser:** a Mavic 3T grava `LRFTargetDistance`, usado no GSD quando válido.

## Licenças
- Pesos do modelo (`modelo/`): treinados sobre features do **DINOv3** (Meta), que tem licença própria; o backbone não é
  redistribuído e é baixado do Hugging Face sob essa licença.
- Dados de treino: Apache-2.0 (PV-HSD, Hlimaaa). Máscara de painel: ZEN, CC BY 4.0 (atribuição acima).
- KAG: CC BY-NC 4.0, usado só como teste, em contexto acadêmico.
- Imagens de exemplo em `modelo/exemplos/`: PV-HSD e Hlimaaa (Apache-2.0); `KAG_C.jpg` (CC BY-NC 4.0).
