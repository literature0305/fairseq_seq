import sys

dir_960=sys.argv[1]

dir_ltr=dir_960 + '/train.original.ltr'
dir_wrd=dir_960 + '/train.original.wrd'
dir_tsv=dir_960 + '/train.original.tsv'

dir_ltr_to_write=dir_960 + '/train.ltr'
dir_wrd_to_write=dir_960 + '/train.wrd'
dir_tsv_to_write=dir_960 + '/train.tsv'

with open(dir_ltr, 'r') as f:
    lines_ltr = f.readlines()
with open(dir_wrd, 'r') as f:
    lines_wrd = f.readlines()
with open(dir_tsv, 'r') as f:
    lines_tsv = f.readlines()

threshold_min=10
threshold_max=800

new_lines_ltr=[]
new_lines_wrd=[]
new_lines_tsv=[]

new_lines_tsv.append(lines_tsv[0])

for idx in range(len(lines_ltr)):
    idx_ltr = idx
    idx_wrd = idx
    idx_tsv = idx+1

    if threshold_min < len(lines_ltr[idx_ltr]) < threshold_max:
        new_lines_ltr.append(lines_ltr[idx_ltr])
        new_lines_wrd.append(lines_wrd[idx_wrd])
        new_lines_tsv.append(lines_tsv[idx_tsv])

with open(dir_ltr_to_write, 'w') as f:
    f.writelines(new_lines_ltr)
with open(dir_wrd_to_write, 'w') as f:
    f.writelines(new_lines_wrd)
with open(dir_tsv_to_write, 'w') as f:
    f.writelines(new_lines_tsv)

