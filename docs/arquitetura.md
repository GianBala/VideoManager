# Arquitetura

Video Manager usa Clean Architecture para separar regras, coordenação,
apresentação Qt e integrações. O [guia completo](clean-architecture/README.md)
explica os conceitos, fluxos e contratos; esta página serve de mapa inicial.

```text
domain          modelos e regras puras
application     casos de uso, sessão, tarefas e portas
infrastructure  Qt, ffmpeg, yt-dlp, arquivos e sistema
presentation    widgets, controllers e apresentação dos resultados
bootstrap/app   montagem explícita das dependências
```

A dependência aponta para dentro: aplicação conhece domínio; adaptadores e
apresentação conhecem os contratos/modelos internos. Domínio e aplicação não
importam ferramentas externas. A apresentação recebe serviços e runtime desktop
por injeção, sem importar suas implementações. Testes de arquitetura protegem
esses limites e a ausência de ciclos.

| Fluxo | Coordenação | Implementação externa |
| --- | --- | --- |
| Abrir/importar/salvar | ReadMedia, EditorService, EditorSession | JSON, ffprobe, MediaWorker e FunctionWorker. |
| Download | DownloadService e política de container/qualidade | YtDlpGateway, probe, seletor, Downloader. |
| Converter/exportar | ProcessingService e pedidos tipados | Converter, compositor, trimmer e FileOutputStore. |
| Fila | JobService com identidade de tentativa | JobQueue, pools e receptores Qt. |
| Prévia/texto/áudio | PreviewRequest e porta de rasterização | Compositor, FramePump, QtTextRasterizer e AudioPreview. |

O editor tem modelos imutáveis e histórico de snapshots. A timeline desenha
e emite intenções; o controller aplica operações dos modelos e atualiza a
sessão da aplicação. Workers produzem resultados, aceitos na thread principal
apenas quando pertencem à operação atual.

Conversões locais usam uma vaga na fila; downloads têm concorrência configurável.
Prévia e trabalhos de fundo usam pools próprias. Saídas de conversão/exportação
são reservadas, renderizadas em temporário e publicadas sobre a reserva após
pós-processamento. Cancelamento também alcança a etapa final.

Os algoritmos de normalização, seleção tolerante, composição compartilhada,
keyframes, hardware e paralelismo são descritos nos capítulos específicos:

- [Editor e persistência](clean-architecture/editor.md)
- [Tarefas e recursos](clean-architecture/tarefas.md)
- [Conversão/exportação](clean-architecture/processamento.md)
- [Downloads e normalização](clean-architecture/downloads.md)
- [Prévia, áudio e texto](clean-architecture/previa.md)
- [Catálogo completo dos módulos](clean-architecture/modulos.md)
- [Evolução e testes](clean-architecture/evolucao.md)
- [Evidências da migração](clean-architecture/migracao.md)

O [plano original](plano-clean-architecture.md) foi preservado como registro.
A estrutura antiga core/workers/ui foi removida; ela não descreve o código atual.
