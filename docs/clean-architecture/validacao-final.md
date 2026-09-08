# Checkup após a migração

Esta revisão verifica se a reorganização em Clean Architecture preservou os
fluxos de download, conversão, edição, prévia e distribuição. Os testes exercitam
as fronteiras entre as camadas e medem arquivos de mídia reais. Não constituem
uma garantia de ausência de defeitos para toda mídia ou dispositivo existente.

## Problemas encontrados e corrigidos

| Problema | Consequência | Correção e proteção |
| --- | --- | --- |
| Sessão comparava apenas o conteúdo do projeto ao substituí-lo. IDs não participam dessa igualdade. | Um projeto equivalente com novas identidades podia ser ignorado, deixando histórico e seleção com referências antigas. | Instalação considera a identidade do objeto e incrementa a revisão. Teste de substituição, invalidação de snapshot, desfazer e refazer. |
| O marcador de fim do áudio era descartado se a fila estivesse cheia. | A reprodução podia esperar indefinidamente após o último bloco de PCM. | Entrega do marcador aguarda espaço com prazo curto e respeita cancelamento. Testes com fila limitada e consumidor atrasado. |
| O formato gerado pelo compositor não acompanhava a negociação da placa. | Taxa/canais podiam divergir; interpretar s16le como outro formato distorcia o áudio. | Runtime transmite a mesma taxa e quantidade de canais ao ffmpeg e ao sink. Formato incompatível não abre processo. |
| Falha ao abrir o sink deixava o produtor ativo. | ffmpeg podia ficar bloqueado produzindo áudio sem consumidor. | Falha de abertura interrompe a reprodução e coleta o processo. |
| EOF do produtor desativava o relógio antes de esvaziar a placa. | O fim do vídeo podia encerrar o áudio ainda armazenado no buffer. | A saída continua sendo o relógio até a parada efetiva. |
| Cancelamento anterior ao início e exceções na capa não cobriam toda a limpeza. | Reservas vazias e temporários podiam permanecer na pasta. | Limpeza externa ao fluxo serial/paralelo cobre preparação, execução, capa e publicação. |
| O temporário serial tinha nome previsível `.tmp_<destino>`. | Um arquivo existente com esse nome era sobrescrito e removido. | `mkstemp` cria arquivo exclusivo no volume de destino; teste preserva arquivo sentinela de outra operação. |
| Converter/exportador paralelo apenas enviavam terminate. | Um filho que ignorasse SIGTERM podia segurar a fila indefinidamente. | Parada imediata com espera em thread e kill após 200 ms; coleta também em exceções de leitura/progresso. Testes iniciam filhos reais que ignoram SIGTERM. |
| Fechar o diálogo de salvamento abandonava a espera; o retorno ignorava a aceitação do snapshot. | O controller podia continuar sem confirmação do estado salvo ou aceitar salvamento de sessão substituída. | Fechar/Escape não encerram o diálogo; somente resultado do worker. O retorno reflete `accept_saved`. |
| Nome personalizado aceitava componentes de caminho. | A saída podia escapar da pasta escolhida. | Rejeição de separadores, NUL e nomes `.`/`..`, antes de criar diretórios ou reservas. |
| Testes arquiteturais liam UTF-8 com encoding padrão do Windows. Outro teste assumia `/`. | Três testes falharam na primeira execução Windows. | Encoding explícito e comparação por `Path`, mantendo as mesmas verificações. |
| Junção paralela usava `-shortest` em streams já codificadas. | Pequenas diferenças de duração do AAC podiam cortar o último quadro de vídeo; a CI encontrou 359 em vez de 360. | Removido o corte adicional na junção. Regressão real reproduziu 44 em vez de 48 quadros e passou a preservar os 48; mantida a comparação serial/paralelo. |
| Provisionamento usava assets 7.1 retirados do `latest` do BtbN. | Primeira instalação e build Windows recebiam HTTP 404. | Publicação mensal fixa da mesma revisão 7.1; três testes de rede verificam os links Linux x86_64, Linux ARM64 e Windows x86_64. |
| Build Windows não verificava todas as saídas de comandos nativos. | PowerShell podia continuar após falha de instalação ou empacotamento. | Verificação de exit code em cada etapa e script reutilizável de diagnóstico com prazo. |
| Download parcial do runtime AppImage podia virar cache válido. | Uma falha de rede podia contaminar builds futuros. | Cache atualizado apenas após download bem-sucedido; patch aplicado numa cópia do runtime. |

A falha de identidade e as falhas de coordenação do salvamento foram encontradas
no código da migração. Parte dos problemas de áudio e gerenciamento de processos
já existia antes; foram corrigidos porque afetam o funcionamento esperado do
editor. A primeira execução dos novos cenários reproduziu seis falhas antes das
correções. Casos adicionais cobrem cancelamento forçado, negociação de PCM,
falha de abertura do dispositivo, final do áudio e fechamento do diálogo.

## Evidências

A matriz final e os links de execução são registrados após a conclusão da CI.
Os resultados locais incluem suíte offline completa, testes externos de rede,
úcleo sem dependências desktop, lint, contratos de arquivos e diagnósticos de
pacotes. As execuções se sobrepõem; seus totais não devem ser somados sem
distinguir quais cenários foram executados.

### Matriz nativa concluída

A [execução final da CI](https://github.com/GianBala/Video_Manager/actions/runs/34203445543)
terminou com **sucesso** no commit
`b2a31392c38790f988f5dcec5138053446352de3`:

| Ambiente | Testes | Empacotamento |
| --- | --- | --- |
| Ubuntu, Python 3.10 | Aprovados | Não previsto nessa variante. |
| Ubuntu, Python 3.12 | 860 aprovados, 5 skips, 11 de rede separados | PyInstaller e diagnóstico aprovados. |
| Windows, Python 3.10 | 858 aprovados, 7 skips, 11 de rede separados | Não previsto nessa variante. |
| Windows, Python 3.12 | Aprovados | Download ffmpeg 7.1, PyInstaller com ferramentas incluídas, diagnóstico e upload aprovados. |
| Núcleo, Python 3.10 sem dependências desktop | Aprovados | Não se aplica. |

A diferença dos skips é esperada: CI sem NVIDIA; testes de SIGTERM apenas
em POSIX; quatro combinações sem vídeo na fixture de áudio. Nenhum teste de
regressão foi desativado para obter esse resultado. Os novos testes de mídia
confirmam a correção do remux, mantendo a comparação serial/paralelo.

### Áudio e GPU reais

O script `scripts/validate_audio.py` usa o runtime da aplicação e a placa
`Built-in Audio Estéreo analógico`. A mídia de entrada é um tom mono a 44,1 kHz;
a saída negociada é s16le, estéreo, 48 kHz. O ensaio pausa e retoma a partir de
0,5 s, verifica que o relógio chega ao fim de 2 s, recebe exatamente um evento
de término e coleta ambos os subprocessos. O volume é baixo e pertence apenas
ao sink do ensaio; preferências e volume global não são modificados.

Último ensaio: pausa de 0,29 ms, posição final 2,000 s, reprodução do trecho
restante em 1,591 s, apenas `Error.NoError`. Isso comprova abertura, entrega e
consumo pelo dispositivo real; não substitui avaliação humana de timbre ou
sincronismo perceptivo com todos os dispositivos.

O teste de codificação NVIDIA executou na GPU física e verificou a fidelidade
por SSIM em comparação à saída por software. Os quatro skips de fixtures de
áudio são intencionais: aquelas entradas não têm vídeo para comparar containers.

### Rede

Os oito casos de mídia em rede passaram. Usam um manifesto HLS público de teste da Apple
e áudio público da NASA no SoundCloud. Medem streams de saída, resolução,
bitrate, cancelamento, cópia de áudio, conversão e preservação da origem.
Não usam cookies pessoais nem credenciais de plataformas. Outros três testes
HEAD verificaram a existência dos arquivos oficiais configurados para download.

### Distribuição

O diagnóstico `--smoke-test` verifica a janela, a fonte Carlito, prévia de texto
não vazia e exportação de um segundo medida com ffprobe. Precisa terminar com
código zero; um processo ainda aberto não conta como sucesso.

Linux possui ensaios do pacote em pasta e do AppImage, incluindo auto-extração.
O AppImage inclui ffmpeg/ffprobe. Windows é compilado e executado no runner
Windows; o pacote da CI fica disponível como artefato temporário por sete dias.
A variante Windows da CI provisiona e inclui ffmpeg/ffprobe com
`VM_BUNDLE_FFMPEG=1`, como o script `packaging/build_windows.ps1`.
A primeira validação do pacote também cobriu o modo sem ferramentas embutidas.

O pacote Windows está no [artefato da CI](https://github.com/GianBala/Video_Manager/actions/runs/34203445543/artifacts/10046937933)
e também foi copiado para `dist/validacao-clean-arch/VideoManager-Windows.zip`.

Os artefatos locais ficam em `dist/validacao-clean-arch/`, acompanhados de
`SHA256SUMS`. O AppImage final tem SHA-256
`18902effe2ddc1a01dec69fcb8d853947a0362e849ad36b22d9bcee699c99854`.

A URL de provisionamento foi fixada na [publicação mensal do BtbN](https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-07-31-14-10),
revisão `n7.1.5-12-g1fdbca85aa`. Atualizar essa dependência requer repetir os
ensaios de codecs, GPU e distribuição.

A branch remota `codex/validacao-clean-arch` contém o snapshot autorizado para a
CI. Não foi feito merge na main nem troca da branch de trabalho local.

## Reproduzir

```bash
.venv/bin/python -m pytest -q -rs
.venv/bin/python -m pytest -q -m network
.venv/bin/python -m pytest -q tests/domain tests/application tests/architecture
.venv/bin/python -m pyflakes src/videomanager tests scripts
PYTHONPATH=src .venv/bin/python scripts/validate_audio.py
packaging/smoke_run.sh dist/VideoManager/VideoManager 30
```

O ensaio de áudio precisa de sessão desktop e saída disponível. Em ambiente
headless, mantenha-o separado da suíte automática. `desktop_app` isola o arquivo
de preferências em diretório temporário, inclusive no Windows. O núcleo puro
não carrega essa fixture nem importa infraestrutura Qt.

`VM_DIST_DIR` e `VM_BUILD_DIR` permitem gerar os pacotes Linux/AppImage em
pastas separadas. O runtime AppImage continua dependente da arquitetura e das
bibliotecas do sistema; o patch de auto-extração não promete compatibilidade
com toda distribuição Linux.
