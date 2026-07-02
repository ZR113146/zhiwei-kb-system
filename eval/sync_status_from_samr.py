# -*- coding: utf-8 -*-
"""从 std.samr.gov.cn (openstd.samr.gov.cn) 全量核对 KB 标准状态 — 外部权威锚定。

背景: standard_status.json 里 121 条只有 4 条带 samr evidence, 其余 117 条是
"规则生成的默认值" (多半按年份推断 effective), 未逐条核对国家权威源。本脚本对
KB 每个标准按 official_code 查 samr, 拉真实 现行/废止/替代 + 官方命名, 写回
status 记录 (带 evidence_url/evidence_source/review_note)。

⚠️ 本环境 fetch 不了 samr (网络策略拦), 故本脚本须在能访问 std.samr.gov.cn 的
环境跑。本脚本设计为: dry-run 默认 (只输出 diff, 不写文件); --apply 才写回;
每条改动都带 evidence_url 供审计; 失败/超时记录不中断。

用法 (在能访问 samr 的环境):
  python eval/sync_status_from_samr.py              # dry-run, 输出 diff 报告
  python eval/sync_status_from_samr.py --apply      # 写回 standard_status.json
  python eval/sync_status_from_samr.py --only GB50204,GBT50720  # 只核指定码

samr 查询 URL 模板 (来自现有 evidence_url 字段):
  https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=<HASH>   (国标详情, 需 hcno)
  https://openstd.samr.gov.cn/bzgk/std/std_list?p.p1=0&p.p2=<CODE>  (搜索列表)
  注意: samr 页面是动态渲染 (JS), 简单 HTTP GET 拿不到结构化结果, 可能需
  selenium/playwright 或逆向其 XHR API。本脚本预留 fetch_std(code) 钩子,
  实际抓取逻辑需在能访问 samr 的环境据其真实响应实现 (见 TODO)。
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STATUS_FILE = os.path.join(ROOT, "data", "kb_json", "standard_status.json")


def fetch_std(code, session=None):
    """查 samr 拉一个标准的权威信息。
    返回 {official_code, standard_name, status, abolished_date, replaced_by,
          evidence_url, raw} 或 None (查不到/失败)。

    TODO (在能访问 samr 的环境实现):
      1. 用 samr 搜索接口 std_list?p.p2=<official_code> 拿结果行
      2. 解析状态 (现行/废止/被替代) — samr 用中文状态词
      3. 若废止, 拉替代标准码
      4. 记录 evidence_url 供审计
    本环境无外网, 此处返回 None 并打印提示, 不假装抓到。"""
    # 占位: 实际实现需 samr 访问。这里返回 None 让 dry-run 报"未核对"。
    print(f"  [fetch_std] {code}: 本环境无 samr 访问, 跳过 (占位实现)")
    return None


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
        # 对比: status / official_code / name / replaced_by
        changes = {}
        if fetched.get("status") and fetched["status"] != rec.get("status"):
            changes["status"] = (rec.get("status"), fetched["status"])
        if fetched.get("official_code") and fetched["official_code"] != official:
            changes["official_code"] = (official, fetched["official_code"])
        if fetched.get("standard_name") and fetched["standard_name"] != rec.get("standard_name"):
            changes["standard_name"] = (rec.get("standard_name"), fetched["standard_name"])
        if changes:
            diffs.append({"code": code, "changes": changes, "evidence_url": fetched.get("evidence_url")})
        time.sleep(0.5)  # 礼貌限速, 别给 samr 压力

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
