# Metodologia

Este documento explica **por que** o modelo é como é: a hipótese, a ligação com a assimilação de dados, cada termo da
cabeça, como os dados foram tratados e quais decisões foram tomadas por evidência (inclusive as que deram errado).
Os números estão em [resultados.md](resultados.md); as fontes, em [dados.md](dados.md).

## Sumário
1. [O problema e a hipótese](#1-o-problema-e-a-hipótese)
2. [A leitura pela assimilação de dados](#2-a-leitura-pela-assimilação-de-dados)
3. [Contrato de entrada: níveis A, B e C](#3-contrato-de-entrada-níveis-a-b-e-c)
4. [Inversão do operador de observação (as entradas R0, R1, R2)](#4-inversão-do-operador-de-observação)
5. [A cabeça: regressão logística com termos de assimilação (R0–R5)](#5-a-cabeça)
6. [Treino](#6-treino)
7. [Controle de qualidade dos rótulos](#7-controle-de-qualidade-dos-rótulos)
8. [Desenho experimental: OSE e OSSE](#8-desenho-experimental-ose-e-osse)
9. [Inconsistências tratadas](#9-inconsistências-dos-dados-e-como-cada-uma-foi-tratada)
10. [Decisões tomadas por evidência](#10-decisões-tomadas-por-evidência)
11. [Limitações](#11-limitações)
12. [Referências](#12-referências)

---

## 1. O problema e a hipótese
Um hotspot é uma região de um módulo fotovoltaico mais quente que as vizinhas (célula danificada, diodo, sujeira).
Ele é inspecionado por drones com câmera térmica. O problema prático é que **cada usina é fotografada de um jeito**:
outra câmera (FLIR XT2, DJI Mavic 3T...), outra lente, outra altitude, outro ângulo, outra paleta de cores, outro
dia (mais quente ou mais frio). Um detector treinado numa usina perde desempenho na seguinte, mesmo que os defeitos
sejam os mesmos. Bommes et al. (2022) mediram essa queda (AUROC de 96 para 86 entre usinas); no v1 deste projeto,
treinar no Plot 16 e testar no Plot 17 custou 6,8 pontos de AUROC com a **mesma** câmera.

**Hipótese:** se a imagem for transformada para remover o efeito da aquisição *antes* de o modelo decidir, a decisão
deixa de depender da câmera. O que sobra é a física do hotspot: uma região alguns desvios acima dos painéis vizinhos,
com o tamanho de uma ou poucas células (~16 cm).

A hipótese é testada de três formas independentes (seção 8): fontes inteiras deixadas de fora do treino (OSE),
perturbações controladas da mesma imagem (OSSE) e fontes nunca vistas.

## 2. A leitura pela assimilação de dados
A sugestão do professor foi tratar a perda entre usinas como um problema de **assimilação de dados** (DA): o mesmo
problema que a previsão do tempo resolve ao combinar observações de satélites diferentes, cada um com seu viés e seu
erro, num estado único da atmosfera (Lahoz & Schneider, 2014). O mapeamento usado:

| Conceito da assimilação de dados | Na previsão do tempo | Neste trabalho | Onde está |
|---|---|---|---|
| Estado verdadeiro **x** | a atmosfera | onde há hotspot em cada célula de 8×8 px | o rótulo |
| Operador de observação **H(x; m)** | como o satélite "vê" a atmosfera, dado o ângulo etc. | como um hotspot aparece na imagem, dados câmera, GSD, ângulo, calibração e paleta (**m** = metadados) | seção 4 |
| *Retrieval* × radiância | produto processado (com priors) × dado cru | pseudo-cor da câmera (paleta e escala automática) × temperatura radiométrica | R0 × R1 |
| Erro de representatividade (**R = E + F**) | resolução que não casa com a escala do fenômeno | hotspot de 10 cm visto a 7 cm/px | R2 e perturbação de escala |
| Correção de viés variacional (VarBC) | viés de cada sensor = combinação linear de preditores, estimada junto | viés da decisão causado pela aquisição: Σβᵢ·Pᵢ(m) | R3 |
| Ganho de Kalman **K = B/(B+R)** | peso da observação = erro do fundo ÷ (erro do fundo + erro da observação) | peso da evidência física (ΔT_z) contra a evidência visual | R4 |
| Dados-âncora | observações não enviesadas (radiossondas) que tornam o viés identificável | critério físico (ΔT_z ≥ 3 sobre painel, tipo IEC TS 62446-3) | R5 |
| Controle de qualidade pela inovação | *first-guess check*: rejeita observação com y − H(x_b) grande demais | rejeita caixa anotada sem contraste térmico | seção 7 |
| OSE (negação de dados) | tirar um sistema de observação e medir o impacto | LOSO: tirar uma fonte inteira (câmera + anotador) | seção 8 |
| OSSE | simular um sistema de observação novo com a verdade conhecida | perturbar a mesma imagem rotulada | seção 8 |

Não há modelo dinâmico nem dimensão temporal (cada imagem é independente); por isso não há 4D-Var nem filtro no
tempo. O que se aproveita da DA é a **forma de pensar a observação**: separar o estado do jeito como ele foi observado.

## 3. Contrato de entrada: níveis A, B e C
Uma imagem térmica pode chegar com mais ou menos informação. Cada imagem recebe um nível, na preparação e na
inferência (`src/solar_hotspots/leitura.py`):

| Nível | O que tem | Como é tratado |
|---|---|---|
| **A** | temperatura radiométrica + FOV conhecido + metadados de voo com GSD entre 0,3 e 15 cm/px | ΔT_z + escala de 3 cm/px + todos os termos |
| **B** | temperatura, mas sem escala confiável (sem metadados, FOV desconhecido, GSD fora da faixa) | ΔT_z na escala fixa; termos geométricos na âncora com o indicador "faltante" |
| **C** | só a pseudo-cor (JPEG sem radiometria, imagem reprocessada) | ΔT_z sobre a luminância da paleta; **ganho = 0** (sem observação física, o termo de Kalman some) |

**Leitores radiométricos** (sem SDK, em Python puro):
- **FLIR FFF** (Zenmuse XT, XT2 e outras FLIR): o bloco APP1 "FLIR" traz a imagem crua de 16 bits e as constantes de
  Planck; a temperatura sai da equação radiométrica da FLIR. A ordem dos bytes do cabeçalho muda com o núcleo (a XT/Tau
  grava em *little-endian*, a XT2 em *big-endian*) e é detectada pelo campo de versão. O FOV horizontal vem do próprio
  CameraInfo (offset 0x1B4), quando existe.
- **DJI APP3** (Mavic 3T): imagem crua de 16 bits em 1/64 K. Sem *fallback* silencioso: dados incompletos → nível C.

**Escala (GSD):** câmera *pinhole*, `GSD = 2·d·tan(HFOV/2)/largura`, com `d` = distância do telêmetro a laser
(`LRFTargetDistance` da M3T) quando válida, senão `altitude / sen(|pitch|)`.

## 4. Inversão do operador de observação
As três variantes da mesma imagem que entram no DINOv3-B/16 congelado (entrada ampliada 2×, para que o patch de 16 px
cubra 8 px da imagem, o tamanho de um hotspot):

**R0, sem assimilação (o *retrieval*).** A pseudo-cor como a câmera gerou. Cada câmera usa a sua paleta e um contraste
automático por imagem: o mesmo hotspot fica com cores diferentes em câmeras diferentes.

**R1, inversão radiométrica (a radiância).** O ΔT_z, a temperatura relativa ao fundo de painel em unidades robustas:

```
fundo(p) = mediana dos pixels de PAINEL numa janela de ~36 px em torno de p
ΔT_z(p)  = (T(p) − fundo(p)) / (1,4826 · MAD{ T − fundo } nos painéis)
```

Subtrair o fundo remove o **deslocamento** (calibração, emissividade, dia quente ou frio); dividir pelo MAD remove a
**escala** (sensibilidade da câmera, contraste da cena). A máscara de painel é uma cabeça linear sobre as features R0,
treinada nas caixas de painel da ZEN (AP 0,994, IoU 0,912). O ΔT_z é então **pintado numa paleta fixa e única**
(inferno, faixa −3 a 8). No v1, a pseudo-cor deu features muito melhores que a temperatura crua (AP 0,58 × 0,43),
porque o DINO foi pré-treinado em imagens coloridas; a paleta canônica mantém esse ganho, agora com a mesma "linguagem
visual" para qualquer câmera.

**R2, + inversão geométrica.** A R1 reamostrada para **3 cm/px** (a resolução mínima recomendada pela IEC TS 62446-3)
pelo GSD de cada imagem: a escala total da entrada é `clip(2·GSD/3, 0,75, 3)`. Assim um hotspot de 16 cm ocupa o
mesmo número de patches em qualquer altitude ou lente. Nos níveis B e C fica igual à R1.

As features são sempre reamostradas de volta para a **grade de 8×8 px da imagem original**, de modo que todas as
variantes e perturbações são avaliadas exatamente nas mesmas células. Para caber no Drive, as features (768) são
projetadas por PCA para 256 dimensões (93,7–94,5% da variância), com a PCA ajustada sem rótulos numa amostra das
fontes de treino.

## 5. A cabeça
Uma regressão logística por célula, com termos de assimilação somados ao logit:

```
logit = w·f̃ + b                      (R0, R1, R2: só a evidência visual, f̃ = features padronizadas)
      + Σᵢ βᵢ·Pᵢ(m)                   (R3: correção de viés tipo VarBC)
      + K(m)·ΔT_z·[nível ≠ C]         (R4: ganho de Kalman sobre a evidência física)
      + α_s + γ_s·ΔT_z               (R5: viés de anotação da fonte s; só no treino)
```

**Preditores de aquisição P(m), ancorados na observação de referência.** Todos valem 0 numa imagem vertical a 3 cm/px
ao meio-dia, de modo que o termo de viés **se anula** numa câmera "ideal" em vez de extrapolar:

| Preditor | Significado |
|---|---|
| `1 − cos(visada)` | ângulo fora do nadir (a emissividade do vidro cai com o ângulo) |
| `log(GSD/3)` | escala relativa à referência |
| `log(MAD/MAD_ref)` | contraste da cena relativo à mediana do treino |
| `sen(hora) − sen(12 h)`, `cos(hora) − cos(12 h)` | hora do voo (irradiância e reflexos) |
| `falta_geometria`, `falta_hora`, `nível_C` | indicadores de metadado ausente |

A padronização pela média do treino colocaria a Índia (100% vertical) no extremo da distribuição (z ≈ −2,7) e o β
extrapolaria; ancorar na referência física resolve isso.

**Ganho de Kalman como razão de erros (R4).** No filtro de Kalman, a observação entra com peso `K = B/(B+R)`. Aqui:

```
ρ(m) = log(σ²_obs / σ²_visual) = a + b·P(m)
K(m) = K_max / (1 + e^ρ(m))        (K_max = 3, a escala em logit por unidade de ΔT_z)
```

`b > 0` quer dizer que aquele metadado aumenta o erro da observação física (menos confiança no ΔT_z). Sem radiometria
(nível C), observação ausente = ganho zero.

**Viés de anotação por fonte, com âncora (R5).** Cada fonte de rótulo é tratada como um "instrumento" com intercepto e
sensibilidade ao contraste próprios (α_s, γ_s). Na correção de viés das agências meteorológicas, o viés só é
identificável com **dados-âncora** não enviesados. A âncora aqui é uma pseudo-fonte física: células de painel com
ΔT_z ≥ 3 são hotspot e com ΔT_z ≤ 0,5 não são, com α = γ = 0 fixos e peso total de 10% dos dados reais. Assim cada
α_s, γ_s mede o desvio do critério do anotador em relação ao critério físico, e a inferência (α = γ = 0) decide pelo
critério físico. Sem a âncora, os α encolheriam só pela L2 e o modelo seguiria o "anotador médio".

## 6. Treino
- **Banco de células por imagem:** todas as positivas, os 64 negativos de maior ΔT_z (difíceis) e 128 sorteados.
- **Pesos pelo inverso da probabilidade de amostragem.** Os negativos difíceis são escolhidos pelo próprio ΔT_z, que é
  uma variável do modelo (R4). Amostrar por *x* (e não só por *y*) enviesa as inclinações de uma regressão logística;
  pesar cada célula por 1/π (Horvitz-Thompson) restaura o estimador.
- **Normalização por imagem:** a soma dos pesos de cada imagem é a mesma. A fração da variância do ΔT_z entre imagens é
  0,83–0,95, então a unidade efetiva de informação é a imagem, não a célula; sem isso, imagens com muitos hotspots
  dominariam a perda.
- **Classes equilibradas** depois da normalização (só desloca o intercepto; o limiar é escolhido na validação).
- **Otimizador: L-BFGS em lote completo**, partindo de pesos zero. Um teste sintético com β e K conhecidos
  (`testar_cabeca.py`) mostrou que Adam em minilotes recuperava **metade** do β verdadeiro (acoplamento entre β, K e w);
  com L-BFGS, o valor verdadeiro (β −0,93/−1,0; 0,82/0,8; a = 0,51/0,5; b = −1,43/−1,5).
- **L2 explícita:** 10⁻⁵ nos pesos visuais e 10⁻⁴ nos termos de assimilação. Uma L2 de 10⁻² encolhia os efeitos reais
  pela metade (a perda é uma média; a penalidade competia com a curvatura dos dados).
- **Limiar:** máximo F1 na validação (grupos das fontes de treino). O teste nunca participa de escolha nenhuma.
- **Sementes:** o L-BFGS em lote completo a partir de zero é determinístico; as 3 sementes deram resultados idênticos.
  A incerteza reportada vem do **bootstrap por imagem** (100 reamostragens).

## 7. Controle de qualidade dos rótulos
No DA, cada observação passa por um *first-guess check*: se a inovação (observação menos o esperado) é grande demais,
a observação é rejeitada. Aqui a observação é a caixa do anotador e o esperado é o contraste térmico. Uma caixa de
imagem **radiométrica** cujo ΔT_z máximo fica abaixo de 1 não tem evidência física de hotspot e é **reprovada**: suas
células ficam fora do treino (nem positivas nem negativas) e as métricas saem com e sem elas. No nível C não há como
checar, e todas passam.

O QC transforma uma observação ("as fontes anotam diferente") num número por fonte: 0,8% das caixas reprovadas no
PV-HSD contra 7,7–8,8% na Índia, com ΔT_z mediano de 9,7 contra 2,5–5,5. O efeito nas métricas é pequeno
([resultados.md](resultados.md#controle-de-qualidade)).

## 8. Desenho experimental: OSE e OSSE
- **OSE por negação de dados (LOSO):** treina em três fontes e testa na quarta inteira. **LOSO-PVHSD é o teste de
  câmera nova** (treino só na Índia/XT2 vertical, teste na China/M3T inclinada). Nos LOSO da Índia, a câmera do teste
  é a mesma das outras usinas de treino (XT2).
- **Referência "mesma fonte" (IN-X):** treina e testa dentro da fonte X, em grupos separados (60/20/20 por voo ou
  sequência, equilibrado em imagens e caixas). A **perda** de generalização é medida nas mesmas imagens: IN-X − LOSO-X
  no teste do IN-X. A escada R0 → R5 mostra quanto da perda cada etapa recupera.
- **OSSE (perturbações controladas):** até 300 imagens rotuladas de cada fonte, cada uma "fotografada de novo": escala
  ×0,5 e ×0,33 (voar 2× ou 3× mais alto, ou câmera de menos pixels), ruído de sensor (0,2 °C), desfoque (σ = 1 px) e
  troca de paleta. Cada versão passa pelo modelo do fold em que a fonte dela ficou de fora. O rótulo e a grade são os
  mesmos; se a decisão não depende da aquisição, a curva fica plana.
- **Fontes nunca vistas:** KAG (agregado da web, sem radiometria) com o modelo final.
- **Alerta de fora de suporte:** distância de Mahalanobis do embedding médio (R2) da imagem até as imagens de treino;
  acima do percentil 99 do treino, a imagem recebe "baixa confiança".
- **Métricas:** AUROC e AP por célula (negativas amostradas a 5% com peso 20; regiões "ignorar" fora da conta),
  **AP/prevalência** (a AP de um classificador aleatório é a prevalência, que muda entre fontes), recall por caixa e
  FP por imagem no limiar da validação. IC 95% por bootstrap sobre imagens.

## 9. Inconsistências dos dados e como cada uma foi tratada
| # | Inconsistência | Problema que causaria | Tratamento |
|---|---|---|---|
| I1 | Critério de anotação diferente por fonte | o modelo aprende o critério da fonte majoritária | viés por fonte com âncora (R5); QC; avaliação por fonte |
| I2 | Resolução e FOV variam entre câmeras | GSD indefinido, grades diferentes | FOV do CameraInfo ou tabela por modelo; grade de 8 px por imagem |
| I3 | Radiometria ausente ou em formato próprio | leitor quebra ou mistura escalas em silêncio | nível de entrada explícito, sem *fallback* |
| I4 | Metadados ausentes ou errados (altitude do ponto de decolagem, telhados) | GSD errado | telêmetro a laser quando existe; GSD fora de 0,3–15 cm/px → nível B |
| I5 | Imagens oblíquas | escala varia dentro da imagem | escala pelo centro (a homografia foi descartada, seção 10) |
| I6 | Paleta e contraste automático | features dependem da câmera | ΔT_z na paleta canônica |
| I7 | Fundo variável (chão, telhado, céu refletido) | z-score instável | fundo e MAD só nos pixels de painel |
| I8 | Negativos difíceis escolhidos pelo ΔT_z | inclinações enviesadas | pesos pelo inverso da probabilidade de amostragem |
| I9 | Prevalência diferente por fonte | AP não comparável | AP/prevalência, AUROC, recall por caixa |
| I10 | Vazamento por sequência e por voo | métricas otimistas | grupo = sequência (PV-HSD) ou voo (Índia) |
| I11 | Extrapolação nos metadados | termos de viés extrapolam | preditores ancorados; alerta de fora de suporte |
| I12 | Ponderação por importância para um alvo | especializa o modelo | removida |
| I13 | Normalização do ΔT_z (anel × imagem dão 10,5 × 1,66) | o ganho muda de significado | uma única definição em tudo |
| I14 | Duplicatas entre fontes | vazamento entre fontes | dHash de 256 bits + correlação das miniaturas (0 pares confirmados) |

## 10. Decisões tomadas por evidência
| Plano inicial | Decisão | Evidência |
|---|---|---|
| R1 = temperatura em z-score (cinza) | ΔT_z na paleta canônica | v1: pseudo-cor AP 0,58 × temperatura 0,43 |
| R2 = homografia para o plano do chão | só escala (pelo GSD do centro) | a homografia transformou os painéis de telhado do PV-HSD em trapézios: painéis inclinados não estão no plano do chão |
| GSD pela periodicidade das células | só auditoria | o passo dominante é o do módulo (~92 cm, igual em 2 câmeras e 2 países), mas por imagem cai em harmônicos |
| FOV da XT pela periodicidade | fonte ALF como nível B | o CameraInfo da XT não traz o FOV; a estimativa deu 118° (impossível) |
| Adam nas cabeças | L-BFGS em lote completo | teste sintético: Adam recuperava metade do β verdadeiro |
| L2 de 10⁻² nos termos de assimilação | 10⁻⁴ | 10⁻² encolhia os efeitos reais pela metade |
| Ponderação por importância para a Índia | removida | contraria o objetivo generalista |
| Split oficial do PV-HSD | split por sequência | 746 das 809 sequências da validação oficial também estão no treino |

## 11. Limitações
- **Duas câmeras radiométricas com rótulo** (XT2 e Mavic 3T). A ALF (Zenmuse XT, Colômbia) ficou de fora da execução
  final porque o servidor (Mendeley) recusou o download automático (HTTP 403).
- **A invariância vale para imagens radiométricas.** Em imagens só com pseudo-cor (nível C), o ΔT_z vem da luminância
  da paleta e herda a dependência da câmera; por isso o pacote usa o R0 no nível C.
- **Calibração do limiar entre fontes:** o limiar escolhido na validação das fontes de treino não se transfere bem para
  uma câmera nova (o R4 marca ~34 células falsas por imagem na China, contra ~3 do R0).
- **Limite físico de resolução:** a escala ×0,33 derruba o recall de todas as cabeças; um hotspot que cabe em menos de um
  pixel não é recuperável por normalização.
- **Tipo de módulo e irradiância** não estão nos dados; entram só como limitação.
- **Uma classe só** ("hotspot"): as fontes não concordam nas classes de defeito.

## 12. Referências
- Lahoz, W. A. & Schneider, P. (2014). Data assimilation: making sense of Earth Observation. *Frontiers in Environmental
  Science* 2:16. doi:10.3389/fenvs.2014.00016
- Derber, J. & Wu, W.-S. (1998). The use of TOVS cloud-cleared radiances in the NCEP SSI analysis system. *Monthly
  Weather Review* 126.
- Dee, D. P. (2005). Bias and data assimilation. *Quarterly Journal of the Royal Meteorological Society* 131.
- Bommes, L. et al. (FAU Erlangen-Nürnberg). Trabalhos sobre detecção e classificação de falhas em módulos PV em vídeos
  infravermelhos aéreos, com avaliação entre usinas (*Progress in Photovoltaics*, 2021–2022).
- Siméoni, O. et al. (2025). DINOv3. Meta AI.
- IEC TS 62446-3:2017. Photovoltaic systems – Outdoor infrared thermography of photovoltaic modules and plants.
- Gulrajani, I. & Lopez-Paz, D. (2021). In search of lost domain generalization. *ICLR*.
