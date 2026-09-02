#!/usr/bin/env bash
# =============================================================
# HMD-AMP 离线依赖下载脚本(Python 3.8 / linux x86_64)
#
#   用法:  bash offline_download.sh [下载目录]      默认 ~/whl
#
# 特点:每个文件用 wget -c 循环续传,连接被掐断会自动重来,
#      直到下完为止。全部下完后用 pip --no-index 离线安装。
#
# 安装(下完后执行):
#   conda activate HMD-AMP
#   pip install --no-index --find-links ~/whl \
#       torch torchvision torchaudio numpy pandas scikit-learn \
#       biopython fair-esm deep-forest
# =============================================================
set -uo pipefail
DEST="${1:-$HOME/whl}"
mkdir -p "$DEST"
cd "$DEST"

URLS=(
# ---- torch 三件套(如已下好会自动跳过) ----
https://files.pythonhosted.org/packages/a9/71/45aac46b75742e08d2d6f9fc2b612223b5e36115b8b2ed673b23c21b5387/torch-2.4.1-cp38-cp38-manylinux1_x86_64.whl
https://files.pythonhosted.org/packages/ed/15/74800e103ea652bef9fc572661b74a081e2194700f0f5f4f184918218af6/torchvision-0.19.1-cp38-cp38-manylinux1_x86_64.whl
https://files.pythonhosted.org/packages/f0/61/bd076dce5ef499a60074aab53af4ecc05b656678156c151fd814102253e3/torchaudio-2.4.1-cp38-cp38-manylinux1_x86_64.whl
# ---- torch 的纯 Python / 编译依赖 ----
https://files.pythonhosted.org/packages/b9/f8/feced7779d755758a52d1f6635d990b8d98dc0a29fa568bbe0625f18fdf3/filelock-3.16.1-py3-none-any.whl
https://files.pythonhosted.org/packages/26/9f/ad63fc0248c5379346306f8668cda6e2e2e9c95e01216d2b8ffd9ff037d0/typing_extensions-4.12.2-py3-none-any.whl
https://files.pythonhosted.org/packages/99/ff/c87e0622b1dadea79d2fb0b25ade9ed98954c9033722eb707053d310d4f3/sympy-1.13.3-py3-none-any.whl
https://files.pythonhosted.org/packages/43/e3/7d92a15f894aa0c9c4b49b8ee9ac9850d6e63b03c9c32c0367a13ae62209/mpmath-1.3.0-py3-none-any.whl
https://files.pythonhosted.org/packages/a8/05/9d4f9b78ead6b2661d6e8ea772e111fc4a9fbd866ad0c81906c11206b55e/networkx-3.1-py3-none-any.whl
https://files.pythonhosted.org/packages/31/80/3a54838c3fb461f6fec263ebf3a3a41771bd05190238de3486aae8540c36/jinja2-3.1.4-py3-none-any.whl
https://files.pythonhosted.org/packages/c7/bd/50319665ce81bb10e90d1cf76f9e1aa269ea6f7fa30ab4521f14d122a3df/MarkupSafe-2.1.5-cp38-cp38-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
https://files.pythonhosted.org/packages/1d/a0/6aaea0c2fbea2f89bfd5db25fb1e3481896a423002ebe4e55288907a97a3/fsspec-2024.9.0-py3-none-any.whl
https://files.pythonhosted.org/packages/4d/b4/c37e2776a1390bab7e78a6d52bd525441cb3cad7260a6a00b11b0b702e7c/triton-3.0.0-1-cp38-cp38-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
https://files.pythonhosted.org/packages/84/4c/69bbed9e436ac22f9ed193a2b64f64d68fcfbc9f4106249dc7ed4889907b/pillow-10.4.0-cp38-cp38-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
# ---- 项目科学计算依赖 ----
https://files.pythonhosted.org/packages/c6/4f/63f6f16d3f44a764a3b66c6233e133baf912e198a93e14c39ee991f587d0/numpy-1.23.5-cp38-cp38-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
https://files.pythonhosted.org/packages/f8/7f/5b047effafbdd34e52c9e2d7e44f729a0655efafb22198c45cf692cdc157/pandas-2.0.3-cp38-cp38-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
https://files.pythonhosted.org/packages/bf/15/d1b649fc7685d11b806b4546a5438191fb2ad761de70da95ff676189dcec/scikit_learn-1.3.0-cp38-cp38-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
https://files.pythonhosted.org/packages/69/f0/fb07a9548e48b687b8bf2fa81d71aba9cfc548d365046ca1c791e24db99d/scipy-1.10.1-cp38-cp38-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
https://files.pythonhosted.org/packages/91/29/df4b9b42f2be0b623cbd5e2140cafcaa2bef0759a00b7b70104dcfe2fb51/joblib-1.4.2-py3-none-any.whl
https://files.pythonhosted.org/packages/4b/2c/ffbf7a134b9ab11a67b0cf0726453cedd9c5043a4fe7a35d1cefa9a1bcfb/threadpoolctl-3.5.0-py3-none-any.whl
https://files.pythonhosted.org/packages/05/2f/4ad16933096030e76046659f40b381869e46c4a26f4735969240d2c0adee/biopython-1.83-cp38-cp38-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
https://files.pythonhosted.org/packages/79/26/1cc82571f507b9dae3b36d4242764edc6e4ae9f3f81f44a6382c15fad565/fair_esm-2.0.0-py3-none-any.whl
https://files.pythonhosted.org/packages/e4/6b/d280c906edb4fd27ac354270fc243fc9d01520c6a45c7429ad05d6207000/deep_forest-0.1.7-cp38-cp38-manylinux1_x86_64.whl
https://files.pythonhosted.org/packages/ec/57/56b9bcc3c9c6a792fcbaf139543cee77261f3651ca9da0c93f5c1221264b/python_dateutil-2.9.0.post0-py2.py3-none-any.whl
https://files.pythonhosted.org/packages/11/c3/005fcca25ce078d2cc29fd559379817424e94885510568bc1bc53d7d5846/pytz-2024.2-py2.py3-none-any.whl
https://files.pythonhosted.org/packages/a6/ab/7e5f53c3b9d14972843a647d8d7a853969a58aecc7559cb3267302c94774/tzdata-2024.2-py2.py3-none-any.whl
https://files.pythonhosted.org/packages/d9/5a/e7c31adbe875f2abbb91bd84cf2dc52d792b5a01506781dbcf25c91daf11/six-1.16.0-py2.py3-none-any.whl
)

total=${#URLS[@]}
i=0
for u in "${URLS[@]}"; do
    i=$((i+1))
    f="$(basename "$u")"
    # 已存在且大小与服务器一致则跳过
    if [ -f "$f" ]; then
        remote=$(wget --spider -S "$u" 2>&1 | awk '/[Cc]ontent-[Ll]ength:/{n=$2} END{print n+0}')
        local_sz=$(stat -c %s "$f")
        if [ "$remote" -gt 0 ] && [ "$local_sz" -eq "$remote" ]; then
            echo "[$i/$total] 已完整,跳过: $f"
            continue
        fi
    fi
    echo "[$i/$total] 下载: $f"
    n=0
    until wget -c --tries=3 --timeout=30 --waitretry=2 --read-timeout=30 \
               -q --show-progress "$u"; do
        n=$((n+1))
        echo "    断线第 ${n} 次,2 秒后继续续传..."
        sleep 2
        [ $n -ge 500 ] && { echo "    放弃: $f"; break; }
    done
done

echo
echo "=============================================="
echo " 下载完毕,文件列表:"
ls -lh "$DEST"
echo "=============================================="
echo " 下一步(离线安装):"
echo "   conda activate HMD-AMP"
echo "   pip install --no-index --find-links $DEST \\"
echo "       torch torchvision torchaudio numpy pandas scikit-learn \\"
echo "       biopython fair-esm deep-forest"
echo "   cd ~/HMD-AMP && bash verify_env.sh"
