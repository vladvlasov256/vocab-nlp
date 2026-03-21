# Corpus data

Large text corpora used to build collocation whitelists. Files are gitignored — download them locally.

## Dutch (OpenSubtitles v2018)

Source: [OPUS OpenSubtitles](https://opus.nlpl.eu/OpenSubtitles/corpus/version/OpenSubtitles)

```sh
curl -o corpus/nl_opensubs.txt.gz "https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2018/mono/nl.txt.gz"
gunzip corpus/nl_opensubs.txt.gz
uv run python scripts/build_collocations.py corpus/nl_opensubs.txt --lang nl --output data/collocations_nl.json
```

~990 MB compressed, ~2.7 GB uncompressed.

Citation:
> P. Lison and J. Tiedemann, 2016, OpenSubtitles2016: Extracting Large Parallel Corpora from Movie and TV Subtitles. LREC 2016.
