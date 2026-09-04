#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_training_data.py
========================
把下载好的原始训练数据整理成 HMD-AMP 训练脚本可以直接使用的格式。

HMD-AMP 有两个训练任务，脚本对输入的要求分别是：

任务 1：AMP / non-AMP 二分类
    需要：1 个 fasta 文件 + 1 个 label.npy
        --training_data  FASTA   所有训练序列（AMP 与 non-AMP 混在一起）
        --training_label label.npy  与 fasta 顺序一一对应的 0/1 整数数组
                                    （1 = AMP 阳性, 0 = non-AMP 阴性）

任务 2：AMP 靶标（target group）预测，共 6 个二分类任务
    （Gram+, Gram-, Mammalian_Cell, Virus, Fungus, Cancer）
    每个靶标各需要：1 个 fasta + 1 个 label.npy（1 = 对该靶标有活性,
    0 = 无活性）。靶标活性标签 *不包含* 在 Zenodo 的训练数据里
    （那里只有 AMP/non-AMP 两类 fasta），需要从 AMP 数据库的活性注释
    获取，或在本脚本生成的标注模板 CSV 中手动填写。

数据来源（由 download_training_data.py 下载）:
    data/raw/AMPs_5985.fasta       5985 条 AMP
    data/raw/non_AMPs_5985.fasta   5985 条 non-AMP

输出（默认 data/processed/）:
    amp_task/
        amp_train.fasta           合并后的训练 fasta
        amp_label.npy             对应的 0/1 标签
    target_tasks/
        <Target>/                 每个靶标一个目录（Gram+, Gram-, ...）
            <Target>_train.fasta
            <Target>_label.npy
        target_annotation_template.csv   靶标活性标注模板（需你填写 1/0）
    prepare_report.txt            数据统计报告

用法:
    python script/prepare_training_data.py --raw_dir data/raw --out_dir data/processed

常用选项:
    --annotation CSV      提供靶标活性注释表（覆盖自动从 fasta 头部解析的结果）
                          CSV 需包含列: id,Gram+,Gram-,Mammalian_Cell,Virus,Fungus,Cancer
                          （值用 1/0 或 yes/no/true/false；缺失留空即可）
    --neg-include-nonamp  靶标任务的阴性样本默认只用“没有该活性的 AMP”，
                          加此选项后额外把 non-AMP 也加入阴性样本
    --strict              丢弃含非标准氨基酸字符（B/J/X/Z/U/* 等）的序列，
                          默认是把 *、-、.、空白去掉、其余小写转大写后保留
    --min-len N           最短肽长（默认 5，与论文 sORF 范围一致）
    --max-len N           最长肽长（默认 100，与论文 sORF 范围一致）

关于靶标标签从哪来（当务之急请先看这里）:
    1) 脚本会先尝试自动从 fasta 头部描述里的关键词
       （如 gram-positive/antibacterial/antiviral/anticancer/...）解析活性；
    2) 但 Zenodo 的 AMPs_5985.fasta 头部通常只有序列 ID，没有活性注释，
       自动解析结果基本为空 —— 这是正常的；
    3) 请打开 target_tasks/target_annotation_template.csv，按序列填写
       各靶标 1（有活性）/0（无活性），再用 --annotation 重新运行本脚本；
    4) 活性注释的权威来源（公开 AMP 数据库，按你的序列 ID/序列去比对获取）:
         - APD3      https://aps.unmc.edu/
         - DBAASP    https://dbaasp.org/
         - DRAMP     http://dramp.cpu-bioinfor.org/
         - dbAMP     https://awi.cuhk.edu.cn/dbAMP/
         - LAMP      http://biotechlab.fudan.edu.cn/database/lamp/
         - CAMP/NCBI/UniProt  （UniProt 中 antimicrobial 关键词 + 功能描述）
       这些数据库都标注了每条 AMP 的抗菌类型（抗 G+/G-、抗病毒、抗真菌、
       抗肿瘤/抗癌、靶向哺乳动物细胞等），按论文 Methods 中的类别
       （Gram+/Gram-/Mammalian_Cell/Virus/Fungus/Cancer）归类即可。
"""

import argparse
import csv
import os
import sys

TARGETS = ["Gram+", "Gram-", "Mammalian_Cell", "Virus", "Fungus", "Cancer"]

# 靶标关键词 -> 命中即视为对该靶标阳性（在 fasta 头部描述中做不区分大小写匹配）
# 注意：Gram+/Gram- 只匹配“特异性”关键词（如 gram-positive / s.aureus / e.coli）。
# 泛指的 antibacterial / antimicrobial 不同时算两类的阳性，否则所有抗菌肽都会
# 被同时标成 G+ 与 G- 阳性，导致没有阴性样本。
TARGET_KEYWORDS = {
    "Gram+": [
        "gram-positive", "gram positive", "gram+", "gram positive bacteria",
        "s. aureus", "staphylococcus aureus", "staph", "micrococcus",
        "bacillus subtilis", "listeria",
    ],
    "Gram-": [
        "gram-negative", "gram negative", "gram-", "gram negative bacteria",
        "e. coli", "escherichia coli", "pseudomonas aeruginosa", "pseudomonas",
        "klebsiella", "acinetobacter", "salmonella",
    ],
    "Mammalian_Cell": [
        "mammalian", "mammal", "hemolysis", "haemolysis", "red blood cell",
        "erythrocyte", "cytotoxic to mammalian", "normal cell",
    ],
    "Virus": [
        "antiviral", "anti-viral", "virucidal", "virus", "hiv", "influenza",
        "herpes", "sars", "cov",
    ],
    "Fungus": [
        "antifungal", "anti-fungal", "fungicide", "fungicidal", "candida",
        "yeast",
    ],
    "Cancer": [
        "anticancer", "anti-cancer", "antitumor", "anti-tumor", "antitumour",
        "anti-tumour", "tumor cell", "tumour cell", "cancer", "cytotoxic to tumor",
        "leukemia", "hela",
    ],
}

STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")


# ---------------------------------------------------------------------------
# FASTA 读写（纯标准库实现，无需 biopython）
# ---------------------------------------------------------------------------
def read_fasta(path):
    """读取 fasta，返回 [(id, description, sequence), ...]，保持文件顺序。"""
    records = []
    cur_id, cur_desc, cur_seq = None, "", []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n").rstrip("\r")
            if not line:
                continue
            if line.startswith(">"):
                if cur_id is not None:
                    records.append((cur_id, cur_desc, "".join(cur_seq)))
                header = line[1:].strip()
                parts = header.split(None, 1)
                cur_id = parts[0] if parts else f"seq_{len(records)}"
                cur_desc = parts[1] if len(parts) > 1 else ""
                cur_seq = []
            else:
                cur_seq.append(line.strip())
        if cur_id is not None:
            records.append((cur_id, cur_desc, "".join(cur_seq)))
    return records


def write_fasta(path, records, wrap=60):
    """写 fasta。records: [(id, desc, seq), ...] 或 [(id, seq), ...]"""
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            if len(rec) == 3:
                sid, desc, seq = rec
                header = sid if not desc else f"{sid} {desc}"
            else:
                sid, seq = rec
                header = sid
            fh.write(f">{header}\n")
            for i in range(0, len(seq), wrap):
                fh.write(seq[i:i + wrap] + "\n")


# ---------------------------------------------------------------------------
# label.npy 写出（优先 numpy；无 numpy 时手写最小合法 .npy 格式）
# ---------------------------------------------------------------------------
def save_label_npy(path, labels):
    labels = [int(x) for x in labels]
    try:
        import numpy as np
        np.save(path, np.array(labels, dtype=np.int64))
        return
    except ImportError:
        pass

    # 手写 .npy v1.0（little-endian int64 一维数组），numpy 可正常 np.load
    import struct
    arr = b"".join(struct.pack("<q", x) for x in labels)
    header = "{'descr': '<i8', 'fortran_order': False, 'shape': (%d,), }" % len(labels)
    # header 长度需补齐到 64 的倍数（含 magic 6 + version 2 + header_len 2 = 10）
    pad = (64 - ((10 + len(header) + 1) % 64)) % 64
    header = header + " " * pad + "\n"
    with open(path, "wb") as fh:
        fh.write(b"\x93NUMPY")          # magic
        fh.write(bytes([1, 0]))         # version 1.0
        fh.write(struct.pack("<H", len(header)))
        fh.write(header.encode("latin1"))
        fh.write(arr)
    print("    （当前环境无 numpy，已用内置写出器生成 .npy；"
          "在训练环境中 np.load 可正常读取）")


# ---------------------------------------------------------------------------
# 序列清洗 / 去重
# ---------------------------------------------------------------------------
def clean_sequence(seq, strict):
    """大写化；默认去掉 *、-、.、空白等非氨基酸字符；strict 时遇到非标残基返回 None。"""
    seq = seq.upper().replace("*", "").replace("-", "").replace(".", "")
    seq = "".join(seq.split())
    if strict:
        if any(ch not in STANDARD_AA for ch in seq):
            return None
    else:
        seq = "".join(ch for ch in seq if ch in STANDARD_AA or ch in "BJXZUO")
    return seq


def dedup(records, min_len, max_len, strict):
    """
    清洗 + 长度过滤 + 按序列去重。
    records: [(id, desc, seq, label)]  label: 1=AMP, 0=non-AMP
    返回去重后的列表；AMP(label=1) 与 non-AMP(label=0) 序列冲突时保留 AMP。
    """
    best = {}  # seq -> (id, desc, label)
    stats = {"kept": 0, "bad_len": 0, "bad_char": 0, "dup": 0}
    for sid, desc, seq, label in records:
        cleaned = clean_sequence(seq, strict)
        if cleaned is None:
            stats["bad_char"] += 1
            continue
        if not (min_len <= len(cleaned) <= max_len):
            stats["bad_len"] += 1
            continue
        if cleaned in best:
            stats["dup"] += 1
            # 阳性优先
            if label == 1 and best[cleaned][2] == 0:
                best[cleaned] = (sid, desc, 1)
            continue
        best[cleaned] = (sid, desc, label)
    out = [(sid, desc, seq, label) for seq, (sid, desc, label) in best.items()]
    stats["kept"] = len(out)
    return out, stats


# ---------------------------------------------------------------------------
# 靶标标签
# ---------------------------------------------------------------------------
def parse_targets_from_header(desc):
    """从 fasta 头部描述关键词中解析靶标阳性集合。"""
    text = desc.lower()
    hits = set()
    for target, kws in TARGET_KEYWORDS.items():
        if any(kw in text for kw in kws):
            hits.add(target)
    return hits


_BOOL_TRUE = {"1", "yes", "y", "true", "t", "positive", "pos", "active"}
_BOOL_FALSE = {"0", "no", "n", "false", "f", "negative", "neg", "inactive"}


def parse_bool(cell):
    """把 CSV 单元格解析成 True/False/None(空)。"""
    if cell is None:
        return None
    c = str(cell).strip().lower()
    if c == "" or c in {"na", "n/a", "nan", "none"}:
        return None
    if c in _BOOL_TRUE:
        return True
    if c in _BOOL_FALSE:
        return False
    return None


def load_annotation(path):
    """读取人工注释 CSV，返回 {seq_id: {target: True/False}}。"""
    table = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            sid = (row.get("id") or row.get("ID") or "").strip()
            if not sid:
                continue
            labels = {}
            for t in TARGETS:
                v = parse_bool(row.get(t))
                if v is not None:
                    labels[t] = v
            table[sid] = labels
    return table


def write_annotation_template(path, amp_records):
    """写出靶标标注模板 CSV：每行一条 AMP，靶标列留空待填。"""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "sequence"] + TARGETS)
        for sid, desc, seq, _label in amp_records:
            writer.writerow([sid, seq] + [""] * len(TARGETS))


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="准备 HMD-AMP 训练数据（生成 fasta + label.npy）")
    ap.add_argument("--raw_dir", default="data/raw",
                    help="原始数据目录（含 AMPs_5985.fasta / non_AMPs_5985.fasta）")
    ap.add_argument("--out_dir", default="data/processed",
                    help="处理后数据输出目录")
    ap.add_argument("--amp_fasta", default=None, help="自定义 AMP fasta 路径")
    ap.add_argument("--nonamp_fasta", default=None, help="自定义 non-AMP fasta 路径")
    ap.add_argument("--annotation", default=None,
                    help="靶标活性注释 CSV（列: id,%s）" % ",".join(TARGETS))
    ap.add_argument("--neg-include-nonamp", action="store_true",
                    help="靶标任务阴性样本中额外加入 non-AMP 序列")
    ap.add_argument("--strict", action="store_true",
                    help="丢弃含非标准氨基酸字符的序列")
    ap.add_argument("--min-len", type=int, default=5, help="最短肽长（默认 5）")
    ap.add_argument("--max-len", type=int, default=100, help="最长肽长（默认 100）")
    args = ap.parse_args()

    amp_path = args.amp_fasta or os.path.join(args.raw_dir, "AMPs_5985.fasta")
    nonamp_path = args.nonamp_fasta or os.path.join(args.raw_dir, "non_AMPs_5985.fasta")

    for p in (amp_path, nonamp_path):
        if not os.path.exists(p):
            print(f"[错误] 找不到文件: {p}\n"
                  f"请先运行: python script/download_training_data.py --out data")
            sys.exit(1)

    print("读取原始 fasta ...")
    amp_raw = [(sid, desc, seq, 1) for sid, desc, seq in read_fasta(amp_path)]
    non_raw = [(sid, desc, seq, 0) for sid, desc, seq in read_fasta(nonamp_path)]
    print(f"  原始 AMP 序列: {len(amp_raw)} 条;  non-AMP 序列: {len(non_raw)} 条")

    print("清洗 / 长度过滤 / 去重 ...")
    all_clean, stats = dedup(amp_raw + non_raw, args.min_len, args.max_len, args.strict)
    amp_clean = [r for r in all_clean if r[3] == 1]
    non_clean = [r for r in all_clean if r[3] == 0]
    print(f"  保留 {stats['kept']} 条（AMP {len(amp_clean)} / non-AMP {len(non_clean)}）;  "
          f"去重 {stats['dup']} 条, 长度不符 {stats['bad_len']} 条, "
          f"非标字符 {stats['bad_char']} 条")

    os.makedirs(args.out_dir, exist_ok=True)
    report = []

    # ------------------------------------------------------------------
    # 任务 1：AMP / non-AMP
    # ------------------------------------------------------------------
    amp_task_dir = os.path.join(args.out_dir, "amp_task")
    os.makedirs(amp_task_dir, exist_ok=True)
    # 固定顺序：AMP 在前，non-AMP 在后（标签与顺序一一对应）
    task1_records = amp_clean + non_clean
    task1_fasta = os.path.join(amp_task_dir, "amp_train.fasta")
    task1_label = os.path.join(amp_task_dir, "amp_label.npy")
    write_fasta(task1_fasta, [(sid, desc, seq) for sid, desc, seq, _ in task1_records])
    save_label_npy(task1_label, [lab for *_, lab in task1_records])
    n_pos = sum(1 for *_, lab in task1_records if lab == 1)
    print(f"\n[任务1 AMP/non-AMP] {len(task1_records)} 条 "
          f"（阳性 {n_pos} / 阴性 {len(task1_records) - n_pos}）")
    print(f"  fasta: {task1_fasta}")
    print(f"  label: {task1_label}")
    report.append(f"Task1 AMP/non-AMP: total={len(task1_records)} "
                  f"pos(AMP)={n_pos} neg(non-AMP)={len(task1_records) - n_pos}")

    # ------------------------------------------------------------------
    # 任务 2：6 个靶标
    # ------------------------------------------------------------------
    annotation = {}
    if args.annotation:
        if not os.path.exists(args.annotation):
            print(f"[错误] 注释文件不存在: {args.annotation}")
            sys.exit(1)
        annotation = load_annotation(args.annotation)
        print(f"\n已载入人工注释: {args.annotation}（{len(annotation)} 条）")

    target_dir = os.path.join(args.out_dir, "target_tasks")
    os.makedirs(target_dir, exist_ok=True)

    # 预先统计每个靶标的阳性数量
    target_pos_ids = {t: set() for t in TARGETS}
    auto_parsed = 0
    for sid, desc, seq, _ in amp_clean:
        auto_hits = parse_targets_from_header(desc)
        manual = annotation.get(sid, {})
        for t in TARGETS:
            if manual.get(t) is True:
                target_pos_ids[t].add(sid)
            elif manual.get(t) is False:
                pass  # 明确阴性
            elif t in auto_hits:
                target_pos_ids[t].add(sid)
        if auto_hits:
            auto_parsed += 1

    # 写出标注模板
    template_path = os.path.join(target_dir, "target_annotation_template.csv")
    write_annotation_template(template_path, amp_clean)

    print(f"\n[任务2 靶标预测] 共 {len(TARGETS)} 个靶标")
    print(f"  自动从 fasta 头部解析到活性关键词的 AMP: {auto_parsed} 条"
          f"（Zenodo 数据通常无活性注释，多为 0 属正常）")
    print(f"  标注模板已写出: {template_path}")

    for t in TARGETS:
        pos_ids = target_pos_ids[t]
        tdir = os.path.join(target_dir, t)
        os.makedirs(tdir, exist_ok=True)

        pos_records = [r for r in amp_clean if r[0] in pos_ids]
        neg_amp_records = [r for r in amp_clean if r[0] not in pos_ids]
        if args.neg_include_nonamp:
            neg_records = neg_amp_records + non_clean
        else:
            neg_records = neg_amp_records

        n_pos, n_neg = len(pos_records), len(neg_records)

        if n_pos == 0 or n_neg == 0:
            # 没有阳性标签（或没有阴性样本）：不生成训练文件，只写说明
            note = os.path.join(tdir, "README.txt")
            with open(note, "w", encoding="utf-8") as fh:
                fh.write(
                    f"靶标 {t} 当前阳性 {n_pos} 条 / 阴性 {n_neg} 条，"
                    f"两类必须都非空才能训练，故未生成训练 fasta/label。\n\n"
                    f"请按以下步骤准备该靶标的标签：\n"
                    f"1. 打开 {template_path}\n"
                    f"2. 在 {t} 列填写 1（有该活性）或 0（无该活性）\n"
                    f"   活性注释可从 APD3 / DBAASP / DRAMP / dbAMP / LAMP /\n"
                    f"   UniProt 等公开 AMP 数据库按序列比对获取\n"
                    f"3. 重新运行：\n"
                    f"   python script/prepare_training_data.py \\\n"
                    f"       --raw_dir {args.raw_dir} --out_dir {args.out_dir} \\\n"
                    f"       --annotation <你填好的csv路径>\n")
            print(f"  - {t:15s}: 阳性 {n_pos:4d} / 阴性 {n_neg:4d}  "
                  f"-> 标签不完整（两类需都非空），请填写 {os.path.basename(template_path)}")
            report.append(f"Task2 {t}: pos={n_pos} neg={n_neg} (annotation needed)")
            continue

        # 平衡阴性数量（随机取与阳性等量的阴性，保持可复现）
        import random
        rng = random.Random(5)
        if n_neg > n_pos:
            neg_records = rng.sample(neg_records, n_pos)
            n_neg = n_pos

        records = pos_records + neg_records
        rng.shuffle(records)
        fasta_path = os.path.join(tdir, f"{t}_train.fasta")
        label_path = os.path.join(tdir, f"{t}_label.npy")
        write_fasta(fasta_path, [(sid, desc, seq) for sid, desc, seq, _ in records])
        save_label_npy(label_path, [lab for *_, lab in records])
        print(f"  - {t:15s}: 阳性 {n_pos:4d} / 阴性 {n_neg:4d}  -> {fasta_path}")
        report.append(f"Task2 {t}: total={len(records)} pos={n_pos} neg={n_neg}")

    # 报告
    report_path = os.path.join(args.out_dir, "prepare_report.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("HMD-AMP 训练数据准备报告\n")
        fh.write(f"原始 AMP: {len(amp_raw)}  原始 non-AMP: {len(non_raw)}\n")
        fh.write(f"清洗后 AMP: {len(amp_clean)}  non-AMP: {len(non_clean)}  "
                 f"(去重 {stats['dup']}, 长度不符 {stats['bad_len']}, "
                 f"非标字符 {stats['bad_char']})\n\n")
        fh.write("\n".join(report) + "\n")
    print(f"\n报告已写出: {report_path}")

    print("\n" + "=" * 70)
    print("数据准备完成。训练命令示例：")
    print("-" * 70)
    print("# 任务1：AMP/non-AMP（微调 ESM-2 + 抽嵌入 -> 训练 deep forest）")
    print("cd script")
    print("python amp_extract_repr.py \\")
    print(f"    --training_data ../{task1_fasta} \\")
    print(f"    --training_label ../{task1_label} \\")
    print("    --ftmodel_save_path ../model/amp_ft \\")
    print("    --emb_path ../emb/amp")
    print("python amp_train.py --training_emb ../emb/amp "
          "--clsmodel_save_path ../model/amp_clsmodel")
    print()
    print("# 任务2：某靶标（以 Gram+ 为例）")
    print("python target_extract_repr.py --target Gram+ \\")
    print(f"    --data_path ../{os.path.join(target_dir, 'Gram+', 'Gram+_train.fasta')} \\")
    print(f"    --label_path ../{os.path.join(target_dir, 'Gram+', 'Gram+_label.npy')} \\")
    print("    --ftmodel_save_path ../model/target_ft \\")
    print("    --emb_path ../emb/target")
    print("python target_train.py --target Gram+ --emb ../emb/target "
          "--clsmodel_save_path ../model/target_clsmodel")
    print("=" * 70)


if __name__ == "__main__":
    main()
