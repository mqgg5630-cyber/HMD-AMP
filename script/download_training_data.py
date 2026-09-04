#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_training_data.py
=========================
一键下载 HMD-AMP 训练所需的全部数据（来源：Zenodo 官方数据仓库）。

论文数据公开地址:
  - https://doi.org/10.5281/zenodo.15622525   (论文正文引用的最新版本 v4)
  - https://doi.org/10.5281/zenodo.15583284   (README 中引用的版本 v3，内容相同)

训练必需的文件只有一个（约 200 KB）:
  training_data.zip  -> 解压后得到
      AMPs_5985.fasta      (5985 条 AMP 阳性序列)
      non_AMPs_5985.fasta  (5985 条 non-AMP 阴性序列)
  这两个文件即可满足【AMP/non-AMP 二分类】训练任务。

其余超大文件（共约 12.6 GB）是论文中用于“宏基因组/哺乳动物基因组 AMP 挖掘”
的待预测 ORF 数据，*不是*训练数据，只有你想复现论文的挖掘流程时才需要，
用 --extra 开关下载。

用法:
  # 1) 只下载训练数据（默认，推荐）
  python script/download_training_data.py --out data

  # 2) 下载后自动运行数据准备脚本，生成可直接喂给训练脚本的 fasta + label.npy
  python script/download_training_data.py --out data --prepare

  # 3) 顺便下载论文用于宏基因组挖掘的超大文件（12.6 GB，非必需）
  python script/download_training_data.py --out data --extra

  # 4) 顺便从 Google Drive 下载作者提供的已训练模型权重（预测时用，非训练必需）
  python script/download_training_data.py --out data --models

注意:
  - 本脚本只依赖 Python 标准库，无需安装任何第三方包即可下载/解压/校验。
  - 下载使用临时文件 + MD5 校验 + 断点续传，网络中断后重跑会自动续传。
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

# ---------------------------------------------------------------------------
# Zenodo 官方文件清单（记录 15622525，v4）
# key=文件名, value=(md5, 字节大小, 是否为训练必需文件)
# ---------------------------------------------------------------------------
ZENODO_RECORD = "15622525"
FALLBACK_RECORDS = ["15583284"]   # training_data.zip 的备用记录（README 引用版本）

ZENODO_FILES = {
    # 训练必需
    "training_data.zip": (
        "f523bce225fb50a469e551618fff56ac", 200_200, True),
    # ---- 以下为论文“基因组挖掘”用的超大文件，非训练必需，需 --extra ----
    "MammalianGenomesID.txt": (
        "59db59c2476dd8cb6165bb577ad08c53", 30_400, False),
    "swineHost_815.faa": (
        "3fee90f52e4a2faced7d0f87117f1766", 124_600, False),
    "8mammalian.faa.gz": (
        "0f23848568331a7e8c4270b44453c84f", 3_300_000_000, False),
    "swineGutORFs.faa.gz": (
        "ac09b6f390d5b9428e6c658ea3e5b306", 9_300_000_000, False),
}

# 作者已训练模型权重（Google Drive），预测时使用，训练不需要
# (AMP/non-AMP 模型包, 6 个 target 模型包)
GDRIVE_MODELS = [
    ("AMP/non-AMP 预测模型 (ft_parts.pth + clsmodel)",
     "1Z4IeD0rUfBtN4OwSh7S-2fJUCbk07qiA"),
    ("AMP target groups 预测模型 (Gram+/Gram-/Mammalian_Cell/Virus/Fungus/Cancer)",
     "199S59bh9KO9IPTmzOYOhd4t1NHN_zdcg"),
]


def md5sum(path, blocksize=1 << 20):
    """计算文件 MD5。"""
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(blocksize), b""):
            h.update(block)
    return h.hexdigest()


def _progress(block_num, block_size, total_size):
    """urllib 下载进度回调。"""
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(downloaded / total_size * 100, 100)
        mb_down = downloaded / 1e6
        mb_total = total_size / 1e6
        sys.stdout.write(f"\r    {pct:6.2f}%  {mb_down:8.1f} / {mb_total:8.1f} MB")
    else:
        sys.stdout.write(f"\r    {downloaded / 1e6:8.1f} MB")
    sys.stdout.flush()


def candidate_urls(record, filename):
    """构造 Zenodo 下载地址（两种写法互为备份）。"""
    return [
        f"https://zenodo.org/records/{record}/files/{filename}?download=1",
        f"https://zenodo.org/api/records/{record}/files/{filename}/content",
    ]


def download_with_resume(url, target_path):
    """下载文件，支持断点续传；返回是否成功。"""
    part_path = target_path + ".part"
    existing = os.path.getsize(part_path) if os.path.exists(part_path) else 0
    headers = {"User-Agent": "Mozilla/5.0 (HMD-AMP data downloader)"}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            mode = "ab" if existing > 0 and resp.status == 206 else "wb"
            if mode == "wb":
                existing = 0
            with open(part_path, mode) as out:
                shutil.copyfileobj(resp, out, length=1 << 20)
        shutil.move(part_path, target_path)
        return True
    except Exception as exc:  # noqa: BLE001 - 网络问题统一处理
        sys.stdout.write("\n")
        print(f"    [警告] 下载失败: {exc}")
        if os.path.exists(part_path):
            print(f"    已保留断点文件 ({os.path.getsize(part_path)} bytes)，重跑可续传。")
        return False


def verify(path, expected_md5):
    """校验文件是否存在且 MD5 正确。"""
    if not os.path.exists(path):
        return False
    if md5sum(path) == expected_md5:
        return True
    print(f"    [警告] MD5 校验不匹配，文件可能损坏，将重新下载: {path}")
    os.remove(path)
    return False


def fetch_file(filename, md5, out_dir):
    """下载单个 Zenodo 文件（含校验/备用记录/重试）。"""
    target = os.path.join(out_dir, filename)
    if verify(target, md5):
        print(f"  [已存在且校验通过] {filename}")
        return True

    records = [ZENODO_RECORD] + FALLBACK_RECORDS
    for attempt in range(1, 4):
        print(f"  [第 {attempt} 次尝试] 下载 {filename} ...")
        for rec in records:
            for url in candidate_urls(rec, filename):
                print(f"    URL: {url}")
                if download_with_resume(url, target):
                    if verify(target, md5):
                        print(f"\n  [完成] {filename}")
                        return True
        print("    所有地址均失败，稍后重试...")
    print(f"  [错误] {filename} 下载失败，请检查网络后重跑本脚本（支持断点续传）。")
    return False


def extract_zip(zip_path, dest_dir):
    """解压 zip，忽略 macOS 的 __MACOSX 元数据。"""
    print(f"  解压 {os.path.basename(zip_path)} -> {dest_dir}")
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist()
                   if "__MACOSX" not in m and not os.path.basename(m).startswith("._")]
        for m in members:
            zf.extract(m, dest_dir)
    print(f"  [完成] 解压出: {', '.join(sorted(os.path.basename(m) for m in members))}")


def download_gdrive_models(out_dir):
    """可选：从 Google Drive 下载作者已训练模型权重（需要 gdown）。"""
    model_dir = os.path.join(out_dir, "models_gdrive")
    os.makedirs(model_dir, exist_ok=True)
    try:
        import gdown  # noqa: F401
    except ImportError:
        print("  [跳过] 下载 Google Drive 模型需要 gdown，请先安装:")
        print("         pip install gdown")
        print("         然后重跑: python script/download_training_data.py --models")
        return
    for desc, file_id in GDRIVE_MODELS:
        print(f"  下载模型: {desc}")
        zip_path = os.path.join(model_dir, f"{file_id}.zip")
        gdown.download(id=file_id, output=zip_path, quiet=False)
        if os.path.exists(zip_path):
            extract_zip(zip_path, model_dir)


def main():
    parser = argparse.ArgumentParser(
        description="下载 HMD-AMP 训练数据（Zenodo 官方来源）")
    parser.add_argument("--out", default="data",
                        help="数据保存目录（默认: data）")
    parser.add_argument("--extra", action="store_true",
                        help="同时下载论文宏基因组挖掘用的超大文件（约 12.6 GB，非训练必需）")
    parser.add_argument("--models", action="store_true",
                        help="同时下载 Google Drive 上作者已训练好的模型权重（预测用，需 gdown）")
    parser.add_argument("--prepare", action="store_true",
                        help="下载完成后自动运行 prepare_training_data.py 生成训练输入")
    args = parser.parse_args()

    raw_dir = os.path.join(args.out, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    print("=" * 70)
    print("HMD-AMP 训练数据下载")
    print(f"保存目录: {raw_dir}")
    print("=" * 70)

    ok = True
    for filename, (md5, _size, required) in ZENODO_FILES.items():
        if not required and not args.extra:
            print(f"  [跳过] {filename} （非训练必需，加 --extra 可下载）")
            continue
        ok = fetch_file(filename, md5, raw_dir) and ok

    if not ok:
        print("\n[错误] 部分文件下载失败。请检查网络后重新运行本脚本（自动续传/校验）。")
        sys.exit(1)

    # 解压训练数据
    zip_path = os.path.join(raw_dir, "training_data.zip")
    if os.path.exists(zip_path):
        extract_zip(zip_path, raw_dir)

    if args.models:
        print("-" * 70)
        download_gdrive_models(args.out)

    print("-" * 70)
    print("全部下载完成！")
    print(f"原始文件位于: {raw_dir}")

    if args.prepare:
        print("-" * 70)
        print("自动运行数据准备脚本 ...")
        cmd = [sys.executable,
               os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "prepare_training_data.py"),
               "--raw_dir", raw_dir,
               "--out_dir", os.path.join(args.out, "processed")]
        subprocess.run(cmd, check=False)
    else:
        print("\n下一步：生成可直接训练的输入文件（fasta + label.npy）:")
        print("  python script/prepare_training_data.py "
              f"--raw_dir {raw_dir} --out_dir {os.path.join(args.out, 'processed')}")


if __name__ == "__main__":
    main()
