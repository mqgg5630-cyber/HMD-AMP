#!/usr/bin/env bash
# =============================================================
# HMD-AMP 环境自检脚本
#   用法: conda activate HMD-AMP && bash verify_env.sh
# 逐项检查依赖是否装好,缺什么一目了然,不会中途退出。
# =============================================================
cd "$(dirname "$0")"

echo "=============================================="
echo " HMD-AMP 环境自检"
echo "=============================================="
echo "python : $(command -v python)"
python -V
echo

python - <<'PYEOF'
import importlib, sys

REQUIRED = [
    ("torch",       "torch"),
    ("torchvision", "torchvision"),
    ("torchaudio",  "torchaudio"),
    ("numpy",       "numpy"),
    ("pandas",      "pandas"),
    ("scikit-learn","sklearn"),
    ("biopython",   "Bio"),
    ("fair-esm",    "esm"),
    ("deep-forest", "deepforest"),
]

ok, missing = [], []
print("--- 依赖包 ---")
for name, mod in REQUIRED:
    try:
        m = importlib.import_module(mod)
        ver = getattr(m, "__version__", "?")
        print("  [OK]   %-14s %s" % (name, ver))
        ok.append(name)
    except Exception as e:
        print("  [缺失] %-14s %s" % (name, type(e).__name__ + ": " + str(e)[:70]))
        missing.append(name)

print()
print("--- deep-forest 功能自测 ---")
df_ok = False
try:
    import numpy as np
    from deepforest import CascadeForestClassifier
    rng = np.random.RandomState(0)
    X = rng.rand(50, 4); y = (X[:, 0] > 0.5).astype(int)
    m = CascadeForestClassifier(n_estimators=5, verbose=0)
    m.fit(X, y)
    assert m.predict(X).shape == (50,)
    assert m.predict_proba(X).shape == (50, 2)
    print("  [OK]   fit / predict / predict_proba 正常")
    df_ok = True
except Exception as e:
    print("  [失败] %s: %s" % (type(e).__name__, str(e)[:120]))

print()
print("--- 项目 src 模块 ---")
src_ok = True
for mod in ("src.Net", "src.loss", "src.utils"):
    try:
        importlib.import_module(mod)
        print("  [OK]   %s" % mod)
    except Exception as e:
        print("  [失败] %s -> %s: %s" % (mod, type(e).__name__, str(e)[:100]))
        src_ok = False

print()
print("--- 硬件 ---")
try:
    import torch
    if torch.cuda.is_available():
        print("  GPU 可用: %s (CUDA %s)" % (torch.cuda.get_device_name(0), torch.version.cuda))
    else:
        print("  未检测到可用 GPU —— 依赖已装好,但 prediction.py 中的 .cuda() 需要显卡才能运行推理")
except Exception as e:
    print("  torch 不可用: %s" % e)

print()
print("==============================================")
if not missing and df_ok and src_ok:
    print(" 结论: 环境安装成功,全部检查通过 ✅")
    sys.exit(0)
else:
    if missing:
        print(" 结论: 仍缺少这些包 ❌ -> %s" % ", ".join(missing))
    else:
        print(" 结论: 包都在,但有功能检查未通过 ❌")
    sys.exit(1)
PYEOF
