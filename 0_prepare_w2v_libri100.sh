#!/bin/bash
stage=3
stop_stage=1000
datadir=/DB/LibriSpeech # dir to save data
tsvdir=data # dir to save tsv
dir_pretrained=pretrained_models # dir to download pretrained models

# name pretrained_model (wav2vec_small.pt, wav2vec_small_10m.pt ...)
name_model=wav2vec_small.pt

# base url for downloads.
data_url=www.openslr.org/resources/12
model_url=https://dl.fbaipublicfiles.com/fairseq/wav2vec/$name_model

# name LibriSpeech datasets
data_sets="dev-clean test-clean dev-other test-other train-clean-100"

if [ ${stage} -le 1 ] && [ ${stop_stage} -ge 1 ]; then
    echo "download Wav2Vec 2.0 Base (without finetuning)"
    mkdir -p $dir_pretrained
    wget -O $dir_pretrained/$name_model $model_url
fi

if [ ${stage} -le 2 ] && [ ${stop_stage} -ge 2 ]; then
    echo "stage 2: Data Download"
    mkdir -p $datadir
    for part in $data_sets; do
        ./1-1_download_and_untar.sh ${datadir} ${data_url} ${part}
    done
fi

if [ ${stage} -le 3 ] && [ ${stop_stage} -ge 3 ]; then
    echo "stage 3: Prepare tsv"
    for part in $data_sets; do
        python3 examples/wav2vec/wav2vec_manifest.py $datadir/LibriSpeech/$part --dest $tsvdir/$part --ext flac --valid-percent 0
        mv $tsvdir/$part/train.tsv $tsvdir/$part/wav_dir.tsv
    done
fi

if [ ${stage} -le 4 ] && [ ${stop_stage} -ge 4 ]; then
    echo "stage 4: Prepare letter labels"
    for part in $data_sets; do
        python3 examples/wav2vec/libri_labels.py $tsvdir/$part/wav_dir.tsv --output-dir $tsvdir/${part} --output-name labels
    done
fi