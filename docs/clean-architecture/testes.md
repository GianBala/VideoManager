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

.venv/bin/python -m pyflakes src/videomanager tests scripts/benchmark_architecture.py
git diff --check
```

No Windows, use os executáveis de `.venv\Scripts`.
Testes `ffmpeg` requerem ferramentas locais; cenários sem hardware disponível
podem ser ignorados. Rede é opcional e depende de plataformas externas.

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

`tests/conftest.py` não inicializa Qt automaticamente.
Os testes que precisam dele solicitam `desktop_app` e, quando pertinente,
`isolated_audio`. A primeira cria QApplication/fontes; a segunda evita
consultar dispositivo de áudio. `wait_until` processa eventos enquanto
aguarda uma condição com prazo, em vez de presumir resultado síncrono.

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

## Integração contínua

`.github/workflows/tests.yml` define núcleo sem desktop e matriz
Linux/Windows com Python 3.10/3.12, lint e suíte offline.
A configuração também gera e verifica pacotes nas variantes 3.12.
Adicionar o workflow ao repositório não significa que a execução remota já
ocorreu; confira o resultado da CI antes de distribuir em outro sistema.

O [checkup final](validacao-final.md) registra as execuções nativas e os problemas
encontrados. O script `scripts/validate_audio.py` é separado da suíte: usa a
placa real em volume baixo e não deve ser incluído em runners sem áudio.
A fixture `desktop_app` redireciona as preferências para pasta temporária para
evitar que fechar janelas de teste modifique o perfil do desenvolvedor.
