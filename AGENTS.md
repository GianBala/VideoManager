# Contexto do projeto

## Visão geral

Video Manager é um aplicativo desktop em pt-BR para Windows e Linux. Reúne
download de vídeo e áudio, conversão de arquivos locais e edição multipista.
A interface usa PySide6; yt-dlp faz a extração e o download; ffmpeg e ffprobe
processam e inspecionam mídia.

O pacote Python chama-se `videomanager`, usa layout `src/` e exige Python 3.10
ou superior. A versão está declarada em `pyproject.toml` e em
`src/videomanager/__init__.py`.

## Funcionalidades e fluxos

- **Download:** análise de URL → normalização dos formatos disponíveis → escolha
  de qualidade/container → criação de opções do yt-dlp → fila. Inclui playlists,
  extração de áudio, legendas, metadados e autenticação por cookies.
- **Convert:** inspeção de arquivos locais → escolha do alvo de vídeo/áudio →
  reserva do destino → fila de processamento com ffmpeg.
- **Editar:** acervo de mídias → projeto com trilhas de vídeo, áudio e adicionais
  → cortes, transformações, volume, velocidade, textos, filtros e transições →
  prévia e exportação. Projetos são salvos como JSON com extensão `.vmp`.
- A fila é compartilhada entre as abas. No editor, ela fica oculta para ampliar
  a área de trabalho. Exportações continuam sendo acompanhadas pela fila.

## Organização do código

| Local | Responsabilidade |
| --- | --- |
| `src/videomanager/__main__.py` | Ponto de entrada do Python e do PyInstaller. |
| `src/videomanager/app.py` e `preflight.py` | Inicialização, estilo, recursos e verificações do ambiente Qt. |
| `src/videomanager/core/` | Modelos, regras de mídia, persistência e integração com ferramentas externas. |
| `src/videomanager/workers/` | Execução em segundo plano com `QRunnable`, sinais Qt e filas. |
| `src/videomanager/ui/` | Janela principal, diálogos, áudio da prévia, tema e textos. |
| `src/videomanager/ui/panels/` | Painéis de download, conversão, edição, qualidade e fila; timeline. |
| `src/videomanager/resources/` | Ícones e fontes distribuídos com o aplicativo. |
| `tests/` | Testes unitários, de interface e de integração com mídia. |
| `tests/fixtures/` | Respostas de extratores para testes offline. |
| `docs/` | Guias de uso, arquitetura, desenvolvimento e empacotamento. |
| `packaging/` | Scripts Linux/Windows, especificação PyInstaller e AppImage. |
| `scripts/` | Scripts auxiliares, incluindo geração de AppImage. |
| `vendor/`, `build/`, `dist/` | Binários provisionados e artefatos de empacotamento. |

A direção arquitetural é interface → workers → domínio, com uso direto dos
modelos de `core` pela interface. A lógica de mídia é independente de Qt.
`core/text_assets.py` define o contrato
de rasterização; `ui/text_renderer.py` instala o adaptador Qt na inicialização
e produz imagens de texto imutáveis, reutilizadas por conteúdo.

## Módulos e conceitos principais

- `core/probe.py`, `format_matrix.py`, `models.py`: transformam a resposta
  heterogênea dos extratores em informações e escolhas de mídia normalizadas.
- `core/selector.py`: transforma a escolha de download em expressões de formato
  e pós-processadores do yt-dlp. `downloader.py` executa cada tarefa com uma
  instância própria de `YoutubeDL` e reporta progresso.
- `core/converter.py`: inspeciona arquivos locais, define alvos, reserva nomes
  de saída, monta comandos e executa conversões e exportações.
- `core/trimmer.py`: segmentos, keyframes e recorte rápido ou exato.
- `core/project.py`: `MediaRef`, `Clip`, `Track` e `Project`; operações de edição
  retornam novos modelos imutáveis. `core/editor_session.py` mantém o histórico
  de desfazer/refazer e o ponto salvo.
- `core/project_io.py`: serialização e leitura de `.vmp`, referências às mídias e
  identificação de arquivos ausentes. O arquivo referencia as mídias; não as embute.
- `core/composer.py`: grafo de filtros usado pela exportação, prévia de quadros
  e mixagem de áudio. `Composition` representa um pedido de exportação.
- `core/preview.py`: extração de quadros, miniaturas, forma de onda e reprodução.
- `core/parallel_export.py`, `memory.py`: divisão da exportação interpolada em
  segmentos, com planejamento de concorrência conforme recursos disponíveis.
- `core/hwaccel.py`: escolha e sondagem de encoders de hardware, com alternativa
  por software. Interpolação de movimento é uma opção explícita e tem custo alto.
- `core/binaries.py`: localização, validação e provisionamento de ffmpeg/ffprobe;
  preparação do ambiente de subprocessos.
- `core/process.py`, `thumbnail.py`: subprocessos com prazo e cancelamento, e
  geração opcional de capa, executada uma única vez antes de entregar a exportação.
- `core/settings.py`: preferências JSON persistidas nos diretórios do usuário,
  com suporte de `platformdirs`. `core/errors.py` reúne as exceções do domínio.
- `workers/queue.py`: `JobQueue` controla os estados de `Job`; há uma pool de
  downloads configurável e outra de processamento local com uma vaga.
- `workers/runner.py`: mantém referências aos workers até seus sinais finais.
  O editor tem pools separadas para prévia/reprodução e trabalho de fundo.
- `ui/panels/edit_panel.py`: coordena projeto, acervo, propriedades, edição,
  reprodução. `ui/editor_project.py` coordena persistência e acervo, com leitura
  cancelável em `workers/media_worker.py`; `edit_widgets.py` reúne os widgets
  visuais. `timeline.py` desenha a timeline e emite intenções
  de edição. `ui/export_dialog.py` configura e enfileira a exportação.
- `ui/audio_preview.py`: recebe PCM do ffmpeg e alimenta `QAudioSink`; o áudio
  fornece o relógio da reprodução. `ui/fullscreen_preview.py` apresenta a prévia
  em tela cheia.

## Ambiente e comandos

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
PYTHONPATH=src .venv/bin/python -m videomanager

# Suíte padrão: inclui integração local e exclui testes marcados como network.
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q

# Suíte rápida, sem integração com ffmpeg.
.venv/bin/python -m pytest -q -m "not network and not ffmpeg"

# Execução direcionada.
.venv/bin/python -m pytest -q tests/test_project_io.py

# Integração marcada como network: pode acessar serviços externos.
.venv/bin/python -m pytest -m network

# Análise estática, quando pyflakes estiver instalado no ambiente.
.venv/bin/python -m pyflakes src/videomanager tests
```

Em Windows, use os executáveis equivalentes de `.venv\Scripts\`.
As dependências de execução declaradas são PySide6, yt-dlp e platformdirs;
o extra `dev` declara pytest e pyflakes. ffmpeg e ffprobe são executáveis externos,
procurados nas localizações gerenciadas pelo aplicativo e no sistema.

Os testes atuais incluem instâncias Qt em modo offscreen. Esse modo dispensa
display; `tests/conftest.py` também isola a disponibilidade do dispositivo de
áudio e configura o renderizador de textos. As fixtures de mídia permitem
verificar extratores sem rede. Testes `ffmpeg` usam executáveis locais e entram
na suíte padrão; apenas os cenários que acessam serviços externos têm marca
`network`. Hardware indisponível é informado como teste ignorado.

## Convenções para alterações

- Use pt-BR em comentários, docstrings, textos de interface, erros e commits.
  Preserve os identificadores e o estilo dos módulos existentes.
- Centralize novos textos de interface em `ui/strings.py`; cores, paleta e QSS
  ficam em `ui/theme.py`. A aplicação utiliza o estilo Qt Fusion.
- Comentários devem explicar decisões e restrições, sem repetir a instrução.
- Preserve a imutabilidade dos modelos de edição e a identidade dos clipes e
  trilhas ao transformar projetos. A timeline comunica intenções; o painel
  aplica as operações ao modelo.
- Preserve a distinção entre codec ausente e codec explicitamente `"none"`
  nas respostas de extratores. Limites de formato usam filtros tolerantes a
  metadados ausentes, como `[height<=?720]`.
- Não introduza recodificação silenciosa em downloads. Compatibilizações de
  stream ou container devem ser comunicadas ao usuário.
- Diferencie corte exato, que recodifica, de corte rápido, que depende de
  keyframes. Prévia e exportação devem representar as mesmas regras de composição.
- Trabalho demorado deve usar workers. Mantenha sinais de sucesso, falha e
  cancelamento, referências aos workers e encerramento dos processos associados.
- Use `core/binaries.subprocess_kwargs()` ao iniciar ferramentas externas:
  ele trata o ambiente do pacote e a janela de console no Windows.
- Preserve a reserva de nomes de saída e a limpeza de resultados parciais.
- Valide mudanças de mídia pela saída real quando necessário: duração, streams,
  codecs, volume e quadros. Comparações de comandos não substituem essa medição.
- Não versione cookies, URLs assinadas ou dados de sessão em fixtures.
- Não adicione `Co-Authored-By` em commits, PRs, tags ou changelogs, conforme a
  convenção registrada em `CLAUDE.md`.

## Empacotamento e documentação

```bash
./packaging/build_linux.sh
./packaging/build_appimage.sh
# Windows/PowerShell:
.\packaging\build_windows.ps1
```

Os builds usam PyInstaller e são feitos no sistema de destino. Os scripts
podem instalar dependências, baixar binários e recriar `build/` e `dist/`.
O AppImage envolve o pacote Linux; `VM_BUNDLE_FFMPEG=0` permite gerar o pacote
Linux sem embutir os binários. `packaging/smoke_run.sh` verifica a inicialização
do executável Linux gerado. O ponto de entrada usa import absoluto para funcionar
também quando executado pelo PyInstaller.

Consulte `README.md` para apresentação e instalação, `docs/` para os guias, e
`CLAUDE.md` para decisões históricas detalhadas. Ao alterar um comportamento,
confira sua implementação e seus testes e mantenha a documentação correspondente
coerente.
