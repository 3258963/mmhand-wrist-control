# H7 二轴腕部 R 矩阵实时算法

版本：2026-10-22。几何参数对应 C2/C3 P03、P04 已纠正的24点CAD中心折线模型。接口为标准C99，输入两个角度，输出完整2×3矩阵和诊断状态。

## 1. 在主算法中一行调用

初始化放在控制循环外：

```c
#include "wrist_r.h"
static wrist_context_t ctx = {0};
static wrist_result_t state;

/* 系统初始化阶段 */
wrist_status_t init_status = wrist_init(&ctx, &wrist_default_config);
/* 检查 init_status == WRIST_OK */

/* 每个控制周期，输入已统一机械零位和正方向的弧度 */
wrist_status_t status = wrist_compute_R_rad(&ctx, theta_r_rad, theta_p_rad, &state);
/* R 的数值为 state.R_m[2][3] */
```

roll 左正右负，pitch 前正后负。第一行roll，第二行pitch，三列C1/C2/C3。`R_m`是按弧度求导的有效力臂SI数值，作为m使用；张力N乘R得到N·m。需要按度输入时调用 `wrist_compute_R_deg()`，不能把度数直接交给rad接口。

`wrist_compute_R_encoder_rad()`另做 `q_physical = sign * (q_encoder - zero)` 映射；不能对已经校正到物理角的输入再校正一次。Fusion旋转2对应roll，旋转1对应负pitch；函数原始输入顺序仍是roll通道、pitch通道，不是Fusion编号顺序。

## 2. 文件与工程集成

将 `src/wrist_r.c`、`src/wrist_default_model.c` 加入工程，包含 `src/wrist_r.h`。`examples/h7_integration.c`给出无HAL依赖的封装示例。模块无堆内存、无隐藏可变全局状态、无硬件访问；上下文在初始化时复制配置。不同输出缓冲区可共用不变上下文；更新配置不得与ISR求值并发。跨任务、ISR或核心发布结果时，由项目用双缓冲或临界区保证完整快照，不能让消费者读取正在写入的一半矩阵。

需要C99、`math.h`及目标C库的 `sinf/cosf/sqrtf/isfinite`。GCC/Clang请保留严格浮点语义，禁用 `-ffast-math`、`-ffinite-math-only` 等可能消除NaN/Inf检查的选项。本包主机验证使用 `-O2 -fno-fast-math -ffp-contract=off`。H7的FPU、浮点ABI、链接库和启动配置须与实际工程一致；本包没有替换用户HAL、链接脚本或控制任务。

R核心复用两个角度的sin、cos：共2次sinf、2次cosf，六段各一次sqrtf及力臂除法；矩阵秩、条件数与正零空间诊断另有运算。完整API执行时间必须在实际芯片、时钟、Cache/Flash/ITCM、编译优化和中断环境测量。主机验证不是H7周期测试。

## 3. 读取状态，避免误用

- `math_valid`：几何求值成功。硬错误时所有R元素置NaN，避免残留半个矩阵或旧结果。
- `rank_2`：按数值阈值判断两行独立。
- `has_positive_internal_preload`：是否有全正向量w使Rw=0；不表示有界张力或任意目标力矩可实现。
- `geometry_gate_passed`：仅表示本模块的必要几何/模型门限通过。还必须执行项目的张力、负载和其他控制检查。
- `status`：位掩码；用 `wrist_status_has_error(status)` 检查硬错误。非零不一定是硬错误，默认模型会有未标定警告。

**默认CAD参数 `calibration_confirmed=false`、`guards_confirmed=false`，所有工程段长门限为0（未设置），所以默认 `geometry_gate_passed` 永远不会为true。** 算法仍输出数学R，便于离线/调试核对。不得只为让程序通过而把确认位改true。

`numerical_min_length_m=1e-8`只是浮点数值退化下限，不是工程段长安全门限。工程门限需逐段根据实测几何不确定度及允许力臂误差确定；`guards_confirmed=true`时所有六项必须大于数值下限。任一正值门限即使尚未确认也会被执行。段长小于门限返回硬错误，并将R置NaN。

本版C1 pitch段在−25°约3.900609 mm；pitch≤−24°默认给出低置信警告并不通过几何门限。这是当前几何的关注区，非数学奇异边界。经独立验证后方可调整相关配置。CAD扫描中1,664/3,621个姿态无全正内部预紧方向，当前实时算法逐姿态计算该标志，不按pitch一个角度硬编码这个判定。

## 4. 实际用的是哪条公式

详细见 `算法说明.md`。理论是 `Rji = -∂li/∂qj`，每段可写成 `r=(βsinθ−γcosθ)/(2√D)`。固件采用相同几何的稳定投影形式，直接用三项平方求段长，避免短段中α、β、γ大数抵消。

因此运行常量为每段5个几何投影数，六段30个float（120字节几何数据），而非18个α/β/γ常数。几何模型没有改变，计算量仍然很小。α/β/γ保存在 `data/derived_constants.json` 便于核对，未作为曲面拟合系数。

## 5. 改点与重新生成

编辑 `data/geometry_source.json` 的真实点坐标/轴线后运行：

```text
python tools/generate_model.py
```

它重算 `src/wrist_default_model.c`，不手改float常量。需要维护完整坐标一致性与原绳路归属；若改成base直接到palm等耦合路径，此两单变量模型不再适用，生成器对已知点归属变化会拒绝继续。应重新推导通用绳长雅可比。

几何或范围变更后，旧CAD表、低置信分区和软件验证结论不能自动沿用。标定确认与工程门限仍需重新确定。默认生成器读取源JSON中的角范围，其他运行策略由工程配置核验。

## 6. 主机验证与H7计时

安装有GCC或Clang时，在包目录运行：

```text
python tools/verify_host.py
```

也支持 `--cc 编译器路径` 或 `--zig zig.exe路径`。脚本编译C自测和驱动，验证3,621网格、5,000随机姿态、603低pitch密集姿态及25个极值/边界组合，共9,249个姿态，结果写入 `主机验证报告.json`。自测覆盖NaN/Inf、角度越界、未初始化、错误参数、工程门限、退化段、秩不足、编码器映射、失效输出清空及配置复制。

比较基准为独立Python双精度3D轴向力矩计算，未调用固件平面常数或原来的geometry_model。另对照CAD0.2°差分表；与该表的差包含有限差分截断，不能当作float误差或真机误差。

本包数值验收阈值是R最大差<0.001 mm、段长最大差<0.0001 mm，仅用于软件核对。实际最大差以运行报告为准，不能据此承诺实机精度。几何修改后必须提供匹配的独立CAD参考，或显式使用 `--skip-cad-comparison`，报告将标注跳过了旧CAD对照。

H7上用项目CMSIS提供的DWT/CYCCNT或计时器包围**完整API调用**，先确认计数器已启用；使用无符号计数差，记录不同姿态的最大值，并覆盖Cache冷热和代表性中断负载。不要把主机耗时或未启用计数器得到的0当作执行时间。是否满足1 kHz等控制频率，要结合控制任务整体最坏时延验证。

本包提供的是R计算及必要诊断，输出给现有的关节控制/张力算法；张力分配、闭环增益、负载模型与电机命令由项目另行接入。
