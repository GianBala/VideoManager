# Configurações

Aberto por **Ferramentas → Configurações…**. As mudanças só são gravadas ao
confirmar com **OK**; **Cancelar** descarta tudo o que foi ajustado no
diálogo. O arquivo salvo é `settings.json` — ver
[`instalacao.md`](instalacao.md#onde-ficam-as-preferências) para o caminho
exato em cada sistema.

O diálogo tem três abas.

## Geral

| Campo | O que faz |
|---|---|
| **Pasta de destino** (+ *Escolher…*) | Onde downloads, conversões e exportações caem por padrão. Cada aba ainda permite escolher "salvar na mesma pasta do original", que ignora esta preferência para aquele arquivo específico. |
| **Criar uma subpasta por site** | Downloads de sites diferentes vão para subpastas próprias (ex.: `youtube/`, `bilibili/`) em vez de tudo junto — ajuda quem baixa de muitas fontes. |
| **Tema** | Escuro ou Claro. |
| **Idioma** | Português (Brasil) ou English, cada um escrito no próprio idioma. Vale ao confirmar com **OK**, com a janela aberta: projeto, reprodução, fila e o que estiver escolhido continuam como estavam, e o desfazer não ganha passo. Acompanham a troca também os textos do próprio Qt (OK, Cancelar, o menu de contexto dos campos) e o separador decimal dos números (vírgula em português, ponto em inglês). O que foi digitado ou nomeado — trilhas, projeto, arquivos, o conteúdo de um texto — não é traduzido; trilhas e textos criados depois nascem no idioma novo. |
| **Codificação de vídeo** | Escolhe entre software (padrão) ou a placa de vídeo disponível (NVENC, Quick Sync, AMF, VAAPI — o que a máquina realmente tiver). O padrão continua sendo software porque comprime melhor no mesmo tamanho de arquivo; a placa é mais rápida, mas produz arquivos maiores para a mesma qualidade percebida. |
| **Testar agora** | Sonda de verdade se o encoder escolhido funciona nesta máquina — não só se o `ffmpeg` o lista, mas se ele **codifica um quadro sem falhar**. O texto ao lado mostra o resultado ("Verificando o que esta máquina aceita…" enquanto roda, depois o veredito). Mesmo que a sonda falhe, a exportação nunca trava por isso: ela cai para software automaticamente. |

## Rede

| Campo | O que faz |
|---|---|
| **Downloads simultâneos** | De 1 a 10 — quantos downloads a fila processa ao mesmo tempo. Não afeta conversões nem exportações de edição, que têm sua própria fila local de uma tarefa por vez (ver [tarefas e concorrência](clean-architecture/tarefas.md#adaptador-qt)). |
| **Fragmentos simultâneos por download** | De 1 a 16 — paralelismo dentro de **um** download (streams fragmentados, como HLS/DASH). |
| **Limite de banda** | Em KB/s; `0` = sem limite. |
| **Ler cookies do navegador** | "Não usar cookies" ou a lista de navegadores suportados pelo yt-dlp instalados na máquina. Necessário para vídeos com restrição de idade, privados, de assinantes/membros, e para as resoluções mais altas do BiliBili — nesses casos o site exige uma sessão conectada, e esta opção reaproveita os cookies já salvos naquele navegador em vez de pedir login dentro do app. |

## Legendas e metadados

| Campo | O que faz |
|---|---|
| **Embutir a capa no arquivo** | Grava a miniatura da mídia como capa do arquivo baixado. Em formatos que não aceitam capa (`.webm`, `.wav`), o arquivo é entregue sem ela e o log da tarefa registra o aviso — o download não falha por isso. |
| **Gravar metadados** | Título, autor, data etc., quando o extrator os fornece. |
| **Baixar legendas em arquivo separado** | Salva um `.srt` ao lado do vídeo. |
| **Embutir legendas no arquivo** | Grava a legenda dentro do próprio arquivo de vídeo. |
| **Incluir legendas geradas automaticamente** | Além das legendas manuais (feitas por humanos), também considera as legendas automáticas da plataforma — que costumam ter mais erros de transcrição. |
| **Idiomas** | Lista separada por vírgula (ex.: `pt, pt-BR, en`), na ordem de preferência. |

## Sobre a codificação por placa de vídeo

Vale registrar como essa opção se comporta na prática, porque ela é diferente
do que "escolher um encoder" costuma significar em outros programas:

- A escolha é **sondada de verdade**, não apenas listada — o app manda a
  placa codificar um quadro antes de confiar nela.
- Se a sondagem falhar (driver incompatível, placa ocupada, recurso ausente),
  a exportação **cai para software sozinha**, sem travar no meio da fila.
- A placa acelera **apenas a codificação**. Filtros da linha do tempo
  (sobreposição de trilhas, cortes) continuam rodando na CPU — não há ganho
  de desempenho na composição em si, só na etapa final de gravar o arquivo.
