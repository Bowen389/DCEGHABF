import io
import math
import re
import struct
import zipfile
import zlib

TDX_PACKAGE_URL = "https://www.tdx.com.cn/products/data/data/g4day/{ymd}.zip"
# 盘后包从这一天起带北交所文件（2026-09-20 二分实测：20220505 无、20220506 有）
TDX_BJ_FIRST_DAY = "20220506"
# 每个市场有收盘价的最少行数。2026-09-20 实测 2021-08-16 ~ 2026-09-18 共 11 个包的最小值：
# 沪 16202、深 3641（2022 年以前深市大部分代码当日无价）、京 87（2022-05-06），下限取明显低于最小值的整数
TDX_MIN_PRICED = {"sh": 10000, "sz": 3000, "bj": 50}


def _tdx_parse_package(content, ymd, only_equities=False):
    """解析通达信每日增量包：每个市场一对 .cod（代码表，150 字节/条）+ .md1（行情块，512 字节/块）。
    布局参考 jing2uo/tdx2db（MIT）的 tdx/merge.go，已用 600519/000001/920000 与腾讯收盘价对拍。"""
    archive = zipfile.ZipFile(io.BytesIO(content))
    names = set(archive.namelist())
    rows = []
    for market in ("sh", "sz", "bj"):
        cod_name, md1_name = f"{market}{ymd[2:]}.cod", f"{market}{ymd[2:]}.md1"
        if (market == "bj" and ymd < TDX_BJ_FIRST_DAY
                and cod_name not in names and md1_name not in names):
            continue            # 这天之前的包还没有北交所文件；之后缺文件按格式改变报错
        if cod_name not in names or md1_name not in names:
            raise RuntimeError(f"通达信盘后包缺少 {cod_name}/{md1_name}，格式可能已变")
        cod, md1 = archive.read(cod_name), archive.read(md1_name)
        if len(cod) % 150 or len(md1) % 512:
            raise RuntimeError(f"{market} 代码表或行情块长度不是整块，文件可能被截断")
        if len(cod) // 150 != len(md1) // 512:
            raise RuntimeError(f"{market} 代码表 {len(cod) // 150} 条、行情块 {len(md1) // 512} 块，对不上")
        before, codes, seqs = len(rows), set(), set()
        for offset in range(0, len(cod), 150):
            record = cod[offset:offset + 150]
            # 11 个真实包（2021-08 ~ 2026-09）的代码全是 6 位 ASCII 数字；用 replace 解码会把坏字节变成 '\ufffd00000' 放行
            code = record[0:6].rstrip(b"\x00 ").decode("ascii", "replace")
            seq = struct.unpack("<H", record[32:34])[0]
            if not re.fullmatch(r"[0-9]{6}", code):
                raise RuntimeError(f"通达信盘后包 {market} 代码表出现非 6 位数字代码 {code!r}，格式可能已变")
            if code in codes or seq in seqs:
                raise RuntimeError(f"通达信盘后包 {market} 代码表有重复的代码 / 行情块序号（{code!r}, seq={seq}）")
            codes.add(code)
            seqs.add(seq)
            if only_equities and not ((market == 'sh' and (code.startswith(('60','68')) or code == '000001')) or (market == 'sz' and code.startswith(('00','30'))) or (market == 'bj' and code.startswith(('4','8','92')))):
                continue
            block = md1[seq * 512:(seq + 1) * 512]
            if len(block) != 512:
                raise RuntimeError(f"{market}{code} 行情块越界（seq={seq}）")
            prev_close = struct.unpack("<d", block[4:12])[0]
            open_, high, low, close = struct.unpack("<4d", block[12:44])
            amount = struct.unpack("<d", block[72:80])[0]
            # NaN 能绕过 close <= 0 被当成有价记录计入下限；11 个真实包里没有一个非有限值
            if not all(math.isfinite(v) for v in (prev_close, open_, high, low, close, amount)):
                raise RuntimeError(f"通达信盘后包 {market}{code} 行情块出现非有限数值，文件可能已损坏")
            if close <= 0:
                continue        # 880/881 等通达信自编板块指数当日无价，整块为 0，不是证券
            volume = struct.unpack("<Q", block[56:64])[0]
            raw_name = record[40:72].split(b"\x00")[0]
            try:                # replace 会把坏字节变成「�」当成正常名称返回（11 个真实包实测零替换字符）
                name = raw_name.decode("gbk").strip()
            except UnicodeDecodeError as exc:
                raise RuntimeError(f"通达信盘后包 {market}{code} 的名称不是 GBK，文件可能已损坏") from exc
            if not name:
                raise RuntimeError(f"通达信盘后包 {market}{code} 有价格却没有名称，文件可能已损坏")
            rows.append({"date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}", "market": market,
                         "code": code,
                         "name": name,
                         "prev_close": round(prev_close, 4), "open": round(open_, 4),
                         "high": round(high, 4), "low": round(low, 4),
                         "close": round(close, 4), "volume": volume,
                         "amount": round(amount, 2)})
        # 逐市场核对下限：只检查总行数会让沪深撑过门槛、北交所静默缺失
        if len(rows) - before < ({'sh':1500,'sz':2000,'bj':50}[market] if only_equities else TDX_MIN_PRICED[market]):
            raise RuntimeError(f"通达信盘后包 {market} 市场只有 {len(rows) - before} 条有价记录"
                               f"（实测下限 {TDX_MIN_PRICED[market]}），文件可能残缺或格式已变")
    return rows


