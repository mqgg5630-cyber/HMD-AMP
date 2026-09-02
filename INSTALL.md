# HMD-AMP 安装指南(Linux / WSL)

本仓库提供一键安装脚本 `install.sh`(已在 Linux 环境实测通过):

```bash
bash install.sh
```

脚本自动选择两种方式之一:

| | 方式 A(推荐) | 方式 B |
|---|---|---|
| 触发条件 | 系统装有 conda | 无 conda,自动回退 |
| 强制指定 | `bash install.sh --conda` | `bash install.sh --venv` |
| Python | 3.8(conda 新建环境) | 系统 Python 3.9~3.11(venv) |
| deep-forest | PyPI cp38 预编译 wheel,免编译 | 从 LAMDA-NJU 官方源码编译(脚本自动处理) |
| 依赖清单 | `requirements-3.8.txt`(与论文 README 版本一致) | `requirements-3.11.txt` |

装完后:

```bash
# 方式 A
conda activate HMD-AMP
# 方式 B
source .venv/bin/activate

# 然后按 README:下载模型权重(Google Drive 链接)、
# 在 prediction.py 中填入模型路径和 FASTA 文件路径,再运行:
python prediction.py
```

## 方式 A 细节(conda,适合 WSL)

脚本等价于:

```bash
conda create -n HMD-AMP python=3.8 -y
conda activate HMD-AMP
pip install -r requirements-3.8.txt   # torch 2.4.1 / numpy 1.19.5 / pandas 1.2.0 / deep-forest 0.1.7 ...
```

如果 conda 下载很慢(国内网络),先配置镜像源,例如清华源:

```bash
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/
conda config --set show_channel_urls yes
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

(配完镜像后删除 `~/.condarc` 中对应行 / `pip config unset global.index-url` 即可还原)

## 方式 B 细节(venv,无 conda 的环境)

前置要求:Python 3.9~3.11(推荐 3.11)、`gcc`/`make`。

- Ubuntu/WSL 缺编译工具时:`sudo apt-get install -y build-essential`
- 缺 `python3-venv` 时:`sudo apt-get install -y python3-venv`
- 缺 Python 头文件时脚本会自动 `apt install python3-dev`;
  apt 不可用时自动回退为从 GitHub 下载 CPython 源码生成头文件(需网络能访问 github.com)
- 方式 B 中 numpy/pandas 用 1.26.4 / 1.5.3(README 里的 1.19.5 / 1.2.0 没有 3.9+ 的包),功能等效

## 常见问题

**Q: 为什么 deep-forest 要特殊处理?**
本项目用的是 LAMDA-NJU 的 GBDT 级联森林(`CascadeForestClassifier`)。
PyPI 上名为 `deep-forest`(带连字符)的包只有 Python 3.7~3.9 的 wheel,
所以 Python 3.10+ 必须源码编译 —— 方式 B 的脚本已自动完成全部编译与兼容补丁
(0.1.7 代码中 `np.int`/`np.bool` 别名在 numpy≥1.24 已移除,`numpy.distutils`
与新版 setuptools 不兼容等问题脚本内均已处理)。
**注意:PyPI 上不带连字符的 `deepforest` 是另一个遥感 CV 包,千万不要装错。**

**Q: torch 为什么直接从 PyPI 装?**
很多网络环境无法访问 `download.pytorch.org`。PyPI 上的 torch wheel 自带 CUDA
运行时,无 GPU 的 CPU 机器可以直接用;WSL2 + NVIDIA 显卡(装好 Windows 侧
NVIDIA 驱动)则可直接用 GPU。

**Q: 没有 GPU 能跑吗?**
本项目的 `src/utils.py` 中写死了 `.cuda()` / `DataParallel`,
**实际推理(运行 ESM-2 模型)需要 GPU**。环境安装、导入、级联森林部分在 CPU 上均可验证通过。

**Q: 首次运行会下载什么?**
首次调用 ESM-2 模型会自动下载 ~2.5GB 的 esm2_t33_650M_UR50D 预训练权重(来自 GitHub),
请预留空间和耐心等待。
