# Guia de desenvolvimento

## Ambiente e execução

Requer Python 3.10+, PySide6, yt-dlp e platformdirs. Processamento local requer
ffmpeg e ffprobe, encontrados pelo aplicativo no pacote, diretório gerenciado
ou PATH. Em Linux, bibliotecas gráficas do sistema também precisam existir;
o preflight apresenta o diagnóstico disponível antes de criar Qt.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
PYTHONPATH=src .venv/bin/python -m videomanager
```

No Windows, substitua os executáveis pelos de `.venv\Scripts`.

## Como começar uma alteração

Leia a [visão geral Clean Architecture](clean-architecture/README.md).
O [catálogo](clean-architecture/modulos.md) localiza cada responsabilidade;
o [guia de evolução](clean-architecture/evolucao.md) mostra uma mudança completa
atravessando domínio, aplicação, apresentação e adaptadores.

Comece pela regra ou caso de uso. Escolha o teste que reproduz o comportamento.
Conecte os efeitos externos por portas e mantenha comandos fora dos widgets.
A montagem concreta fica no bootstrap. Atualize a documentação do fluxo alterado.

## Testes

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests/domain tests/application tests/architecture
.venv/bin/python -m pytest -q -m "not network and not ffmpeg"
.venv/bin/python -m pytest -m network
.venv/bin/python -m pytest tests/test_selector.py -k formato
.venv/bin/python -m pyflakes src/videomanager tests scripts/benchmark_architecture.py
git diff --check
```

A suíte padrão não acessa a rede. Inclui Qt offscreen e mídia local marcada
ffmpeg. Testes de hardware podem ser ignorados se a máquina não o oferece.
Não confunda ignorado com aprovado.

As fixtures `desktop_app` e `isolated_audio` são explícitas; testes internos
não iniciam Qt. Para operações assíncronas, use `wait_until`, que processa
eventos com prazo. Veja [testes e arquitetura](clean-architecture/testes.md)
para rodar o núcleo em ambiente contendo apenas Python e pytest.

Ausência de exceção não prova correção de mídia. Meça duração, streams,
codecs, volume, quadros e texto. `tests/test_integration.py` reúne exemplos
de validação por saída real.

## Fixtures de extratores

`infrastructure/yt_dlp/formats.py` normaliza respostas diferentes.
`tests/fixtures/` guarda exemplos reais sanitizados, escolhidos por estruturas
distintas. Para capturar outra fixture:

```bash
PYTHONPATH=src .venv/bin/python tests/capture_fixture.py <nome> <url>
```

O script remove URLs de mídia, cabeçalhos, fragmentos e dados não consumidos.
Revise o resultado antes de versionar. Registre a fixture em `FIXTURE_NAMES`
de conftest e explique sua estrutura no README da pasta.

Expressões geradas são testadas com o parser real do yt-dlp. Comparar strings
não detecta toda incompatibilidade de sintaxe do provedor.

## Inspecionar a interface offscreen

```python
# QT_QPA_PLATFORM=offscreen .venv/bin/python shot.py
from videomanager.app import build_app

app, window = build_app([], audio_enabled=False)
window.show()
for _ in range(3):
    app.processEvents()
window.grab().save("tela.png")
window.close()
```

Para um ensaio isolado, defina XDG_CONFIG_HOME, XDG_DATA_HOME e XDG_CACHE_HOME
para diretórios temporários antes de rodar, evitando gravar preferências ou
integração desktop do seu perfil. `build_app` já aplica Fusion, fontes, tema
e dependências corretas. Não construir `MainWindow` sem injetar seus serviços.

O diagnóstico `python -m videomanager --smoke-test` verifica janela, fontes,
prévia e vídeo exportado e encerra sozinho. Não consulta dispositivo de áudio;
ffmpeg/ffprobe continuam necessários.

## Convenções

Comentários, docstrings e mensagens seguem pt-BR. Novos textos de controles
ficam em `presentation/qt/strings.py`; tema e paleta em `theme.py`.
Comentários explicam decisões. Preserve IDs, compatibilidade .vmp, avisos de
download, comportamento temporal e propriedade das saídas.

Não incluir cookies, URLs assinadas ou dados de sessão em fixtures.
Não adicionar Co-Authored-By a commits, PRs, tags ou changelogs.
Documentos históricos locais podem conter caminhos anteriores à migração;
a referência atual é este guia e o código.

Para distribuir, consulte [empacotamento](empacotamento.md). Linux e Windows
precisam de validação nos respectivos sistemas.
