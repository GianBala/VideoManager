# Fixtures

Respostas reais de extratores do yt-dlp, capturadas com `tests/capture_fixture.py`.

URLs de mídia, cabeçalhos HTTP e listas de fragmentos foram **removidos**: são
assinados com tokens de sessão, expiram em minutos e não devem ser versionados.
Todos os campos que `videomanager.core.format_matrix` consulta estão preservados
exatamente como vieram — inclusive ausentes ou nulos, que é o que se quer testar.

Cada fixture existe por causa de uma estrutura específica:

| Fixture | Origem | Por que está aqui |
|---|---|---|
| `youtube_dash.json` | YouTube | DASH com trilhas separadas, três codecs de vídeo (H.264/VP9/AV1) na mesma resolução, 60 fps, e 4 storyboards `mhtml` que **não** são mídia. Também traz duas faixas de áudio HLS (`233`, `234`) que declaram `vcodec` mas **omitem** `acodec`. |
| `archive_muxed.json` | archive.org | Não declara **nenhuma** chave de codec, e nenhum formato tem `fps`. Só arquivos mesclados. Um filtro estrito de fps eliminaria os três, e um classificador que exija codec declarado descartaria o site inteiro. |
| `hls_no_metadata.json` | HLS de teste da Apple (extrator genérico) | Manifesto HLS puro: 27 variantes, sem `filesize` em nenhuma, e as faixas de áudio declaram `vcodec: "none"` mas **omitem** `acodec` — se descartadas, o download sai mudo. |
| `soundcloud_audio.json` | SoundCloud | Só áudio, sem nenhum formato de vídeo, com `filesize_approx` em vez de `filesize`. |
| `instagram_reel.json` | Instagram | Três formatos progressivos que **não têm a chave `vcodec`** (nem sequer nula) — só `acodec: "none"` — e nenhuma dimensão. A altura/família ficam desconhecidas, e são as extensões `mp4`/`_VIDEO_EXTS` que impedem `_infer_presence` de descartar os três como não-mídia. |

## Recapturar

```bash
PYTHONPATH=src python tests/capture_fixture.py <nome> <url>
```

Fixtures não precisam ser atualizadas com frequência: elas registram formas de
resposta, não o conteúdo das mídias. Vale recapturar quando uma plataforma muda
a estrutura que entrega — que é exatamente quando os testes devem ser revistos.
