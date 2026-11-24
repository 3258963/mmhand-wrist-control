/**
 * @file OverloadSafetyPolicy.h
 * @brief 集中定义控制输出的舵机过载作用域、连续帧判定和关节故障映射。
 *
 * Policy 只计算判定结果，不写故障位图、不打印日志、不发送舵机命令。
 */
#ifndef P4_SAFETY_POLICIES_OVERLOAD_SAFETY_POLICY_H
#define P4_SAFETY_POLICIES_OVERLOAD_SAFETY_POLICY_H

#include <stdint.h>

#include "../../runtime/SystemRuntimeContext.h"

namespace p4::safety {

struct OverloadHistory {
    uint8_t highCount;
    uint32_t firstHighMs;
    uint32_t lastHighMs;
};

struct OverloadSampleDecision {
    OverloadHistory next;
    bool shouldLatch;
    int16_t threshold;
};

/** 返回当前控制模式真正主动驱动的舵机集合。 */
uint32_t overloadActiveMotorMask(SystemRuntimeContext* runtime,
                                 const ControlCommandSnapshot_t& command);

/** 逐电机判断过载；sampleMs 为舵机遥测采样时间，单位 ms。 */
OverloadSampleDecision evaluateOverloadSample(uint8_t controlMode,
                                              uint8_t motorChannel,
                                              int16_t signedLoad,
                                              uint32_t sampleMs,
                                              const OverloadHistory& previous);

/** 判断指定关节任一执行器是否已存在过载故障。 */
bool jointHasOverloadFault(uint8_t jointIndex, uint32_t overloadFaultBitmap);

} // namespace p4::safety

#endif // P4_SAFETY_POLICIES_OVERLOAD_SAFETY_POLICY_H
