#!/usr/bin/env python3
"""给 Source Han Sans CN 补上游戏使用、但字体本身缺失的符号字形。

背景：汉化版通过 applier.py 把 "Source Han Sans CN" 插到每个 CSS 字体族列表的最前面，
于是所有字符都优先用思源黑体渲染；思源黑体缺字的码位不再回退到系统字体，而是直接画
.notdef（空心方框带叉）。修复办法是把这些码位的字形直接并进字体本体。

思源黑体的 OTF 是 CID-keyed CFF 字体（带 ROS/FDArray/FDSelect），本脚本按 CID 规则
追加字形：新字形命名为 cidNNNNN，挂在拉丁字母所在的 FontDict 上，并同步更新
charset / FDSelect / hmtx / cmap / maxp。

用法（需 fonttools）：
    uv run --with fonttools python patch_font.py            # 就地打补丁（自动备份 .bak）
    uv run --with fonttools python patch_font.py --check    # 只检查，不写入
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from fontTools.misc.transform import Transform
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "Source Han"
DONOR_DIR = HERE / "symbols"

# 字形来源（全部为可再分发的自由字体）：
#   symbols  = Noto Sans Symbols     (OFL-1.1)
#   symbols2 = Noto Sans Symbols 2   (OFL-1.1)
#   emoji    = Noto Emoji            (OFL-1.1)
#   dejavu   = DejaVu Sans           (Bitstream Vera / Arev，游戏本体已内置)
DONORS = {
    "symbols": {"regular": "NotoSansSymbols-Regular.ttf"},
    "symbols2": {"regular": "NotoSansSymbols2-Regular.ttf"},
    "emoji": {"regular": "NotoEmoji[wght].ttf"},
    "dejavu": {"regular": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf"},
}

# 码位 -> (来源, 注释)
SYMBOLS = [
    (0x26E4, "symbols", "五角星（精华符号 UtilText.getPentagramSymbol）"),
    (0x26E7, "symbols", "倒五角星（附魔容量 getEnchantmentCapacitySymbol*）"),
    (0x267E, "symbols", "循环符（getInfinitySymbol 注释里的备选）"),
    (0x26CA, "symbols2", "盾牌（UtilText.getShieldSymbol）"),
    (0x1F3B2, "emoji", "骰子（CompanionManagement 随机名字按钮）"),
    (0x1F4F7, "symbols2", "相机（RenderingEngine 截图提示）"),
    (0x207A, "dejavu", "上标加号（CharacterModificationUtils）"),
] + [
    (cp, "symbols2", f"骰子面 {cp - 0x2680 + 1}（DiceFace）")
    for cp in range(0x2680, 0x2686)
]

PROBES = (0x41, 0x30, 0x2E)  # 用拉丁字母/数字/句点所在 FontDict 取私有字典
TARGET_UPEM = 1000


def donor_for(kind: str, weight: str) -> Path:
    entry = DONORS[kind]
    name = entry.get(weight) or entry["regular"]
    # DejaVu 是游戏本体自带的字体，优先用子模块里的那份，避免重复提交 1.4MB
    fallbacks = [
        DONOR_DIR / name,
        HERE.parent.parent / "liliths-throne-chinese" / "res" / "fonts" / "DejaVu Sans" / name,
    ]
    for path in fallbacks:
        if path.exists():
            return path
    raise SystemExit(f"缺少字形来源字体：{fallbacks[0]}")


def make_charstring(donor_path: Path, cp: int, upem: int, private, global_subrs):
    """从提供方字体取出字形，返回 (charstring, 宽度, 左边界)。"""
    donor = TTFont(donor_path, lazy=True)
    cmap = donor.getBestCmap()
    if cp not in cmap:
        raise SystemExit(f"{donor_path.name} 不含 U+{cp:04X}")
    glyph_name = cmap[cp]
    glyph_set = donor.getGlyphSet()
    scale = upem / donor["head"].unitsPerEm
    advance = donor["hmtx"][glyph_name][0] * scale

    # Type2 charstring 的首个操作数要与 private.nominalWidthX 相加才是实际宽度
    nominal = getattr(private, "nominalWidthX", 0) or 0
    pen = T2CharStringPen(round(advance) - nominal, glyph_set)
    glyph_set[glyph_name].draw(TransformPen(pen, Transform(scale, 0, 0, scale, 0, 0)))
    charstring = pen.getCharString(private=private, globalSubrs=global_subrs)

    bounds_pen = BoundsPen(glyph_set)
    glyph_set[glyph_name].draw(
        TransformPen(bounds_pen, Transform(scale, 0, 0, scale, 0, 0))
    )
    lsb = int(round(bounds_pen.bounds[0])) if bounds_pen.bounds else 0
    donor.close()
    return charstring, round(advance), lsb


def patch(path: Path, weight: str, check_only: bool) -> int:
    font = TTFont(path)
    cff = font["CFF "].cff
    top_dict = cff[cff.fontNames[0]]
    charstrings = top_dict.CharStrings
    cmaps = [t for t in font["cmap"].tables if t.isUnicode()]
    primary = cmaps[0].cmap
    upem = font["head"].unitsPerEm
    is_cid = hasattr(top_dict, "ROS")
    vmtx = font.get("vmtx")
    vhea = font.get("vhea")
    vorg = font.get("VORG")
    probe_glyph = None
    for probe in PROBES:
        if probe in primary:
            probe_glyph = primary[probe]
            break
    if probe_glyph is None:
        raise SystemExit("找不到可用的拉丁字形作为度量参照")

    if is_cid:
        charset = top_dict.charset
        fd_select = top_dict.FDSelect
        fd_array = top_dict.FDArray
        # CID 空间几乎用满（最大 65528），不能往 65535 以上加；改为占用未使用的
        # 空号段。charset 的顺序即 GID 顺序，所以只要每个连续段内部递增，
        # 尾部追加非单调的号段依然是合法编码（format 1/2 按段重建 GID→CID）。
        used_cids = {int(name[3:]) for name in charset[1:]}
        free_cids = []
        cursor = max(used_cids)
        while len(free_cids) < len(SYMBOLS):
            if cursor not in used_cids:
                free_cids.append(cursor)
            cursor -= 1
            if cursor <= 0:
                raise SystemExit("没有足够的空闲 CID 可用")
        free_cids.sort()
        cid_pool = iter(free_cids)
        fd_index = 0
        for probe in PROBES:
            if probe in primary:
                fd_index = fd_select[font.getGlyphID(primary[probe])]
                break
        private = fd_array[fd_index].Private
        global_subrs = cff.GlobalSubrs
    else:
        cid_pool = None
        fd_index = None
        private = top_dict.Private
        global_subrs = cff.GlobalSubrs

    added, present = [], []
    for cp, kind, note in SYMBOLS:
        if any(cp in t.cmap for t in cmaps):
            present.append(cp)
            continue
        if check_only:
            added.append(cp)
            continue

        if is_cid:
            name = f"cid{next(cid_pool):05d}"
        else:
            name = f"uni{cp:04X}"

        charstring, advance, lsb = make_charstring(
            donor_for(kind, weight), cp, upem, private, global_subrs
        )
        index = len(charstrings.charStringsIndex)
        charstrings.charStringsIndex.append(charstring)
        charstrings.charStrings[name] = index
        top_dict.charset.append(name)
        if is_cid:
            charstring.fdSelectIndex = fd_index
            fd_select.append(fd_index)
        font["hmtx"].metrics[name] = (advance, lsb)
        if vmtx is not None:
            vmtx.metrics[name] = vmtx.metrics[probe_glyph]
        if vorg is not None:
            vorg.VOriginRecords[name] = vorg.VOriginRecords.get(
                probe_glyph, vorg.defaultVertOriginY
            )
        for table in cmaps:
            # format 4 的 cmap 只能装 BMP 码位，星平面字符只写 format 12
            if cp > 0xFFFF and table.format not in (12, 13):
                continue
            table.cmap[cp] = name
        order = font.getGlyphOrder()
        # CFF 字体的 getGlyphOrder() 就是 charset 这个列表本身，已经 append 过，别再追加一次
        if name not in order:
            order.append(name)
            font.setGlyphOrder(order)
        font["maxp"].numGlyphs = len(order)
        added.append(cp)

    if added and not check_only:
        order = font.getGlyphOrder()
        font["maxp"].numGlyphs = len(order)
        font["hhea"].numberOfHMetrics = len(order)
        if vhea is not None:
            vhea.numberOfVMetrics = len(order)

    print(f"{path.name}: 已有 {len(present)} 个，{'待补' if check_only else '已补'} {len(added)} 个")
    for cp, kind, note in SYMBOLS:
        print(f"   [{'有' if cp in present else '缺'}] U+{cp:04X} {note}")
    if check_only or not added:
        font.close()
        return len(added)

    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    font.save(path)
    font.close()
    print(f"   已写入 {path}（备份 {backup.name}）")
    return len(added)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(FONT_DIR), help="思源黑体所在目录")
    parser.add_argument("--check", action="store_true", help="只检查缺字，不修改字体")
    args = parser.parse_args()

    total = 0
    for name, weight in (
        ("SourceHanSansCN-Regular.otf", "regular"),
        ("SourceHanSansCN-Bold.otf", "bold"),
    ):
        path = Path(args.dir) / name
        if not path.exists():
            raise SystemExit(f"找不到字体：{path}")
        total += patch(path, weight, args.check)
    print(f"\n共 {'待补' if args.check else '已补'} {total} 个字形")
    sys.exit(0)


if __name__ == "__main__":
    main()
