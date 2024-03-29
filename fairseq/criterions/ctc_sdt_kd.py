# All rights reserved.
#
# This source code is licensed under the license found in the LICENSE file in
# the root directory of this source tree. An additional grant of patent rights
# can be found in the PATENTS file in the same directory.

import math
from argparse import Namespace
from dataclasses import dataclass, field
from omegaconf import II
from typing import Optional

import torch
import torch.nn.functional as F
from fairseq import metrics, utils
from fairseq.criterions import FairseqCriterion, register_criterion
from fairseq.dataclass import FairseqDataclass
from fairseq.data.data_utils import post_process
from fairseq.tasks import FairseqTask
from fairseq.logging.meters import safe_round
import random
import editdistance
from aligner_pytorch import mas

torch.set_printoptions(threshold=999999)


def pad_list(xs, pad_value):
    """Perform padding for the list of tensors.

    Args:
        xs (List): List of Tensors [(T_1, `*`), (T_2, `*`), ..., (T_B, `*`)].
        pad_value (float): Value for padding.

    Returns:
        Tensor: Padded tensor (B, Tmax, `*`).

    Examples:
        >>> x = [torch.ones(4), torch.ones(2), torch.ones(1)]
        >>> x
        [tensor([1., 1., 1., 1.]), tensor([1., 1.]), tensor([1.])]
        >>> pad_list(x, 0)
        tensor([[1., 1., 1., 1.],
                [1., 1., 0., 0.],
                [1., 0., 0., 0.]])

    """
    n_batch = len(xs)
    max_len = max(x.size(0) for x in xs)
    pad = xs[0].new(n_batch, max_len, *xs[0].size()[1:]).fill_(pad_value)

    for i in range(n_batch):
        pad[i, : xs[i].size(0)] = xs[i]

    return pad



@dataclass
class CtcCriterionConfigSdtKD(FairseqDataclass):
    zero_infinity: bool = field(
        default=False,
        metadata={"help": "zero inf loss when source length <= target length"},
    )
    pretrained_roberta_dir: str = field(
        default='None',
        metadata={"help": "e.x /home/Workspace/fairseq/pretrained_models/roberta/roberta.base"},
    )
    sentence_avg: bool = II("optimization.sentence_avg")
    post_process: str = field(
        default="letter",
        metadata={
            "help": "how to post process predictions into words. can be letter, "
            "wordpiece, BPE symbols, etc. "
            "See fairseq.data.data_utils.post_process() for full list of options"
        },
    )
    wer_kenlm_model: Optional[str] = field(
        default=None,
        metadata={
            "help": "if this is provided, use kenlm to compute wer (along with other wer_* args)"
        },
    )
    wer_lexicon: Optional[str] = field(
        default=None,
        metadata={"help": "lexicon to use with wer_kenlm_model"},
    )
    wer_lm_weight: float = field(
        default=2.0,
        metadata={"help": "lm weight to use with wer_kenlm_model"},
    )
    wer_word_score: float = field(
        default=-1.0,
        metadata={"help": "lm word score to use with wer_kenlm_model"},
    )
    wer_sil_weight: float = field(
        default=0,
        metadata={"help": "lm word score to use with wer_kenlm_model"},
    )

    wer_args: Optional[str] = field(
        default=None,
        metadata={
            "help": "DEPRECATED: tuple of (wer_kenlm_model, wer_lexicon, wer_lm_weight, wer_word_score)"
        },
    )


@register_criterion("ctc_sdt_kd", dataclass=CtcCriterionConfigSdtKD)
class CtcCriterionSdtKD(FairseqCriterion):
    def __init__(
        self, cfg: CtcCriterionConfigSdtKD, task: FairseqTask, rdrop_alpha: int = 0.0
    ):
        super().__init__(task)
        self.blank_idx = (
            task.target_dictionary.index(task.blank_symbol)
            if hasattr(task, "blank_symbol")
            else 0
        )
        self.pad_idx = task.target_dictionary.pad()
        self.eos_idx = task.target_dictionary.eos()
        self.post_process = cfg.post_process

        self.rdrop_alpha = rdrop_alpha

        if cfg.wer_args is not None:
            (
                cfg.wer_kenlm_model,
                cfg.wer_lexicon,
                cfg.wer_lm_weight,
                cfg.wer_word_score,
            ) = eval(cfg.wer_args)

        if cfg.wer_kenlm_model is not None and cfg.wer_kenlm_model != "":
            from examples.speech_recognition.w2l_decoder import W2lKenLMDecoder

            dec_args = Namespace()
            dec_args.nbest = 1
            dec_args.criterion = "ctc"
            dec_args.kenlm_model = cfg.wer_kenlm_model
            dec_args.lexicon = cfg.wer_lexicon
            dec_args.beam = 50
            dec_args.beam_size_token = min(50, len(task.target_dictionary))
            dec_args.beam_threshold = min(50, len(task.target_dictionary))
            dec_args.lm_weight = cfg.wer_lm_weight
            dec_args.word_score = cfg.wer_word_score
            dec_args.sil_weight = cfg.wer_sil_weight
            dec_args.unk_weight = -math.inf
            dec_args.sil_weight = 0

            self.w2l_decoder = W2lKenLMDecoder(dec_args, task.target_dictionary)
        else:
            self.w2l_decoder = None

        self.zero_infinity = cfg.zero_infinity
        self.sentence_avg = cfg.sentence_avg

        from fairseq.models.roberta import RobertaModel
        model_lm = RobertaModel.from_pretrained(cfg.pretrained_roberta_dir, checkpoint_file='checkpoint_best.pt')
        model_lm.cuda()
        model_lm.eval()
        self.model_lm = model_lm
        self.target_dictionary = task.target_dictionary
        self.criterion_kl=torch.nn.KLDivLoss(reduction="none")

    def lm_forward(self, tokens_tensor, model_lm, num_layer=-9):
        # num_layer: -1 ~ -13
        # logits:
        #torch.Size([8, 240, 33]),  # (00)output layer (33: num letters)
        #torch.Size([240, 8, 768]), # (-1)penultimate layer 
        #torch.Size([240, 8, 768]), # (-2)hidden layer
        #torch.Size([240, 8, 768])  # (-3)hidden layer
        
        logits=model_lm.model.forward(tokens_tensor, return_all_hiddens=True)
        
        # logits=model_lm.model.forward(tokens_tensor, return_all_hiddens=True)[1]["inner_states"][-1].detach().transpose(0,1)
        # logits=model_lm.model.forward(tokens_tensor)[0].detach()
        return logits[0].detach(), logits[1]["inner_states"][num_layer].detach().transpose(0,1)

    def lm_forward_roberta(self, lines, model_lm, num_layer=-1):
        # logits:
        #torch.Size([8, 240, 33]),  # (00)output layer (33: num letters)
        #torch.Size([240, 8, 768]), # (-1)penultimate layer 
        #torch.Size([240, 8, 768]), # (-2)hidden layer
        #torch.Size([240, 8, 768])  # (-3)hidden layer
        lines = lines.replace(' ','').replace('|',' ').replace('<pad>','').split('\n')
        new_lines = []
        for line in lines:
            line = model_lm.encode(line).to(model_lm.device)
            new_lines.append(line)
        # print('pad', model_lm.dictionary.pad())
        new_lines = pad_list(new_lines, 1)
        mask = (new_lines == 1)

        logits=model_lm.model.forward(new_lines, return_all_hiddens=True)
        return logits[0].detach(), logits[1]["inner_states"][-1].detach().transpose(0,1), mask

    def txt_augment(self, txt, target_length, dict, num_aug=1):
        def partial_shuffle(lst, imin, imax):
            lst[imin:imax] = sorted(lst[imin:imax], key=lambda x: random.random())
            return lst
        # txt: B,T
        # target_length: B
        lines_str = dict.string(txt).split('\n')
        txt_auged = [txt]

        for iii in range(num_aug):
            # random swap
            txt_rand_swap = torch.ones(txt.size()).to(txt.device).to(txt.dtype)
            for idx, line in enumerate(lines_str):
                line = line.replace(' ','').split('|')
                if len(line) > 3:
                    len_swap = min(((torch.randperm(len(line))[0] // 2) + 2).item(), len(line) - 1)
                    start_position  = min((torch.randperm( max(len(line) - len_swap - 1,1) )[0]).item(), len(line) - len_swap - 1) # -1 for pading
                    line = partial_shuffle(line, start_position, start_position+len_swap)
                    line = '|'.join(line)
                    new_line = ''
                    for letter in line:
                        new_line = new_line + ' ' + letter
                    new_line = new_line.strip().replace('><','> <').replace('< p a d >','<pad>')
                    new_line = dict.encode_line(new_line).to(txt.device).to(txt.dtype)
                    new_line = new_line[:-1] # remove EOS token
                    txt_rand_swap[idx, :len(new_line)] = new_line
                else:
                    txt_rand_swap[idx] = txt[idx]
            txt_auged.append(txt_rand_swap)

            # random deletion
            txt_rand_del = torch.ones(txt.size()).to(txt.device).to(txt.dtype)
            for idx, line in enumerate(txt):
                line_len=target_length[idx]
                rand_len_to_del = torch.randperm(line_len // 2)[0] + 1
                if line_len > rand_len_to_del:
                    rand_start_idx_to_del = torch.randperm(line_len - rand_len_to_del)[0]
                    txt_rand_del[idx,:rand_start_idx_to_del] = line[:rand_start_idx_to_del]
                    txt_rand_del[idx,rand_start_idx_to_del:-rand_len_to_del] = line[rand_start_idx_to_del+rand_len_to_del:]
                else:
                    txt_rand_del[idx] = txt[idx]
            txt_auged.append(txt_rand_del)

            # random insertion (dynamic size)
            max_len_ins=4
            txt_rand_ins = torch.ones(txt.size(0), txt.size(1) + max_len_ins).to(txt.device).to(txt.dtype)
            for idx, line in enumerate(txt):
                line_len=target_length[idx]
                rand_len_to_ins = torch.randperm(max_len_ins)[0] + 1
                if line_len > rand_len_to_ins:
                    rand_start_idx_to_ins = torch.randperm(line_len - rand_len_to_ins)[0]
                    txt_rand_ins[idx,:rand_start_idx_to_ins] = line[:rand_start_idx_to_ins]
                    txt_rand_ins[idx,rand_start_idx_to_ins:rand_start_idx_to_ins+rand_len_to_ins] = line[rand_start_idx_to_ins].item()
                    txt_rand_ins[idx,rand_start_idx_to_ins+rand_len_to_ins: len(line)+rand_len_to_ins] = line[rand_start_idx_to_ins:]
                else:
                    txt_rand_ins[idx][:-max_len_ins] = txt[idx]
            txt_auged.append(txt_rand_ins)

            # word wise random swap
            # word wise random deletion
            # word wise random insertion
            # word wise random substitution

        return txt_auged


    def forward(self, model, sample, reduce=True, **kwargs):
        net_output = model(**sample["net_input"], target=sample["target"])
        # raise ValueError('net otutput:', net_output)
        lprobs = model.get_normalized_probs(
            net_output, log_probs=True
        ).contiguous()  # (T, B, C) from the encoder

        # CTC loss is calculated over duplicated inputs
        # sample is already duplicated for R-Drop
        if self.rdrop_alpha > 0:
            for k, v in sample.items():
                if k in ["target", "target_lengths"]:
                    sample[k] = torch.cat([v, v.clone()], dim=0)
                elif k == "net_input":
                    if sample[k]["src_tokens"].size(1) != sample[k]["src_lengths"].size(
                        0
                    ):
                        # for decoder CTC loss
                        sample[k]["src_lengths"] = torch.cat(
                            [
                                sample[k]["src_lengths"],
                                sample[k]["src_lengths"].clone(),
                            ],
                            dim=0,
                        )

        if "src_lengths" in sample["net_input"]:
            input_lengths = sample["net_input"]["src_lengths"]
        else:
            if net_output["padding_mask"] is not None:
                non_padding_mask = ~net_output["padding_mask"]
                input_lengths = non_padding_mask.long().sum(-1)
            else:
                input_lengths = lprobs.new_full(
                    (lprobs.size(1),), lprobs.size(0), dtype=torch.long
                )

        pad_mask = (sample["target"] != self.pad_idx) & (
            sample["target"] != self.eos_idx
        )
        targets_flat = sample["target"].masked_select(pad_mask)
        if "target_lengths" in sample:
            target_lengths = sample["target_lengths"]
        else:
            target_lengths = pad_mask.sum(-1)

        with torch.backends.cudnn.flags(enabled=False):
            loss = F.ctc_loss(
                lprobs,
                targets_flat,
                input_lengths,
                target_lengths,
                blank=self.blank_idx,
                reduction="sum",
                zero_infinity=self.zero_infinity,
            )


        num_update = model.get_num_updates()
        if self.model_lm is not None and self.training and num_update > -1:
            if torch.randperm(3000)[0] == 0:
                print_option=True
            else:
                print_option=False

            import editdistance

            # input
            # net_output  ["target_embed"].size(): [227, 8, 768]: T,B,F
            # net_output["encoder_out_kd"].size(): [696, 8, 768]: T',B,F

            # output
            # sequence discriminative training loss

            squeeze = -1# 2

            # target mask
            target_mask = (sample["target"] != self.target_dictionary.pad())
            if net_output["padding_mask"] is not None:
                encoder_out_kd_mask = (net_output["padding_mask"] == False).unsqueeze(-1)
                encoder_out_kd_mask2 = (net_output["padding_mask"] == False)
                encoder_masking = True
                if squeeze > 1:
                    # print('encoder_out_kd_mask:', encoder_out_kd_mask.size()) # B,T
                    # print('encoder_out_kd_mask2:', encoder_out_kd_mask2.size())
                    encoder_out_kd_mask = encoder_out_kd_mask[:, ::squeeze]
                    encoder_out_kd_mask2 = encoder_out_kd_mask2[:, ::squeeze]
                    # x before: torch.Size([778, 8, 768])
                    # x after: torch.Size([389, 8, 768])
                    # encoder_out_kd_mask: torch.Size([8, 778, 1])
                    # encoder_out_kd_mask2: torch.Size([8, 778])
            else:
                encoder_out_kd_mask = 1
                encoder_out_kd_mask2 = 1
                encoder_masking = False

            # text data augmentation1 (insertion/deletion/swap error)
            noisy_target = self.txt_augment(sample["target"], sample["target_lengths"], self.target_dictionary, num_aug=1) # noise_type+1 x B x T

            # text data augmentation2 (LM based perturbation)
            lm_based_aug = False
            if lm_based_aug:
                rand_idx = torch.randperm(len(noisy_target))[0]
                logits, _ = self.lm_forward(noisy_target[rand_idx], self.model_lm) 
                logits = torch.argmax(logits, dim=-1)
                logits_mask = (noisy_target[rand_idx] == self.target_dictionary.pad()).to(logits.dtype)
                logits = logits * (1-logits_mask) + logits_mask
                noisy_target.append(logits)
            
            use_batch_samples = False # use samples in batch as the denominator sample
            use_length_norm_for_editdistance = True # use Levenshetein similarity measure
            if use_batch_samples:
                levenshtein=torch.zeros(sample["target"].size(0), len(noisy_target) + sample["target"].size(0) - 1).to(net_output["encoder_out_kd"].device) # B x B+#aug
            else:
                levenshtein=torch.zeros(sample["target"].size(0), len(noisy_target)).to(net_output["encoder_out_kd"].device) # B x #aug

            str_ref = []
            for idx_batch in range(sample["target"].size(0)):
                str_line = self.target_dictionary.string(sample["target"][idx_batch]).replace(' <pad>','')
                str_ref.append(str_line)

            max_projection_axis='mas' # 'speech' # 'text'

            # score matrix for noise target (B x T')
            for idx in range(len(noisy_target)):
                roberta=False
                if roberta:
                    # use roberta base (that doesn't share vocabulary)
                    lines = self.target_dictionary.string(noisy_target[idx])
                    logits, embed_denominator, target_mask_tmp = self.lm_forward_roberta(lines, self.model_lm)
                else:
                    # use masked LM that share the same vocabulary (letter voca)
                    logits, embed_denominator = self.lm_forward(noisy_target[idx], self.model_lm) # B,T,f
                    target_mask_tmp = (noisy_target[idx] != self.target_dictionary.pad()) # 1 is the padding idx, B x T
                score_mat_negative = torch.matmul(embed_denominator, (net_output["encoder_out_kd"].transpose(0,1)*encoder_out_kd_mask).transpose(1,2)) * target_mask_tmp.unsqueeze(-1) # B,T,T'
                if idx == 0:
                    # noisy_target[0] is true label (numerator)
                    embed_numerator = embed_denominator.clone().detach() # True label: numerator
                    align_numerator = score_mat_negative.transpose(1,2).max(-1).indices # to check alignment between ctc&lm
                    score_mat_negative_word_wise = score_mat_negative.max(-1).values * target_mask_tmp # B x T
                    score_mat_negative_word_wise = score_mat_negative_word_wise / score_mat_negative_word_wise.sum(1).unsqueeze(1) # B x T (normalize)

                if max_projection_axis=='speech':
                    # max
                    score_mat_negative = score_mat_negative.transpose(1,2).max(-1).values # B x T'
                    if encoder_masking:
                        # average
                        score_mat_negative = ((score_mat_negative * encoder_out_kd_mask2).sum(1) / encoder_out_kd_mask2.sum(-1)) # B
                    else:
                        # average
                        score_mat_negative = ((score_mat_negative).sum(1) / score_mat_negative.size(-1))  # B
                elif max_projection_axis == 'text':
                    # max & average (max_projection_axis == 'text')
                    score_mat_negative = score_mat_negative.max(-1).values # B x T
                    score_mat_negative = (score_mat_negative*target_mask_tmp).sum(1) / target_mask_tmp.sum(-1) # B
                elif max_projection_axis == 'mas':
                    if print_option:
                        score_mat_negative2 = score_mat_negative.transpose(1,2).max(-1).values # B x T'
                        if encoder_masking:
                            # average
                            score_mat_negative2 = ((score_mat_negative2 * encoder_out_kd_mask2).sum(1) / encoder_out_kd_mask2.sum(-1)) # B
                        else:
                            # average
                            score_mat_negative2 = ((score_mat_negative2).sum(1) / score_mat_negative2.size(-1))  # B
                        score_mat_negative2_position1 = score_mat_negative.transpose(1,2).max(-1).indices # B x T'
                        score_mat_negative2_position2 = score_mat_negative.max(-1).indices # B x T'
                    masks = mas(score_mat_negative) # B x T' x T

                    # target_mask_tmp # B x T
                    # print('target_mask_tmp:', target_mask_tmp.size()) # target_mask_tmp: torch.Size([8, 248])
                    # raise ValueError('score_mat_negative:', score_mat_negative.size()) # torch.Size([8, 248, 778])
                    score_mat_negative = (score_mat_negative * masks).sum(-1)
                    score_mat_negative = (score_mat_negative * target_mask_tmp).mean(-1)

                    if print_option:
                        print('score_mat_neg mas:', score_mat_negative)
                        print('score_mat_neg max:', score_mat_negative2.sum(-1))
                        print('mask 1, mas text:', torch.argmax(masks[0], dim=-1))
                        print('mask 2, max text:', score_mat_negative2_position2[0])
                        print('mask 1, mas speech:', torch.argmax(masks[0].transpose(0,1), dim=-1))
                        print('mask 2, max speech:', score_mat_negative2_position1[0])
                if idx == 0:
                    score_mat = score_mat_negative.unsqueeze(-1) # B,#aug
                else:
                    score_mat = torch.cat((score_mat, score_mat_negative.unsqueeze(-1)), dim=-1) # B,#aug

                    # get levenshtein distance
                    for idx_batch in range(len(sample["target"])):
                        str_denom = self.target_dictionary.string(noisy_target[idx][idx_batch]).replace(' <pad>','')
                        assert levenshtein[idx_batch][idx] == 0
                        if use_length_norm_for_editdistance:
                            len_str = max(len(str_ref[idx_batch]), len(str_denom))
                            levenshtein[idx_batch][idx] = editdistance.eval(str_ref[idx_batch], str_denom) / len_str
                        else:
                            levenshtein[idx_batch][idx] = editdistance.eval(str_ref[idx_batch], str_denom)

            # score matrix for samples in batch
            # for i in range(0, net_output["target_embed"].size(1) - 1):
            if use_batch_samples:
                for i in range(0, embed_numerator.size(0) - 1):
                    idx=(torch.arange(embed_numerator.size(0)) - (i+1)) % embed_numerator.size(0)
                    idx=idx.tolist() # [1,2,3,4,5,6,...,B,0]
                    score_mat_negative = torch.matmul(embed_numerator[idx], (net_output["encoder_out_kd"].transpose(0,1)*encoder_out_kd_mask).transpose(1,2)) * target_mask[idx].unsqueeze(-1) # B,T,T'
                    if max_projection_axis=='speech':
                        # max
                        score_mat_negative = score_mat_negative.transpose(1,2).max(-1).values # B x T'
                        if encoder_masking:
                            # average
                            score_mat_negative = ((score_mat_negative * encoder_out_kd_mask2).sum(1) / encoder_out_kd_mask2.sum(-1)) # B
                        else:
                            # average
                            score_mat_negative = ((score_mat_negative).sum(1) / score_mat_negative.size(-1))  # B
                    else:
                        # max_projection_axis == 'text'
                        # max & average
                        score_mat_negative = score_mat_negative.max(-1).values # B x T
                        score_mat_negative = (score_mat_negative*target_mask[idx]).sum(1) / target_mask[idx].sum(-1) # B

                    score_mat = torch.cat((score_mat, score_mat_negative.unsqueeze(-1)), dim=-1) # B x #aug

                    # get levenshtein distance
                    for j in range(embed_numerator.size(0)):
                        str_denom = str_ref[idx[j]]
                        assert levenshtein[j][len(noisy_target) + i] == 0

                        if use_length_norm_for_editdistance:
                            len_str = max(len(str_ref[idx_batch]), len(str_denom))
                            levenshtein[j][len(noisy_target) + i] = editdistance.eval(str_ref[j], str_denom) / len_str
                        else:
                            levenshtein[j][len(noisy_target) + i] = editdistance.eval(str_ref[j], str_denom)

            if use_length_norm_for_editdistance:
                temperature_lev = 1.5
                levenshtein = torch.softmax(-levenshtein * (1+temperature_lev), dim=-1)
            else:
                levenshtein_max = levenshtein.max(-1).values.unsqueeze(-1) # # B x B+#aug
                levenshtein = levenshtein_max - levenshtein
                levenshtein_sum = levenshtein.sum(-1) # # B x B+#aug
                levenshtein = levenshtein / levenshtein_sum.unsqueeze(-1) # B x B+#aug

            # print
            ramp_func = min(num_update / 6000, 1)
            alpha_kd = 1 * embed_numerator.size(0) # * ramp_func # * sample["target"].size(-1) # score_mat_negative.size(-1) # 1.0

            if print_option:
                print('max axis:', max_projection_axis)
                print('score_mat:', torch.softmax(score_mat[0], dim=-1))
                print('score_mat size:', score_mat.size())
                print('levenshtein:', levenshtein[0])
                print('alignment:', align_numerator[0])
                print('score_mat_negative_word_wise', score_mat_negative_word_wise[0])

            # summation
            normalized_score = self.criterion_kl(torch.log_softmax(score_mat, dim=-1), levenshtein).sum()
            if print_option:
                print('normalized_score:', normalized_score, 'loss', loss, 'alpha_kd', alpha_kd)

            loss = loss + alpha_kd * normalized_score 

        ntokens = (
            sample["ntokens"] if "ntokens" in sample else target_lengths.sum().item()
        )

        sample_size = sample["target"].size(0) if self.sentence_avg else ntokens
        logging_output = {
            "loss": utils.item(loss.data),  # * sample['ntokens'],
            "ntokens": ntokens,
            "nsentences": sample["id"].numel(),
            "sample_size": sample_size,
        }

        if not model.training:
            import editdistance

            with torch.no_grad():
                lprobs_t = lprobs.transpose(0, 1).float().contiguous().cpu()

                c_err = 0
                c_len = 0
                w_errs = 0
                w_len = 0
                wv_errs = 0
                for lp, t, inp_l in zip(
                    lprobs_t,
                    sample["target_label"]
                    if "target_label" in sample
                    else sample["target"],
                    input_lengths,
                ):
                    lp = lp[:inp_l].unsqueeze(0)

                    decoded = None
                    if self.w2l_decoder is not None:
                        decoded = self.w2l_decoder.decode(lp)
                        if len(decoded) < 1:
                            decoded = None
                        else:
                            decoded = decoded[0]
                            if len(decoded) < 1:
                                decoded = None
                            else:
                                decoded = decoded[0]

                    p = (t != self.task.target_dictionary.pad()) & (
                        t != self.task.target_dictionary.eos()
                    )
                    targ = t[p]
                    targ_units = self.task.target_dictionary.string(targ)
                    targ_units_arr = targ.tolist()

                    toks = lp.argmax(dim=-1).unique_consecutive()
                    pred_units_arr = toks[toks != self.blank_idx].tolist()

                    c_err += editdistance.eval(pred_units_arr, targ_units_arr)
                    c_len += len(targ_units_arr)

                    targ_words = post_process(targ_units, self.post_process).split()

                    pred_units = self.task.target_dictionary.string(pred_units_arr)
                    pred_words_raw = post_process(pred_units, self.post_process).split()

                    if decoded is not None and "words" in decoded:
                        pred_words = decoded["words"]
                        w_errs += editdistance.eval(pred_words, targ_words)
                        wv_errs += editdistance.eval(pred_words_raw, targ_words)
                    else:
                        dist = editdistance.eval(pred_words_raw, targ_words)
                        w_errs += dist
                        wv_errs += dist

                    w_len += len(targ_words)

                logging_output["wv_errors"] = wv_errs
                logging_output["w_errors"] = w_errs
                logging_output["w_total"] = w_len
                logging_output["c_errors"] = c_err
                logging_output["c_total"] = c_len

        return loss, sample_size, logging_output

    @staticmethod
    def reduce_metrics(logging_outputs) -> None:
        """Aggregate logging outputs from data parallel training."""

        loss_sum = utils.item(sum(log.get("loss", 0) for log in logging_outputs))
        ntokens = utils.item(sum(log.get("ntokens", 0) for log in logging_outputs))
        nsentences = utils.item(
            sum(log.get("nsentences", 0) for log in logging_outputs)
        )
        sample_size = utils.item(
            sum(log.get("sample_size", 0) for log in logging_outputs)
        )

        metrics.log_scalar(
            "loss", loss_sum / sample_size / math.log(2), sample_size, round=3
        )
        metrics.log_scalar("ntokens", ntokens)
        metrics.log_scalar("nsentences", nsentences)
        if sample_size != ntokens:
            metrics.log_scalar(
                "nll_loss", loss_sum / ntokens / math.log(2), ntokens, round=3
            )

        c_errors = sum(log.get("c_errors", 0) for log in logging_outputs)
        metrics.log_scalar("_c_errors", c_errors)
        c_total = sum(log.get("c_total", 0) for log in logging_outputs)
        metrics.log_scalar("_c_total", c_total)
        w_errors = sum(log.get("w_errors", 0) for log in logging_outputs)
        metrics.log_scalar("_w_errors", w_errors)
        wv_errors = sum(log.get("wv_errors", 0) for log in logging_outputs)
        metrics.log_scalar("_wv_errors", wv_errors)
        w_total = sum(log.get("w_total", 0) for log in logging_outputs)
        metrics.log_scalar("_w_total", w_total)

        if c_total > 0:
            metrics.log_derived(
                "uer",
                lambda meters: safe_round(
                    meters["_c_errors"].sum * 100.0 / meters["_c_total"].sum, 3
                )
                if meters["_c_total"].sum > 0
                else float("nan"),
            )
        if w_total > 0:
            metrics.log_derived(
                "wer",
                lambda meters: safe_round(
                    meters["_w_errors"].sum * 100.0 / meters["_w_total"].sum, 3
                )
                if meters["_w_total"].sum > 0
                else float("nan"),
            )
            metrics.log_derived(
                "raw_wer",
                lambda meters: safe_round(
                    meters["_wv_errors"].sum * 100.0 / meters["_w_total"].sum, 3
                )
                if meters["_w_total"].sum > 0
                else float("nan"),
            )

    @staticmethod
    def logging_outputs_can_be_summed() -> bool:
        """
        Whether the logging outputs returned by `forward` can be summed
        across workers prior to calling `reduce_metrics`. Setting this
        to True will improves distributed training speed.
        """
        return True
