# Documentação do Video Manager

Aplicativo desktop para Windows e Linux que baixa vídeo e áudio de centenas
de plataformas (via yt-dlp), converte arquivos locais e edita vídeo em
múltiplas trilhas — tudo sobre `ffmpeg`. Veja o `README.md` na raiz do
repositório para uma visão geral rápida; esta pasta traz o manual completo.

## Para quem usa o aplicativo

- [**Instalação e primeira execução**](instalacao.md) — pacotes prontos
  (AppImage, Windows), rodar a partir do código, o que acontece com o
  `ffmpeg` na primeira execução.
- [**Janela principal**](interface-geral.md) — menus, as três abas, a fila de
  tarefas comum a elas.
- [**Aba Download**](guia-download.md) — baixar de uma URL: qualidade,
  perfis rápidos, playlists e canais.
- [**Aba Convert**](guia-conversao.md) — converter arquivos que já estão no
  disco.
- [**Aba Editar**](guia-edicao.md) — o editor multipista: importar, cortar,
  montar trilhas, atalhos de teclado, exportar.
- [**Configurações**](configuracoes.md) — toda preferência ajustável, o que
  cada uma faz.

## Para quem desenvolve o aplicativo

- [**Arquitetura**](arquitetura.md) — como `core`, `workers` e `ui` se
  relacionam, os módulos que concentram a dificuldade do projeto (matriz de
  formatos, seletor, compositor, corte, aceleração por placa de vídeo) e como
  a fila de tarefas evita esgotar a memória da máquina.
- [**Guia de desenvolvimento**](desenvolvimento.md) — ambiente, testes,
  fixtures de extratores, convenções do projeto.
- [**Empacotamento**](empacotamento.md) — gerar os pacotes de Linux
  (pasta e AppImage) e Windows.

Para o raciocínio detalhado por trás de cada decisão não-óbvia do código —
com as medições que a sustentam — ver `CLAUDE.md` na raiz do repositório:
escrito para orientar mudanças futuras, é a referência mais profunda que o
projeto tem.

## Aviso

Este aplicativo é uma interface para o yt-dlp. Respeitar os termos de uso e
os direitos autorais de cada plataforma é responsabilidade de quem usa.
