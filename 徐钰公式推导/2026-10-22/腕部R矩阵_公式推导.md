# 绳驱二轴腕部：R 矩阵公式推导

> 目标：从几何出发，推出每段绳长 `s(θ)` 与力臂 `r(θ)`，进而得到 R 矩阵。

---

## 1. 符号

| 符号 | 含义 | 单位 |
|---|---|---|
| $\vec{o}$ | 轴心（roll 段为原点，pitch 段为 $(0,0,24)$） | mm |
| $\hat{a}$ | 轴方向，单位向量（roll: $+Y$，pitch: $+X$） | — |
| $\vec{A}$ | 固定端（P4 / P6） | mm |
| $\vec{B}_0$ | 动端零位（P5 / P7） | mm |
| $\theta$ | 关节转角，右手为正 | rad |
| $a$ | 固定端到轴的距离 | mm |
| $b$ | 动端到轴的距离 | mm |
| $h$ | 两端沿轴错开量（带符号） | mm |
| $\Delta$ | 两个半径的有向夹角 | rad |
| $s$ | 该段绳长 | mm |
| $r$ | 力臂 $r=-ds/d\theta$ | mm |

---

## 2. 几何设定

- roll 轴：过原点，方向 $+Y$
- pitch 轴：过 $(0,0,24)$，方向 $+X$
- 3 根绳 / 2 个自由度，每根绳跨两个关节

每段绳只跨一个关节，因此

$$l_i(\theta_r,\theta_p)=c_i+s_{ri}(\theta_r)+s_{pi}(\theta_p)$$

---

## 3. 单段推导

### 3.1 两个向量

$$\vec{u}=\vec{A}-\vec{o},\qquad \vec{v}=\vec{B}_0-\vec{o}$$

### 3.2 拆成沿轴与垂直

$$h_1=\vec{u}\cdot\hat{a},\qquad \vec{u}_\perp=\vec{u}-h_1\hat{a}$$

$$h_2=\vec{v}\cdot\hat{a},\qquad \vec{v}_\perp=\vec{v}-h_2\hat{a}$$

三个不变量：

$$a=\|\vec{u}_\perp\|,\qquad b=\|\vec{v}_\perp\|,\qquad h=h_2-h_1$$

### 3.3 动端旋转

$$\mathrm{Rot}(\theta)\,\vec{v}_\perp=\vec{v}_\perp\cos\theta+(\hat{a}\times \vec{v}_\perp)\sin\theta$$

$$\vec{B}(\theta)=\vec{o}+h_2\hat{a}+\mathrm{Rot}(\theta)\,\vec{v}_\perp$$

### 3.4 距离平方

$$\vec{B}-\vec{A}=h\,\hat{a}+\mathrm{Rot}(\theta)\,\vec{v}_\perp-\vec{u}_\perp$$

轴向与垂直方向正交，故

$$s^2=h^2+\left\|\mathrm{Rot}(\theta)\,\vec{v}_\perp-\vec{u}_\perp\right\|^2$$

展开垂直部分（$\|\mathrm{Rot}(\theta)\vec{v}_\perp\|=b$，$\|\vec{u}_\perp\|=a$）：

$$s^2=a^2+b^2+h^2-2\,\mathrm{Rot}(\theta)\,\vec{v}_\perp\cdot \vec{u}_\perp$$

### 3.5 点积展开

$$\mathrm{Rot}(\theta)\,\vec{v}_\perp\cdot \vec{u}_\perp=(\vec{v}_\perp\cdot \vec{u}_\perp)\cos\theta+\big((\hat{a}\times \vec{v}_\perp)\cdot \vec{u}_\perp\big)\sin\theta$$

由定义合并为两角和：

$$\mathrm{Rot}(\theta)\,\vec{v}_\perp\cdot \vec{u}_\perp=ab\cos(\Delta+\theta)$$

其中

$$\cos\Delta=\frac{\vec{v}_\perp\cdot \vec{u}_\perp}{ab},\qquad \sin\Delta=-\frac{(\hat{a}\times \vec{v}_\perp)\cdot \vec{u}_\perp}{ab}$$

### 3.6 闭式

$$s^2=\alpha+\beta\cos\theta+\gamma\sin\theta$$

$$\alpha=a^2+b^2+h^2$$

$$\beta=-2\,(\vec{v}_\perp\cdot \vec{u}_\perp),\qquad \gamma=-2\,\big((\hat{a}\times \vec{v}_\perp)\cdot \vec{u}_\perp\big)$$

---

## 4. 力臂

$$\frac{ds}{d\theta}=\frac{\gamma\cos\theta-\beta\sin\theta}{2s}$$

约定 $r=-ds/d\theta$，则

$$r(\theta)=\frac{\beta\sin\theta-\gamma\cos\theta}{2s}$$

$$r(0)=-\frac{\gamma}{2\sqrt{\alpha+\beta}}$$

R 矩阵：

$$R=-\left(\frac{\partial l}{\partial q}\right)^{\mathrm T},\qquad R_{ij}=r_i(\theta_j)$$

张力映射：

$$\tau=Rf,\qquad f=R^{+}\tau+t\,w$$

---

## 5. 零位标定（mm）

| 绳 | roll $a$ | roll $b$ | roll $h$ | roll $\Delta$ | $r(0)$ roll | $r(0)$ pitch |
|---|---|---|---|---|---|---|
| C1 | 5.02 | 18.17 | 3.00 | $+2.20^\circ$ | −0.259 | −58.105 |
| C2 | 27.46 | 37.15 | 4.00 | $+18.49^\circ$ | −22.050 | +11.805 |
| C3 | 27.46 | 41.60 | 4.00 | $-15.14^\circ$ | +17.372 | +10.990 |

$\Delta$ 为有向角，正负由 $\sin\Delta=\gamma/(2ab)$ 决定。

---

## 6. 算法（每段）

1. 取常数 $u_1,u_2,v_1,v_2,h$
2. 计算 $\cos\theta,\ \sin\theta$
3. $d_1=v_1\cos\theta-v_2\sin\theta-u_1$
4. $d_2=v_1\sin\theta+v_2\cos\theta-u_2$
5. $s=\sqrt{d_1^2+d_2^2+h^2}$
6. $r=(u_2d_1-u_1d_2)/s$

三根绳 × 两段 = 6 次调用，得到 R 的 6 个元素。

---

## 7. 数值验证（C2 / roll）

| $\theta$ | $s$ (mm) | $r$ (mm) |
|---|---|---|
| 0° | 14.671 | −22.050 |
| 25° | 25.884 | −26.99 |
| 30° | 28.249 | −27.04 |

$\theta=30^\circ$ 手算：

$$\vec{v}_\perp=(-32.5,\,0,\,18),\qquad \hat{a}\times \vec{v}_\perp=(18,\,0,\,32.5)$$

$$\mathrm{Rot}(\theta)\,\vec{v}_\perp=0.8660\,(-32.5,0,18)+0.5\,(18,0,32.5)=(-19.145,\,0,\,31.839)$$

$$\vec{B}=(0,0,0)+(0,-12,0)+(-19.145,0,31.839)=(-19.145,\,-12,\,31.839)$$

$$s=\|\vec{B}-\vec{A}\|=\sqrt{7.855^2+4^2+26.838^2}=28.249\ \text{mm}$$

---

## 8. 工程要点

- 每段 5 个常数，可预计算为 float
- 单段：2 次 sin/cos + 4 次乘 + 1 次开方
- 9,249 个姿态验证：float32 与 double 最大差 $4.67\times10^{-5}$ mm
- 参考实现：`src/wrist_r.c`

---

## 9. 常见错误

| 错误 | 后果 |
|---|---|
| 把 pitch 轴心当原点 | 力臂全错（差 24 mm 量级） |
| 用 $\|\vec{v}\|$ 当半径 $b$ | 少减了轴向分量 |
| 角度用度 | cos/sin 结果错 |
| 力臂符号取反 | 控制方向反，闭环发散 |

---

## 10. 修订记录

| 日期 | 版本 | 修改 |
|---|---|---|
| 2026-10-22 | v1.0 | 初稿 |
| 2026-10-26 | v1.1 | 补 30° 算例与标定表 |
