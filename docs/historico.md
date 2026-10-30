# Histórico: v1 → v2 → versão final

O trabalho passou por três versões. As duas primeiras não estão mais no repositório; ficam aqui as lições que
moldaram a versão final.

## v1: dá para rotular pela temperatura? (27/10/2026)
Uma pergunta de eficiência de rótulos: cada pixel já traz a temperatura; quanto do desempenho supervisionado se alcança
usando só a física como rótulo?

| Experimento | Resultado (Plot 16, XT2) |
|---|---|
| Cabeça linear sobre DINOv2 congelado, todas as caixas | AP 0,58 |
| ~100 caixas (≈ 27 imagens) | AP 0,57: o mesmo nível |
| Rótulo pela temperatura (ΔT local) | AP 0,10 |
| Treino no Plot 16 → teste no Plot 17 (mesma câmera) | AP 0,38; AUROC −6,8 pontos |
| PatchCore e OWLv2 zero-shot | quase aleatórios |

**Lições levadas adiante:**
- A pseudo-cor deu features muito melhores que a temperatura crua (AP 0,58 × 0,43) → na versão final, o ΔT_z é pintado
  numa paleta canônica.
- Mesmo com a mesma câmera, trocar de usina custa caro → o problema central é a mudança de domínio.
- Pouquíssimas caixas já bastam → anotar uma fonte nova é barato; o difícil é generalizar.
- Módulos inteiros quentes não estavam anotados como hotspot → regiões "ignorar" e, depois, o controle de qualidade.

## v2: mais dados, mais backbones (28/10/2026)
Quatro notebooks: índice de 4 domínios (P16–P18 e PV-HSD), máscara de painel (ZEN), torneio de 5 backbones × 3 entradas,
6 experimentos, 4 protocolos LODO e YOLOv8-P2. Chegou até o YOLO no Colab, mas era pesado demais e as saídas ficaram só
no Drive.

**Lições levadas adiante:**
- O split oficial do PV-HSD vaza (746/809 sequências) → split por sequência.
- A máscara de painel treinada na ZEN funciona nas duas câmeras → reaproveitada.
- Fazer tudo ao mesmo tempo dilui a pergunta → a versão final responde **uma** pergunta.

## Versão final: invariância à aquisição com assimilação de dados (28–29/10/2026)
A sugestão do professor (tratar a perda entre usinas como assimilação de dados) virou a hipótese central: inverter o
operador de observação para que a decisão não dependa da câmera. Um único notebook, um único backbone (DINOv3),
regressão logística com termos de assimilação, e três formas de teste (OSE, OSSE, fontes nunca vistas). Ver
[metodologia.md](metodologia.md).
