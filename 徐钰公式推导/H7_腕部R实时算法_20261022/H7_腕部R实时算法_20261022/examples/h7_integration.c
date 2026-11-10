/* Compile this alongside the C files in src, or adapt it to the control task.
 * This example touches no motor, register, encoder or HAL peripheral.
 */
#include "wrist_r.h"

static wrist_context_t wrist_context={0};

wrist_status_t wrist_application_init(void)
{
    /* Default flags remain uncalibrated; replace parameters only after calibration. */
    return wrist_init(&wrist_context,&wrist_default_config);
}

wrist_status_t wrist_application_update(float roll_rad,float pitch_rad,wrist_result_t *state)
{
    /* One runtime call; output R is in state->R_m[2][3]. */
    return wrist_compute_R_rad(&wrist_context,roll_rad,pitch_rad,state);
}

/* Control-task policy must examine state->math_valid, state->geometry_gate_passed
 * and the other project-specific health/tension/load checks before using R.
 * No previous-good-R reuse or actuator action is hidden inside this module.
 */
