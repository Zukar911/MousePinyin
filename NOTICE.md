# NOTICE —— 数据来源与许可声明

本项目的候选词库（`data/index.db` 及 `data/*.json`）由以下公开数据集构建
（构建脚本见 `tools/`），分发时必须保留本声明：

| 数据 | 来源 | 许可证 | 在本项目中的用途 |
|---|---|---|---|
| 汉字→拼音映射 | mozillazg/pinyin-data `pinyin.txt` | MIT | 音节全集、声母→韵母映射 |
| 汉字频率 | rsennrich/wordfreq（SUBTLEX-CH 数据） | 代码 MIT；**数据 CC BY-SA 4.0** | 候选字排序、韵母权重 |
| 词与联想 | jieba `dict.txt` | MIT | bigram 联想（assoc 表） |

## CC BY-SA 4.0 边界

`index.db` / `candidates.json` / `final_weights.json` 中的频率排序信息
**派生自 wordfreq 的 CC BY-SA 4.0 数据**，属于演绎数据：

- 以本仓库（含词库）形式**公开分发**时，词库部分需按
  **CC BY-SA 4.0** 提供并注明上述来源；
- 仅个人使用/不分发，无额外义务；
- 程序代码（不含词库数据）按仓库根 LICENSE（MIT）许可。

原始语料文件（`data/raw/`）不入库；重建词库请按 `tools/` 脚本头部注释
自行下载对应数据集。
