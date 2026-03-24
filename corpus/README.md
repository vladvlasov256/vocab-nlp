# Corpus data

Large text corpora used to build collocation whitelists. Files are gitignored — download them locally.

Source: [OPUS OpenSubtitles v2018](https://opus.nlpl.eu/OpenSubtitles/corpus/version/OpenSubtitles)

## Dutch

```sh
curl -o corpus/nl_opensubs.txt.gz "https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2018/mono/nl.txt.gz"
gunzip corpus/nl_opensubs.txt.gz
```

~990 MB compressed, ~2.7 GB uncompressed, ~105M lines.

## English

```sh
curl -o corpus/en_opensubs.txt.gz "https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2018/mono/en.txt.gz"
gunzip corpus/en_opensubs.txt.gz
```

~3.6 GB compressed. Very large — consider truncating before upload:

```sh
head -n 100000000 corpus/en_opensubs.txt > corpus/en_opensubs_100m.txt
```

## Processing

Upload to Modal volume and run with spaCy on GPU:

```sh
modal volume put vocab-data corpus/<lang>_opensubs.txt <lang>_opensubs.txt
modal run scripts/collocations/modal_run.py --lang <lang>
modal volume get vocab-data collocations_<lang>.json data/collocations_<lang>.json
```

Citation:
> P. Lison and J. Tiedemann, 2016, OpenSubtitles2016: Extracting Large Parallel Corpora from Movie and TV Subtitles. LREC 2016.
