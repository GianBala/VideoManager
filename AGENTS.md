# Contexto do projeto

## Visão geral

Video Manager é um aplicativo desktop em pt-BR para Windows e Linux. Reúne
download de vídeo/áudio, conversão local e edição multipista com projetos
`.vmp`. Usa Python 3.10+, PySide6, yt-dlp e platformdirs; ffmpeg/ffprobe são
executáveis externos. O pacote é `videomanager`, com layout `src/`.
A versão é declarada em `pyproject.toml` e `src/videomanager/__init__.py`.

Este arquivo é uma visão geral do projeto. A documentação técnica detalhada
começa em [docs/clean-architecture/README.md](docs/clean-architecture/README.md).
O plano e as evidências da migração estão em documentos próprios.

## Fluxos principais

- Download: URL → extração e normalização → qualidade/container → pedido tipado
  → fila yt-dlp. Inclui playlists, áudio, legendas, metadados e cookies.
- Convert: inspeção local assíncrona → alvo de áudio/vídeo → reserva de saída
  → processamento ffmpeg na fila.
- Editar: acervo → projeto imutável com trilhas e clipes → cortes, transforms,
  animação por quadros-chave, volume, velocidade, texto, filtros, chroma key e
  transições → prévia/exportação (MP4, MKV, WebM, MOV ou GIF animado). Importar
  só leva a mídia ao acervo; ela vai à trilha por arrasto ou por "Inserir no
  cursor". Proporção, tela e taxa são preferências do painel, fora do histórico.
- A fila é comum às abas e fica oculta no editor para ampliar a área de trabalho.
- O .vmp é JSON versão 3, com leitura de v1 e v2; referencia mídias externas,
  sem embutir seus bytes. Salvar sobre v1/v2 preserva `.vmp.v1.bak`/`.vmp.v2.bak`.
  Imagens vivem na trilha de vídeo, ajustadas à tela; ao abrir v1/v2 elas saem
  das trilhas de Adicionais com a escala convertida. "Salvar como" grava outro
  `.vmp` e a sessão passa a apontar para ele, com o histórico intacto.

## Estrutura e direção de dependências

| Local em src/videomanager | Responsabilidade |
| --- | --- |
| `domain/` | Modelos imutáveis, regras de edição, quadros-chave, formatos, compatibilidade, tempo e estimativas. |
| `application/editor/` | Sessão, histórico, snapshots, abrir/importar/salvar. |
| `application/jobs/` | Pedidos tipados e transições de tarefas por tentativa. |
| `application/media/` | Preparação de conversão/exportação/download/prévia e descrições. |
| `application/ports/` | Contratos de repositório, probe, gateway, saída e rasterização. |
| `infrastructure/ffmpeg/` | Inspeção, comandos, compositor, cortes, quadros, hardware e execução. |
| `infrastructure/yt_dlp/` | Extração, normalização, seletores e download. |
| `infrastructure/storage/` | JSON de projetos/preferências e reserva/publicação de arquivos. |
| `infrastructure/system/` | Binários, subprocessos, cancelamento e memória disponível. |
| `infrastructure/qt/` | Áudio, rasterização e workers/pools. |
| `presentation/qt/` | Janela, controllers, diálogos, painéis, timeline, estilos e textos. |
| `bootstrap.py` / `app.py` | Montagem das dependências e QApplication. |
| `__main__.py` / `preflight.py` | Entrada absoluta compatível com PyInstaller e diagnóstico do ambiente Qt. |
| `resources/` | Ícones e fontes empacotados. |

A aplicação depende do domínio; infraestrutura e apresentação dependem das
camadas internas. Domínio/aplicação usam apenas biblioteca padrão, sem Qt,
yt-dlp, platformdirs ou subprocessos. Apresentação não importa infraestrutura.
`DesktopRuntimePort`, definido pela apresentação, recebe a implementação
`DesktopRuntime` pelo bootstrap. O runtime fornece adaptadores Qt e serviços
do ambiente, sem possuir estado de sessão ou tarefas.

Não há pacotes de produção `core/`, `ui/` ou `workers/` na raiz do pacote.
O [catálogo de módulos](docs/clean-architecture/modulos.md) cobre os arquivos
atuais e suas responsabilidades.

## Estado, concorrência e recursos

- `Project`, `Track`, `Clip` e `MediaRef` são imutáveis.
  Operações preservam identidades ao transformar objetos.
- `EditorSession` possui projeto, caminho, ponto salvo e histórico de 60 estados.
  Workers recebem snapshots; a thread principal aceita resultados por geração/revisão.
  Cada gesto (arrastar bloco, alça ou objeto) é uma transação
  (`begin_edit`/`commit_edit`/`cancel_edit`): um gesto, um desfazer.
- Resultados de prévia só chegam à tela no contexto que os pediu
  (`PreviewResultKey`: geração, revisão, instante, tamanho e taxa). O quadro
  parado mostra o quadro que contém o instante da agulha; o cache de quadros da
  agulha (`domain/scrub` + `application/media/scrub`) só responde durante o
  arrasto, e o quadro exato chega quando a mão para.
- `JobService` possui transições. Eventos levam a identidade da tentativa;
  término é aceito uma vez. Widgets observam Job, sem alterar seus estados.
- A fila Qt separa downloads configuráveis de processamento local com uma vaga.
  Editor e inspeção da conversão têm pools próprias.
- `WorkerRunner` mantém referências até os sinais finais.
  Encerrar/cancelar deve alcançar subprocessos e pós-processamento.
- `OutputLease` identifica a reserva de saída. O arquivo é renderizado em
  temporário no mesmo volume, recebe capa e só então é publicado.
  A limpeza não pode apagar uma saída concluída ou um arquivo de outra operação.
- O compositor é compartilhado entre exportação, quadros, reprodução e áudio.
  A prévia usa buffers limitados e áudio como relógio quando disponível.
- Texto usa `TextRasterizer` injetado, sem registro global. O adaptador Qt
  mantém PNGs imutáveis por conteúdo; deve viver enquanto houver consumidores.
  Fontes são carregadas depois de criar QApplication e antes de rasterizar.

## Ambiente e validação

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
PYTHONPATH=src .venv/bin/python -m videomanager

QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests/domain tests/application tests/architecture
.venv/bin/python -m pytest -q -m "not network and not ffmpeg"
.venv/bin/python -m pytest -m network
# Ensaio opt-in com áudio real em volume baixo:
PYTHONPATH=src .venv/bin/python scripts/validate_audio.py
# Resposta da agulha com e sem o cache de quadros:
PYTHONPATH=src .venv/bin/python scripts/validate_scrub.py
# Gestos na prévia e responsividade do editor (Qt e ffmpeg reais, sem áudio):
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python scripts/validate_preview_gestures.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python scripts/validate_editor_responsiveness.py
.venv/bin/python -m pyflakes src/videomanager tests scripts
git diff --check
```

Em Windows, use `.venv\Scripts`. O extra dev contém pytest e pyflakes.
A suíte padrão exclui rede e inclui integração local ffmpeg e Qt offscreen.
Fixtures Qt são explícitas; domínio e aplicação não inicializam QApplication.
Hardware indisponível pode causar skip. O teste arquitetural verifica imports,
ciclos e carregamento interno sem site-packages. O ffmpeg do usuário vai da 6 à
9 e algumas opções mudam entre elas (`command_assets` escolhe a do grafo em
arquivo; o VP9 exige `-pix_fmt`); testes que dependem de comportamento posterior
à 6 declaram `_exige_ffmpeg(tools, 7)`. A CI cobre 6.1, 7.1 e 9.0.

`tests/fixtures/` contém respostas sanitizadas de extratores.
`scripts/benchmark_architecture.py` compara inicialização, prévia, busca e
exportação entre checkouts usando mídia sintética e ferramentas iguais.
Veja [testes](docs/clean-architecture/testes.md) para detalhes e limites.

## Convenções

- Use pt-BR em comentários, docstrings, interface, erros e mensagens de commit.
- Novos textos de controles ficam em `presentation/qt/strings.py`; cores,
  QSS e paleta em `theme.py`. O estilo é Fusion.
- Comentários explicam decisões e restrições, sem repetir a instrução.
- Preserve a diferença entre codec desconhecido e `"none"` no yt-dlp.
  Limites tolerantes usam sintaxe como `[height<=?720]`.
- Não recodifique vídeo silenciosamente por incompatibilidade de container.
  Preserve avisos de substituição e escolhas explícitas.
- Diferencie corte exato e rápido; copiar streams depende de keyframes e da
  elegibilidade da edição. Prévia e saída devem representar as mesmas regras.
- I/O demorado deve rodar em workers. Não instalar respostas de operações antigas.
- Use `infrastructure.system.binaries.subprocess_kwargs()` para ferramentas.
- Teste mudanças de mídia medindo duração, streams, codecs, volume e quadros.
- Em interação Qt, teste com eventos reais (`QTest`, `sendEvent`), não chamando
  handlers. Em fluidez e tempo, meça no painel real e compare com o commit
  anterior antes de concluir que algo regrediu ou melhorou.
- Não versione cookies, cabeçalhos, URLs assinadas ou dados de sessão.
- Não adicione `Co-Authored-By` a commits, PRs, tags ou changelogs, conforme
  a convenção histórica registrada em CLAUDE.md.

## Distribuição e documentação

```bash
./packaging/build_linux.sh
./packaging/build_appimage.sh
# Windows/PowerShell:
.\packaging\build_windows.ps1
```

Os builds PyInstaller acontecem no sistema de destino. Os scripts podem baixar
dependências/binários e recriar build/dist. Nos scripts de Linux os testes rodam
em modo rápido por padrão (`-m "not ffmpeg and not network"`); `VM_FAST_TESTS=0`
inclui as integrações com ffmpeg, e `build_windows.ps1` sempre roda a suíte
completa. No Windows o resultado é um único
`dist\VideoManager.exe`, que funciona sozinho mas extrai tudo para `%TEMP%` a
cada abertura (~3 s de extração e janela em ~5 s; o `--smoke-test` inteiro leva
~8 s, contra ~2 s da pasta); `VM_ONEFILE=0` gera a pasta `dist\VideoManager\`,
que abre na hora e só funciona com `_internal` ao lado. No Linux é sempre pasta
(o AppImage a envelopa). `VM_BUNDLE_FFMPEG=0` dispensa
embutir ffmpeg; nesse caso as ferramentas devem estar disponíveis no ambiente.
`VM_BUNDLE_DENO=0` dispensa o Deno que o yt-dlp usa no YouTube (vale então
Deno/Node do sistema). O ícone do .exe sai de `packaging/make_icon.py` (bitmap
clássico em todos os tamanhos; no pacote em pasta o `.ico` também vai solto ao
lado do `.exe`) e precisa existir antes do PyInstaller.
`VideoManager --diagnose-url URL --report ARQ` refaz a análise pela janela no
pacote; o log fica em `platformdirs.user_log_dir`.

`--smoke-test` verifica janela, fontes, prévia e exportação curta, sem consultar
dispositivo físico de áudio. `packaging/smoke_run.sh` exige conclusão com prazo
e marcador de sucesso. Um build Linux não valida Windows.

Leia [README.md](README.md) para apresentação, [docs/README.md](docs/README.md)
para manuais e [docs/desenvolvimento.md](docs/desenvolvimento.md) para contribuir.
Mantenha esses documentos coerentes com o código. CLAUDE.md registra decisões
históricas locais, mas seus caminhos podem refletir versões anteriores.
