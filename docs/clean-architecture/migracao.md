# Registro da migração

Base: commit `e2e91d0` (`correcao de bugs`).
Implementação e validação local em 7 de setembro de 2026.
O [plano original](../plano-clean-architecture.md) está preservado; este registro
descreve o que foi entregue, sem converter validações pendentes em aprovações.

## Entregas por etapa

| Etapa | Implementação e evidência |
| --- | --- |
| 0 — Proteção | Baseline: 806 aprovados, 5 ignorados, 8 de rede excluídos em 51,85 s. Fixtures Qt tornadas explícitas; testes internos e verificações de dependência criados. |
| 1 — Domínio e montagem | Modelos de edição/mídia, seleções, compatibilidade, tempo, estimativas e composição sem ferramentas externas. Bootstrap explícito; importação interna testada sem site-packages. |
| 2 — Editor e sessão | ReadMedia/EditorService/EditorSession, portas de repositório/probe, histórico encapsulado, geração/revisão, escrita de snapshot fora da UI e API pública para o controller de projetos. |
| 3 — Tarefas | JobService com um proprietário das transições, pedidos tipados, ProgressStage e identidade por tentativa. Fila Qt separa pools e entrega sinais em receptores próprios. Job.opts removido. |
| 4 — Conversão/exportação | ProcessingService prepara alvos e recursos; ffmpeg fica em adaptadores. OutputLease, publicação atômica e limpeza por propriedade. Inspeção da aba Convert tornou-se assíncrona e cancelável. |
| 5 — Download | Gateway yt-dlp, normalização externa, modelos neutros, política de seleção/container e tradução de opções isoladas. Resultados de análise antigos não alteram uma nova solicitação. Fixtures/parser offline preservados. |
| 6 — Prévia/áudio/editor | Pedidos semânticos, RawFrame sem Qt, compositor comum, runtime injetado, buffers/pools preservados e rasterização por instância sem registro global. Controller mantém somente coordenação visual e chamadas de modelos/serviços. |
| 7 — Consolidação | Preferências compartilhadas, remoção dos pacotes antigos, documentação completa, CI, recursos da wheel e PyInstaller atualizados. Diagnóstico Linux verifica janela, fonte, prévia e exportação. Validação nativa Windows permanece dependente do ambiente de destino. |

Não há implementação duplicada nos antigos core/ui/workers. Alguns adaptadores
reexportam tipos/constantes usados por seus consumidores diretos; as definições
originais desses tipos estão nas camadas internas e não existem wrappers legados.

## Ajustes em relação à estrutura sugerida

- Os serviços foram agrupados por fluxo em editor/jobs/media, sem framework
  de injeção e sem uma classe para cada função pura.
- O contrato DesktopRuntimePort pertence à apresentação, que consome fábricas
  Qt e serviços desktop. A implementação não importa widgets.
- EditPanel combina widgets e controller de gestos; não foi criado um view model
  separado para cada controle. Projeto/histórico pertencem à sessão da aplicação.
- Formatações reutilizadas em descrições de tarefas ficam na aplicação; rótulos
  de estado Qt ficam na apresentação. Decisões não dependem de texto traduzido.
- Parte dos testes antigos permanece em tests/test_*.py, com imports atualizados
  e fixtures explícitas, preservando seus cenários. Os novos grupos protegem
  contratos e fronteiras.
- A validação do pacote foi reforçada: apenas sobreviver alguns segundos não
  comprova inicialização. --smoke-test exige trabalho concluído e saída válida.

## Verificações executadas

| Verificação | Resultado local |
| --- | --- |
| Suíte completa | **834 aprovados, 5 ignorados, 8 de rede excluídos**, 54,66 s. |
| Núcleo em ambiente sem dependências desktop | **86 aprovados**, 0,33 s, com Python/pytest e dependências do pytest; PATH sem ferramentas externas. |
| Verificação final direcionada a recorte/aplicação/arquitetura | **102 aprovados**, 0,36 s, após o ajuste de rótulo OGA/Vorbis. |
| Pyflakes | Sem erros em src, tests e script de benchmark. |
| Imports/ciclos | Nenhum import proibido, ciclo ou referência aos pacotes antigos. |
| Compatibilidade .vmp | Projeto criado pela versão nova foi lido e regravado pelo baseline e2e91d0 e lido novamente pela nova versão, preservando conteúdo e IDs. |
| Wheel | Gerada sem baixar dependências; fontes incluídas e pacotes antigos ausentes. Diagnóstico executado a partir da wheel extraída. |
| PyInstaller Linux | Pacote em pasta gerado com VM_BUNDLE_FFMPEG=0; diagnóstico passou usando as ferramentas locais no PATH. |
| Diagnóstico de distribuição | Janela, Carlito, prévia de texto não vazia e exportação de 1 s com stream/duração válidos. Encerramento com código zero. |
| Interface offscreen | As três abas foram renderizadas e encerradas; não substitui interação/áudio físicos. |
| Documentação | Links locais e sintaxe dos exemplos Python conferidos; catálogo cobre todos os módulos de produção. |

A suíte completa e o grupo interno se sobrepõem; os números não devem ser
somados como testes distintos. Rede não foi consultada na validação funcional.

## Comparação de desempenho

Cinco execuções por cenário, intercalando baseline e versão migrada em processos
separados. Ambiente: Linux x86_64, Python 3.12.3, Intel Core i7-13650HX.
Entrada: testsrc2 e seno, 640×360, 24 fps, 3 s, H.264/AAC.
As duas versões usam o mesmo ffmpeg. Dados e identificação completa:
[medicoes.json](medicoes.json).

| Cenário | Mediana anterior | Mediana atual | Intervalo anterior | Intervalo atual |
| --- | ---: | ---: | ---: | ---: |
| Montar janela | 867,4 ms | 883,4 ms | 865,6–896,2 ms | 878,9–906,5 ms |
| Primeiro quadro de prévia | 31,4 ms | 28,8 ms | 27,0–32,7 ms | 25,2–35,2 ms |
| Buscar a 1,5 s | 30,6 ms | 29,9 ms | 28,1–35,0 ms | 29,4–33,5 ms |
| Exportar composição serial | 226,4 ms | 233,8 ms | 214,6–234,6 ms | 227,2–236,8 ms |

A mediana da inicialização aumentou cerca de 16 ms e a da exportação, 7,4 ms
neste ensaio. Os intervalos se sobrepõem; cinco amostras pequenas não permitem
atribuir essas diferenças exclusivamente à arquitetura. Não há evidência aqui
de aceleração significativa do processamento de vídeo.

O pico mediano de RSS do Python na exportação passou de aproximadamente
43,0 MiB para 27,7 MiB; o maior pico de um subprocesso ficou próximo de
150 MiB nas duas versões. Na janela, o Python ficou próximo de 143 MiB.
Esses valores são picos separados, não memória simultânea total. A importação
de menos integrações no caminho direto do backend é uma explicação plausível
para a diferença do processo Python, não uma garantia para todo projeto.

O ensaio de inicialização desabilita a consulta a áudio nas duas versões.
Ele não mede latência de dispositivo, rede, aceleração GPU, interpolação 4K,
projetos extensos ou fluidez sob interação. O objetivo da migração é
manutenção, isolamento e testabilidade; medições representativas continuam
necessárias ao alterar algoritmos e buffers.

## Checkup posterior e validações nativas

O [checkup final](validacao-final.md) substitui as pendências do registro acima
pelas evidências atualizadas. A revisão acrescentou testes de regressão e
corrigiu identidade da sessão, coordenação do salvamento, áudio, limpeza e
cancelamento de processos, arquivos temporários, nomes de saída, portabilidade
Windows e perda de quadros na junção da exportação paralela.

A [CI final Linux/Windows](https://github.com/GianBala/Video_Manager/actions/runs/34203445543)
foi concluída com sucesso em Python 3.10/3.12, incluindo o pacote Windows com
ffmpeg e diagnóstico nativo. A suíte final local alcançou **861 aprovados**, com GPU real; os quatro skips
são casos de fixtures sem vídeo. Os oito testes de mídia em rede e os três testes dos endereços de provisionamento passaram. AppImage,
áudio físico, wheel e pacote Linux foram verificados. O relatório registra a
matriz Windows/Linux e distingue os ensaios automatizados da avaliação humana
de sincronismo perceptivo e de projetos extensos.
