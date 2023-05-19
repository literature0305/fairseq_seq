#!/bin/bash
import sys

# Usage: python3 2_combine_960.py data/combined_dir data/train_clean_100 data/train_clean_360 data/train_other_500

dir_input = []
dir_output = ""
for idx in range(1, len(sys.argv)):
    if idx == 1:
        dir_output = sys.argv[idx]
    else:
        dir_input.append(sys.argv[idx])

ltr_to_write=[]
wrd_to_write=[]
tsv_to_write=[]
tsv_to_write.append('/DB/LibriSpeech/LibriSpeech\n')

for dir_name in dir_input:
    dir_ltr = dir_name + '/labels.ltr'
    dir_wrd = dir_name + '/labels.wrd'
    dir_tsv = dir_name + '/wav_dir.tsv'
    pre_fix = dir_name.replace('data/', '') + '/'

    with open(dir_ltr, 'r') as f:
        lines = f.readlines()

    ltr_to_write.extend(lines)

    with open(dir_wrd, 'r') as f:
        lines = f.readlines()
    wrd_to_write.extend(lines)


    with open(dir_tsv, 'r') as f:
        lines = f.readlines()
    for idx, line in enumerate(lines):
        if idx ==0:
            pass
        else:
            new_line = pre_fix + line
            tsv_to_write.append(new_line)

# write
dir_ltr = dir_output + '/labels.ltr'
dir_wrd = dir_output + '/labels.wrd'
dir_tsv = dir_output + '/wav_dir.tsv'

with open(dir_ltr, 'w') as f1, open(dir_wrd, 'w') as f2, open(dir_tsv, 'w') as f3:
    f1.writelines(ltr_to_write)
    f2.writelines(wrd_to_write)
    f3.writelines(tsv_to_write)


# root@6e37a0302757:/home/Workspace/fairseq# cat data/train-clean-100/labels.ltr | wc -l
# 28539
# root@6e37a0302757:/home/Workspace/fairseq# cat data/train-clean-360/labels.ltr | wc -l
# 104014
# root@6e37a0302757:/home/Workspace/fairseq# cat data/train-other-500/labels.ltr | wc -l
# 148688
# -> 281,241

# 281242
