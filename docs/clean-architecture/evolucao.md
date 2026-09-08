# Como evoluir o projeto

## Primeiro contato com o código

Prepare o ambiente pelo [guia de desenvolvimento](../desenvolvimento.md).
Leia a [visão geral](README.md), depois o capítulo do fluxo que vai alterar.
Use o [catálogo](modulos.md) para localizar os módulos.

A inicialização segue esta ordem:

1. `__main__.py` chama `app.main`, com import absoluto compatível com PyInstaller.
2. O preflight verifica bibliotecas gráficas antes de criar Qt.
3. `build_app` cria QApplication, carrega fontes, ícone, Fusion, paleta e QSS.
4. `load_preferences` lê a configuração por infraestrutura e entrega `Preferences`.
5. O bootstrap monta editor, processamento, downloads e runtime desktop.
6. `MainWindow` recebe essas dependências e cria painéis/fila.
7. Depois de mostrar a janela, o bootstrap visual resolve ffmpeg.
8. O laço de eventos recebe ações e resultados dos workers.

Serviços ficam vivos com a janela. Não buscar dependências concretas num módulo
global a partir de um caso de uso: acrescente uma porta ou use a dependência
já fornecida.

## Exemplo: acrescentar uma regra de edição

Imagine adicionar uma operação de ajuste de volume em lote:

1. Expresse a transformação em `domain/project.py` ou módulo de política.
   Receba projeto, IDs e ganho; devolva novo projeto preservando IDs.
2. Teste seleção parcial, clipes sem áudio e limites no domínio.
3. O controller registra `remember()` uma vez para a ação do usuário e
   instala o projeto com `replace_current`.
4. Acrescente controle/atalho e texto em `presentation/qt`.
5. Se o ganho persistido não mudou de formato, o JSON pode não exigir alteração.
   Se houver campo novo, adapte o serializador e a leitura de arquivos anteriores.
6. Verifique o compositor: o ganho da prévia e o da exportação devem coincidir.
7. Se o processamento de áudio mudou, meça o volume de uma saída real.

Uma transformação matemática não precisa virar um worker nem um repositório.
Se a operação passa a consultar disco ou executar ferramenta, essa parte
deve ser uma dependência explícita da aplicação/adaptador.

## Exemplo: trocar uma persistência

`EditorService` depende de `ProjectRepository`, não de JSON.
Uma implementação de teste pode guardar projetos num dicionário; uma nova
implementação real pode manter o mesmo contrato com outro mecanismo.
O construtor e as chamadas do serviço continuam iguais.

Antes de trocar a montagem no bootstrap, confirme a semântica: erros não
marcam salvamento, abrir informa ausentes, caminhos continuam resolvidos
corretamente e a versão gravada é a capturada. Reutilize os cenários de sessão
e acrescente testes reais do novo adaptador.

Evite criar classes que apenas repassem cada função pura do domínio.
A abstração deve permitir substituir um efeito externo ou proteger uma
decisão, não aumentar o número de arquivos por si só.

## Preferências e recursos

`application/preferences.py` é o esquema compartilhado.
`infrastructure/storage/settings.py` acrescenta leitura/escrita JSON,
padrões de diretórios via platformdirs e resolução da pasta de downloads.
Campos desconhecidos são ignorados e ausentes recebem padrão.
A gravação é atômica. A apresentação recebe dados; pede persistência ao runtime.

Fontes e ícones vivem em `resources/`. A wheel inclui a subpasta de fontes,
e o spec PyInstaller coleta os recursos. Os caminhos partem da localização
do pacote ou de `sys._MEIPASS`; não do diretório de onde o usuário executou.
Após mover um módulo, revise cálculos de `Path(__file__).parents`.

`system/binaries.py` procura binários empacotados, gerenciados e do sistema.
Use `subprocess_kwargs()` ao iniciar ferramentas: ele prepara bibliotecas
e trata o console no Windows. Não repetir essa lógica num painel.

## Diagnosticar um defeito

| Sintoma | Primeiros lugares para investigar |
| --- | --- |
| Opção de download ausente ou áudio descartado | Fixture e normalização yt-dlp; diferença entre codec ausente e none. |
| Seletor inválido ou incompatibilidade | Política de download e parser real do seletor. |
| Projeto perde alteração depois de salvar | Snapshot, geração, revisão e aceitação do resultado. |
| Estado da fila volta ao anterior | attempt_id, evento terminal e receptor Qt. |
| Prévia mostra busca antiga | Token/geração do pedido e aceitação pelo controller. |
| Prévia e exportação divergem | Dados entregues e grafo comum do compositor. |
| Saída vazia ou arquivo de outra tarefa apagado | Lease, temporário, cancelamento e publicação. |
| Exportação aumenta consumo de RAM | Filtros ativos, decodificadores e plano de trechos, além de limites de buffers. |
| Funciona no fonte e falha empacotado | Entrypoint, imports dinâmicos, recursos e ambiente dos binários. |

Comece reproduzindo o comportamento na menor fronteira que o explica.
Uma falha de sessão deve ter teste com repositório falso; uma falha de
mixagem precisa de mídia medida. Preserve a causa original ao limpar recursos.

## Distribuir e verificar

Leia o [guia de empacotamento](../empacotamento.md).
PyInstaller gera no sistema de destino; Linux não certifica Windows.
Os scripts de build podem baixar ferramentas e recriar build/dist.

O aplicativo aceita `--smoke-test` para diagnóstico automatizado.
Ele desabilita consulta ao dispositivo de áudio, monta a janela, verifica a
fonte Carlito, renderiza texto na prévia, exporta um vídeo curto, inspeciona
o resultado e encerra com código de sucesso/falha.

No Linux, `packaging/smoke_run.sh` usa perfil temporário, prazo e marcador
de conclusão. Um processo vivo sem concluir já não conta como aprovação.
Se o pacote não embute ffmpeg, as ferramentas precisam estar no PATH.
No Windows, aguarde o processo terminar e confira seu ExitCode.
Áudio físico e usabilidade continuam exigindo validação no desktop de destino.
