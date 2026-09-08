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
O worker entrega quadro e token; o controller só aceita a geração vigente.
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

## Reprodução e relógio

`FramePump` mantém a saída de vídeo em uma fila limitada. Quando o consumidor
não acompanha, a produção encontra limite em vez de acumular o vídeo inteiro
na memória.

`infrastructure/qt/audio.py` recebe PCM do ffmpeg e alimenta `QAudioSink`
por blocos, com fila limitada e sobra parcial controlada. Quando há dispositivo
de áudio, sua posição é a referência temporal; a imagem acompanha esse relógio.
Sem áudio disponível, a interface usa seu caminho de relógio sem dispositivo.

O runtime negocia taxa e canais uma vez e os usa tanto no comando do ffmpeg
quanto na abertura do sink. Os bytes são sempre s16le; não há reinterpretação
como float/int32 quando o dispositivo não aceita o formato. Falha de abertura
limpa o produtor. EOF aguarda espaço na fila e o relógio continua ativo até
esvaziar o buffer da placa, preservando o final do áudio.

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
As evidências e limites estão no [checkup final](validacao-final.md).
