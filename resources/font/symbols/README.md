# 符号字形来源（补字脚本用的字形捐献字体）

这些字体只用于给思源黑体补上游戏用到、但思源黑体本身缺失的符号字形，
补字脚本是上一级的 `../patch_font.py`。

| 文件 | 用途 | 授权 | 来源 |
| --- | --- | --- | --- |
| `NotoSansSymbols-Regular.ttf` | ⛤ U+26E4 / ⛧ U+26E7 五角星、♾ U+267E | OFL-1.1 | https://github.com/googlefonts/noto-fonts (`hinted/ttf/NotoSansSymbols/`) |
| `NotoSansSymbols2-Regular.ttf` | ⚀–⚅ U+2680–U+2685 骰子面、⛊ U+26CA、📷 U+1F4F7 | OFL-1.1 | https://github.com/googlefonts/noto-fonts (`hinted/ttf/NotoSansSymbols2/`) |
| `NotoEmoji[wght].ttf` | 🎲 U+1F3B2（单色） | OFL-1.1 | https://github.com/google/fonts (`ofl/notoemoji/`) |
| `OFL.txt` | 上面三款字体的授权原文 | OFL-1.1 | — |
| DejaVu Sans（未在此目录） | ⁺ U+207A | Bitstream Vera / Arev | 直接取用子模块里游戏自带的 `liliths-throne-chinese/res/fonts/DejaVu Sans/`，不重复提交 |

SHA256（下载校验用）：

```
8f02f31959bbdf6061547a188248e13f84dc5fdd940326ec494675f453f072bb  NotoSansSymbols-Regular.ttf
630846d528dbe4c4981370a4d0a9475a1fd1491a129bb411f8e157cd5bde13c6  NotoSansSymbols2-Regular.ttf
de6c18832938afc99caf132b39d6a30a19bac7f2e812e28db2535b4608d27551  NotoEmoji[wght].ttf
```

## 为什么需要补字

`applier.py` 的 `modify_css()` 会把 `"Source Han Sans CN"` 插到每个 CSS 字体族列表的
**最前面**，因此全部字符都优先用思源黑体渲染；思源黑体缺字的码位不会回退到系统字体，
而是直接画 `.notdef`（空心方框带叉）。把这些字形并进字体本体是最省事、也最彻底的修法：
一次解决 13 个码位，而且不用改任何游戏代码。

## 什么时候需要重新跑补字脚本

`Source Han/` 里的两个 OTF **已经打好补丁**（31036 → 31049 字形），正常跑管线不需要任何额外
步骤。只有在替换了思源黑体文件（比如上游更新字体版本）之后才需要重跑：

```bash
cd resources/font
uv run --with fonttools python patch_font.py --check   # 只看缺什么，不写入
uv run --with fonttools python patch_font.py           # 补字（自动留 .bak）
```

补字是幂等的：已经存在的码位会跳过。首次写入前会把原文件复制成 `*.otf.bak`
（已在 `.gitignore` 里，不入库）。

如果要在库内直接看效果，把 `Source Han/` 整个目录拷到子模块的
`liliths-throne-chinese/res/fonts/` 下（等价于 `applier.py` 的 `add_files()`）。
