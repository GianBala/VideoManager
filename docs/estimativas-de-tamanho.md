# Estimativas de tamanho

Como o aplicativo diz, antes de gravar, quanto um arquivo vai pesar — e por que passou a **medir** em vez de calcular.
Esta página é a revisão que originou a mudança: o que havia, o que a indústria faz, o que foi medido e o que continua
sem garantia.

## O defeito

O aplicativo anunciava que um arquivo ia **crescer** quando ele saía menor. A causa não era um erro de arredondamento:
a conta antiga partia de uma tabela fixa (4500 kbps em 1080p a 30 fps, escalada por pixels, taxa, codec e nível), e o
quanto um encoder gasta depende do **conteúdo**, que nenhum metadado mostra. Medido em 10 vídeos reais (gravações de
tela, séries, um filme), com o mesmo H.264 em CRF 20, o que saiu foi de **0,03× a 2,5×** o bitrate da fonte. Uma
gravação de tela de 10 Mbps cabe em 0,3–0,7 Mbps; uma série em 1080p60 pede 12 Mbps para uma fonte de 5. Nenhuma
fórmula acerta os dois lados.

## O que havia, por área

| Onde | Como era o número | Erro medido |
| --- | --- | --- |
| Download | `filesize` do extrator; senão `tbr × duração` | ≤ 2% em fonte direta (SoundCloud, em MP3, Opus e original); +5% e +30% nos dois HLS medidos, cujo `tbr` vem da largura de banda declarada pelo manifesto |
| Converter, vídeo | fórmula por pixels, limitada a 1,1× o bitrate da fonte | mediana 39%, pior +906% |
| Converter, Comprimir | 3 trechos de 8 s a 25/50/75%, média simples | mediana 4–11%, pior +29% (num recorte de 60 s, em que os trechos cobrem 40%) |
| Converter, áudio | bitrate pedido × duração | AAC copiado −35%; AAC, Opus e Vorbis recodificados até ±30%; FLAC de −55% a +39% |
| Editar, exportação | a mesma fórmula, mais 192 kbps de áudio e 1,5% de container | o da fórmula (não medido à parte) |

Dois defeitos escondiam outros. O limite de 1,1× a fonte (para "não superestimar") era o que fabricava o "vai crescer": uma
tela de 10 Mbps que encolhia 97% aparecia como +10%. E o áudio copiado de um vídeo era estimado pelo bitrate pedido,
não pelo da trilha: um AAC de 191 kbps copiado saía 34% acima do anunciado.

## O que a indústria faz

- **Amostrar e extrapolar.** Ferramentas que escolhem CRF por tamanho alvo (como o `ab-av1`) codificam trechos curtos e
  projetam. A projeção ingênua erra quando o áudio é grande ou o conteúdo varia; a que sobrevive é escalar pelo tamanho
  do **stream de vídeo**, e não do arquivo.
- **Várias amostras espalhadas, não uma.** A prática dos tempos do AviSynth (`SelectRangeEvery`: uns 2% do filme em
  trechos espalhados) dava ±10%; uma amostra só não presta.
- **Duas passadas** quando o tamanho precisa ser previsível (wiki do FFmpeg). Serve para quem escolhe o bitrate (é o que a
  opção de bitrate do Download faz), não para quem escolhe a qualidade.
- **Per-title encoding** (curva convexa da Netflix): mede a complexidade de cada título com muitas codificações. Caro
  demais para um número de interface.
- **Amostragem estatística.** O que o problema pede é o de uma pesquisa por amostragem: estratificar (nenhuma região do
  arquivo fica de fora) e usar uma variável auxiliar conhecida para toda a população — aqui, o tamanho de cada pacote da
  **fonte**, que o `ffprobe` lê sem decodificar (1 GB em 2 s) — no **estimador de razão**.

## O que o aplicativo faz agora

Tudo o que recodifica é medido: vídeo (qualquer codec, qualquer modo da aba Converter, e a exportação), e o áudio dos
codecs de taxa variável (AAC, Opus, Vorbis, FLAC, ALAC). Copiar não precisa (sai o que está lá), e MP3 e WAV (taxa
constante e PCM) saem por conta. A medida codifica trechos com o **mesmo** comando da conversão, em segundo plano, e a
tela mostra "medindo…" até o número chegar.

1. **Estratos.** O arquivo é dividido em 6 a 24 partes iguais, com um trecho em cada. Trechos em frações fixas caem, por
   azar, só nas cenas leves ou só nas pesadas.
2. **Trecho representativo.** Em cada estrato, o trecho medido é o que a fonte pesa por segundo o mais perto da média do
   estrato (com desempate pelo centro, para uma fonte de taxa constante não escolher sempre a borda).
3. **Razão pela fonte.** O que sai de cada trecho é multiplicado pelo quanto a fonte pesa no estrato inteiro em relação ao
   que pesa no trecho. O que a amostra erra de representativa, a curva da fonte corrige. Um trecho que a fonte quase não
   pesa (tela preta) volta à extrapolação direta, para a divisão não amplificar ruído.
4. **Quanto medir depende de quanto custa.** Um piloto de 4 s mede a velocidade do encoder neste conteúdo. Cabendo o
   arquivo inteiro em 20 s de relógio, ele é codificado inteiro (o número é o da conversão); senão a cobertura cresce com
   a velocidade, de 24 s a 192 s de vídeo. O piloto soma a partida do processo à codificação e por isso subestima a
   velocidade (0,4× a 1× da real): erra para o lado de medir menos, nunca de gastar mais.
5. **Soma dos pacotes, não do arquivo.** O container de um trecho curto distorce (cabeçalhos, tabelas); o `ffprobe` soma o
   que o encoder gravou, e o container do arquivo inteiro entra depois por um modelo (0,2–0,4% em 1080p, 2,6% num arquivo
   de 0,75 Mbps; mp4 paga por amostra, mkv e webm menos).
6. **Áudio.** Oito trechos de 5 s: o encoder de áudio custa centenas de vezes o tempo real, então se mede mais denso. A
   correção pela fonte não acrescentou nada (medido), e o desenho ficou na média.
7. **Quando a medida falha** (pouca memória, ffmpeg indisponível, arquivo sem duração), a conta antiga volta, **marcada
   como aproximada**: a tela avisa que o tamanho pode errar bastante e **não afirma** que o arquivo cresce nem que
   encolhe. Variação até ±3% aparece como "≈0%" e não como "+2%": a medida erra uns pontos, e a cor de aviso diria um
   lado que ela não sabe.

## O que foi medido

Corpus: 15 vídeos pessoais (H.264 + AAC; de 15 s a 85 min; 480p a 1080p60; gravações de tela de 10 Mbps CBR, séries,
um filme), usados só para leitura. O erro é `(estimado − real) / real` contra a codificação inteira, com o comando da
conversão. Reproduzir:

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_size_estimates.py MIDIA... --recorte 0 --cache est.json --detalhe
```

**Antes** (código antigo, 10 vídeos, recorte de 60 s a partir de 30% da duração):

| Caso | Fórmula (mediana / pior) | Amostra de 3×8 s (mediana / pior) |
| --- | --- | --- |
| H.264 CRF 20 | 29,5% / +906% | 8,2% / +25% |
| HEVC CRF 20 | 43,4% / +528% | 7,5% / +29% |
| H.264 720p | 41,1% / +667% | 10,7% / +25% |
| Comprimir, Equilibrada | 24,4% / +1093% | 3,6% / +16% |
| Comprimir, Forte | 38,3% / +814% | 4,3% / +21% |

O recorte favorece o desenho antigo (24 s de 60 são 40% do arquivo). Sobre as codificações **inteiras** de 9 vídeos, o
desenho antigo simulado erra 5,9% de mediana e −33% no pior caso (uma gravação de tela quase parada com rajadas de
movimento); numa fonte sintética pesada só nos primeiros 20% do arquivo, que nenhum dos três trechos alcança, erra −99,9%.

**Depois** (código novo, 10 vídeos **inteiros**, de 23 s a 5 min):

| Caso | n | Mediana | p90 | Pior | Viés |
| --- | --- | --- | --- | --- | --- |
| H.264 CRF 20 (vídeo + áudio) | 10 | 1,0% | 4,2% | +4% | +1,5% |
| Comprimir, Equilibrada | 10 | 0,5% | 6,4% | +6% | +1,2% |
| Áudio AAC 128 recodificado | 10 | 0,5% | 2,6% | −3% | −0,2% |
| Áudio Opus 128 | 10 | 0,6% | 4,5% | −5% | −0,6% |
| Áudio FLAC | 10 | 0,8% | 1,7% | +2% | +0,8% |

No mesmo conjunto a conta antiga dá mediana de 38,6% (pior +906%) em H.264 e 32,1% (pior +1093%) em Comprimir, e erra
o áudio recodificado em até 27% (AAC), 30% (Opus) e 39% (FLAC). Num filme de **85 min e 1 GB**, a medida levou 13,6 s contra 378 s da conversão e errou
+2,6% (H.264) e +4,5% (Comprimir). A medida levou uma mediana de 1,4 s (máximo 23 s, num 1080p60 pesado): um arquivo
barato de codificar é medido inteiro, e por isso sai exato.

**Exportação** (a janela de exportação sobre um clipe de cada vídeo, H.264 em "Equilibrada"; o real é o arquivo que
`composer.export_args` grava, pelo mesmo grafo da exportação): 7 vídeos de 54 s a 5 min, de 480p a 1080p60. A janela erra de
−0,6% a +3,0% (mediana 0,2%); os dois mais pesados, que são extrapolados e não medidos inteiros (117 s e 302 s a 60 fps),
saem +3,0% e +2,1%. A conta antiga errava de −29% a +828% (mediana +58%). A medida usa a tela e a taxa efetivas da janela
(as da exportação), e não as da mídia: comparar com o arquivo de outra tela dá erros de ±60% que não são da amostra.

Os encoders mais lentos, em 2 vídeos de 1080p60 (HEVC e H.264 em 720p sobre o vídeo inteiro de 90–117 s; VP9 e AV1 sobre
cortes de 30 s, porque o VP9 anda a 0,17× o tempo real):

| Caso | n | Mediana | Pior | Conta antiga (mediana / pior) |
| --- | --- | --- | --- | --- |
| HEVC CRF 20 | 2 | 3,9% | +5% | 30,3% / −55% |
| H.264 720p | 2 | 1,9% | −4% | 25,0% / −31% |
| VP9 | 2 | 2,6% | −4% | 59,5% / −62% |
| AV1 | 2 | 0,1% | 0% | 70,6% / −73% |

São poucos casos: mostram que o desenho vale para os outros encoders, não o erro que cada um terá. O custo cresce com a
lentidão: a medida do HEVC levou até 45 s, e a do VP9 num corte de 30 s levou 157–172 s, quase a conversão inteira (170–181 s),
porque o mínimo de 24 s de vídeo pesa. É o mesmo custo do desenho antigo (também 24 s), e o piloto acrescenta 4 s.

## O que continua sem garantia

- **Conteúdo caro de codificar e em rajadas** (uma gravação de tela 4K em AV1): a cobertura cai ao mínimo de 24 s (6
  trechos de 4 s), e nas simulações a mesma gravação de tela que a amostra antiga errava em −33% errou +49% nesse
  desenho. O orçamento de 20 s não alcança esse caso.
- **Download de HLS:** o número vem da largura de banda que o manifesto declara, que é o pico. Fica acima do que baixa
  (+5% a +30% medido); é um teto.
- **Download com bitrate escolhido:** o arquivo sai perto de *bitrate × duração* só quando a imagem é complexa o bastante
  para gastá-lo; numa tela quase parada sai muito abaixo. O número é um teto.
- **Exportação com várias fontes:** só a mídia principal é medida, e as outras seguem a taxa dela. Interpolação de
  movimento acrescenta quadros que a medida não vê.
- **Placa de vídeo:** a medida usa o encoder da placa quando configurado, mas o controle de taxa dele não é o do x264, e
  essa combinação não foi medida contra a codificação inteira.
- **Sem memória para a amostra** (um 4K com a fila convertendo ao lado): a conta antiga fica no lugar, marcada.
