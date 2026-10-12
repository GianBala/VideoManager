# Testes e regras de dependência

## Comandos principais

```bash
# Suíte padrão: Qt offscreen e mídia local; exclui rede.
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q

# Regras internas e arquitetura.
.venv/bin/python -m pytest -q tests/domain tests/application tests/architecture

# Sem as integrações marcadas ffmpeg.
.venv/bin/python -m pytest -q -m "not network and not ffmpeg"

# Casos que consultam plataformas reais.
.venv/bin/python -m pytest -m network

.venv/bin/python -m pyflakes src/videomanager tests scripts
git diff --check
```

No Windows, use os executáveis de `.venv\Scripts`.
Testes `ffmpeg` requerem ferramentas locais; cenários sem hardware disponível
podem ser ignorados. Rede é opcional e depende de plataformas externas.

Além da suíte, quatro ensaios **opt-in** medem o que ela não alcança (ver
[medições reproduzíveis](#medições-reproduzíveis)): áudio real, cache da
agulha, gestos na prévia e responsividade do editor.

A versão do ffmpeg muda o resultado de alguns cenários, e a CI roda com a do
sistema (6.1 no Ubuntu, 9.0 no Windows) e, num job Linux, com a 7.1 que o pacote
traz (ver [integração contínua](#integração-contínua)). Um teste
que dependa de comportamento posterior à 6 declara isso com
`_exige_ffmpeg(tools, 7)` em vez de falhar — ver
[processamento.md](processamento.md#versões-do-ffmpeg).

## Camadas e cobertura

| Local | O que verifica |
| --- | --- |
| `tests/domain/` | Modelos/edição imutável, sem Qt ou arquivos de mídia. |
| `tests/application/` | Sessão, salvamento, leitura, estados/tentativas e preparação com portas falsas. |
| `tests/contracts/` | Reserva, publicação e propriedade com sistema de arquivos real. |
| `tests/architecture/` | Imports internos/externos, ciclos, legado e importação sem site-packages. |
| `tests/test_*.py` | Regressões preservadas: formatos, seletores, Qt, JSON, subprocessos, ffmpeg, áudio e exportação. |

Parte da suíte existente permanece na raiz de tests para preservar os cenários
e facilitar comparação com a linha de base. O nome do diretório não substitui
a verificação de dependências.

### Regressões do editor, da prévia e da exportação

Cada arquivo abaixo nasceu de um defeito ou de uma mudança que foi medida; os
testes de defeito foram escritos para falhar no código anterior à correção, e
vários carregam nas docstrings o "antes" e o "depois". Os que exercitam o ffmpeg
usam o programa de verdade, porque o defeito só existe na execução.

| Arquivo | O que protege |
| --- | --- |
| `tests/domain/test_keyframe.py` | Curvas, interpolação, menor caminho angular, presets, divisão/aparo preservando a curva e edição por instante × animação inteira. |
| `tests/domain/test_project.py` | Tela automática (o maior vídeo e a maior taxa mandam; foto não), transições ligadas ao corte por identidade, mover/trocar/aparar/dividir blocos, separar áudio, trilhas, soltura de mídia e aritmética temporal. |
| `tests/domain/test_reverse_windows.py` | O planejador de janelas do bloco invertido: orçamento com blocos simultâneos somados, grade de quadros, pulo do trecho sem inversão, janela da prévia e termina em qualquer combinação. |
| `tests/domain/test_reversed_clip.py` | Bloco invertido sem ffmpeg: tempo da origem, divisão sem perder nem repetir, alças que tiram do topo ou da base, teto de memória e quem pode ser invertido. |
| `tests/domain/test_export_safety.py` | O corte rápido não pode descartar velocidade, opacidade, quadros-chave nem lacunas. |
| `tests/application/test_editor.py` | Histórico, transações de gesto (`begin_edit`/`commit_edit`/`cancel_edit`), respostas atrasadas. |
| `tests/application/test_formatting.py` | Nome da proporção de aspecto. |
| `tests/test_project_io.py` | Persistência real: ida e volta, quadros-chave, versão não suportada, caminhos relativos a partir da pasta do documento, cópia `.v1.bak` exata sem sobrescrever, pontos de suporte negativos, a inversão do bloco no v5 e a curva de volume no v6. |
| `tests/test_stages.py` | Comandos em sequência como um cano só: ordem e contagem, abertura da janela seguinte só na metade, falha no meio, término que derruba todos e arquivos de filtro que vivem até o fim. |
| `tests/test_reversal.py` | Bloco invertido medido na saída do ffmpeg: exportação espelho da normal (quadros e amostras), quadro parado e reprodução iguais à exportação, divisão, quadros-chave, transições contra o mesmo projeto montado com um arquivo invertido de verdade, e as janelas: exportação em janelas igual à de um processo só, reprodução e som encadeados no ritmo e sem estalo nas emendas, e o cache da agulha. |
| `tests/domain/test_volume_animado.py` | A curva de volume sem Qt nem ffmpeg: interpolação em dB e easing, soma ao volume do bloco e limites, `has_pose_keyframes`, edição do ponto, pose que não apaga o volume, dividir e aparar sem degrau e separar áudio. |
| `tests/test_volume_animado_som.py` | O som da curva medido na saída: nível em janelas de 20 ms contra o mesmo trecho sem curva, na exportação, na prévia (inclusive a partir do meio), em bloco invertido, dividido, com transição e depois de separar o áudio; mais o grafo (filtro, relógio e caminho da imagem). |
| `tests/test_audio_bordas_da_transicao.py` | As bordas de uma transição de som medidas na saída, com seno em fase em PCM/MOV e FLAC de 16384/MKV: com alças, sem estouro no começo da janela nem buraco no fim (envelope contra cos+sin); sem alças, o de-click de 12 ms no lugar e sem silêncio depois do corte; e as pontas do `acrossfade` em quadros de 480 amostras. |
| `tests/test_propriedades_som.py` | A aba Propriedades por tipo de bloco (fundo verde só onde há imagem, velocidade e volume, animação do volume e efeitos rápidos filtrados), o que ela emite e o desfazer. |
| `tests/test_reversal_menu.py` | O "Inverter" do botão direito: quem o recebe, marca, desfazer e o bloco clicado (não o selecionado). |
| `tests/test_images_in_video_tracks.py` | Fotos na trilha de vídeo, ajuste à tela, migração v1/v2 → v3 com a mesma aparência (comparada ao ffmpeg). |
| `tests/test_track_order.py`, `tests/test_timeline_ruler.py` | Ordem livre das trilhas; régua e agulha fixas com as trilhas rolando por baixo. |
| `tests/test_media_drop.py` | Importar só leva ao acervo; arrasto com eventos de mouse reais até a trilha, bloco fantasma, trilha nova, um passo de desfazer. |
| `tests/test_editor_interactions.py`, `tests/test_editor_regressions.py`, `tests/test_additional_tracks_ui.py` | Gestos, alvos de comando, rolagem, cancelamento por Escape, propriedades, popups, Adicionais, persistência e mudanças pendentes. |
| `tests/test_chromakey_and_transitions.py`, `tests/test_editor_media_integration.py` | Chroma key, transições (duração, alças, quadro final, filtros e adicionais na passagem) e classificação/orientação de mídias sintéticas; os que dependem do ffmpeg 7 declaram `_exige_ffmpeg(tools, 7)`. |
| `tests/test_fundo_desfocado_caminhos.py` | O fundo desfocado do bloco medido por pixel contra o mesmo projeto sem a opção: onde aparece e onde o quadro sai byte a byte igual (proporção × pose, quadros-chave e giro completo), opacidade, imagem com transparência (o alfa é composto sobre preto, não a cor escondida), trilha de baixo só na janela do bloco, último quadro em várias taxas, duração e quadros exportados, velocidade, divisão, filtro acima e transição. |
| `tests/test_still_frame.py` | Quadro parado no meio de um quadro, nos cortes e no fim, inclusive num GIF de passo irregular (o brilho da fonte diz qual quadro apareceu). |
| `tests/test_preview.py` | Taxa da prévia, quadros de reprodução (cancelamento, pré-carga sem consumir o relógio, só o quadro mais recente), encaixe na área e tira de miniaturas. |
| `tests/test_scrub_cache.py` | Assinatura por instante, teto de memória, obsolescência, preenchimento e arrasto com quadro guardado. |
| `tests/test_preview_interaction_layers.py`, `tests/test_preview_overlay_alignment.py` | Camadas de interação, resposta imediata do objeto e alinhamento pixel a pixel entre a pausa e a reprodução. |
| `tests/test_playback_smoothness.py` | Resolução do relógio, fila adiantada, hora marcada, espera pelo som, acerto do relógio e volta do loop. |
| `tests/test_loop_seam.py`, `tests/test_loop_tail.py` | Emenda do loop sem corte; fim de bloco sem quadros pretos (duração da trilha de vídeo, `tpad`). |
| `tests/test_middle_thumbnails.py` | Miniatura e capa mostram o quadro do meio. |
| `tests/test_gif_export.py`, `tests/test_export_dialog.py` | Exportação GIF real conferida com ffprobe (loop, sem som, imagem parada) e a janela de exportação (corte rápido, qualidade, GIF em "Automática", volta do GIF ao codec anterior). A troca de paleta acima de 512 MB fica em `tests/test_composer.py`. |
| `tests/test_conversion_checkup.py` | Um teste por achado do checkup da conversão (ver [processamento](processamento.md#regras-da-conversão-local)). |
| `tests/domain/test_i18n.py`, `tests/application/test_texts.py`, `tests/test_language.py`, `tests/test_language_window.py` | Idioma: catálogos com os mesmos parâmetros nos dois idiomas, texto guardado que se traduz ao exibir, separador decimal, nomes-padrão de trilha; o inglês com os nomes, parâmetros e estruturas do português e sem resto de português; a janela trocada ao vivo igual à que nasce no idioma, sem editar o projeto nem refazer a divisão das colunas; a opção nas Configurações, a abertura direto em inglês e os textos e números do próprio Qt. |
| `tests/test_binaries.py`, `tests/test_probe_lifecycle.py`, `tests/test_workers.py` | Ambiente dos binários e versão do ffmpeg, análise cancelada sem instalar resultado, cancelamento dos workers e diagnóstico de falha da prévia (cancelar não é erro). |

Testes de interação Qt usam eventos reais (`QTest`, `sendEvent`), não chamadas
diretas aos handlers: o arrasto do acervo "passava" chamando `mimeData` e os
handlers da timeline direto e não funcionava no aplicativo, porque
`setMovement(Static)` desliga o `dragEnabled` que o construtor tinha ligado.

`tests/conftest.py` não inicializa Qt automaticamente.
Os testes que precisam dele solicitam `desktop_app` e, quando pertinente,
`isolated_audio`. A primeira cria QApplication/fontes; a segunda evita
consultar dispositivo de áudio. `wait_until` processa eventos enquanto
aguarda uma condição com prazo, em vez de presumir resultado síncrono.

Três fixtures do `conftest.py` rodam em todo teste: `sem_sondagem_de_placa`
desliga a sondagem da placa de vídeo, `idioma_padrao` devolve o idioma ao
português e `janelas_do_teste_apagadas` apaga as janelas sem pai que o teste
criou — sem ela, na altura dos testes de idioma havia 35 mil widgets de testes
anteriores vivos, e cada troca entregava eventos a todos. Sem PySide6 (job
`internal`) as três não fazem nada. O fixture `pseudo` troca o inglês por um
pseudoidioma (cada texto entre ⟦ ⟧), para conferir o mecanismo da troca sem
depender da tradução.

## Provar que o núcleo independe do desktop

```bash
python3 -m venv /tmp/vm-pure
/tmp/vm-pure/bin/pip install pytest
PYTHONPATH=src /tmp/vm-pure/bin/python -m pytest -q \
    tests/domain tests/application tests/architecture
```

Esse ambiente não precisa instalar o projeto com dependências. A CI possui um
job exclusivo com Python e pytest. O teste arquitetural também inicia Python
com `-S` e importa todos os módulos internos, removendo site-packages da busca.

A análise AST cobre imports absolutos, relativos, `from pacote import modulo`
e blocos `TYPE_CHECKING`. Constrói o grafo dos módulos de produção e detecta
ciclos e imports dos pacotes antigos. Reexportações são consideradas por seus
imports. Importações dinâmicas construídas por strings arbitrárias não são
um escape permitido; exigem revisão e validação específica.

## Teste o contrato e a saída

- Sessão: salvar A enquanto B já foi editado não pode marcar B como salvo.
- Abertura: resultado antigo não substitui sessão ou revisão nova.
- Fila: um término é aceito uma vez; eventos de tentativa antiga são descartados.
- Análise: resposta já enfileirada antes de cancelar não altera a próxima análise.
- Arquivos: reserva perdida não autoriza apagar/sobrescrever outra saída.
- Cancelamento: capa e publicação também fazem parte do processamento.
- Mídia: verifique duração, streams, codecs, volume, quadros e texto.

Use fakes para controlar resultados e falhas dos casos de uso. Para bugs de
ffmpeg, produza mídia pequena e inspecione o resultado. Não substitua uma
medição de som/imagem por uma comparação de argumentos.

Fixtures de extratores ficam em `tests/fixtures`.
`tests/capture_fixture.py` sanitiza respostas; novas fixtures precisam de
revisão e registro em `FIXTURE_NAMES`. O parser real do yt-dlp valida as
expressões geradas sem baixar mídia.

## Medições reproduzíveis

`scripts/benchmark_architecture.py` cria uma mídia sintética local de 3 s,
640×360 a 24 fps com áudio, e intercala versões em subprocessos separados.

```bash
.venv/bin/python scripts/benchmark_architecture.py \
    --baseline /tmp/checkout-anterior/src --repeat 5 > resultado.json
```

O baseline deve conter o código da versão anterior, obtido por checkout ou
`git archive`. O script usa as mesmas ferramentas localizadas na versão atual
e não consulta a rede. Mede montagem inicial da janela, primeiro quadro, busca
a 1,5 s e exportação serial, com mínimo/máximo/mediana.

Na inicialização, a consulta ao dispositivo de áudio é desabilitada igualmente
nas duas versões. Os tempos de prévia/exportação começam depois de importar
módulos e inspecionar a fonte. Picos de RSS do Python e dos filhos são registrados
separadamente no Linux; não somá-los como se fossem um pico simultâneo.
Não são medidas de GPU, projetos grandes ou fluidez subjetiva.

Veja [os resultados da migração](migracao.md). Ao mudar algoritmos de mídia ou
buffers, repita com entradas representativas do caso real e registre variação.

### Ensaios opt-in do editor

Os scripts abaixo ficam fora da suíte: precisam de Qt e ffmpeg reais (o
primeiro, também de uma placa de som) e imprimem números — o de idioma também
um veredito, pelo código de saída.
Meça **antes e depois** de mexer em fluidez ou gestos, no mesmo ambiente — um
worktree do commit anterior serve de referência.

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_audio.py
PYTHONPATH=src .venv/bin/python scripts/validate_scrub.py --seconds 30 --size 1920x1080
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python scripts/validate_preview_gestures.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python scripts/validate_editor_responsiveness.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python scripts/validate_language.py --modo ingles
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python scripts/validate_blur_drag.py
PYTHONPATH=src .venv/bin/python scripts/validate_blur_export.py --tela 1080 --casos mp4,gif
```

| Script | O que mede |
| --- | --- |
| `validate_audio.py` | Toca um tom baixo na placa real: abertura, pausa/retomada, fim do relógio e coleta dos processos. |
| `validate_scrub.py` | Custo por movimento da agulha com o cache de quadros (assinatura + JPEG + `QPixmap`) e sem ele (um ffmpeg por quadro), mais o ritmo de preenchimento. |
| `validate_preview_gestures.py` | Eventos de mouse reais na prévia: se as bordas dos pixels do objeto acompanham cada movimento. `--canonical-only` desliga as camadas para comparar no mesmo código. |
| `validate_editor_responsiveness.py` | 30 gestos a 60 Hz: latência dos quadros parciais e finais, workers vivos, processos e encerramento. |
| `validate_language.py` | A troca de idioma em quinze cenas: a janela trocada ao vivo contra uma que nasce no idioma, a ida e volta, pinturas durante a troca, efeitos colaterais e o tempo. `--modo pseudo` acha texto fora do catálogo, `identidade` confere a geometria da troca, `ingles` acha texto com cara de português; `--cortes` lista o texto que corta em inglês e não em português. A troca durante a reprodução se mede com `validate_playback.py --trocar-idioma`. |
| `validate_playback.py` | Pré-carga, ritmo, velocidade da mídia e emenda do loop em duas cenas (`--cenas` escolhe outras). `reduzido`, `montagem_reduzida` e o sufixo `_fundo` medem o fundo desfocado contra uma cena gêmea de mesma geometria. `--trocar-idioma` troca a interface durante a reprodução. |
| `validate_blur_drag.py` | Arrasto de um bloco com fundo desfocado em quatro variantes (sem fundo, com o fundo já à vista e o bloco 16:9 que só descobre a tela ao sair do lugar, mais o 16:9 sem a opção para separar o custo): em todas o gesto usa as camadas prontas, com o fundo como quarta imagem: quanto a imagem fica atrás da mão, se a faixa descoberta mostra o borrão e não a trilha de baixo, e o tempo até assentar depois de soltar. |
| `validate_blur_export.py` | **Só Linux** (o pico de memória vem de `os.wait4` e `/proc/meminfo`; em outro sistema o roteiro recusa com uma mensagem). O custo do fundo na exportação, sem e com a opção em rodadas alternadas: tempo, pico de memória, quadros e duração do arquivo, em MP4, GIF, interpolado e em trechos paralelos × serial. Recusa os casos interpolados em 4K e sem memória livre. |

Nenhum deles substitui arrastar a agulha e reproduzir no aplicativo; servem
para comparar máquinas e versões.

## Integração contínua

`.github/workflows/tests.yml` tem três jobs. O `internal` roda só Python 3.10 e
pytest sobre `tests/domain tests/application tests/architecture`, provando que
o núcleo não depende do desktop. O `desktop` é uma matriz Ubuntu × Windows e
Python 3.10 × 3.12 (prazo de 20 min, `QT_QPA_PLATFORM=offscreen`) que instala o
ffmpeg do sistema, roda `pyflakes src/videomanager tests` e a suíte offline.
O `pacote` gera os pacotes (ver abaixo) ao lado dos testes, e não depois deles.

A versão do ffmpeg é parte do que a CI cobre: o Ubuntu instala a 6.1 e o
Chocolatey do Windows, a 9.0, enquanto o pacote entrega a 7.1. Por isso, no
job Linux com Python 3.12, `packaging/fetch_binaries.py` roda antes dos testes e
o aplicativo passa a usar o ffmpeg do pacote (`find_tools` procura o `vendor/`
primeiro): sem isso, nada testaria a combinação que o usuário recebe. O resultado
é uma cobertura de três versões — Linux 3.10 com a 6.1, Linux 3.12 com a 7.1 e
Windows com a 9.0. Como a integração com o ffmpeg depende da versão dele e não
do Python, o Windows com Python 3.10 roda `-m "not ffmpeg and not network"`: o
ffmpeg 9 já é testado pelo 3.12, e o resto da suíte continua cobrindo o 3.10.

### Fatias e tempo

As integrações com o ffmpeg (`-m ffmpeg`) são ~85% do tempo da suíte — 301 dos
2100 testes —, e um runner tem 4 núcleos que elas já ocupam. Por isso cada
célula do `desktop` é dividida em **duas fatias** que correm em máquinas
diferentes, e cada fatia roda `pytest -n auto` (pytest-xdist). A divisão é a
variável `VM_SHARD="i/n"`, lida por `fatiar` em `tests/conftest.py`:

- a fatia é por posição na lista ordenada por id, em revezamento — por arquivo,
  uma fatia levaria o `test_integration.py` inteiro (36% do tempo);
- **a ordem de coleta é preservada** dentro da fatia, e uma `VM_SHARD` inválida
  interrompe a execução em vez de rodar a suíte errada;
- todas as fatias de uma célula usam o **mesmo** `-m`, senão a união delas deixa
  de ser a suíte;
- o `pyflakes` e a conferência de referências rodam só na primeira fatia.

**Todo teste tem de passar em qualquer metade.** A divisão trocou os vizinhos de
cada teste e expôs um defeito que a ordem inteira escondia: o sinal de quadros-chave
de um painel já encerrado chegava ao teste seguinte (`QPushButton already
deleted`). Para reproduzir uma falha que só aparece na CI:

```bash
VM_SHARD=2/2 .venv/bin/python -m pytest -q          # a segunda metade
VM_SHARD=1/2 .venv/bin/python -m pytest -q -n auto  # a primeira, em paralelo
```

Os pacotes — Linux em pasta com `smoke_run.sh`, Windows em arquivo único com
`smoke_windows.ps1 -Icon` — saem do job `pacote`, que não espera os testes. O
`VideoManager.exe` é guardado por sete dias **mesmo que um teste do `desktop`
falhe**: ele só vale como entrega com a execução inteira verde.

Adicionar o workflow ao repositório não significa que a execução remota já
ocorreu; confira o resultado da CI antes de distribuir em outro sistema.

O [checkup final](validacao-final.md) registra as execuções nativas e os problemas
encontrados. O script `scripts/validate_audio.py` é separado da suíte: usa a
placa real em volume baixo e não deve ser incluído em runners sem áudio.
A fixture `desktop_app` redireciona as preferências para pasta temporária para
evitar que fechar janelas de teste modifique o perfil do desenvolvedor.
