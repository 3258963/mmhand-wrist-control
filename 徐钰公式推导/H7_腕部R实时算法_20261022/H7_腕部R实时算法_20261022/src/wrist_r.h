#ifndef WRIST_R_H
#define WRIST_R_H

/* Portable C99, no HAL dependency, allocation, hidden state or hardware access.
 * Input physical angles: radians (roll left+, pitch forward+).
 * Output effective moment arms: metres; tau[N*m] = R[m] * tension[N].
 * Numerically R=-d(length_m)/d(angle_rad); rad is dimensionless in SI.
 */
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define WRIST_AXES 2u
#define WRIST_CABLES 3u
#define WRIST_ROLL 0u
#define WRIST_PITCH 1u

typedef uint32_t wrist_status_t;
enum {
    WRIST_OK                    = 0u,
    WRIST_ERR_ARGUMENT          = 1u << 0,
    WRIST_ERR_NOT_INITIALIZED   = 1u << 1,
    WRIST_ERR_CONFIG            = 1u << 2,
    WRIST_ERR_NONFINITE_INPUT   = 1u << 3,
    WRIST_ERR_ANGLE_RANGE       = 1u << 4,
    WRIST_ERR_SEGMENT_NUMERICAL = 1u << 5,
    WRIST_ERR_SEGMENT_GUARD     = 1u << 6,
    WRIST_ERR_NONFINITE_RESULT  = 1u << 7,

    WRIST_WARN_UNCALIBRATED     = 1u << 16,
    WRIST_WARN_GUARDS_UNSET     = 1u << 17,
    WRIST_WARN_LOW_PITCH        = 1u << 18,
    WRIST_WARN_RANK             = 1u << 19,
    WRIST_WARN_NO_POSITIVE_NULL = 1u << 20
};
#define WRIST_ERROR_MASK UINT32_C(0x000000ff)

/* Coordinates of a fixed endpoint u and rotating zero endpoint v in a plane
 * perpendicular to the joint axis. e1 x e2 = positive joint axis.
 * h is the axial endpoint separation. All five values are metres.
 */
typedef struct {
    float u1_m, u2_m;
    float v1_m, v2_m;
    float h_m;
} wrist_segment_t;

typedef struct {
    wrist_segment_t segment[WRIST_AXES][WRIST_CABLES];
    float angle_min_rad[WRIST_AXES];
    float angle_max_rad[WRIST_AXES];
    /* Only an arithmetic floor, NOT a certified engineering clearance. */
    float numerical_min_length_m;
    /* All entries must be > numerical floor if guards_confirmed is true. */
    float min_length_guard_m[WRIST_AXES][WRIST_CABLES];
    bool calibration_confirmed;
    bool guards_confirmed;
    /* q_physical = sign * (q_encoder - encoder_zero_rad). */
    float encoder_sign[WRIST_AXES];
    float encoder_zero_rad[WRIST_AXES];
    /* Numerical margins only. These are NOT experimental force margins. */
    float relative_rank_epsilon;
    float positive_null_epsilon;
    bool low_pitch_warning_enabled;
    float low_pitch_warning_max_rad;
} wrist_config_t;

/* Caller must initialize with {0}, then call wrist_init once outside the ISR.
 * Initialization copies configuration, so later caller mutations do not alter it.
 * Do not reinitialize a context concurrently with evaluation.
 */
typedef struct {
    wrist_config_t cfg;
    uint32_t initialized_tag;
} wrist_context_t;

typedef struct {
    float R_m[WRIST_AXES][WRIST_CABLES];
    float segment_length_m[WRIST_AXES][WRIST_CABLES];
    float physical_angle_rad[WRIST_AXES];
    float positive_null_unit[WRIST_CABLES];
    float condition_2;
    bool math_valid;
    bool rank_2;
    bool has_positive_internal_preload;
    /* Necessary geometry/model gate only; NOT bounded-load feasibility. */
    bool geometry_gate_passed;
    wrist_status_t status;
    uint8_t bad_axis;   /* 0xff when not applicable */
    uint8_t bad_cable;  /* 0xff when not applicable */
} wrist_result_t;

extern const wrist_config_t wrist_default_config;

wrist_status_t wrist_init(wrist_context_t *ctx, const wrist_config_t *cfg);
wrist_status_t wrist_compute_R_rad(const wrist_context_t *ctx,
    float roll_rad, float pitch_rad, wrist_result_t *out);
wrist_status_t wrist_compute_R_deg(const wrist_context_t *ctx,
    float roll_deg, float pitch_deg, wrist_result_t *out);
wrist_status_t wrist_compute_R_encoder_rad(const wrist_context_t *ctx,
    float roll_encoder_rad, float pitch_encoder_rad, wrist_result_t *out);
bool wrist_status_has_error(wrist_status_t status);

#ifdef __cplusplus
}
#endif
#endif
