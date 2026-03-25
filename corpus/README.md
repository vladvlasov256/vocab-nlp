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

## Serbian

```sh
curl -o corpus/sr_opensubs.txt.gz "https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2018/mono/sr.txt.gz"
gunzip corpus/sr_opensubs.txt.gz
```

~260 MB compressed, ~50M lines.

**Encoding fix:** The OPUS Serbian dump has broken encoding — č/ć/đ appear as è/æ/ð (ISO 8859-2 data misread as Latin-1, then re-encoded to UTF-8). Fix with a character replacement:

```python
replacements = {'è': 'č', 'æ': 'ć', 'ð': 'đ', 'È': 'Č', 'Æ': 'Ć', 'Ð': 'Đ'}
with open('corpus/sr_opensubs_50m.txt') as f:
    text = f.read()
for old, new in replacements.items():
    text = text.replace(old, new)
with open('corpus/sr_opensubs_50m.txt', 'w') as f:
    f.write(text)
```

Truncate for testing:

```sh
head -n 1000000 corpus/sr_opensubs_50m.txt > corpus/sr_opensubs_1m.txt
```

## Processing

Upload to Modal volume and run collocation extraction:

- **Dutch/English** (spaCy + GPU): `modal run scripts/collocations/modal_run.py --lang <lang>`
- **Serbian** (Stanza + GPU): `modal run scripts/collocations/modal_run_stanza.py --lang sr --corpus sr_opensubs_1m.txt`

```sh
modal volume put vocab-data corpus/<lang>_opensubs.txt <lang>_opensubs.txt
modal run scripts/collocations/modal_run.py --lang <lang>  # or modal_run_stanza.py for sr
modal volume get vocab-data collocations_<lang>.json data/collocations_<lang>.json
```

Citation:
> P. Lison and J. Tiedemann, 2016, OpenSubtitles2016: Extracting Large Parallel Corpora from Movie and TV Subtitles. LREC 2016.
