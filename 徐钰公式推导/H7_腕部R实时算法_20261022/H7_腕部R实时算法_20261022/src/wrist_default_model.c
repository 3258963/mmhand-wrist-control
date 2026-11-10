/* Auto-generated from data/geometry_source.json; do not edit constants by hand.
 * SHA256: 952e9c40702d5e140a9f2cd77b88f1416bbfe2941dac7699dba0e74b6d87a59f
 * C2/C3 P03/P04 already corrected. NOT hardware-calibrated.
 */
#include "wrist_r.h"
const wrist_config_t wrist_default_config = {
    .segment = {
        {
            { 5.000000000e-04f, -5.000000000e-03f, 2.500000000e-03f, -1.800000000e-02f, 3.000000000e-03f },
            { -2.700000000e-02f, -5.000000000e-03f, -3.250000000e-02f, -1.800000000e-02f, 4.000000000e-03f },
            { 2.700000000e-02f, -5.000000000e-03f, 3.750000000e-02f, -1.800000000e-02f, 4.000000000e-03f },
        },
        {
            { 6.000000000e-03f, -5.800000000e-02f, 3.247216913e-02f, -5.300000002e-02f, -1.785426117e-04f },
            { 6.000000000e-03f, 1.200000000e-02f, 2.200000000e-02f, 1.250000000e-02f, 2.835870693e-04f },
            { 6.000000000e-03f, 1.200000000e-02f, 2.200000000e-02f, 1.249999999e-02f, 6.283587067e-03f },
        },
    },
    .angle_min_rad = { -4.363323130e-01f, -4.363323130e-01f },
    .angle_max_rad = { 4.363323130e-01f, 7.853981634e-01f },
    .numerical_min_length_m = 1.0e-8f,
    .min_length_guard_m = { {0.0f,0.0f,0.0f}, {0.0f,0.0f,0.0f} },
    .calibration_confirmed = false,
    .guards_confirmed = false,
    .encoder_sign = { 1.0f, 1.0f },
    .encoder_zero_rad = { 0.0f, 0.0f },
    .relative_rank_epsilon = 1.0e-6f,
    .positive_null_epsilon = 1.0e-6f,
    .low_pitch_warning_enabled = true,
    .low_pitch_warning_max_rad = -4.188790205e-01f
};
