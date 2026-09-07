# Guia de desenvolvimento

## Preparando o ambiente

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Rodando o app a partir do código

```bash
PYTHONPATH=src .venv/bin/python -m videomanager
```

## Testes

```bash
.venv/bin/python -m pytest -q                                 # suíte offline (padrão)
.venv/bin/python -m pytest -m network                         # testes com serviços externos
.venv/bin/python -m pytest tests/test_selector.py -k formato  # um teste só
```

A suíte padrão (`addopts = -m 'not network'`) não acessa a internet. Ela inclui
Qt offscreen, com áudio isolado pelas fixtures, e testes de mídia local marcados
`ffmpeg`. Os testes de hardware são ignorados quando o dispositivo não responde.
Apenas testes que acessam plataformas externas têm marca `network`.

Para verificar somente regras e interface, sem executar a integração de mídia:

```bash
.venv/bin/python -m pytest -q -m "not network and not ffmpeg"
```

Importações e abertura de projetos são assíncronas. Em testes de interface,
use a fixture `wait_until` para aguardar o término processando eventos Qt, em
vez de assumir que o resultado existe assim que o método retorna.

### Lint

```bash
.venv/bin/python -m pyflakes src/videomanager tests
```

## A filosofia de teste do projeto

**A ausência de exceção não prova nada.** Os defeitos mais caros já
encontrados neste projeto — vídeo mudo, som acelerado, mixagem 3 dB abaixo do
esperado — não levantaram erro nenhum; todos passariam num teste que só
conferisse "rodou sem explodir". Por isso, qualquer coisa que produza mídia é
testada **medindo a saída com o `ffprobe`** (duração, trilhas presentes,
volume médio), não pela ausência de exceção. `TestExportacaoDaEdicao`, em
`tests/test_integration.py`, é o exemplo a seguir para qualquer teste novo que
gere arquivo.

## Fixtures de extratores

`core/format_matrix.py` precisa lidar com a resposta de qualquer extrator do
yt-dlp, e cada plataforma devolve uma estrutura diferente. Em vez de dados
sintéticos, `tests/fixtures/` guarda **respostas reais** capturadas de
extratores de verdade, cada uma escolhida por expor uma estrutura própria —
ver `tests/fixtures/README.md` para a lista completa e o motivo de cada uma
existir.

Capturar uma fixture nova:

```bash
PYTHONPATH=src .venv/bin/python tests/capture_fixture.py <nome> <url>
```

O script remove automaticamente URLs de mídia, cabeçalhos HTTP e listas de
fragmentos (são assinados com tokens de sessão, expiram em minutos, e não
devem ser versionados), além de comentários, contagem de curtidas/comentários
e outros campos que a aplicação nunca lê — para a fixture continuar legível
numa revisão de código e não carregar dados pessoais de terceiros à toa
(alguns extratores, como o do Instagram, incluem comentários de outros
usuários mesmo numa extração só de metadados).

Depois de capturar, registre o nome do arquivo em `FIXTURE_NAMES`
(`tests/conftest.py`) para que ele entre automaticamente nos testes de
invariante que rodam contra toda fixture (`test_format_matrix.py`), e
descreva no `README.md` da pasta a estrutura específica que motivou a
captura.

Toda expressão de formato que o app gera para o yt-dlp também é validada pelo
**parser real do yt-dlp** (`ydl.build_format_selector`) nos testes — um erro
de sintaxe num filtro como `~=` ou `<=?` não apareceria num teste de
comparação de strings, só no primeiro download de um usuário de verdade.

## Inspecionando a interface sem abrir uma janela

Os testes de interface usam Qt offscreen. Para conferir layout — alinhamento,
tamanhos, se um painel nasce cortado — use também esse modo num
script de rascunho e leia o PNG gerado:

```python
# QT_QPA_PLATFORM=offscreen python shot.py
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setPalette(qpalette(s.theme))
app.setStyleSheet(stylesheet(s.theme))
w = MainWindow(s)
w.show()
for _ in range(3):
    app.processEvents()  # deixa o layout assentar
w.grab().save("tela.png")
```

`app.setStyle("Fusion")` é obrigatório: é o único estilo idêntico no Windows e
no Linux, e todo o QSS do projeto foi escrito em cima dele. Para medir
alinhamento com precisão, `widget.mapTo()` e `sizeHint()` dão números exatos
— mais confiável do que contar pixels numa captura de tela.

## Convenções do projeto

- **Tudo em pt-BR** — comentários, docstrings, texto de interface, mensagens
  de erro e mensagens de commit.
- **Texto visível só nasce em `ui/strings.py`** — nenhuma tela cria uma
  string de interface diretamente, o que permite traduzir o app inteiro sem
  abrir um painel se algum dia for preciso.
- **Comentário explica o porquê, não o quê** — o padrão do código é registrar
  a decisão e o defeito que ela evita, não parafrasear a linha seguinte.
- **Commits nunca levam `Co-Authored-By`** — em nenhuma mensagem de commit,
  corpo de PR, tag ou changelog.

Para o raciocínio completo por trás de cada decisão não-óbvia do código —
com as medições que a sustentam — ver `CLAUDE.md` na raiz do repositório.
