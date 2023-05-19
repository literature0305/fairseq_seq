#!/bin/bash
stage=6
stop_stage=100

dir_trainset=data/train-clean-100
dir_dev_clean=data/dev-clean
dir_dev_other=data/dev-other
combined_data_dir=/home/Workspace/fairseq/data/combined_data_100h
dir_pretrained=/home/Workspace/fairseq/pretrained_models # dir for pretrained models
name_model=wav2vec_small.pt # name pretrained_model (wav2vec_small.pt, wav2vec_small_10m.pt ...)

if [ ${stage} -le 5 ] && [ ${stop_stage} -ge 5 ]; then
    echo "stage 5: prepare finetuning"
    mkdir -p $combined_data_dir
    cat $dir_trainset/wav_dir.tsv > $combined_data_dir/train.tsv
    cat $dir_trainset/labels.ltr > $combined_data_dir/train.ltr
    cat $dir_trainset/labels.wrd > $combined_data_dir/train.wrd

    cat $dir_dev_clean/wav_dir.tsv > $combined_data_dir/dev_clean.tsv
    cat $dir_dev_clean/labels.ltr > $combined_data_dir/dev_clean.ltr
    cat $dir_dev_clean/labels.wrd > $combined_data_dir/dev_clean.wrd

    cat $dir_dev_other/wav_dir.tsv > $combined_data_dir/dev_other.tsv
    cat $dir_dev_other/labels.ltr > $combined_data_dir/dev_other.ltr
    cat $dir_dev_other/labels.wrd > $combined_data_dir/dev_other.wrd

    # make dictionary
    cat 2-1_letter_dictionary > $combined_data_dir/dict.ltr.txt
fi


if [ ${stage} -le 6 ] && [ ${stop_stage} -ge 6 ]; then
    echo "stage 6: do finetuning"
    CUDA_VISIBLE_DEVICES=0,1,2,3 fairseq-hydra-train \
        task.data=$combined_data_dir \
        model.w2v_path=$dir_pretrained/$name_model \
        --config-dir examples/wav2vec/config/finetuning \
        --config-name base_100h_sdt_kd
fi
