/**
 * @file OverloadSafetyPolicy.cpp
 * @brief 实现过载安全规则；所有阈值统一读取 ControlConfig。
 */
#include "OverloadSafetyPolicy.h"

#include "../../config/ControlConfig.h"
#include "../../config/topology/HardwareMap.h"
#include "../../hal/servo/ServoValue.h"
#include "../../platform/rtos/SharedSafetyState.h"

namespace p4::safety {

using namespace mmhand::config::control;

uint32_t overloadActiveMotorMask(SystemRuntimeContext* runtime,
                                 const ControlCommandSnapshot_t& command)
{
    if (!runtime) {
        return 0;
    }
    const uint32_t validMask = validMotorChannelMask();
    if (command.controlMode == CONTROL_MODE_DIRECT_MOTOR) {
        return sharedAtomicLoad(&runtime->active_motor_mask) & validMask;
    }

    uint32_t motorMask = 0;
    const uint32_t jointMask = sharedAtomicLoad(&runtime->active_joint_mask) &
        ((1UL << ENCODER_TOTAL_NUM) - 1UL);
    for (uint8_t joint = 0; joint < ENCODER_TOTAL_NUM; ++joint) {
        if ((jointMask & (1UL << joint)) == 0) {
            continue;
        }
        const uint8_t count = getJointActuatorCount(joint);
        for (uint8_t index = 0; index < count; ++index) {
            JointActuatorItem actuator = {};
            if (getJointActuator(joint, index, &actuator) &&
                actuator.motorChannel < SERVO_TOTAL_NUM) {
                motorMask |= 1UL << actuator.motorChannel;
            }
        }
    }
    return motorMask & validMask;
}

OverloadSampleDecision evaluateOverloadSample(uint8_t controlMode,
                                              uint8_t motorChannel,
                                              int16_t signedLoad,
                                              uint32_t sampleMs,
                                              const OverloadHistory& previous)
{
    OverloadSampleDecision decision = {};
    const bool feedbackMode = controlMode == CONTROL_MODE_JOINT;
    const bool wristDirect = controlMode == CONTROL_MODE_DIRECT_MOTOR &&
                            motorChannel >= 27 && motorChannel <= 29;
    decision.threshold = feedbackMode ? kFeedbackOverloadLoadThreshold : kDirectOverloadLoadThreshold;
    if (wristDirect) {
        decision.threshold = kWristDirectOverloadLoadThreshold;
    }
    if (mmhand::servo::loadMagnitude(signedLoad) < decision.threshold) {
        return decision;
    }

    decision.next = previous;
    if (wristDirect && (sampleMs - previous.lastHighMs) > kServoTelemetryTimeoutMs) {
        decision.next = {};
    }
    if (decision.next.highCount == 0) {
        decision.next.firstHighMs = sampleMs;
    }
    if (decision.next.highCount < UINT8_MAX) {
        ++decision.next.highCount;
    }
    decision.next.lastHighMs = sampleMs;
    if (wristDirect) {
        decision.shouldLatch = (sampleMs - decision.next.firstHighMs) >= kWristDirectOverloadHoldMs;
    } else {
        const uint8_t latchCycles = feedbackMode ? kFeedbackOverloadLatchCycles : kDirectOverloadLatchCycles;
        decision.shouldLatch = decision.next.highCount >= latchCycles;
    }
    return decision;
}

bool jointHasOverloadFault(uint8_t jointIndex, uint32_t overloadFaultBitmap)
{
    const uint8_t count = getJointActuatorCount(jointIndex);
    for (uint8_t index = 0; index < count; ++index) {
        JointActuatorItem actuator = {};
        if (getJointActuator(jointIndex, index, &actuator) &&
            actuator.motorChannel < SERVO_TOTAL_NUM &&
            (overloadFaultBitmap & (1UL << actuator.motorChannel)) != 0) {
            return true;
        }
    }
    return false;
}

} // namespace p4::safety
