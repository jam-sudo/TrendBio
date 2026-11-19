"""Translate missing public website text with the original English/Korean OPUS-MT model."""
from collections import Counter
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

import ctranslate2
from ctranslate2.converters import OpusMTConverter
import sentencepiece as sp
import yaml

URL = 'https://object.pouta.csc.fi/Tatoeba-MT-models/eng-kor/opusTCv20210807-sepvoc_transformer-big_2022-07-28.zip'
SHA256 = '41f771fa28e864428dd7589992867b2b6dfa402f1191670e818e019dddfceef7'
MODEL = Path(os.environ.get('TRENDBIO_KO_MODEL', Path.home() / '.cache/trendbio/opus-en-ko-20220728'))
PROTECTED = re.compile(r'https?://[^\s<>]+|(?:arXiv:\s*)?\b\d{4}\.\d{4,5}(?:v\d+)?\b|\b10\.\d{4,9}/[^\s<>]+', re.I)


def prepare():
    if (MODEL / 'model.bin').is_file():
        return
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=MODEL.parent) as workdir:
        temp = Path(workdir)
        archive = temp / 'model.zip'
        with urlopen(URL, timeout=120) as src, archive.open('wb') as dst:
            shutil.copyfileobj(src, dst)
        with archive.open('rb') as file:
            if hashlib.file_digest(file, 'sha256').hexdigest() != SHA256:
                raise ValueError('Unexpected OPUS-MT archive checksum')
        with ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                if Path(entry.filename).name != entry.filename:
                    raise ValueError('Unexpected OPUS-MT archive path')
            bundle.extractall(temp)
        conf = yaml.safe_load((temp / 'decoder.yml').read_text())
        for i, side in enumerate(['source', 'target']):
            # This release uses separate ordered token lists instead of Marian YAML vocabularies.
            tokenizer = sp.SentencePieceProcessor(model_file=str(temp / (side + '.spm')))
            name = side + '.vocab.yml'
            (temp / name).write_text(''.join(json.dumps(tokenizer.id_to_piece(n), ensure_ascii=False) +
                                              ': ' + str(n) + '\n' for n in range(len(tokenizer))))
            conf['vocabs'][i] = name
        (temp / 'decoder.yml').write_text(yaml.safe_dump(conf))
        dest = temp / 'converted'
        OpusMTConverter(str(temp)).convert(str(dest), quantization='int8')
        for name in ['source.spm', 'target.spm', 'LICENSE', 'README.md']:
            shutil.copyfile(temp / name, dest / name)
        try:
            dest.rename(MODEL)
        except OSError:
            if not (MODEL / 'model.bin').is_file():
                raise


NUMBER = re.compile(r'\d+(?:,\d{3})*(?:\.\d+)?')
# On retry keep each numerical expression or alphanumeric identifier together.
NUMERIC_TOKEN = re.compile(PROTECTED.pattern + r'|[^\W\d_]*\d+(?:[.,/-]\d+|[A-Za-z0-9_])*', re.I)


def numbers(text):
    return Counter(Decimal(value.replace(',', '')) for value in NUMBER.findall(text))


def decode(batch, source, target, translator, protected=PROTECTED):
    parts, owners = [], []
    output_parts = [[] for _ in batch]
    for i, text in enumerate(batch):
        for part in re.split('(' + protected.pattern + ')', text, flags=protected.flags):
            if not part:
                continue
            if protected.fullmatch(part) or not re.search('[a-zA-Z]', part):
                output_parts[i].append(part.strip())
                continue
            for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z(])', part.strip()):
                tokens = source.encode(sentence, out_type=str)
                for n in range(0, len(tokens), 220):
                    owners.append((i, len(output_parts[i])))
                    output_parts[i].append('')
                    parts.append(tokens[n:n + 220])
    translated = translator.translate_batch(parts, beam_size=2, max_batch_size=48,
                                              max_decoding_length=330, no_repeat_ngram_size=5)
    for (i, pos), result in zip(owners, translated, strict=True):
        output_parts[i][pos] = target.decode(result.hypotheses[0]).strip()
    return [' '.join(p for p in fragments if p).strip() for fragments in output_parts]


def translate(texts, output):
    old = json.loads(output.read_text()) if output.exists() else {}
    missing = [t for t in dict.fromkeys(texts) if t not in old]
    if missing:
        prepare()
        source = sp.SentencePieceProcessor(model_file=str(MODEL / 'source.spm'))
        target = sp.SentencePieceProcessor(model_file=str(MODEL / 'target.spm'))
        cores = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else (os.cpu_count() or 2)
        threads = min(2, cores)
        translator = ctranslate2.Translator(str(MODEL), device='cpu', compute_type='int8',
                                             inter_threads=threads, intra_threads=min(6, max(1, cores // threads)))
        for start in range(0, len(missing), 384):
            batch = missing[start:start + 384]
            results = decode(batch, source, target, translator)
            retry = [i for i, (text, result) in enumerate(zip(batch, results, strict=True))
                     if numbers(text) - numbers(result)]
            if retry:
                corrected = decode([batch[i] for i in retry], source, target, translator, NUMERIC_TOKEN)
                for i, result in zip(retry, corrected, strict=True):
                    results[i] = result
            for text, result in zip(batch, results, strict=True):
                if not result or numbers(text) - numbers(result):
                    raise ValueError('Translation lost text or a numeric value')
                old[text] = result
            temp = output.with_suffix('.tmp')
            temp.write_text(json.dumps(old, ensure_ascii=False))
            os.replace(temp, output)
            print(f'Korean translations {min(start + len(batch), len(missing))}/{len(missing)}', flush=True)
    elif not output.exists():
        output.write_text('{}')


if __name__ == '__main__':
    translate(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2]))
