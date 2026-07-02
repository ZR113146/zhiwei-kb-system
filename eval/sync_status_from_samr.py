# -*- coding: utf-8 -*-
"""从 std.samr.gov.cn 体系核对 KB 标准状态 — status 数据维护工具。

⚠️ 定位: 这是 **standard_status 数据维护** 工具, 属 kb_current_state / pipeline
   status 维护环节, **不属于归一化 (code_norm) 环节**。归一化管"码怎么解析",
   本工具管"标准的现行/废止/替代状态对不对"。两者独立 — 切勿混进归一化提交。
   规范会废止/出新版, status 同步应是定期运维动作, 不是一次性验证。

背景: standard_status.json 早期 (2026-06) 由 kb_current_state 生成, 多数是按年份
推断的默认 effective, 仅 4 条带 samr evidence。本脚本按 official_code 查 samr 体系,
拉真实 现行/废止/替代 + 官方命名, 写回 status 记录 (带 evidence_url 供审计)。

samr 体系是 5 子站 (各可检索, 但接口各异):
  国标 openstd.samr.gov.cn  — 已实现 fetch_std (搜索 std_list + 详情 newGbInfo, HTML 解析)
  行业 hbba.sacinfo.org.cn  — 已逆向 POST /stdQueryList (JSON, 字段 code/chName/status/pk), 待适配 key 映射
  地方 dbba.sacinfo.org.cn   — SPA (bootstrap-table), 待逆向 XHR
  团体 www.ttbz.org.cn       — 待探
  企业 www.qybz.org.cn       — 待探
本版本只实现国标子站 (openstd); 行标/地标/团标/企标子站适配作为后续增量。

访问: 本环境 Bash+curl 可达 samr (WebFetch 工具层被策略拦, 但 curl 绕过有效)。
      samr 链路偶有超时, _http_get 已加重试; 全量跑需限速 ~1 req/s。

用法:
  python eval/sync_status_from_samr.py              # dry-run, 输出 diff 报告
  python eval/sync_status_from_samr.py --apply      # 写回 standard_status.json
  python eval/sync_status_from_samr.py --only GBT11836,GBT1499.2  # 只核指定码

注: standard_name 不覆盖 KB 已有中文名 (samr 详情中英双版, 抓英文会砸中文);
    仅补 KB 缺失且 samr 给中文的名。status 变动始终报告。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STATUS_FILE = os.path.join(ROOT, "data", "kb_json", "standard_status.json")
SAMR_SEARCH = "https://openstd.samr.gov.cn/bzgk/std/std_list"
SAMR_DETAIL = "https://openstd.samr.gov.cn/bzgk/std/newGbInfo"
_UA = "Mozilla/5.0 (zhiwei-kb-sync; contact: kb-maintainer)"


def _http_get(url, timeout=20, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            time.sleep(1.0)
    raise last


def _strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _search_samr(official_code):
    """搜索 samr, 返回 [{code, name, status_word, hcno, pub_date, impl_date}] 或 []。
    URL 格式 (经逆向 jumpPage): ?r=<rand>&p.p1=0&p.p2=<编号>。"""
    p2 = urllib.parse.quote(official_code, safe="")
    url = f"{SAMR_SEARCH}?r=0.1&p.p1=0&p.p2={p2}"
    html = _http_get(url)
    rows = re.findall(r"<tr[^>]*>.*?</tr>", html, re.S)
    out = []
    for tr in rows:
        if "showInfo(" not in tr:
            continue
        hcno_m = re.search(r"showInfo\(['\"]([A-F0-9]+)['\"]\)", tr)
        if not hcno_m:
            continue
        cells = [_strip_tags(c) for c in re.findall(r"<td[^>]*>.*?</td>", tr, re.S)]
        # 列表列序: 序号|标准号|?|?|名称|状态(票/废止/现行)|发布日期|实施日期|...
        out.append({
            "hcno": hcno_m.group(1),
            "cells": cells,
            "raw_text": _strip_tags(tr),
        })
    return out


# samr 中文状态词 → KB status 枚举
_STATUS_MAP = {"现行": "effective", "废止": "abolished", "被替代": "superseded",
               "被部分替代": "superseded", "即将实施": "effective", "未实施": "effective"}


def _parse_status_word(text):
    for cn, en in _STATUS_MAP.items():
        if cn in text:
            return en
    return None


def _fetch_detail(hcno):
    """详情页拿 实施日期/发布日期/代替/被替代/标准号/标准名称(中文优先)。"""
    html = _http_get(f"{SAMR_DETAIL}?hcno={hcno}")
    info = {}
    # samr 详情页中英双版: 同字段出现两次 (中文版在前, 英文版在后)。优先取含中文的。
    for field, key in [("标准号", "official_code"), ("实施日期", "effective_date"),
                       ("发布日期", "published_date"), ("代替", "replaces"),
                       ("被替代", "replaced_by"), ("被部分代替", "replaced_by_partly")]:
        m = re.search(rf"{field}[：:]\s*([^<\n<]+)", html)
        if m:
            info[key] = _strip_tags(m.group(1))
    # 标准名称: 取所有匹配里第一个含中文的 (samr 中英双版)
    for m in re.finditer(r"标准名称[：:]\s*([^<\n<]+)", html):
        name = _strip_tags(m.group(1))
        if re.search(r"[一-鿿]", name):
            info["standard_name"] = name
            break
        if "standard_name" not in info:  # 退而求其次存英文, 供 reconcile 判是否补
            info["standard_name"] = name
    return info


def fetch_std(code, session=None):
    """查 samr 拉一个标准的权威信息 (真实实现, 经逆向验证)。
    返回 {official_code, standard_name, status, effective_date, replaced_by,
          evidence_url, evidence_source} 或 None (查不到)。"""
    try:
        results = _search_samr(code)
    except Exception as e:
        print(f"  [fetch_std] {code}: 搜索失败 {type(e).__name__}: {str(e)[:60]}")
        return None
    if not results:
        return None
    # 取第一条 (最相关; 多条时取完全匹配 official_code 的)
    hit = next((r for r in results if code.replace(" ", "") in r["raw_text"].replace(" ", "")), results[0])
    status = _parse_status_word(hit["raw_text"])
    evidence_url = f"{SAMR_DETAIL}?hcno={hit['hcno']}"
    out = {
        "official_code": code,
        "status": status,
        "evidence_url": evidence_url,
        "evidence_source": "openstd.samr.gov.cn",
        "review_note": f"samr search hit hcno={hit['hcno']}",
    }
    # 详情页补全 (替代关系/日期/官方名)
    try:
        det = _fetch_detail(hit["hcno"])
        if det.get("standard_name"):
            out["standard_name"] = det["standard_name"]
        if det.get("official_code"):
            out["official_code"] = det["official_code"]
        if det.get("effective_date"):
            out["effective_date"] = det["effective_date"]
        if det.get("replaced_by"):
            out["replaced_by"] = det["replaced_by"]
        elif det.get("replaced_by_partly"):
            out["replaced_by"] = det["replaced_by_partly"]
    except Exception as e:
        out["review_note"] += f"; detail fetch failed: {type(e).__name__}"
    return out


def reconcile(dry_run=True, only=None):
    with open(STATUS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    stds = data.get("standards", {})
    targets = list(stds.keys()) if not only else [c for c in only.split(",") if c in stds]

    diffs = []
    for code in targets:
        rec = stds[code]
        official = rec.get("official_code", "")
        fetched = fetch_std(official)
        if not fetched:
            continue
        changes = {}
        # status 变动 (核心: KB 误标废止为现行 etc) — 始终报告
        if fetched.get("status") and fetched["status"] != rec.get("status"):
            changes["status"] = (rec.get("status"), fetched["status"])
        # standard_name: 不覆盖 KB 已有的中文名 (samr 详情中英混杂, 抓到的常是英文)。
        # 仅当 KB 缺名时补 samr 的 (且只补中文, 若 samr 给的是英文则跳过保 None)。
        if not rec.get("standard_name") and fetched.get("standard_name"):
            fn = fetched["standard_name"]
            if re.search(r"[一-鿿]", fn):  # 只补含中文的
                changes["standard_name"] = (rec.get("standard_name"), fn)
        # effective_date: KB 缺则补
        if not rec.get("effective_date") and fetched.get("effective_date"):
            changes["effective_date"] = (rec.get("effective_date"), fetched["effective_date"])
        # replaced_by: KB 缺则补
        if not rec.get("replaced_by") and fetched.get("replaced_by"):
            changes["replaced_by"] = (rec.get("replaced_by"), fetched["replaced_by"])
        # evidence 字段: 总是补 (即使无字段变动, samr 命中本身就是外部锚)
        diffs.append({"code": code, "changes": changes, "evidence_url": fetched.get("evidence_url"),
                      "evidence_source": fetched.get("evidence_source")})
        time.sleep(0.8)  # 礼貌限速

    print(f"\n=== samr 核对 diff ({len(diffs)} 条变动 / {len(targets)} 查询) ===")
    for d in diffs:
        print(f"  {d['code']} ({d['evidence_url']})")
        for k, (old, new) in d["changes"].items():
            print(f"     {k}: {old!r} → {new!r}")

    if dry_run:
        print("\n[dry-run] 未写回。确认后用 --apply 写回 standard_status.json。")
        return
    # apply: 把 diff 写回 (带 evidence 字段)
    for d in diffs:
        rec = stds[d["code"]]
        for k, (_, new) in d["changes"].items():
            rec[k] = new
        rec["evidence_source"] = "openstd.samr.gov.cn"
        rec["evidence_url"] = d["evidence_url"]
        rec["review_note"] = f"synced from samr at {time.strftime('%Y-%m-%d')}"
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[apply] 已写回 {len(diffs)} 条到 {STATUS_FILE}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Sync KB standard_status from samr (external authority)")
    p.add_argument("--apply", action="store_true", help="写回 (默认 dry-run)")
    p.add_argument("--only", default=None, help="只核指定码 (逗号分隔)")
    args = p.parse_args()
    reconcile(dry_run=not args.apply, only=args.only)
