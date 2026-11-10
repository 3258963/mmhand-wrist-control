# 绳驱二轴腕部：动态 R 矩阵解算

> **一句话结论**：R 是 2 行 3 列，元素为每段绳的力臂 `r = −ds/dθ`；用 5 个常数（u₁, u₂, v₁, v₂, h）即可在任意姿态实时算出，单段误差 < 1e-4 mm。

---

## 1. 符号约定

| 符号 | 含义 | 单位 |
|---|---|---|
| o | 轴心（roll 段为原点，pitch 段为 (0,0,24)） | mm |
| â | 轴方向，单位向量（roll:+Y，pitch:+X） | — |
| A | 固定端坐标（P4 / P6） | mm |
| B₀ | 动端零位坐标（P5 / P7） | mm |
| θ | 关节转角，右手为正 | rad |
| a | 固定端到轴的距离 | mm |
| b | 动端到轴的距离 | mm |
| h | 两端沿轴错开量，带符号 | mm |
| Δ | 两个半径的有向夹角 | rad |
| s | 该段绳长 | mm |
| r | 力臂 `r = −ds/dθ` | mm |

---

## 2. 几何设定

腕部为 n+1 = 3 绳 / 2 自由度的冗余驱动：

- roll 轴：过原点，方向 +Y；
- pitch 轴：过 (0,0,24)，方向 +X；
- 每根绳跨两个关节，绳长可写成两段之和。

**解耦条件**：每段绳只跨一个关节，因此

$$l_i(\theta_r,\theta_p) = c_i + s_{ri}(\theta_r) + s_{pi}(\theta_p)$$

---

## 3. 单段绳长推导

### 3.1 两个向量

$$\vec{u} = \vec{A} - \vec{o},\qquad \vec{v} = \vec{B}_0 - \vec{o}$$

### 3.2 拆成沿轴与垂直

$$h_1 = \vec{u}\cdot\hat{a},\qquad \vec{u}_\perp = \vec{u} - h_1\hat{a}$$
$$h_2 = \vec{v}\cdot\hat{a},\qquad \vec{v}_\perp = \vec{v} - h_2\hat{a}$$

三个不变量：

$$a = \|\vec{u}_\perp\|,\qquad b = \|\vec{v}_\perp\|,\qquad h = h_2 - h_1$$

> â 是单位向量，所以 h₁、h₂ 就是两点沿轴的坐标；u⊥、v⊥ 都垂直于 â。

### 3.3 动端转过去

记 $\mathrm{Rot}(\theta)$ 为“绕 â 转 θ”这个操作：

$$\mathrm{Rot}(\theta)\,\vec{v}_\perp = \vec{v}_\perp\cos\theta + (\hat{a}\times \vec{v}_\perp)\sin\theta$$

$$\vec{B}(\theta) = \vec{o} + h_2\hat{a} + \mathrm{Rot}(\theta)\,\vec{v}_\perp$$

### 3.4 距离平方

先把 $\vec{B}-\vec{A}$ 写出来（注意 $h = h_2 - h_1$）：

$$\vec{B} - \vec{A} = h\,\hat{a} + \mathrm{Rot}(\theta)\,\vec{v}_\perp - \vec{u}_\perp$$

â 与两个垂直分量都正交，所以平方时轴向那一项单独分离：

$$s^2 = \|\vec{B}-\vec{A}\|^2 = h^2 + \left\|\,\mathrm{Rot}(\theta)\,\vec{v}_\perp - \vec{u}_\perp\right\|^2$$

垂直部分再用 $\|\xi-\eta\|^2 = \|\xi\|^2 + \|\eta\|^2 - 2\xi\cdot\eta$ 展开，并代入
$\|\mathrm{Rot}(\theta)\vec{v}_\perp\| = b$、$\|\vec{u}_\perp\| = a$：

$$\left\|\,\mathrm{Rot}(\theta)\,\vec{v}_\perp - \vec{u}_\perp\right\|^2 = b^2 + a^2 - 2\,\mathrm{Rot}(\theta)\,\vec{v}_\perp\cdot \vec{u}_\perp$$

合起来：

$$s^2 = a^2 + b^2 + h^2 - 2\,\mathrm{Rot}(\theta)\,\vec{v}_\perp\cdot \vec{u}_\perp$$

### 3.5 点积展开（两角和）

把 $\mathrm{Rot}(\theta)\vec{v}_\perp$ 代入点积，得到第一步：

$$\mathrm{Rot}(\theta)\,\vec{v}_\perp\cdot \vec{u}_\perp = (\vec{v}_\perp\cdot \vec{u}_\perp)\cos\theta + \big((\hat{a}\times \vec{v}_\perp)\cdot \vec{u}_\perp\big)\sin\theta$$

再代入 $\cos\Delta$、$\sin\Delta$ 的定义，并合并成两角和：

$$\mathrm{Rot}(\theta)\,\vec{v}_\perp\cdot \vec{u}_\perp = ab\,(\cos\Delta\cos\theta - \sin\Delta\sin\theta) = ab\cos(\Delta+\theta)$$

其中

$$\cos\Delta = \frac{\vec{v}_\perp\cdot \vec{u}_\perp}{ab},\qquad \sin\Delta = -\frac{(\hat{a}\times \vec{v}_\perp)\cdot \vec{u}_\perp}{ab}$$

### 3.6 得到闭式

$$s^2 = \alpha + \beta\cos\theta + \gamma\sin\theta$$

$$\alpha = a^2+b^2+h^2,\qquad
\beta = -2(\vec{v}_\perp\cdot \vec{u}_\perp),\qquad
\gamma = -2\big((\hat{a}\times \vec{v}_\perp)\cdot \vec{u}_\perp\big)$$

---

## 4. 力臂与 R 矩阵

对 $s$ 求导：

$$\frac{ds}{d\theta} = \frac{\gamma\cos\theta - \beta\sin\theta}{2s}$$

论文约定 $r = -ds/d\theta$，因此

$$r(\theta) = \frac{\beta\sin\theta - \gamma\cos\theta}{2s},\qquad
r(0) = -\frac{\gamma}{2\sqrt{\alpha+\beta}}$$

R 矩阵（2 行 × 3 列，行 = 关节，列 = 绳）：

$$R = -\left(\frac{\partial l}{\partial q}\right)^{\mathsf T},\qquad R_{ij} = r_i(\theta_j)$$

零位时的数值：

| | C1 | C2 | C3 |
|---|---|---|---|
| **roll** | −0.259 | −22.050 | +17.372 |
| **pitch** | −58.105 | +11.805 | +10.990 |

张力映射：

$$\tau = R f,\qquad f = R^{+}\tau + t\,w$$

---

## 5. 零位标定表（mm）

| 绳 | roll 段 a | roll 段 b | roll 段 h | roll 段 Δ | **r(0), roll** | pitch 段 r(0) |
|---|---|---|---|---|---|---|
| C1 | 5.02 | 18.17 | 3.00 | +2.20° | **−0.259** | **−58.105** |
| C2 | 27.46 | 37.15 | 4.00 | +18.49° | **−22.050** | **+11.805** |
| C3 | 27.46 | 41.60 | 4.00 | −15.14° | **+17.372** | **+10.990** |

> Δ 是**有向角**，由 $\sin\Delta = \gamma/(2ab)$ 决定正负；完整 α、β、γ 见 `segment_parameters.csv`。

---

## 6. 算法流程（每段）

1. 取常数 `u₁, u₂, v₁, v₂, h`；
2. 计算 $\theta$ 的 cos / sin；
3. $d_1 = v_1\cos\theta - v_2\sin\theta - u_1$；
4. $d_2 = v_1\sin\theta + v_2\cos\theta - u_2$；
5. $s = \sqrt{d_1^2 + d_2^2 + h^2}$；
6. $r = (u_2 d_1 - u_1 d_2)/s$。

三根绳 × 两段 = 6 次调用，得到 R 的 6 个元素。

---

## 7. 数值验证

以 C2 / roll 为例：

| θ | s (mm) | r (mm) |
|---|---|---|
| 0° | 14.671 | −22.050 |
| 25° | 25.884 | −26.99 |
| 30° | 28.249 | −27.04 |

C2 手算（θ = 30°）：

$$\vec{v}'_\perp = (-32.5,0,18)\cos30° + (18,0,32.5)\sin30° = (-19.145,\,0,\,31.839)$$

$$\vec{B} = (0,0,0)+(0,-12,0)+\vec{v}'_\perp = (-19.145,-12,31.839)$$

$$s = \|\vec{B}-\vec{A}\| = \sqrt{7.855^2+4^2+26.838^2} = 28.249\ \text{mm}$$

---

## 8. 工程实现要点

- 每段 5 个常数，可预计算为 float；
- 单段只需 2 次 sin/cos + 4 次乘 + 1 次开方；
- 全姿态 9,249 点验证：float32 与 double 最大差 4.67e-5 mm；
- 参考实现：`src/wrist_r.c`。

---

## 9. 常见错误

| 错误 | 后果 |
|---|---|
| 把 pitch 轴心当原点 | 力臂全错（约差 24 mm 量级） |
| 用 ‖v‖ 当半径 b | 少减了轴向分量 |
| 角度用度 | cos/sin 结果错 |
| 力臂符号取反 | 控制方向反，闭环发散 |

---

## 10. 修订记录

| 日期 | 版本 | 修改 |
|---|---|---|
| 2026-10-22 | v1.0 | 初稿 |
| 2026-10-26 | v1.1 | 补 30° 算例与标定表 |
