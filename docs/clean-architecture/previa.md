# Prévia, áudio e rasterização de texto

## Dados que atravessam a fronteira

`application/media/preview.py` define `PreviewRequest`: projeto imutável,
instante, tamanho, token, fps e recursos de texto. `prepare_preview` valida
dimensões positivas, normaliza o instante e limita a taxa de prévia.

`domain/preview.py` contém geometria, instantes das miniaturas e `RawFrame`.
Um quadro transporta bytes RGB24, largura, altura e tempo. Sua integridade
exige exatamente largura × altura × 3 bytes. Ele não contém `QImage`.

O controller pede quadro ou reprodução ao `DesktopRuntimePort`.
O adaptador `DesktopRuntime` prepara o pedido, usa o compositor para montar
o comando e cria o worker. A interface não monta linhas de ffmpeg.

## Quadro parado e busca

Buscar na timeline invalida solicitações anteriores e agenda a prévia atual.
O worker entrega quadro e token; `PreviewResultKey` confere geração, revisão,
instante, dimensões e taxa. Há um quadro pausado em execução e um destino mais
recente pendente; pedidos intermediários são substituídos.
Isso impede que uma busca lenta para o segundo 5 apareça depois da busca para
o segundo 20.

O quadro parado mostra o quadro que **contém** o instante, como a reprodução e
o cache. O `-ss` exato descarta todo quadro que começa antes do pedido: com a
agulha no meio de um quadro vinha o seguinte e, dentro do último quadro de um
bloco, nenhum — preto no fim do vídeo e em cada corte, fácil de ver com zoom
máximo. Por isso `frame_command` compõe com `still=True`: cada vídeo é aberto
com `-noaccurate_seek` a ¼ de quadro depois do começo do quadro que contém o
instante, e a cadeia descarta o que vier antes de ½ quadro atrás desse ponto
(`_still_seek`). Recuar a busca, em vez disso, faria o ffmpeg decodificar desde
o keyframe anterior sempre que a agulha caísse num keyframe (+32 ms por quadro
com GOP de 2 s). Instantes no fim exato da edição ou depois dele mostram o
último quadro. Reprodução e exportação continuam com a busca exata, e as
transições já compunham o quadro certo pelo próprio recorte.

No **último quadro de um arquivo** a grade da taxa declarada não descreve o que
existe: um GIF de 128 quadros declarando 30 q/s anda de 33,4 ms, e seu último
quadro começa 37 ms antes do que a grade diz — mais de um quadro, e a tela
ficava preta no fim. Só nesse caso (`_still_lead`) a composição começa alguns
quadros antes e o comando entrega o do instante (`trim=start_frame`): o fluxo
tem quadro, o `tpad` segura o último e ele chega onde a agulha está. O recuo
acompanha a taxa da fonte (um vídeo de 10 q/s numa tela de 30 recua mais) e tem
teto de meio segundo de composição; a janela nunca passa para antes do fim de um
bloco que já terminou, para não abrir arquivo à toa. Fora do último quadro nada
muda, e o custo por quadro continua o mesmo.

### Cache da agulha

Um quadro exato custa um ffmpeg (perto de 100 ms no Windows), o que limitava o
arrasto da agulha a uns 10 quadros por segundo. Por isso a prévia mantém quadros
já compostos em JPEG pequeno (até 640×360, até 30 q/s):

- `domain/scrub.py` calcula a **assinatura** de um instante: tela e blocos
  visíveis que entram na composição, na ordem da pilha, ampliada para a janela
  inteira de uma transição. `signature_segments` a calcula por trecho, porque
  ela só muda nas pontas dos blocos e das transições.
- `application/media/scrub.py` guarda os quadros por índice com a assinatura;
  um quadro de composição diferente é descartado ao ser consultado. Há teto de
  memória (`scrub_cache_budget`: até 512 MB e 15% da livre) e saem primeiro os
  mais distantes da agulha.
- O preenchimento roda numa pool de uma vaga, com o ffmpeg em prioridade baixa,
  depois de 700 ms sem edição, busca ou reprodução. `composer.scrub_command`
  compõe um trecho de até 20 s e emite MJPEG; `jpeg_frames` separa as imagens
  pelos segmentos do JPEG. Os lotes guardam a assinatura do projeto que foi
  composto, então um trecho editado no meio do caminho nasce obsoleto. Tocar,
  arrastar um bloco ou um objeto cancela o preenchimento.
- Ao arrastar a agulha, um quadro guardado vai direto para a tela (cerca de
  1 ms) e o exato só é pedido quando a mão para 120 ms ou solta. Quadros exatos
  atrasados de pontos anteriores do arrasto não cobrem o guardado mais novo.
  Sem quadro guardado vale o caminho exato de sempre. A pré-carga do play não é
  aberta durante o arrasto, só quando ele termina.

`scripts/validate_scrub.py` mede preenchimento e custo por movimento com e sem
cache. `--smoke-test` confere o suporte a JPEG do Qt no pacote.

`ffmpeg/preview.py` decodifica o quadro; o adaptador/painel Qt cria a
representação gráfica. A imagem apresentada precisa possuir os bytes pelo
tempo necessário à pintura. Não guardar um ponteiro para buffer temporário
que já pode ter sido liberado.

O tamanho da prévia depende da área disponível e dos limites definidos no
controller. Não se decodifica sempre na resolução final do projeto.
Quadro parado, reprodução e exportação usam as mesmas regras de composição,
embora tamanho, fps e interpolação possam diferir conforme o pedido.

No instante pausado, `interaction_plan` separa fundo, objeto e frente quando a
composição admite essa separação. Um worker prepara três imagens com o mesmo
compositor (incluindo alfa/chroma e origem temporal); o Qt reaplica a pose a
cada movimento e conserva a ordem da pilha. A textura inteira é limitada a duas
vezes as dimensões da prévia. O fim do gesto pede o quadro canônico completo.
Seleção, instante, geração, tamanho e alterações de conteúdo invalidam o plano;
um callback antigo não pode instalar camadas em outro contexto.

Transições ativas e filtros posteriores ao objeto que dependem da composição
continuam no caminho canônico. Nesses casos, snapshots completos da mesma
posição podem ser apresentados em ordem crescente de revisão, com indicação
pendente até a revisão final. Um seek nunca aceita o quadro antigo. Não se
recorta a imagem composta nem se apaga a posição anterior com um retângulo preto.
Erros atuais são mostrados sem diálogo modal; erros e conclusões de pedidos
obsoletos não liberam nem substituem o pedido vigente.

## Reprodução e relógio

`FramePump` mantém a saída de vídeo no pipe limitado. Depois do play, uma thread
lê quadros adiante numa fila curta (até 10 quadros e 32 MB); o laço de ritmo
retira cada um na hora dele. Uma demora do ffmpeg — abrir o decodificador do
bloco seguinte num corte, uma transição pesada — é paga com quadros já prontos,
em vez de aparecer como imagem parada. Cheia, a fila segura a leitura e o pipe
segura o ffmpeg. Atrasado mais de três quadros e com quadros na fila, o ritmo
descarta em vez de despejar uma rajada. `PreviewFrameInbox` conserva somente o
último quadro e uma notificação pendente na fila Qt. Se a interface ficar
ocupada, os quadros intermediários são substituídos sem acumular imagens RGB. O
sinal do worker leva a caixa; o painel retira o snapshot imutável.

O ritmo e todos os instantes trocados entre painel e fluxo usam
`playback_clock` (`application/media/preview.py`), que é `perf_counter`. No
Windows até o Python 3.12, `monotonic` anda em degraus de 15,6 ms: medida por
ele, a espera de cada quadro errava até um degrau, e a imagem saía em dente de
serra (intervalos de 25 a 48 ms num fluxo de 33 ms) o tempo todo.

Enquanto a prévia está pausada, o controller pode abrir o comando de reprodução
e manter seu primeiro quadro atrás de uma comporta. O clique em play reutiliza
esse worker; não monta novamente o grafo nem abre outro processo. O relógio do
`FramePump` só começa depois que a comporta é liberada. O tempo de abertura do
ffmpeg, portanto, nunca vira atraso acumulado nem rajada de quadros no início.
Quadro parado e pré-carga ocupam as duas vagas da pool ao vivo e podem ser
preparados em paralelo; uma busca ou revisão do projeto cancela a pré-carga cuja
chave de projeto, instante, tamanho ou fps deixou de corresponder.

`infrastructure/qt/audio.py` recebe PCM do ffmpeg e alimenta `QAudioSink`
por blocos, com fila limitada e sobra parcial controlada. Quando há dispositivo
de áudio, sua posição é a referência temporal; a imagem acompanha esse relógio.
Sem áudio disponível, a interface usa `playback_clock`, iniciado com a
liberação do primeiro quadro. Taxas fracionárias, como 29,97 fps, permanecem
fracionárias no comando e na entrega. Terminar o áudio não encerra um vídeo
mais longo; o relógio continua do último instante do áudio.

A cada tique, `_sync_video_clock` compara o relógio do fluxo
(`clock_position`) com o da reprodução e repassa a diferença
(`set_clock_offset`). Abaixo de 15 ms nada muda: é o degrau do relógio da placa.
Nos primeiros 0,35 s, ou acima de 0,25 s, o fluxo corrige de uma vez; no meio,
no máximo 3 ms por quadro, sem salto visível. Diferenças acima de 0,35 s ainda
reabrem o fluxo no instante do som, mas só depois de o fluxo atual ter mostrado
um quadro: antes disso a tela ainda exibe o ponto anterior.

No play com som, a imagem pronta é segurada (`hold_start`) até a posição da
placa começar a andar. Abrir a mixagem e a placa leva de 100 a 150 ms a mais que
soltar a imagem; sem esperar, ela saía na frente e o acerto a fazia parar duas
vezes logo depois do play. A soltura é ancorada no instante em que o som
começou (`start_playback(at=…)`), não no tique que percebeu. Sem trilha
audível, a imagem sai no primeiro quadro; com a placa parada por 0,5 s, sai
mesmo assim.

Se o usuário pedir play antes de a pré-carga terminar, o áudio espera o sinal de
primeiro quadro pronto. No pause, a interface preserva o último quadro realmente
mostrado e alinha o cursor a seu timestamp antes de preparar a retomada. Ela não
renderiza novamente a mesma imagem: isso evita tanto o pico de decodificação
quanto o pequeno retorno causado por reabrir no timestamp anterior do relógio de
áudio.

O runtime negocia taxa e canais uma vez e os usa tanto no comando do ffmpeg
quanto na abertura do sink. Os bytes são sempre s16le; não há reinterpretação
como float/int32 quando o dispositivo não aceita o formato. Falha de abertura
limpa o produtor. EOF aguarda espaço na fila e o relógio continua ativo até
esvaziar o buffer da placa, preservando o final do áudio.

### Loop sem corte

Com Loop marcado, `_on_tick` arma a volta quando faltam até 1,5 s para o fim do
loop (`export_duration`): abre o fluxo de imagem em 0 atrás da comporta, como a
pré-carga, e chama `AudioPreview.queue_next` com a mixagem do começo. O som em
andamento é aberto com `audio_command(until=fim)`, que completa com silêncio e
corta exatamente no fim, para a emenda cair no instante certo. Quando o trecho
atual acaba, `_pump` troca para a fila preparada sem parar a placa e registra a
fronteira em `_segments`: `position` passa a contar a partir de 0. Ao ver o
O fim do loop é o fim do **último quadro**, não o da edição: uma edição de
4,27 s a 30 q/s tem o último quadro começando em 4,2667 s, e voltar em 4,27
deixava esse quadro 3 ms na tela — o que se vê como uma piscada na volta
(medido: 6 ms em vez de 33 ms). O som ganha o mesmo tanto de silêncio.

Ao ver o relógio voltar, o painel passa a ele o controle (`_swap_loop_video`). A imagem
do começo, porém, é solta já ao armar, com hora marcada para quando o relógio
da imagem atual chega ao fim; os quadros dela são aceitos antes da troca, e
quadros atrasados do fluxo que acabou não a cobrem. Esperar o tique que percebe
a volta deixava o último quadro parado e descartava o primeiro do começo:
147 ms de imagem parada, medidos. Sem som, a volta é feita em `playback_clock`.
Se a preparação falhar, vale o caminho antigo de reabrir do zero. Editar,
buscar, parar ou alternar o Loop cancela o que foi preparado.

A sondagem guarda a duração de cada trilha; um bloco novo de vídeo dura a
trilha de vídeo, e não o container. Blocos de vídeo recebem `tpad` clone de até
1 s no grafo, para projetos antigos cujo bloco passa do fim do vídeo não
mostrarem preto no fim.

Parar incrementa a geração, encerra alimentação e solicita descarte dos processos.
Callbacks agendados para uma reprodução antiga não podem parar a reprodução
nova. A janela de tela cheia observa a mesma prévia e seus controles.

`AudioPreview(enabled=False)` evita consultar dispositivos em diagnósticos
headless. O aplicativo normal mantém áudio habilitado. Isso permite validar
o pacote em CI sem depender de PulseAudio, PipeWire ou uma placa de som.

## Miniaturas e forma de onda

Filmstrip e waveform são trabalho de fundo, separado da reprodução.
A quantidade de miniaturas é limitada e depende do espaço visual.
A forma de onda também tem largura máxima. A extração de miniaturas pode usar
uma passagem quando isso reduz o trabalho de decodificação.

Pedidos equivalentes de waveform reutilizam o trabalho; novas janelas cancelam
as anteriores. A prévia não guarda cache próprio de imagens: as camadas vêm do
compositor, e quem retém pixels é o quadro corrente e o plano de interação.
Ao concluir, os workers liberam a referência a `Popen`, incluindo buffers
internos de `communicate`. O runner conserva referência forte somente enquanto
o trabalho está vivo e usa referência fraca no callback de conclusão.

Os caches consideram mídia, identidade e parâmetros necessários para distinguir
resultados. Uma alteração de recorte, geometria ou texto precisa invalidar a
prévia correspondente. Não remover limites de fila/cache para mascarar atrasos:
isso converte um problema de latência em consumo crescente de memória.

## Texto como recurso explícito

`TextRasterizer` é uma porta da aplicação.
`QtTextRasterizer` implementa essa porta com fontes e pintura Qt, usando
`QImage` em vez de desenhar num widget.

A aplicação gráfica e as fontes são inicializadas antes da rasterização.
Cada instância mantém lock e diretório temporário próprios. O nome do PNG é
derivado do conteúdo e estilo do texto: conteúdo idêntico é reaproveitado,
e uma edição nova não sobrescreve o recurso usado por uma exportação anterior.

O consumidor recebe `{clip_id: Path}`; pedidos congelam esse mapa como tupla.
O compositor somente lê os PNGs recebidos. Não existe registro global mutável
de renderizador, nem import de Qt no backend ffmpeg.

O renderizador deve viver pelo menos tanto quanto os trabalhos que consomem
seus arquivos. Os serviços montados no bootstrap permanecem vivos com a janela.
Não criar um renderizador local descartável e enfileirar somente seu caminho:
a destruição da instância pode apagar o diretório antes da leitura.

## Testes e limites

Testes medem bytes, quadros e PCM, além de gestos, busca, texto e tela cheia.
A fixture `isolated_audio` desliga a consulta ao dispositivo nos testes Qt;
ela não simula o compositor nem os arquivos de mídia.
`tests/test_playback_smoothness.py` fixa a resolução do relógio, a fila adiantada
diante de uma demora do ffmpeg, a hora marcada, a espera pelo som, o acerto do
relógio e a volta do loop agendada.

O benchmark registra primeira prévia e busca com uma mídia sintética fixa.
Essas medidas não substituem avaliar sincronismo audível, fluidez de projetos
longos ou memória com muitas trilhas. O teste do pacote verifica fontes,
prévia de texto e exportação real, sem afirmar que testou uma placa de áudio.

Para o ensaio opt-in com placa real, use `scripts/validate_audio.py`.
`scripts/validate_editor_responsiveness.py` mede 30 gestos com Qt e FFmpeg reais,
latência dos snapshots/final, workers, processos e encerramento, sem placa de som.
`scripts/validate_preview_gestures.py` envia eventos de mouse e verifica se as
bordas dos pixels do objeto acompanham cada movimento; a opção `--canonical-only`
desativa a preparação de camadas para comparação no mesmo código e ambiente.
As evidências e limites estão no [checkup final](validacao-final.md).
