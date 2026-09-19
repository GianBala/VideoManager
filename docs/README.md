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

- [**Guia completo de Clean Architecture**](clean-architecture/README.md) —
  conceitos, camadas, fluxos de ponta a ponta, concorrência, testes e catálogo
  de módulos para quem está chegando ao projeto.
- [**Arquitetura**](arquitetura.md) — mapa resumido da estrutura atual.
- [**Decisões de projeto**](decisoes-de-projeto.md) — os algoritmos por trás
  das escolhas principais (normalização de extratores, corte sem recodificar,
  grafo único do ffmpeg) e o motivo de cada uma.
- [**Plano de migração para Clean Architecture**](plano-clean-architecture.md)
  — registro da proposta original; veja as entregas e evidências no
  [registro da migração](clean-architecture/migracao.md).
- [**Guia de desenvolvimento**](desenvolvimento.md) — ambiente, testes,
  fixtures de extratores, convenções do projeto.
- [**Empacotamento**](empacotamento.md) — gerar os pacotes de Linux
  (pasta e AppImage) e Windows.

`AGENTS.md` na raiz oferece uma visão geral para trabalho no repositório.
`CLAUDE.md`, quando disponível localmente, registra decisões históricas e pode
conter caminhos anteriores à migração; o guia acima descreve o código atual.

## Aviso

Este aplicativo é uma interface para o yt-dlp. Respeitar os termos de uso e
os direitos autorais de cada plataforma é responsabilidade de quem usa.
