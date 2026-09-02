#!/usr/bin/env bash
# =============================================================
# HMD-AMP 一键环境安装脚本(Linux / WSL)
#
# 用法:
#   bash install.sh            自动选择:有 conda 走方式 A,否则走方式 B
#   bash install.sh --conda    方式 A:conda + Python 3.8(与论文 README 一致,免编译)
#   bash install.sh --venv     方式 B:venv + Python 3.9~3.11(源码编译 deep-forest)
#
# 可选环境变量:
#   VENV_DIR    方式 B 的虚拟环境目录,默认 .venv
#
# 两种方式装完后:
#   方式 A: conda activate HMD-AMP
#   方式 B: source .venv/bin/activate
#   python prediction.py   (先按 README 下载模型权重并填好路径)
# =============================================================
set -euo pipefail
cd "$(dirname "$0")"

CONDA_ENV_NAME="HMD-AMP"
VENV_DIR="${VENV_DIR:-.venv}"
DEEP_FOREST_GIT="https://github.com/LAMDA-NJU/Deep-Forest.git"
DEEP_FOREST_TAG="v0.1.7"

log() { printf '\033[1;32m[HMD-AMP]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[HMD-AMP][错误]\033[0m %s\n' "$*" >&2; exit 1; }

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

# -------------------------------------------------------------
# 参数解析:--conda / --venv / 自动
# -------------------------------------------------------------
MODE=""
case "${1:-}" in
    --conda) MODE="conda" ;;
    --venv)  MODE="venv" ;;
    "")      if command -v conda >/dev/null 2>&1; then MODE="conda"; else MODE="venv"; fi ;;
    *)       die "未知参数: $1(支持 --conda / --venv)" ;;
esac
log "选择安装方式: $MODE"

# -------------------------------------------------------------
# 通用:安装完成后的验证(依赖导入 + 级联森林功能自测 + 项目模块)
# -------------------------------------------------------------
verify_install() {
    log "验证安装 ..."
    python - <<'PYEOF'
import numpy as np, torch
import numpy, pandas, sklearn, Bio, esm
from deepforest import CascadeForestClassifier
import src.Net, src.loss, src.utils
rng = np.random.RandomState(0)
X = rng.rand(50, 4); y = (X[:, 0] > 0.5).astype(int)
m = CascadeForestClassifier(n_estimators=5)
m.fit(X, y)
assert m.predict(X).shape == (50,)          # predict 输出类别标签
assert m.predict_proba(X).shape == (50, 2)  # predict_proba 输出两类概率
print("  torch %s | numpy %s | pandas %s | scikit-learn %s | biopython %s" % (
    torch.__version__, numpy.__version__, pandas.__version__,
    sklearn.__version__, Bio.__version__))
print("  deep-forest OK(fit/predict 自测通过)")
print("  项目 src 模块导入 OK")
PYEOF
    log "全部验证通过,环境安装成功!"
}

# -------------------------------------------------------------
# 方式 A:conda + Python 3.8
# -------------------------------------------------------------
install_conda() {
    command -v conda >/dev/null 2>&1 || die "未找到 conda,请改用:bash install.sh --venv"
    if ! conda env list | awk '{print $1}' | grep -qx "$CONDA_ENV_NAME"; then
        log "创建 conda 环境 $CONDA_ENV_NAME (python=3.8) ..."
        conda create -y -n "$CONDA_ENV_NAME" python=3.8 \
            || die "conda 环境创建失败。若为网络问题,请先配置 conda 镜像源(见 INSTALL.md),或改用:bash install.sh --venv"
    else
        log "conda 环境 $CONDA_ENV_NAME 已存在,直接使用"
    fi
    # shellcheck disable=SC1091
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate "$CONDA_ENV_NAME"

    log "安装依赖(requirements-3.8.txt,deep-forest 使用 cp38 预编译 wheel)..."
    python -m pip install --upgrade pip
    python -m pip install -r requirements-3.8.txt \
        || die "依赖安装失败。网络慢可先配置 pip 镜像源(见 INSTALL.md)"

    verify_install
    log "完成!使用方式: conda activate $CONDA_ENV_NAME"
}

# -------------------------------------------------------------
# 方式 B 的子步骤:确保存在 Python 头文件(编译 C 扩展用)
# 结果:头文件在 sysconfig 的 include 目录中,或设置 EXTRA_CFLAGS
# -------------------------------------------------------------
EXTRA_CFLAGS=""
ensure_python_headers() {
    PYH_DIR=$(python -c "import sysconfig; print(sysconfig.get_paths()['include'])")
    [ -f "$PYH_DIR/Python.h" ] && return 0

    log "未找到 Python.h,尝试 apt 安装 python3-dev(可能需要输入 sudo 密码)..."
    if command -v apt-get >/dev/null 2>&1; then
        if $SUDO apt-get update -qq && $SUDO apt-get install -y -qq python3-dev; then
            [ -f "$PYH_DIR/Python.h" ] && { log "python3-dev 安装成功"; return 0; }
        fi
    fi

    log "apt 不可用,回退方案:从 GitHub 下载 CPython 源码生成头文件 ..."
    local full tmp
    full=$(python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
    tmp=$(mktemp -d)
    curl -fsSL "https://github.com/python/cpython/archive/refs/tags/v${full}.tar.gz" -o "$tmp/cpython.tar.gz" \
        || { rm -rf "$tmp"; die "CPython 源码下载失败,请检查网络(需能访问 github.com)"; }
    tar -xzf "$tmp/cpython.tar.gz" -C "$tmp"
    ( cd "$tmp/cpython-${full}" && ./configure --prefix=/tmp/cpython-hdrs -q >/dev/null 2>&1 && make pyconfig.h ) \
        || { rm -rf "$tmp"; die "CPython 头文件生成失败,请确认已安装 gcc/make"; }
    cp "$tmp/cpython-${full}/pyconfig.h" "$tmp/cpython-${full}/Include/"
    EXTRA_CFLAGS="-I$tmp/cpython-${full}/Include"
    log "使用 CPython 源码头文件: $EXTRA_CFLAGS"
}

# -------------------------------------------------------------
# 方式 B 的子步骤:从 LAMDA-NJU 官方源码编译安装 deep-forest 0.1.7
# (PyPI 的 deep-forest 只有 py3.7~3.9 的 wheel,新版 Python 只能源码编译;
#  注意 PyPI 上不带连字符的 "deepforest" 是另一个遥感 CV 包,不要装错)
# -------------------------------------------------------------
install_deep_forest_from_source() {
    # 已安装且可用则跳过(含功能自测,可发现装错包/未打补丁的情况)
    if python - <<'PYEOF' >/dev/null 2>&1
from deepforest import CascadeForestClassifier
from deepforest.tree import _tree
import numpy as np
m = CascadeForestClassifier(n_estimators=2)
m.fit(np.random.rand(8, 2), [0, 1] * 4)
PYEOF
    then
        log "deep-forest 已安装且可用,跳过编译"
        return 0
    fi

    ensure_python_headers

    # numpy.distutils 在 Python 3.11+ 会引用已删除的 distutils.msvccompiler,打兼容性补丁
    local npy
    npy=$(python -c "import numpy, os; print(os.path.dirname(numpy.__file__))")
    if grep -q "^from distutils.msvccompiler import get_build_version" "$npy/distutils/mingw32ccompiler.py" 2>/dev/null; then
        python - "$npy/distutils/mingw32ccompiler.py" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace(
    "from distutils.msvccompiler import get_build_version as get_build_msvc_version",
    "try:\n    from distutils.msvccompiler import get_build_version as get_build_msvc_version\n"
    "except ImportError:  # distutils.msvccompiler removed in Python 3.11\n"
    "    def get_build_msvc_version():\n        return 0",
)
open(p, "w").write(s)
PYEOF
        log "已为 numpy.distutils 打 Python 3.11 兼容补丁"
    fi

    local workdir
    workdir=$(mktemp -d)
    git clone -q --depth 1 --branch "$DEEP_FOREST_TAG" "$DEEP_FOREST_GIT" "$workdir/deep-forest" \
        || { rm -rf "$workdir"; die "Deep-Forest 源码下载失败(需能访问 github.com)"; }

    # 0.1.7 代码使用了 numpy>=1.24 已删除的别名,打兼容性补丁
    sed -i 's/dtype=np\.int\b/dtype=int/g'        "$workdir/deep-forest/deepforest/forest.py" "$workdir/deep-forest/deepforest/tree/tree.py"
    sed -i 's/dtype=np\.bool\b/dtype=np.bool_/g'  "$workdir/deep-forest/deepforest/_cutils.pyx"

    log "从源码编译 deep-forest 0.1.7(约 1~3 分钟)..."
    (
        cd "$workdir/deep-forest"
        export SETUPTOOLS_USE_DISTUTILS=stdlib   # numpy.distutils 与新版 setuptools 不兼容
        [ -n "$EXTRA_CFLAGS" ] && export CFLAGS="$EXTRA_CFLAGS${CFLAGS:+ $CFLAGS}"
        python -m pip install --no-build-isolation .
    ) || { rm -rf "$workdir"; die "deep-forest 编译失败,请把上方报错发出来排查(常见原因:缺 gcc)"; }

    rm -rf "$workdir"
    log "deep-forest 0.1.7 编译安装完成"
}

# -------------------------------------------------------------
# 方式 B:venv + Python 3.9~3.11
# -------------------------------------------------------------
install_venv() {
    local py ver
    py=$(command -v python3) || die "未找到 python3"
    ver=$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    case "$ver" in
        3.9|3.10|3.11) : ;;
        *) die "方式 B 需要 Python 3.9~3.11(当前 $ver)。推荐装 Python 3.11,或改用:bash install.sh --conda" ;;
    esac
    "$py" -m venv --help >/dev/null 2>&1 \
        || die "缺少 venv 模块,请先执行:sudo apt-get install -y python3-venv"

    if [ ! -d "$VENV_DIR" ]; then
        log "创建虚拟环境 $VENV_DIR ..."
        "$py" -m venv "$VENV_DIR"
    fi
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    log "安装依赖(requirements-3.11.txt,torch 从 PyPI 安装)..."
    python -m pip install --upgrade pip
    python -m pip install -r requirements-3.11.txt \
        || die "依赖安装失败。网络慢可先配置 pip 镜像源(见 INSTALL.md)"

    install_deep_forest_from_source
    verify_install
    log "完成!使用方式: source $VENV_DIR/bin/activate"
}

# -------------------------------------------------------------
case "$MODE" in
    conda) install_conda ;;
    venv)  install_venv  ;;
esac
