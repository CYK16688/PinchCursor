# 界面决策

## 2026-10-28 · 主界面按连续控制任务组织
- Decided by: Codex（默认方案，依据用户授权实施）
- Why: 使用者需要判断是否正在控制以及本次捏合发生了什么，状态反馈与开始/停止位于同一区域。
- Rejected: 再加诊断仪表和置信度百分比；没有可靠用户含义，也会增加控制负担。
- Rests on: 用户要求结合软件功能重构 UI；[运行时状态](../../core/control_engine.py)与[评估](evaluation-pinchcursor.md)。

## 2026-10-28 · 保留原生桌面与现有深色视觉体系
- Decided by: Codex（默认方案）
- Why: 保持现有品牌、平台快捷键和设置习惯，把变化集中在信息层次及操作反馈。
- Rejected: 改成网页外壳或加入新主题切换；与连续输入需求无直接关系。
- Rests on: [主题](../../gui/theme.py)与[项目约束](context-pinchcursor.md)。

## 2026-10-28 · UI 结果只来自实际控制证据
- Decided by: Codex（默认方案）
- Why: 手势确认不能替代动作执行成功；结果保留仅改变呈现，不延迟下一次输入。
- Rejected: 根据手形直接显示点击成功，或把一次操作失败显示成整段控制停止。
- Rests on: [反馈与时序测试](../../tests/test_interaction_feedback.py)。
