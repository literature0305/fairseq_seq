#!/bin/bash
stage=7
stop_stage=100

combined_data_dir=/home/Workspace/fairseq/data/combined_data
# subset=dev_clean
subsets="test_clean test_other dev_clean dev_other"
dir_checkpoint=pretrained_models/errlog050_best.pt #errlog003.pt # /home/Workspace/fairseq/outputs/2023-02-16/01-15-13/errlog003_kd/checkpoint_best.pt
# dir_checkpoint=outputs/2023-02-23/16-39-01/errlog005_sdt_kd/checkpoint_best.pt
results_path=/home/Workspace/fairseq/decode_results
SHELL_PATH=`pwd -P`
echo $SHELL_PATH

if [ ${stage} -le 7 ] && [ ${stop_stage} -ge 7 ]; then
    echo "stage 7: do decode (viterbi)"
    for subset in $subsets; do
        echo "Start decode $subset"
        python3 /home/Workspace/fairseq/examples/speech_recognition/infer.py $combined_data_dir --task audio_finetuning \
        --nbest 5 --path $dir_checkpoint --gen-subset $subset --results-path $results_path --w2l-decoder viterbi \
        --lm-weight 2 --word-score -1 --sil-weight 0 --criterion ctc --labels ltr --max-tokens 4000000 \
        --post-process letter
    done
fi

# if [ ${stage} -le 7 ] && [ ${stop_stage} -ge 7 ]; then
#     echo "stage 7: do decode (kenlm)"
#     for subset in $subsets; do
#         results_path=/home/Workspace/fairseq/decode_results_$subset
#         python /home/Workspace/fairseq/examples/speech_recognition/infer.py $combined_data_dir --task audio_finetuning \
#         --nbest 5 --path $dir_checkpoint --gen-subset $subset --results-path $results_path --w2l-decoder kenlm \
#         --lm-model libri_3gram.bin --lm-weight 2 --word-score -1 --sil-weight 0 --criterion ctc --labels ltr --max-tokens 4000000 \
#         --post-process letter
#     done
# fi