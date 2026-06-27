"""浮动标签训练器 v3 — AI 生成工程行业真实搜索查询, 覆盖全部标准
每标准2-3条真实查询, 200+轮并行搜索, 收敛停止
"""
import os, sys, subprocess, json, re, time, random

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.dirname(os.path.dirname(SCRIPTS_DIR))

QUERIES = [
    # ── 地基基础 ──
    "地基承载力 深宽修正 特征值", "桩基 静载 试验 极限承载力", "基坑 支护 锚杆 止水帷幕",
    "回填土 压实系数 环刀法", "复合地基 置换率 桩土应力比", "地下连续墙 泥浆护壁 槽段接头",
    # ── 主体结构 ──
    "混凝土 强度 等级 养护 同条件试块", "钢筋 接头 百分率 同一连接区段", "模板 支架 立杆 间距 扫地杆",
    "预应力 张拉 锚固 孔道 灌浆", "砌体 砂浆 饱满度 灰缝 构造柱", "钢结构 焊缝 探伤 超声波 检测比例",
    "钢梁 高强螺栓 扭矩 终拧", "型钢 混凝土 组合结构 栓钉", "预制构件 吊装 灌浆 套筒连接",
    "大体积混凝土 温控 裂缝", "混凝土 抗渗 等级 P6 防水剂", "钢筋 保护层 厚度 检测 扫描",
    # ── 建筑装饰 ──
    "石材 幕墙 干挂 龙骨 连接件", "玻璃 幕墙 立柱 横梁 预埋件", "抹灰 基层 甩浆 分层 养护",
    "涂饰 腻子 打磨 底漆", "吊顶 龙骨 吊杆 间距 反支撑", "楼地面 找平 层 平整度 偏差",
    # ── 屋面防水 ──
    "屋面 防水 卷材 搭接 宽度 收头", "地下室 防水 后浇带 止水带 遇水膨胀", "种植 屋面 耐根穿刺 排水板",
    "涂膜 防水 厚度 检测 割取法", "瓦屋面 挂瓦 顺水条 挂瓦条",
    # ── 机电安装 ──
    "电缆 桥架 支架 接地 跨接", "配电箱 回路 标识 绝缘电阻", "风管 法兰 垫片 严密性 漏光 检测",
    "水管 保温 橡塑 厚度 密度", "消防 喷淋 间距 溅水盘", "防雷 引下线 间距 焊接 防腐",
    # ── 给水排水 ──
    "给水 管道 水压 试验 验收", "室外 排水 管道 闭水 试验", "化粪池 容积 停留 时间",
    "消防 水泵 结合器 安装", "检查井 砌筑 流槽 盖板",
    # ── 暖通消防 ──
    "防排烟 风机 联动 控制", "空调 风管 保温 严密性", "灭火器 配置 危险 等级 保护 距离",
    "消防 水池 有效 容积 补水", "采暖 管道 补偿器 固定 支架",
    # ── 市政路桥 ──
    "路基 压实度 弯沉 检测", "路面 基层 配合比 无侧限抗压", "桥梁 灌注桩 清孔 沉渣 厚度",
    "箱梁 预应力 张拉 伸长值", "管沟 回填 压实 分层", "隧道 开挖 支护 收敛 监测",
    # ── 园林绿化 ──
    "种植穴 深 径 换土 基肥", "苗木 规格 分枝点 高度 冠幅", "草坪 播种量 成坪 修剪 高度",
    "大树 移植 断根 土球 规格", "园路 垫层 结合层 面层 防滑",
    # ── 轨道交通 ──
    "盾构 推进 速度 注浆 同步", "轨道 精调 轨距 水平 高低", "车站 基坑 监测 频率 报警 值",
    # ── 安全防护 ──
    "脚手架 连墙件 竖向 间距 水平 间距", "高处 作业 临边 防护 栏杆 高度", "施工 用电 TN-S 三级 配电",
    "塔吊 附着 间距 自由 高度", "卸料 平台 限载 牌 锚固", "安全网 平网 立网 冲击 试验",
    # ── 施工管理 ──
    "施工组织设计 审批 顺序", "质量 验收 检验批 主控 项目 一般 项目",
    "隐蔽 工程 验收 记录 影像", "试块 留置 同条件 标养", "分包 单位 资质 审查 报审",
]

# 去重
QUERIES = list(set(QUERIES))
random.seed(42)
random.shuffle(QUERIES)

def run_search_round():
    procs = []
    for q in QUERIES:
        p = subprocess.Popen([sys.executable,
            os.path.join(SKILLS_DIR, 'kb', 'kb.py'), 'search', q],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(p)
        if len(procs) >= 8:
            for p in procs: p.wait(timeout=60)
            procs = []
    for p in procs: p.wait(timeout=60)

def run_scorer():
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, 'tag_scorer.py')],
                      capture_output=True, text=True, timeout=30)
    for line in r.stdout.split('\n'):
        m = re.search(r'(\d+)\s*文件', line)
        if m: return int(m.group(1))
    return 0

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--target', type=float, default=0.05)
    args = p.parse_args()

    print(f'[TagTrainer v3] {len(QUERIES)} 条工程真实查询, 8并发')
    scores_history = []
    stable_count = 0

    for rnd in range(1, 501):
        run_search_round()
        affected = run_scorer()
        scores_history.append(affected)

        if len(scores_history) >= 5:
            recent = scores_history[-5:]
            if max(recent) > 0:
                fluctuation = (max(recent) - min(recent)) / max(recent)
                if fluctuation < args.target:
                    stable_count += 1
                else:
                    stable_count = 0

        if rnd % 3 == 0 or rnd == 1:
            pct = affected * 100 // 112
            print(f'  Round {rnd:>3d}: {affected} files ({pct}%)'
                  f'{" [OK]" if stable_count >= 3 else ""}')

        if stable_count >= 3:
            print(f'\n[TagTrainer v3] 收敛! {rnd}轮, {affected}文件({pct}%)')
            break

    if stable_count < 3:
        print(f'\n[TagTrainer v3] 完成{500}轮, {scores_history[-1]}文件')
    print(f'[TagTrainer v3] 结束')

if __name__ == '__main__':
    main()
