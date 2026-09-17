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

`FramePump` mantém a saída de vídeo no pipe limitado. `PreviewFrameInbox`
conserva somente o último quadro e uma notificação pendente na fila Qt. Se a
interface ficar ocupada, os quadros intermediários são substituídos sem acumular
imagens RGB. O sinal do worker leva a caixa; o painel retira o snapshot imutável.

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
Sem áudio disponível, a interface usa relógio monotônico, iniciado com a
liberação do primeiro quadro. Taxas fracionárias, como 29,97 fps, permanecem
fracionárias no comando e na entrega. Terminar o áudio não encerra um vídeo
mais longo; o relógio monotônico continua do último instante do áudio.

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
relógio voltar, o painel libera a imagem preparada (`_swap_loop_video`). Sem
som, a volta é feita no relógio monotônico. Se a preparação falhar, vale o
caminho antigo de reabrir do zero. Editar, buscar, parar ou alternar o Loop
cancela o que foi preparado.

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
